"""A tiny procedural companion: idle, approach the glass, greet and return."""
from __future__ import annotations

from functools import lru_cache
import math
import threading
import time

from PIL import Image, ImageDraw, ImageFilter
from cube_player import CubeConnection, rgb565
from smooth_player import encode_jpeg, wait_frame
from cubedesk.widgets import font

APPROACH = 2.4
HOLD = 3.0
RETURN = 2.4
FPS = 12
LABELS = {'idle':'Отдыхает', 'approaching':'Идёт к вам', 'greeting':'У стекла', 'returning':'Возвращается'}
LABELS['curious']='Присматривается'
CHARACTERS = {'moti': {'name':'Моти','look':0.0,'approach':APPROACH,'hold':HOLD,'return':RETURN},
              'momo': {'name':'Момо','look':1.0,'approach':2.6,'hold':4.0,'return':2.7}}


def validate_character(character):
    if not isinstance(character,str) or character not in CHARACTERS:
        raise ValueError('Выберите Моти или Момо')
    return character


def ease(value):
    value=max(0,min(1,value))
    return value*value*(3-2*value)


class PetState:
    def __init__(self, now=None, character='moti'):
        self.lock=threading.RLock()
        self.epoch=time.monotonic() if now is None else now
        self.called_at=None
        self.start_depth=0.0
        self.pending=False
        self.calls=0
        self.generation=0
        self.cached_key=None
        self.cached_image=None
        self.character=validate_character(character)

    def select(self, character, now=None):
        character=validate_character(character)
        with self.lock:
            if character==self.character:return
            self.character=character
            self.epoch=time.monotonic() if now is None else now
            self.reset()

    def reset(self):
        with self.lock:
            self.called_at=None;self.pending=False;self.start_depth=0.0
            self.generation+=1

    def request_call(self):
        with self.lock:
            self.pending=True;self.calls+=1

    def activate_pending(self, now=None):
        now=time.monotonic() if now is None else now
        with self.lock:
            if not self.pending:return
            pose=self.pose(now)
            timing=CHARACTERS[self.character]
            if pose['phase']=='greeting':
                self.called_at=now-timing['look']-timing['approach']
            elif pose['phase'] not in ('approaching','curious'):
                self.start_depth=pose['depth'];self.called_at=now
            self.pending=False;self.generation+=1

    def pose(self, now=None):
        now=time.monotonic() if now is None else now
        with self.lock:
            elapsed=now-self.called_at if self.called_at is not None else float('inf')
            timing=CHARACTERS[self.character]
            look,approach,hold,back=(timing[k] for k in ('look','approach','hold','return'))
            if elapsed<look:
                phase='curious';depth=self.start_depth;phase_elapsed=elapsed
            elif elapsed<look+approach:
                phase='approaching';phase_elapsed=elapsed-look
                depth=self.start_depth+(1-self.start_depth)*ease(phase_elapsed/approach)
            elif elapsed<look+approach+hold:
                phase='greeting';depth=1.0;phase_elapsed=elapsed-look-approach
            elif elapsed<look+approach+hold+back:
                phase='returning';phase_elapsed=elapsed-look-approach-hold;depth=1-ease(phase_elapsed/back)
            else:phase='idle';depth=0.0;phase_elapsed=now-self.epoch
            return {'phase':phase,'depth':depth,'time':now-self.epoch,'phase_elapsed':phase_elapsed}

    def status(self):
        with self.lock:
            pose=self.pose()
            return {'phase':pose['phase'],'label':'Зову…' if self.pending else LABELS[pose['phase']],
                    'pending':self.pending,'calls':self.calls,'id':self.character,'name':CHARACTERS[self.character]['name']}

    def image(self, now=None):
        now=time.monotonic() if now is None else now
        with self.lock:
            key=(self.generation,int(now*FPS))
            if key!=self.cached_key:
                self.cached_image=render_pet(self.pose(now),self.character);self.cached_key=key
            return self.cached_image.copy()


@lru_cache(maxsize=1)
def room():
    image=Image.new('RGBA',(480,480))
    d=ImageDraw.Draw(image)
    for y in range(480):
        t=y/479
        d.line((0,y,480,y),fill=(round(237-22*t),round(228+3*t),round(249-4*t)))
    light=Image.new('RGBA',image.size,(255,255,255,0))
    ImageDraw.Draw(light).ellipse((160,-90,600,330),fill=(255,255,255,145))
    image=Image.alpha_composite(image,light.filter(ImageFilter.GaussianBlur(45)))
    d=ImageDraw.Draw(image)
    d.ellipse((-150,300,650,680),fill='#dfdcf1')
    d.arc((-150,300,650,680),180,360,fill='#eeedf8',width=2)
    # A quiet room, rather than a busy decorative background.
    d.ellipse((48,94,56,102),fill='#c5b7dc')
    d.ellipse((389,173,395,179),fill='#cfbfdc')
    return image


def render_pet(pose,character='moti'):
    validate_character(character)
    if character=='momo':return render_momo(pose)
    image=room().copy()
    depth=pose['depth'];t=pose['time'];phase=pose['phase']
    walking=phase in ('approaching','returning')
    greeting=phase=='greeting'
    scale=.70+.92*depth
    bob=(math.sin(t*10)*1.5 if walking else math.sin(t*2)*.7)
    cx=120+math.sin(t*2.4)*(1-depth)*1.4
    cy=119+21*depth+bob
    # Draw at double resolution for smooth silhouettes and whiskers.
    def point(x,y):return ((cx+x*scale)*2,(cy+y*scale)*2)
    def box(bounds):
        a=point(bounds[0],bounds[1]);b=point(bounds[2],bounds[3]);return (*a,*b)
    shadow=Image.new('RGBA',image.size)
    sd=ImageDraw.Draw(shadow)
    width=29+32*depth;floor=min(239,cy+80*scale)
    sd.ellipse(((cx-width)*2,(floor-5)*2,(cx+width)*2,(floor+8)*2),fill=(92,76,128,45))
    image=Image.alpha_composite(image,shadow.filter(ImageFilter.GaussianBlur(5)))
    d=ImageDraw.Draw(image)
    outline='#b6a0b4';fur='#f5e8dc';lightfur='#fff5e9';pink='#e8b4bd'
    def ellipse(bounds,fill,edge=None,width=1):d.ellipse(box(bounds),fill=fill,outline=edge,width=max(1,round(width*scale*2)))
    def line(points,fill,width=2):
        coords=[point(x,y) for x,y in points]
        stroke=max(1,round(width*scale*2))
        d.line(coords,fill=fill,width=stroke,joint='curve')
        radius=stroke/2
        for x,y in (coords[0],coords[-1]):d.ellipse((x-radius,y-radius,x+radius,y+radius),fill=fill)
    # Tail follows a continuous curve; the step phase does not reset on calls.
    wag=math.sin(t*2.7)*7
    tail=[]
    for i in range(31):
        u=i/30
        tail.append(((1-u)**2*24+2*(1-u)*u*67+u*u*(54+wag),
                     (1-u)**2*55+2*(1-u)*u*60+u*u*16))
    line(tail,outline,12);line(tail,fur,9)
    ellipse((-28,12,29,76),fur,outline)
    ellipse((-20,21,21,69),lightfur)
    step=math.sin(t*11)*3 if walking else 0
    ellipse((-29,64+step,-5,83+step),lightfur,outline)
    ellipse((5,64-step,29,83-step),lightfur,outline)
    # Ears and an oversized, soft head.
    for sign in (-1,1):
        ear=[(sign*39,-18),(sign*34,-64),(sign*11,-43)]
        d.polygon([point(*p) for p in ear],fill=fur,outline=outline,width=max(1,round(scale*2)))
        inside=[(sign*31,-30),(sign*30,-53),(sign*17,-41)]
        d.polygon([point(*p) for p in inside],fill=pink)
    ellipse((-44,-47,44,29),fur,outline)
    ellipse((-39,-43,37,21),lightfur)
    # A lilac scarf and a little brass bell.
    d.rounded_rectangle(box((-29,22,29,36)),radius=round(6*scale*2),fill='#ad9acb')
    d.polygon([point(*p) for p in [(10,31),(26,32),(27,56),(12,51)]],fill='#b6a4d0')
    ellipse((-5,29,5,39),'#e6c48c')
    line([(0,35),(0,38)],'#bb9968',.8)
    blink=t%5.8>5.55
    gaze=0 if depth>.6 else math.sin(t*.65)*1.1
    for x in (-16,16):
        if blink:
            line([(x-5,-10),(x,-8),(x+5,-10)],'#364254',1.8)
        else:
            ellipse((x-5+gaze,-18,x+5+gaze,-3),'#344252')
            ellipse((x-3+gaze,-17,x+.5+gaze,-12),'#ffffff')
            ellipse((x+1+gaze,-8,x+3+gaze,-6),'#94a3af')
    ellipse((-34,-4,-20,3),'#ecc2c1');ellipse((20,-4,34,3),'#ecc2c1')
    d.polygon([point(-4,-2),point(4,-2),point(0,3)],fill='#cf929f')
    line([(0,3),(-3,7),(-7,6)],'#a88091',1)
    line([(0,3),(3,7),(7,6)],'#a88091',1)
    for sign in (-1,1):
        line([(sign*27,7),(sign*39,5)],'#baa6b5',.7)
        line([(sign*26,11),(sign*38,13)],'#baa6b5',.7)
    if greeting:
        # Front paws lift against the imaginary glass.
        for sign in (-1,1):
            x=sign*42
            ellipse((x-10,19,x+10,42),lightfur,outline)
            ellipse((x-4,29,x+4,37),pink)
            for dx,dy in [(-5,24),(0,22),(5,24)]:ellipse((x+dx-1.8,dy-1.8,x+dx+1.8,dy+1.8),pink)
        # One small heart, drifting rather than flashing.
        hx,hy=190,43+math.sin(t*2)*2
        d.ellipse(((hx-7)*2,(hy-4)*2,hx*2,(hy+3)*2),fill='#dca9bf')
        d.ellipse((hx*2,(hy-4)*2,(hx+7)*2,(hy+3)*2),fill='#dca9bf')
        d.polygon([(2*(hx-7),2*hy),(2*(hx+7),2*hy),(2*hx,2*(hy+9))],fill='#dca9bf')
    else:
        for x in (-18,18):ellipse((x-7,49,x+7,73),lightfur,outline)
    # The glass reflection is faint until the pet is at the front.
    glass=Image.new('RGBA',image.size,(255,255,255,0));gd=ImageDraw.Draw(glass)
    alpha=round(20+42*depth)
    gd.line((26,24,63,99),fill=(255,255,255,alpha),width=5)
    gd.line((451,305,451,420),fill=(255,255,255,alpha),width=2)
    image=Image.alpha_composite(image,glass)
    d=ImageDraw.Draw(image)
    if depth<.2:
        d.text((240,428),'Моти',font=font(12,'bold'),fill='#827194',anchor='mt')
        d.text((240,462),'Позовите меня',font=font(8),fill='#9b8ba8',anchor='mb')
    return image.convert('RGB').resize((240,240),Image.Resampling.LANCZOS)


@lru_cache(maxsize=1)
def momo_room():
    image=Image.new('RGBA',(480,480))
    d=ImageDraw.Draw(image)
    for y in range(480):
        t=y/479
        d.line((0,y,480,y),fill=(round(235-12*t),round(243-10*t),round(242-12*t)))
    light=Image.new('RGBA',image.size)
    ld=ImageDraw.Draw(light)
    ld.ellipse((-70,-150,390,350),fill=(255,245,218,115))
    image=Image.alpha_composite(image,light.filter(ImageFilter.GaussianBlur(40)))
    ImageDraw.Draw(image).ellipse((-140,315,640,650),fill='#d9e1da')
    return image


def render_momo(pose):
    """Colourpoint portrait and Momo's own curious / prowl / single-paw greeting."""
    image=momo_room().copy()
    depth,t,phase=pose['depth'],pose['time'],pose['phase']
    local=pose.get('phase_elapsed',t)
    walking=phase in ('approaching','returning')
    scale=.73+.86*depth
    progress=local/2.6 if phase=='approaching' else local/2.7
    # A low, deliberate prowl with a side step, unlike Moti's straight walk.
    crouch=math.sin(math.pi*max(0,min(1,progress)))*5 if walking else 0
    cx=120+(math.sin(progress*math.pi)*7 if walking else math.sin(t*.9)*(1-depth))
    cy=119+20*depth+crouch+math.sin(t*1.6)*.65
    def point(x,y):return ((cx+x*scale)*2,(cy+y*scale)*2)
    def box(bounds):return (*point(*bounds[:2]),*point(*bounds[2:]))
    def tools(layer):
        d=ImageDraw.Draw(layer)
        def ellipse(bounds,fill,edge=None,width=1):
            d.ellipse(box(bounds),fill=fill,outline=edge,width=max(1,round(width*scale*2)))
        def line(points,fill,width=1):
            d.line([point(*p) for p in points],fill=fill,width=max(1,round(width*scale*2)),joint='curve')
        def polygon(points,fill):d.polygon([point(*p) for p in points],fill=fill)
        return d,ellipse,line,polygon
    shadow=Image.new('RGBA',image.size)
    floor=min(240,cy+79*scale)
    ImageDraw.Draw(shadow).ellipse(((cx-32-24*depth)*2,(floor-5)*2,(cx+32+24*depth)*2,(floor+8)*2),fill=(69,80,73,43))
    image=Image.alpha_composite(image,shadow.filter(ImageFilter.GaussianBlur(5)))
    d,ellipse,line,polygon=tools(image)
    edge,fur,chest,dark='#735d50','#bda58d','#dfcdb6','#3b2c28'
    tail=[]
    curl=math.sin(t*1.8)*4
    for i in range(40):
        u=i/39
        tail.append((25+37*math.sin(u*1.9)+curl*u,59-42*u+12*math.sin(u*math.pi)))
    line(tail,edge,12);line(tail,dark,9)
    ellipse((-30,12,31,77),fur,edge)
    ellipse((-20,22,20,67),chest)
    step=math.sin(local*7)*2.8 if walking else 0
    ellipse((-29,64+step,-5,83+step),dark,edge)
    ellipse((5,64-step,29,83-step),dark,edge)
    # His short blue collar matches the real cat's eyes; no lilac scarf.
    d.rounded_rectangle(box((-28,23,28,32)),radius=max(1,round(4*scale)),fill='#7eaaa9')
    ellipse((-4,28,4,36),'#d6bf87')
    head=Image.new('RGBA',image.size)
    hd,he,hl,hp=tools(head)
    for sign in (-1,1):
        hp([(sign*40,-17),(sign*35,-63),(sign*10,-43)],dark)
        hp([(sign*32,-30),(sign*31,-53),(sign*18,-41)],'#78564d')
    he((-45,-47,45,29),'#97745b',edge)
    # Soft cheeks and warm fur framing the deep chocolate mask.
    for sign in (-1,1):
        hp([(sign*34,-7),(sign*46,-2),(sign*41,3),(sign*47,7),(sign*34,12)],'#97745b')
    mask=Image.new('RGBA',image.size)
    md,me,ml,mp=tools(mask)
    me((-34,-39,34,24),'#3e2e29')
    me((-25,-29,25,23),'#2e2422')
    mask=mask.filter(ImageFilter.GaussianBlur(max(1,2.8*scale)))
    head=Image.alpha_composite(head,mask)
    hd,he,hl,hp=tools(head)
    he((-22,4,22,22),'#49342e')
    he((-12,18,13,26),'#94705a')
    blink=1.0
    if phase=='greeting' and 1.3<local<2.6:
        blink=1-math.sin(math.pi*(local-1.3)/1.3)**2
    elif t%6.8>6.25:
        blink=1-math.sin(math.pi*(t%6.8-6.25)/.55)**2
    gaze=-1.2 if phase=='curious' else math.sin(t*.45)*(1-depth)*.65
    for x in (-16,16):
        if blink<.15:
            hl([(x-7,-11),(x,-8.5),(x+7,-11)],'#a4c7d5',1.3)
        else:
            height=max(2.3,8.2*blink)
            he((x-7.5,-12-height,x+7.5,-12+height),'#15232a')
            he((x-6.3,-12-height+.8,x+6.3,-12+height-.8),'#91bdd5')
            he((x-4.4,-12-height+2,x+4.4,-12+height-.6),'#679ab9')
            he((x-2.8+gaze,-12-height+1,x+2.8+gaze,-12+height-.7),'#14252e')
            if blink>.6:
                he((x-4,-18,x-.3,-14),'#f4fcff')
                he((x+2,-9,x+4,-7),'#cbe8ef')
    hp([(-4,1),(4,1),(0,5)],'#1e1c1c')
    hl([(0,5),(0,8),(-5,10)],'#211d1c',.8)
    hl([(0,8),(5,10)],'#211d1c',.8)
    for sign in (-1,1):
        for y,dy in ((7,-3),(12,0),(16,3)):
            hl([(sign*22,y),(sign*43,y+dy)],'#c8b9a7',.65)
    # Only the head turns: a curious tilt, followed by a look back on return.
    tilt=math.sin(min(1,local)*math.pi)*13 if phase=='curious' else math.sin(local*1.8)*3 if phase=='idle' else math.sin(progress*math.pi)*-8 if phase=='returning' else 0
    if abs(tilt)>.1:head=head.rotate(tilt,resample=Image.Resampling.BICUBIC,center=point(0,-10))
    image=Image.alpha_composite(image,head)
    d,ellipse,line,polygon=tools(image)
    # Momo touches the glass with ONE paw, then holds it and slow-blinks.
    grooming=phase=='idle' and 10.2<t%14<11.6
    if phase=='greeting' or grooming:
        lift=(min(1,local/.55) if phase=='greeting' else math.sin((t%14-10.2)/1.4*math.pi))
        tap=math.sin(local*12)*1.6*max(0,1-local/1.1) if phase=='greeting' else 0
        px=36 if not grooming else 18
        py=53-31*ease(lift)+tap
        ellipse((px-11,py-10,px+10,py+13),dark,edge)
        ellipse((px-4.5,py+1,px+4,py+9),'#8a645e')
        for dx,dy in ((-5,-4),(0,-6),(5,-4)):ellipse((px+dx-2,py+dy-2,px+dx+2,py+dy+2),'#a17b72')
        ellipse((-27,48,-10,72),fur,edge)
    else:
        for x in (-18,18):ellipse((x-8,48,x+8,72),fur,edge)
    if phase=='greeting' and .25<local<.9:
        radius=9+(local-.25)*14
        ellipse((36-radius,23-radius,36+radius,23+radius),None,'#c3dad8',.6)
    glass=Image.new('RGBA',image.size)
    ImageDraw.Draw(glass).line((29,25,54,77),fill=(255,255,255,round(22+30*depth)),width=4)
    image=Image.alpha_composite(image,glass)
    if depth<.2:
        d=ImageDraw.Draw(image)
        d.text((240,428),'Момо',font=font(12,'bold'),fill='#697d7d',anchor='mt')
        d.text((240,462),'Любопытный тихоня',font=font(8),fill='#8a9994',anchor='mb')
    return image.convert('RGB').resize((240,240),Image.Resampling.LANCZOS)


def play_pet(host,token,pet,stop,report=print,on_stats=None):
    connection=None;frames=0
    try:
        while not stop.is_set():
            started=time.monotonic()
            try:
                if connection is None:
                    connection=CubeConnection(host,token,modern=True)
                    report('Питомец · '+pet.status()['name'])
                pet.activate_pending()
                image=pet.image()
                if connection.flags & 1:
                    payload=encode_jpeg(image,connection.max_jpeg,80,edge=120)[0]
                    stats=connection.send_jpeg(payload)
                else:stats=connection.send(rgb565(image))
                frames+=1
                if on_stats:on_stats(dict(stats,widget='pet',frames=frames,resolution=120 if connection.flags & 1 else 240,
                                          phase=pet.status()['phase'],pet_character=pet.status()['id'],updated_at=time.time()))
                wait_frame(stop,max(0,1/FPS-(time.monotonic()-started)))
            except OSError:
                if connection:connection.close()
                connection=None
                report('Связь прервалась. Повторное подключение через 2 секунды…')
                stop.wait(2)
    finally:
        if connection:connection.close()
