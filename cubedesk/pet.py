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


def ease(value):
    value=max(0,min(1,value))
    return value*value*(3-2*value)


class PetState:
    def __init__(self, now=None):
        self.lock=threading.RLock()
        self.epoch=time.monotonic() if now is None else now
        self.called_at=None
        self.start_depth=0.0
        self.pending=False
        self.calls=0
        self.generation=0
        self.cached_key=None
        self.cached_image=None

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
            if pose['phase']=='greeting':
                self.called_at=now-APPROACH  # Stay at the glass a little longer.
            elif pose['phase']!='approaching':
                self.start_depth=pose['depth'];self.called_at=now
            self.pending=False;self.generation+=1

    def pose(self, now=None):
        now=time.monotonic() if now is None else now
        with self.lock:
            elapsed=now-self.called_at if self.called_at is not None else float('inf')
            if elapsed<APPROACH:
                phase='approaching';depth=self.start_depth+(1-self.start_depth)*ease(elapsed/APPROACH)
            elif elapsed<APPROACH+HOLD:
                phase='greeting';depth=1.0
            elif elapsed<APPROACH+HOLD+RETURN:
                phase='returning';depth=1-ease((elapsed-APPROACH-HOLD)/RETURN)
            else:phase='idle';depth=0.0
            return {'phase':phase,'depth':depth,'time':now-self.epoch}

    def status(self):
        with self.lock:
            pose=self.pose()
            return {'phase':pose['phase'],'label':'Зову…' if self.pending else LABELS[pose['phase']],
                    'pending':self.pending,'calls':self.calls}

    def image(self, now=None):
        now=time.monotonic() if now is None else now
        with self.lock:
            key=(self.generation,int(now*FPS))
            if key!=self.cached_key:
                self.cached_image=render_pet(self.pose(now));self.cached_key=key
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


def render_pet(pose):
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


def play_pet(host,token,pet,stop,report=print,on_stats=None):
    connection=None;frames=0
    try:
        while not stop.is_set():
            started=time.monotonic()
            try:
                if connection is None:
                    connection=CubeConnection(host,token,modern=True)
                    report('Питомец · Моти')
                pet.activate_pending()
                image=pet.image()
                if connection.flags & 1:
                    payload=encode_jpeg(image,connection.max_jpeg,80,edge=120)[0]
                    stats=connection.send_jpeg(payload)
                else:stats=connection.send(rgb565(image))
                frames+=1
                if on_stats:on_stats(dict(stats,widget='pet',frames=frames,resolution=120 if connection.flags & 1 else 240,
                                          phase=pet.status()['phase'],updated_at=time.time()))
                wait_frame(stop,max(0,1/FPS-(time.monotonic()-started)))
            except OSError:
                if connection:connection.close()
                connection=None
                report('Связь прервалась. Повторное подключение через 2 секунды…')
                stop.wait(2)
    finally:
        if connection:connection.close()
