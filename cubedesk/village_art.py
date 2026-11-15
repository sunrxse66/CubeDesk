"""Scrolling pixel-art map for the shared coastal village."""
from functools import lru_cache
import math
import os
from pathlib import Path
import random

from PIL import Image, ImageColor, ImageDraw, ImageFont

from cubedesk.village import COLORS, HOMES, LOOKS, MINUTES_PER_SECOND, PLACES, STORIES
from cubedesk.village_map import game_map
from cubedesk.village_tiles import asset_sprite, ground_layer, worker_sprite


MAP_SIZE = (640, 512)
VIEW = 120
PALETTES = (
    ('#69a848', '#3d843d', '#a0bd55', '#315b3b', '#4b963e', '#9dcc5a', '#d9a451', '#398ca1'),
    ('#7da83b', '#548834', '#aabc4d', '#3a6934', '#5b9838', '#bbd45a', '#e5ac5d', '#368ba5'),
    ('#ad9355', '#987544', '#c5a760', '#845739', '#be7a43', '#e4a357', '#dcb070', '#548f9d'),
    ('#d4e4dd', '#b7d3d2', '#e9efe0', '#59828c', '#91afae', '#e2eee5', '#d4c5a2', '#6095ac'),
)
SHORE = [(0,354),(60,363),(119,370),(170,383),(217,406),(272,429),(335,449),
         (392,465),(460,459),(523,447),(582,433),(640,421)]
GARDEN = game_map().garden
RIVER = [(265,0),(261,76),(270,137),(267,203),(280,250),(293,311),(315,365),(338,449)]


def map_point(position):
    x, y = position
    return round(x * 2 + 20), round(y * 2 + 32)





def box(draw, x, y, width, height, color):
    draw.rectangle((x, y, x + width - 1, y + height - 1), fill=color)


def mix(color, other, amount):
    a = ImageColor.getrgb(color) if isinstance(color, str) else color
    b = ImageColor.getrgb(other) if isinstance(other, str) else other
    return tuple(round(x + (y - x)*amount) for x, y in zip(a, b))


# Legacy journal coordinates, used only to read snapshots from older versions.
ART_PLACES = {
    'lighthouse':(135,189), 'coast':(180,457), 'forest':(523,150),
    'square':(369,289), 'pier':(452,538), 'grove':(578,300), 'garden':(226,351),
    'market':(387,339), 'workshop':(491,253), 'inn':(390,200),
    'west_lane':(268,154), 'east_lane':(609,209), 'mill':(138,329),
    'orchard':(212,270), 'bridge':(322,339), 'beach':(258,482), 'pond':(596,421),
}
ART_WAYPOINTS = {(171,139):(428,405), (181,179):(451,480),
                 (182,59):(440,174), (194,43):(471,152),
                 (178,111):(451,313), (195,101):(491,279)}
LEGACY_COORDS = dict(zip(ART_PLACES,[(40,55),(77,154),(216,43),(144,89),(183,204),(260,106),
                                   (96,109),(150,110),(196,79),(153,60),(105,45),(246,63),
                                   (59,108),(68,85),(130,109),(110,175),(239,138)]))


def art_point(position):
    key = next((key for key,value in LEGACY_COORDS.items() if tuple(position)==value),None)
    raw = ART_PLACES[key] if key else ART_WAYPOINTS.get(tuple(position))
    if raw:
        return round(raw[0]*640/701),round(raw[1]*512/561)
    return map_point(position)


def actor_position(actor):
    if actor.get('coordinate_space')=='world' and actor.get('map_revision')!=game_map().revision:
        target=actor.get('target',actor.get('place'))
        if target in PLACES:
            return PLACES[target]
    points = [tuple(point) if actor.get('coordinate_space')=='world' else art_point(point) for point in actor.get('path',())]
    if not points:
        target = actor.get('target')
        return PLACES[target] if target in PLACES else art_point(actor['position'])
    if len(points)==1:
        return points[0]
    lengths = [math.dist(a,b) for a,b in zip(points,points[1:])]
    remaining = sum(lengths)*actor.get('travel_progress',1)
    for a,b,length in zip(points,points[1:],lengths):
        if remaining<=length:
            return tuple(round(x+(y-x)*remaining/max(1,length)) for x,y in zip(a,b))
        remaining -= length
    return points[-1]


@lru_cache(maxsize=4)
def map_layers(season):
    layers=[]
    for obj in game_map().objects:
        image=asset_sprite(obj.asset,season).convert('RGBA')
        layers.append((obj,image.convert('RGB'),image.getchannel('A')))
    return ground_layer(season),tuple(layers)


def terrain(season):
    floor,_=map_layers(season)
    return floor,game_map().water.point(lambda value:0 if value else 1)


ART_MAP = dict(PLACES)


def crop_garden(draw, growth, season):
    gx, gy, _, _ = GARDEN
    leaves = PALETTES[season][4]
    produce = ('#df7e8e','#e2bd55','#d6924b','#ece4ad')[season]
    for row in range(3):
        for col in range(6):
            index = row*6+col
            if growth <= index % 5:
                continue
            x,y = gx+5+col*10, gy+9+row*15
            box(draw,x,y-2,1,4,'#3e753d')
            box(draw,x-2,y-2,2,2,leaves)
            box(draw,x+1,y-3,2,2,leaves)
            if growth >= 8 + index % 4:
                box(draw,x-1,y-5,3,3,produce)
                box(draw,x-1,y-5,1,1,'#ffe7a8')


def sprite(draw, x, y, look, outfit, facing, stride=0):
    outline = '#4a3936'
    skin = {'wanderer':'#f0bf90','fox':'#db905a','cat':'#e0ba9e'}[look]
    draw.ellipse((x-5,y-2,x+5,y+1), fill='#695941')
    box(draw,x-5,y-12,10,10,outline)
    box(draw,x-4,y-12,8,7,outfit)
    box(draw,x+2,y-11,2,6,mix(outfit,'#423944',.3))
    box(draw,x-4,y-11,2,4,mix(outfit,'#fff0d0',.3))
    box(draw,x-3,y-13,6,2,'#f3cc9c')
    box(draw,x-3,y-4,3,3+max(stride,0),'#485169')
    box(draw,x+1,y-4,3,3+max(-stride,0),'#485169')
    box(draw,x-3,y-1+max(stride,0),3,1,'#503929')
    box(draw,x+1,y-1+max(-stride,0),3,1,'#503929')
    box(draw,x-6,y-22,12,10,outline)
    box(draw,x-5,y-21,10,8,skin)
    box(draw,x+3,y-20,2,7,mix(skin,'#976d60',.3))
    if look == 'wanderer':
        box(draw,x-5,y-23,10,5,'#714732')
        box(draw,x-4,y-22,6,2,'#9e6b43')
        box(draw,x-6,y-20,2,6,'#714732')
        if facing=='up':
            box(draw,x-5,y-21,10,8,'#714732')
    else:
        for offset in (-4,2):
            box(draw,x+offset,y-25,3,5,skin)
            box(draw,x+offset+1,y-24,1,2,'#ad7463')
        if look == 'fox':
            draw.line((x+3,y-5,x+8,y-5,x+10,y-8),fill=skin,width=2)
            box(draw,x+9,y-9,2,2,'#fae1c7')
    if facing != 'up':
        eyes = (-2,2) if facing == 'down' else (-3,) if facing == 'left' else (3,)
        for offset in eyes:
            box(draw,x+offset,y-17,1,2,outline)
        box(draw,x,y-14,1,1,'#a6725b')


def held_tool(draw, x, y, task, color, seconds):
    if task not in ('fish','tend','plant','harvest','gather','build','repair','restore','supplies'):
        return
    direction = -1 if task in ('plant','harvest') else 1
    hand_x = x+direction*9
    hand_y = y-14+round(math.sin(seconds*5))
    draw.line((x+direction*3,y-11,x+direction*6,y-12),fill=color,width=3)
    draw.line((x+direction*6,y-12,hand_x,hand_y),fill='#d8a677',width=2)
    box(draw,hand_x-1,hand_y-1,2,2,'#efc79b')
    if task == 'fish':
        draw.line((hand_x,hand_y,hand_x+12,hand_y-13),fill='#a96d48')
        draw.line((hand_x+12,hand_y-13,hand_x+14,y+7),fill='#f7e0b3')
        box(draw,hand_x+14,y+7,2,2,'#f09e78')
    elif task == 'tend':
        box(draw,hand_x+2,hand_y-3,7,5,'#6d97ad')
        draw.line((hand_x+8,hand_y-1,hand_x+13,hand_y-4),fill='#aad3dc',width=2)
        box(draw,hand_x+13,hand_y+2+int(seconds*6)%5,1,2,'#bfe5ef')
    elif task in ('harvest','plant','gather'):
        item_x = hand_x-5 if direction < 0 else hand_x+2
        box(draw,item_x,hand_y-3,5,5,'#a8774e')
        box(draw,item_x+1,hand_y-4,3,2,'#adc36a')
    else:
        tip_y = hand_y-6+round(math.sin(seconds*8)*2)
        draw.line((hand_x,hand_y,hand_x+3,tip_y),fill='#a77348',width=2)
        box(draw,hand_x+1,tip_y-1,6,3,'#bcc3c3')


@lru_cache(maxsize=1)
def dialogue_font():
    fonts = [Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/'segoeuib.ttf',
             'DejaVuSans.ttf']
    for name in fonts:
        try:
            return ImageFont.truetype(str(name),10)
        except OSError:
            continue
    return ImageFont.load_default(size=10)


def speech(draw, x, y, message):
    font = dialogue_font()
    width = min(VIEW-4, math.ceil(draw.textlength(message,font=font))+10)
    left = max(2, min(VIEW-width-2, x-width//2))
    top = max(2,min(VIEW-21, y-43))
    draw.rounded_rectangle((left,top,left+width,top+16),radius=3,fill='#fff0cd',outline='#604738')
    tail = min(left+width-5,max(left+5,x))
    draw.polygon([(tail-2,top+15),(tail+4,top+15),(tail+1,top+20)],fill='#fff0cd')
    draw.text((left+5,top+3),message,fill='#362b30',font=font,anchor='lt')


def event_props(draw, kind, seconds):
    x,y = ART_MAP[STORIES[kind].place]
    if kind in ('glow', 'festival'):
        for i in range(15):
            drift = seconds*(4+i%4)+i*13
            px = x - 24 + (i*17 % 52) + round(math.sin(drift*.12)*4)
            py = y+11-round(drift%35)
            box(draw,px,py,3,2,'#67ead7' if kind=='glow' else '#ffbd66')
            box(draw,px+1,py,1,1,'#fff6be')
    elif kind=='deer':
        box(draw,x+9,y-9,13,6,'#a46b44')
        box(draw,x+19,y-14,7,7,'#cc9865')
        draw.line((x+21,y-13,x+19,y-22,x+16,y-23),fill='#e4bd87')
        draw.line((x+23,y-14,x+25,y-22,x+28,y-24),fill='#e4bd87')
        for dx in (11,19):
            box(draw,x+dx,y-4,2,6,'#a46b44')
    elif kind=='kite':
        top = y-28+round(math.sin(seconds*2)*5)
        draw.polygon([(x+20,top-6),(x+26,top),(x+20,top+8),(x+15,top)], fill='#eaa15f')
        draw.line((x+20,top+8,x+23,top+15,x+17,top+19,x,y),fill='#eee3ba')
    elif kind=='boat':
        bx = x+22+round(5*math.sin(seconds*.9))
        draw.polygon([(bx-11,y+12),(bx+13,y+12),(bx+8,y+17),(bx-7,y+17)],fill='#965e46')
        draw.polygon([(bx,y-7),(bx,y+10),(bx-8,y+10)],fill='#f3deb0')
        draw.line((bx,y-7,bx,y+12),fill='#704c40')
    elif kind=='tracks':
        for i in range(7):
            box(draw,x+11+(i%2)*5,y+5+i*4,2,2,'#668298')
    elif kind=='letter':
        box(draw,x+9,y-6,9,6,'#f6dcad')
        draw.line((x+9,y-6,x+13,y-3,x+17,y-6),fill='#b68662')
    else:
        if kind=='guest':
            sprite(draw,x+15,y,'wanderer','#af9dcb','left')
        box(draw,x+21,y-9,5,8,'#986044')
        box(draw,x+22,y-8,3,5,'#fff0a4')


def camera_bounds(scene):
    x,y = actor_position(scene)
    left = max(0, min(MAP_SIZE[0]-VIEW, x-VIEW//2))
    lx,ly = ART_MAP['lighthouse']
    tower_room = max(0, 28 - abs(x-lx)//2 - abs(y-ly))
    top = max(0, min(MAP_SIZE[1]-VIEW, y-69-tower_room))
    return left,top,left+VIEW,top+VIEW


def map_annotations(image, scene):
    draw = ImageDraw.Draw(image)
    font = dialogue_font()
    for place, title in [('lighthouse','Маяк'),('market','Рынок'),('workshop','Мастерская'),
                         ('inn','Трактир'),('forest','Лесной дом'),('garden','Грядки'),('pier','Причал')]:
        x,y = ART_MAP[place]
        width = math.ceil(draw.textlength(title,font=font))+10
        top = {'garden':y+48,'pier':y+21,'market':y-41}.get(place,y-61)
        left = min(MAP_SIZE[0]-width-3,max(3,x-width//2))
        draw.rounded_rectangle((left,top,left+width,top+16),radius=3,fill='#efe0bc',outline='#7b6b55')
        draw.text((left+5,top+3),title,font=font,fill='#3d4036',anchor='lt')
    draw.rectangle(camera_bounds(scene),outline='#163c45',width=3)
    draw.rectangle(camera_bounds(scene),outline='#a9f3d9',width=1)
    x,y = actor_position(scene)
    draw.ellipse((x-4,y-4,x+4,y+4),fill='#fff0b0',outline='#554c39',width=2)


@lru_cache(maxsize=1)
def lantern_glow():
    image=Image.new('RGBA',(37,37));draw=ImageDraw.Draw(image)
    for radius in range(18,2,-2):
        draw.ellipse((18-radius,18-radius,18+radius,18+radius),fill=(255,196,97,3+(18-radius)*2))
    return image


def scene_life(frame, scene, bounds, seconds, night):
    """A few local animations; no additional world simulation or frame buffers."""
    left,top,right,bottom=bounds
    draw=ImageDraw.Draw(frame)
    flowers=[]
    for obj in game_map().objects:
        ox,oy,oright,obottom=obj.bounds
        if not (left-20<ox<right+20 and top-20<obottom<bottom+35):continue
        if obj.asset=='lamp' and night>.5:
            glow=lantern_glow()
            frame.paste(glow,((ox+oright)//2-left-18,oy-top-12),glow)
        if obj.asset=='flowerbed':flowers.append(obj)
    if scene['weather']=='clear' and scene['season'] in (0,1) and night<.55:
        for index,obj in enumerate(flowers[:3]):
            ox,oy,oright,obottom=obj.bounds
            phase=seconds*.75+ox*.07
            x=round((ox+oright)/2-left+math.sin(phase)*9)
            y=round(oy-top-5+math.cos(phase*.8)*5)
            wings=2 if int(seconds*7+index)%2 else 1
            color=('#ffe39b','#f3abd0','#adceee')[index%3]
            draw.line((x-wings,y-1,x-1,y+1),fill=color,width=2)
            draw.line((x+1,y+1,x+wings,y-1),fill=color,width=2)
            draw.point((x,y),fill='#635641')


def render_village(scene=None, overview=False, show_bounds=False):
    scene = scene or village_poster()
    season = scene['season']
    seconds = scene['minute']/MINUTES_PER_SECOND
    x,y = actor_position(scene)
    lx,ly = ART_MAP['lighthouse']
    bounds = (0,0,*MAP_SIZE) if overview else camera_bounds(scene)
    left,top,right,bottom = bounds
    base, material = terrain(season)
    world = base.copy()
    draw = ImageDraw.Draw(world)
    for i in range(24):
        px = left + (i*31+int(seconds*(3+i%3))) % (right-left)
        py = top + (i*23+int(seconds)) % (bottom-top)
        if material.getpixel((px,py)) == 0:
            box(draw,px,py,5+i%5,1,mix(PALETTES[season][-1],'#cde9cf',.42))
    crop_garden(draw,scene['garden'],season)
    for place,progress in scene.get('projects',{}).items():
        xx,yy = ART_MAP[place]
        if progress<3:
            box(draw,xx-8,yy+9,16,3,'#8e6244')
            for index in range(progress):
                box(draw,xx-6+index*5,yy+8,3,2,'#e8be79')
        elif place=='garden':
            glass = Image.new('RGBA',world.size)
            gd = ImageDraw.Draw(glass)
            gx,gy,garden_right,garden_bottom = GARDEN
            gd.polygon([(gx-3,gy),(gx+12,gy-18),(garden_right-12,gy-18),(garden_right+3,gy),
                        (garden_right+3,garden_bottom+3),(gx-3,garden_bottom+3)],fill=(156,217,212,60),outline=(227,244,221,230))
            for col in range(gx+12,garden_right,16):
                gd.line((col,gy-18,col,garden_bottom+3),fill=(222,243,226,180))
            world.paste(glass,mask=glass.getchannel('A'))
    home_x,home_y = ART_MAP[scene['profile']['home']]
    box(draw,home_x+11,home_y-7,4,5,'#9b5d45')
    box(draw,home_x+11,home_y-8,5,2,COLORS[scene['profile']['color']])
    for i in range(scene['improvements']):
        box(draw,home_x-19+i*6,home_y+5,4,4,'#a77550')
        box(draw,home_x-18+i*6,home_y+3,2,3,('#ebad6f','#e3bf75','#c9dd9e')[i%3])
    if scene['lantern']:
        box(draw,lx+16,ly-9,4,6,'#f5c374')
    if scene['day'] % 7 == 6 and 12 <= scene['hour'] < 19:
        sx,sy = ART_MAP['square']
        for offset, color in [(-21,'#c18d9b'),(14,'#79b19f')]:
            box(draw,sx+offset,sy-11,13,8,color)
            box(draw,sx+offset,sy-11,13,2,'#f0cb97')
            box(draw,sx+offset+2,sy-3,2,6,'#8f6444')
            box(draw,sx+offset+10,sy-3,2,6,'#8f6444')
    pier_x,pier_y = ART_MAP['pier']
    for repair in range(scene.get('pier_repairs',0)):
        row = pier_y-9+repair*10
        for side in (-9,8):
            box(draw,pier_x+side,row,2,7,'#684934')
            box(draw,pier_x+side-1,row-2,4,3,'#d2a879')

    night = (1-math.sin((scene['minute']%1440/1440-.25)*math.tau))/2
    if night > .12:
        world = Image.blend(world,Image.new('RGB',MAP_SIZE,'#223854'), .38*night)
        draw = ImageDraw.Draw(world)
    if night > .58:
        for hx,hy in (ART_MAP[key] for key in HOMES):
            for dx in (-14,10):
                box(draw,hx+dx,hy-18,5,5,'#e7ac61')
                box(draw,hx+dx+1,hy-18,1,4,'#ffdaa1')
        box(draw,lx-38,ly-80,11,5,'#f9d88c')
    if scene['active']:
        event_props(draw,scene['active'],seconds)
    dialogue = scene.get('dialogue')
    actors = []
    for resident in scene.get('residents', []):
        sx,sy = actor_position(resident)
        if not resident['moving']:
            sx,sy = game_map().nearest((sx+(-5 if resident['id'] in ('mila','taya','rina') else 5),sy))
        if scene['task'] in ('talk','trade') and dialogue and resident['id']==dialogue['resident']:
            sx,sy = game_map().nearest((x+16,y))
        if left-18 <= sx <= right+18 and top <= sy <= bottom+25:
            actors.append((sy,sx,resident))
    if scene['task']!='sleep' or scene['moving']:
        profile = scene['profile']
        actors.append((y,x,{'id':'hero','look':profile['look'],'color':COLORS[profile['color']],
                            'facing':scene.get('facing','down'),'moving':scene['moving'],'task':scene['task']}))
    for obj,image,mask in map_layers(season)[1]:
        ox,oy,oright,obottom=obj.bounds
        if oright>=left and ox<=right and obottom>=top and oy<=bottom:
            if obj.kind=='tree':
                image=asset_sprite(obj.asset,season,int(seconds*5+ox//13)%4)
                mask=image.getchannel('A')
                image=image.convert('RGB')
                if not overview and ox-6<x<oright+6 and oy+12<y<obj.depth:
                    # Fade only the crown hiding the hero, as in a tile RPG.
                    mask=mask.point(lambda alpha:round(alpha*.52))
            actors.append((obj.depth,ox,{'layer':(obj,image,mask)}))
    bubble = None
    for sy,sx,actor in sorted(actors,key=lambda entry: entry[0]):
        if 'layer' in actor:
            obj,layer,mask=actor['layer']
            if night>.12:
                layer=Image.blend(layer,Image.new('RGB',layer.size,'#223854'),.38*night)
            world.paste(layer,obj.bounds[:2],mask)
            detail=ImageDraw.Draw(world)
            ox,oy,oright,obottom=obj.bounds
            if obj.ident=='mill':
                cx,cy=(ox+oright)//2,oy+22
                for blade in range(4):
                    angle=seconds*.45+blade*math.pi/2
                    dx,dy=math.cos(angle),math.sin(angle)
                    tip=(round(cx+dx*26),round(cy+dy*26))
                    detail.line((cx,cy,*tip),fill='#665447',width=2)
                    detail.line((round(cx+dx*12-dy*2),round(cy+dy*12+dx*2),
                                 round(tip[0]-dy*2),round(tip[1]+dx*2)),fill='#dfd5ad',width=4)
                detail.ellipse((cx-2,cy-2,cx+2,cy+2),fill='#a2714a')
            if obj.ident=='beacon':
                cx=(ox+oright)//2
                detail.rectangle((cx-12,oy+12,cx+12,oy+28),fill='#594e44')
                detail.rectangle((cx-10,oy+14,cx+10,oy+25),fill='#ecce90' if night>.4 else '#99c0be')
                for dx in (-4,4):detail.line((cx+dx,oy+13,cx+dx,oy+27),fill='#74624b')
                detail.polygon([(cx-17,oy+12),(cx,oy+3),(cx+17,oy+12)],fill='#ad7759')
            if night>.58 and obj.asset.startswith('house-'):
                for wx in (ox+14,oright-17):
                    detail.rectangle((wx,obottom-25,wx+4,obottom-18),fill='#f5d392')
            if obj.asset.startswith('house-') and (6<=scene['hour']<11 or 17<=scene['hour']<23):
                chimney_x,chimney_y=oright-12,oy+23
                detail.rectangle((chimney_x-2,chimney_y-6,chimney_x+3,chimney_y+4),fill='#8e6a59')
                detail.line((chimney_x-3,chimney_y-6,chimney_x+4,chimney_y-6),fill='#c5a182',width=2)
                for puff in range(3):
                    age=(seconds*2+puff*7+ox*.11)%22
                    px=round(chimney_x+math.sin(seconds*.7+puff)*2+age*.15)
                    py=round(chimney_y-8-age)
                    radius=1+int(age/9)
                    detail.ellipse((px-radius,py-radius,px+radius,py+radius),fill='#aebcbd' if night>.5 else '#d1dcce')
            continue
        facing = 'left' if dialogue and actor['id'] == dialogue['resident'] else actor['facing']
        character=worker_sprite(actor['look'],actor['color'],actor['moving'],int(seconds*9)%6,facing)
        world.paste(character,(sx-character.width//2,sy-character.height+3),character)
        if not actor['moving']:
            task = {'Рыбачит':'fish','Ухаживает за растениями':'tend','Мастерит':'build'}.get(actor['task'],actor['task'])
            held_tool(draw,sx,sy,task,actor['color'],seconds)
        if not overview and dialogue and actor['id'] == dialogue['speaker'] and 5 <= sx-left <= VIEW-5 and 20 <= sy-top <= VIEW:
            bubble = sx-left,sy-top,dialogue['text']
    frame = world.crop(bounds)
    scene_life(frame,scene,bounds,seconds,night)
    if not overview and season in (0,1,2) and scene['weather']=='clear':
        breeze = ImageDraw.Draw(frame)
        for index in range(4):
            px = int(index*37+seconds*(3+index%2))%VIEW
            py = int(index*29+seconds*2+4*math.sin(seconds*.7+index))%VIEW
            color = ('#f2c1cd','#d4dca1','#dfb46d')[season]
            box(breeze,px,py,2,1,color)
    if scene['weather'] != 'clear':
        draw = ImageDraw.Draw(frame)
        rain = scene['weather']=='rain'
        for i in range(20):
            px = (i*47 + int(seconds*(13 if rain else 4))) % frame.width
            py = (i*31 + int(seconds*(48 if rain else 11))) % frame.height
            if rain:
                draw.line((px,py,px-1,py+3),fill='#9eb8ca')
            else:
                box(draw,px,py,1,1,'#e8f0e8')
    if bubble:
        speech(ImageDraw.Draw(frame),*bubble)
    if overview:
        if show_bounds:
            overlay=Image.new('RGBA',MAP_SIZE)
            od=ImageDraw.Draw(overlay)
            for obj in game_map().objects:
                if obj.solid:
                    od.rectangle(obj.solid,fill=(235,93,98,65),outline=(255,133,118,220))
            world_path=scene.get('path',()) if scene.get('coordinate_space')=='world' else ()
            if len(world_path)>1:
                od.line([tuple(p) for p in world_path],fill=(184,255,180,230),width=2)
            frame.paste(overlay,mask=overlay.getchannel('A'))
        map_annotations(frame,scene)
        return frame.resize((MAP_SIZE[0]*2,MAP_SIZE[1]*2),Image.Resampling.NEAREST)
    return frame.resize((240,240), Image.Resampling.NEAREST)


def village_poster(home='lighthouse', look='wanderer', color='mint'):
    home = home if home in HOMES else 'lighthouse'
    x,y = PLACES[home]
    return {'profile': {'home': home, 'look': look if look in LOOKS else 'wanderer',
                        'color': color if color in COLORS else 'mint'},
            'minute': 640, 'day': 1, 'hour': 10, 'season': 0, 'position': (x-5,y+4), 'task': 'arrive', 'moving': False,
            'target':home,'path':(PLACES[home],),'travel_progress':1,
            'coordinate_space':'world',
            'map_revision':game_map().revision,
            'improvements': 0, 'garden': 10, 'lantern': False, 'weather': 'clear', 'active': None}
