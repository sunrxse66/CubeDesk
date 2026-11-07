"""Scrolling pixel-art map for the shared coastal village."""
from functools import lru_cache
import math
import os
from pathlib import Path
import random

from PIL import Image, ImageColor, ImageDraw, ImageFont

from cubedesk.village import COLORS, HOMES, LOOKS, MINUTES_PER_SECOND, PLACES, ROADS, STORIES, road_points


MAP_SIZE = (420, 350)
VIEW = 120
PALETTES = (
    ('#69a848', '#3d843d', '#a0bd55', '#315b3b', '#4b963e', '#9dcc5a', '#d9a451', '#398ca1'),
    ('#7da83b', '#548834', '#aabc4d', '#3a6934', '#5b9838', '#bbd45a', '#e5ac5d', '#368ba5'),
    ('#ad9355', '#987544', '#c5a760', '#845739', '#be7a43', '#e4a357', '#dcb070', '#548f9d'),
    ('#d4e4dd', '#b7d3d2', '#e9efe0', '#59828c', '#91afae', '#e2eee5', '#d4c5a2', '#6095ac'),
)
SHORE = [(0, 213), (29, 217), (60, 231), (90, 239), (123, 239), (161, 249),
         (195, 266), (224, 285), (275, 303), (323, 299), (371, 315), (420, 324)]
GARDEN = (230, 242, 286, 272)


def map_point(position):
    x, y = position
    return round(x * 1.6 + 22), round(y * 1.5 + 36)


MAP_PLACES = {place: map_point(pos) for place, pos in PLACES.items()}


def box(draw, x, y, width, height, color):
    draw.rectangle((x, y, x + width - 1, y + height - 1), fill=color)


def mix(color, other, amount):
    a = ImageColor.getrgb(color) if isinstance(color, str) else color
    b = ImageColor.getrgb(other) if isinstance(other, str) else other
    return tuple(round(x + (y - x)*amount) for x, y in zip(a, b))


def planks(draw, x, y, width, height, color, dark, step=4):
    box(draw, x, y, width, height, color)
    for row in range(y + step - 1, y + height, step):
        draw.line((x, row, x + width - 1, row), fill=dark)


def fence(draw, x, y, count):
    for row in (y - 7, y - 3):
        box(draw, x, row, (count - 1)*8 + 3, 2, '#6d4b34')
        box(draw, x, row, (count - 1)*8 + 3, 1, '#a87648')
    for index in range(count):
        px = x + index*8
        box(draw, px, y - 10, 3, 12, '#604632')
        box(draw, px, y - 10, 2, 10, '#b98655')
        box(draw, px, y - 11, 3, 1, '#d09e64')


def tree(draw, x, y, palette, rng, tall=False):
    _, grass_shade, _, dark, leaves, shine, _, _ = palette
    height = 34 if tall else 25
    radius = 12 if tall else 10
    draw.ellipse((x-9, y-4, x+13, y+3), fill=grass_shade)
    box(draw, x-2, y-13, 5, 15, '#65412f')
    box(draw, x-2, y-12, 2, 12, '#a87445')
    canopy = (x-radius, y-height, x+radius, y-8)
    draw.ellipse(canopy, fill=dark)
    for ox, oy in [(-4,5),(3,4),(-4,11),(2,10)]:
        draw.ellipse((x+ox-radius//2-2, y-height+oy-4, x+ox+radius//2, y-height+oy+5), fill=leaves)
    for _ in range(28 if tall else 20):
        dx = rng.randrange(-radius+2, radius-2)
        dy = rng.randrange(3, height-11)
        if (dx/radius)**2 + ((dy-(height-8)/2)/((height-8)/2))**2 < .83:
            color = rng.choice((mix(shine, leaves, .45), leaves, mix(dark, leaves, .44)))
            box(draw, x+dx, y-height+dy, rng.choice((1,2,3)), 2, color)


def cottage(draw, x, y, roof, winter):
    dark_roof = mix(roof, '#2d283a', .52)
    ridge = '#eef1e3' if winter else mix(roof, '#ffe0ad', .34)
    box(draw, x-23, y-4, 49, 4, '#695744')
    box(draw, x-21, y-25, 43, 22, '#644331')
    planks(draw, x-20, y-24, 40, 19, '#b7804d', '#97603d')
    box(draw, x+18, y-23, 3, 19, '#825237')
    draw.polygon([(x-25,y-24),(x-25,y-32),(x-17,y-45),(x+17,y-45),
                  (x+25,y-32),(x+25,y-24)], fill=dark_roof)
    draw.polygon([(x-23,y-25),(x-23,y-32),(x-15,y-44),(x+15,y-44),
                  (x+23,y-32),(x+23,y-25)], fill=roof)
    for row in range(0, 4):
        yy = y - 40 + row*4
        inset = max(0, 7 - row*3)
        draw.line((x-22+inset, yy, x+22-inset, yy), fill=dark_roof)
        for col in range(x-16 + row%2*3, x+20-inset, 7):
            draw.line((col, yy-2, col, yy), fill=dark_roof)
    draw.line((x-16, y-44, x+16, y-44), fill=ridge, width=2)
    if winter:
        draw.line((x-16,y-44,x-23,y-33), fill=ridge, width=2)
        draw.line((x+16,y-44,x+23,y-33), fill=ridge, width=2)
    box(draw, x+12, y-49, 6, 10, '#7c554e')
    box(draw, x+11, y-50, 8, 3, '#b9896d')
    box(draw, x-5, y-20, 11, 16, '#54382d')
    box(draw, x-3, y-18, 7, 13, '#784f37')
    box(draw, x+2, y-12, 1, 2, '#e4b96a')
    for offset in (-15, 9):
        box(draw, x+offset, y-19, 8, 9, '#694934')
        box(draw, x+offset+1, y-18, 6, 6, '#81a4a5')
        box(draw, x+offset+3, y-18, 1, 6, '#e7b986')
    box(draw, x-7, y-4, 15, 2, '#d6ae77')
    box(draw, x-9, y-2, 19, 2, '#a9885f')


@lru_cache(maxsize=4)
def terrain(season):
    palette = PALETTES[season]
    grass, deep, tip, _, _, _, sand, water = palette
    image = Image.new('RGB', MAP_SIZE, water)
    mask = Image.new('L', MAP_SIZE)
    draw = ImageDraw.Draw(image)
    ground = ImageDraw.Draw(mask)
    dry_land = [(x, y-13) for x, y in SHORE]
    for border, color, material in [(SHORE, '#e7cc91', 2), (dry_land, grass, 1)]:
        area = [(0,0),(MAP_SIZE[0],0), *reversed(border)]
        draw.polygon(area, fill=color)
        ground.polygon(area, fill=material)
    draw.line(SHORE, fill=mix(water, '#e3f1ce', .67), width=2)

    plaza = MAP_PLACES['square']
    for origin, destination in ROADS:
        points = [map_point(point) for point in road_points(origin,destination)]
        draw.line(points, fill=mix(deep, sand, .33), width=15)
        draw.line(points, fill=sand, width=12)
        ground.line(points, fill=3, width=13)
    px, py = plaza
    draw.ellipse((px-21,py-13,px+21,py+13), fill=sand)
    ground.ellipse((px-21,py-13,px+21,py+13), fill=3)

    rng = random.Random(31)
    for y in range(3, MAP_SIZE[1], 4):
        for x in range(3, MAP_SIZE[0], 4):
            dx, dy = x+rng.randrange(-2,2), y+rng.randrange(-2,2)
            if dx >= MAP_SIZE[0] or dy >= MAP_SIZE[1]:
                continue
            kind = mask.getpixel((dx,dy))
            if kind == 1:
                shade = rng.choice((deep, tip, mix(deep, grass, .56), mix(tip, grass, .64)))
                if dx > 2 and mask.getpixel((dx-2,dy)) == 3:
                    shade = mix(grass, sand, .64)
                box(draw,dx,dy,rng.choice((1,1,2)),1,shade)
                if rng.random() < .31:
                    draw.line((dx+1,dy-2,dx+1,dy),fill=shade)
            elif kind in (2, 3) and rng.random() < .37:
                edge = dx > 1 and mask.getpixel((dx-1,dy)) == 1
                box(draw,dx,dy,2,1,mix(sand, grass, .56) if edge else mix(sand, '#7b6b54', rng.uniform(.12,.28)))
            elif kind == 0 and rng.random() < .12:
                box(draw,dx,dy,3,1,mix(water, '#d5e7c7', .19))

    trees = [(36,58),(60,104),(52,145),(74,119),(192,75),(174,45),(217,105),(218,70),(255,117),
             (270,77),(305,69),(321,104),(337,121),(348,88),(378,109),(386,76),(402,130),(361,146),
             (334,169),(355,196),(393,188),(369,219),(338,235),(367,263),(400,253),(305,257),
             (300,282),(270,293),(211,233),(174,225),(121,156),(169,151),(94,95),(26,166),
             (59,161),(176,166),(273,162),(346,150),(236,215),(205,253)]
    for x,y in sorted(trees, key=lambda p: p[1]):
        tree(draw, x,y,palette,rng,tall=rng.choice((True,True,False)))
    for x,y in [(62,169),(116,201),(130,141),(162,105),(228,187),(284,192),(320,146),(275,214),(306,139)]:
        draw.ellipse((x-4,y-4,x+5,y+2), fill=deep)
        for ox,oy in [(0,-3),(-3,-1),(4,0)]:
            box(draw,x+ox,y+oy,2,2,rng.choice(('#f5d891','#ecabc5','#eff1dd')))
    lx, ly = MAP_PLACES['lighthouse']
    tx = lx-32
    box(draw,tx-7,ly-69,15,63,'#a6988c')
    box(draw,tx-7,ly-69,11,63,'#eee0bc')
    for yy in (ly-58,ly-36):
        box(draw,tx-7,yy,15,8,'#b45e53')
        box(draw,tx-7,yy,10,8,'#cc7861')
    box(draw,tx-10,ly-72,21,4,'#82645b')
    box(draw,tx-8,ly-82,17,11,'#4d535b')
    box(draw,tx-6,ly-81,13,7,'#d9c585')
    draw.polygon([(tx-11,ly-82),(tx,ly-94),(tx+11,ly-82)],fill='#9a5b59')
    box(draw,tx-3,ly-18,6,12,'#725447')
    for key, roof in [('lighthouse','#a95e55'),('coast','#5d8098'),('forest','#65874a')]:
        x,y = MAP_PLACES[key]
        cottage(draw,x,y,roof,season==3)
        fence(draw,x+27,y-6,3)
        planks(draw,x-25,y-10,6,6,'#be925d','#79563c',2)
        box(draw,x+15,y-3,8,3,'#6f553d')
        for i in range(3):
            box(draw,x+16+i*2,y-6,1,3,PALETTES[season][4])
            box(draw,x+16+i*2,y-7,1,1,('#f6ce80','#edd2dd','#edac89')[i])
    for key, roof in [('west_lane','#8d747e'),('east_lane','#537f77'),
                      ('workshop','#8e6c55'),('inn','#946595')]:
        x,y = MAP_PLACES[key]
        cottage(draw,x,y,roof,season==3)
        if key == 'workshop':
            for i in range(4):
                planks(draw,x+24,y-13+i*3,12,3,'#bf925d','#67483a',2)
            box(draw,x-12,y-10,7,5,'#474c58')
        elif key == 'inn':
            box(draw,x+8,y-11,12,7,'#a57447')
            box(draw,x+10,y-10,8,5,'#f3c985')
            box(draw,x+11,y-9,3,3,'#a7644b')
    mx,my = MAP_PLACES['market']
    for offset, color in [(-13,'#db8d69'),(13,'#80bca1')]:
        sx = mx+offset
        for post in (-8,8):
            box(draw,sx+post,my-22,2,24,'#765139')
        box(draw,sx-9,my-19,20,6,color)
        for stripe in range(3):
            box(draw,sx-7+stripe*6,my-19,3,6,'#ffdda4')
        planks(draw,sx-9,my-5,20,6,'#ad804b','#714e37',3)
        for i in range(4):
            box(draw,sx-7+i*4,my-8,3,3,('#b86662','#d6be55','#8eb269','#efd49a')[i])
    coast_x, coast_y = MAP_PLACES['coast']
    planks(draw,coast_x-37,coast_y+5,10,6,'#a97e52','#79543e',3)
    box(draw,coast_x-35,coast_y+6,6,2,'#7198a0')

    x,y = MAP_PLACES['pier']
    planks(draw,x-7,y-17,14,34,'#a7764d','#795339',3)
    for offset in (-5,4):
        box(draw,x+offset,y+10,2,11,'#604937')
        box(draw,x+offset,y-16,2,2,'#e4b67f')
    box(draw,px-4,py-14,2,10,'#6b4a36')
    box(draw,px-8,py-14,12,4,'#9d6c40')
    box(draw,px-6,py-13,8,1,'#d8ac68')
    gx, gy, right, bottom = GARDEN
    box(draw,gx,gy,right-gx,bottom-gy,'#785239')
    for row in range(3):
        box(draw,gx+2,gy+2+row*9,right-gx-4,7,'#9d6843')
        draw.line((gx+2,gy+8+row*9,right-3,gy+8+row*9), fill='#815138')
    fence(draw,gx-2,bottom+3,8)
    planks(draw,gx-10,gy+6,7,9,'#c09258','#815734',3)
    return image, mask


def crop_garden(draw, growth, season):
    gx, gy, _, _ = GARDEN
    leaves = PALETTES[season][4]
    produce = ('#df7e8e','#e2bd55','#d6924b','#ece4ad')[season]
    for row in range(3):
        for col in range(6):
            index = row*6+col
            if growth <= index % 5:
                continue
            x,y = gx+5+col*8, gy+5+row*9
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
    box(draw,x-4,y-10,8,8,outline)
    box(draw,x-3,y-10,6,5,outfit)
    box(draw,x-3,y-4,3,3+max(stride,0),'#485169')
    box(draw,x+1,y-4,3,3+max(-stride,0),'#485169')
    box(draw,x-3,y-1+max(stride,0),3,1,'#503929')
    box(draw,x+1,y-1+max(-stride,0),3,1,'#503929')
    box(draw,x-5,y-17,10,7,outline)
    box(draw,x-4,y-17,8,6,skin)
    if look == 'wanderer':
        box(draw,x-4,y-18,8,3,'#714732')
        box(draw,x-5,y-16,2,3,'#714732')
    else:
        for offset in (-4,2):
            box(draw,x+offset,y-20,3,5,skin)
            box(draw,x+offset+1,y-19,1,2,'#ad7463')
        if look == 'fox':
            draw.line((x+3,y-5,x+8,y-5,x+10,y-8),fill=skin,width=2)
            box(draw,x+9,y-9,2,2,'#fae1c7')
    if facing != 'up':
        eyes = (-2,2) if facing == 'down' else (-3,) if facing == 'left' else (3,)
        for offset in eyes:
            box(draw,x+offset,y-14,1,1,outline)


def held_tool(draw, x, y, task, color, seconds):
    if task not in ('fish','tend','plant','harvest','gather','build','repair'):
        return
    direction = -1 if task in ('plant','harvest') else 1
    hand_x = x+direction*9
    hand_y = y-12+round(math.sin(seconds*5))
    draw.line((x+direction*3,y-9,x+direction*6,y-10),fill=color,width=3)
    draw.line((x+direction*6,y-10,hand_x,hand_y),fill='#d8a677',width=2)
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
    x,y = MAP_PLACES[STORIES[kind].place]
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


def render_village(scene=None):
    scene = scene or village_poster()
    season = scene['season']
    seconds = scene['minute']/MINUTES_PER_SECOND
    x,y = map_point(scene['position'])
    left = max(0, min(MAP_SIZE[0]-VIEW, x-VIEW//2))
    lx,ly = MAP_PLACES['lighthouse']
    tower_room = max(0, 28 - abs(x-lx)//2 - abs(y-ly))
    top = max(0, min(MAP_SIZE[1]-VIEW, y-69-tower_room))
    bounds = (left, top, left+VIEW, top+VIEW)
    base, material = terrain(season)
    world = base.copy()
    draw = ImageDraw.Draw(world)
    for i in range(24):
        px = left + (i*31+int(seconds*(3+i%3))) % VIEW
        py = top + (i*23+int(seconds)) % VIEW
        if material.getpixel((px,py)) == 0:
            box(draw,px,py,5+i%5,1,mix(PALETTES[season][-1],'#cde9cf',.42))
    crop_garden(draw,scene['garden'],season)
    home_x,home_y = MAP_PLACES[scene['profile']['home']]
    box(draw,home_x+11,home_y-7,4,5,'#9b5d45')
    box(draw,home_x+11,home_y-8,5,2,COLORS[scene['profile']['color']])
    for i in range(scene['improvements']):
        box(draw,home_x-19+i*6,home_y+5,4,4,'#a77550')
        box(draw,home_x-18+i*6,home_y+3,2,3,('#ebad6f','#e3bf75','#c9dd9e')[i%3])
    if scene['lantern']:
        box(draw,lx+16,ly-9,4,6,'#f5c374')
    if scene['day'] % 7 == 6 and 12 <= scene['hour'] < 19:
        sx,sy = MAP_PLACES['square']
        for offset, color in [(-21,'#c18d9b'),(14,'#79b19f')]:
            box(draw,sx+offset,sy-11,13,8,color)
            box(draw,sx+offset,sy-11,13,2,'#f0cb97')
            box(draw,sx+offset+2,sy-3,2,6,'#8f6444')
            box(draw,sx+offset+10,sy-3,2,6,'#8f6444')
    pier_x,pier_y = MAP_PLACES['pier']
    for repair in range(scene.get('pier_repairs',0)):
        row = pier_y-9+repair*10
        for side in (-9,8):
            box(draw,pier_x+side,row,2,7,'#684934')
            box(draw,pier_x+side-1,row-2,4,3,'#d2a879')

    night = (1-math.sin((scene['minute']%1440/1440-.25)*math.tau))/2
    if night > .12:
        world = Image.blend(world,Image.new('RGB',MAP_SIZE,'#1b2949'), .48*night)
        draw = ImageDraw.Draw(world)
    if night > .58:
        for hx,hy in (MAP_PLACES[key] for key in HOMES):
            for dx in (-14,10):
                box(draw,hx+dx,hy-18,5,5,'#e7ac61')
                box(draw,hx+dx+1,hy-18,1,4,'#ffdaa1')
        box(draw,lx-38,ly-80,11,5,'#f9d88c')
    if scene['active']:
        event_props(draw,scene['active'],seconds)
    dialogue = scene.get('dialogue')
    actors = []
    for resident in scene.get('residents', []):
        sx,sy = map_point(resident['position'])
        if left-18 <= sx <= left+VIEW+18 and top <= sy <= top+VIEW+25:
            actors.append((sy,sx,resident))
    if scene['task']!='sleep' or scene['moving']:
        profile = scene['profile']
        actors.append((y,x,{'id':'hero','look':profile['look'],'color':COLORS[profile['color']],
                            'facing':scene.get('facing','down'),'moving':scene['moving'],'task':scene['task']}))
    bubble = None
    for sy,sx,actor in sorted(actors,key=lambda entry: entry[0]):
        facing = 'left' if dialogue and actor['id'] == dialogue['resident'] else actor['facing']
        stride = (1 if int(seconds*7)%2 else -1) if actor['moving'] else 0
        sprite(draw,sx,sy,actor['look'],actor['color'],facing,stride)
        if not actor['moving']:
            task = {'Рыбачит':'fish','Ухаживает за растениями':'tend','Мастерит':'build'}.get(actor['task'],actor['task'])
            held_tool(draw,sx,sy,task,actor['color'],seconds)
        if dialogue and actor['id'] == dialogue['speaker'] and 5 <= sx-left <= VIEW-5 and 20 <= sy-top <= VIEW:
            bubble = sx-left,sy-top,dialogue['text']
    frame = world.crop(bounds)
    if scene['weather'] != 'clear':
        draw = ImageDraw.Draw(frame)
        rain = scene['weather']=='rain'
        for i in range(20):
            px = (i*47 + int(seconds*(13 if rain else 4))) % VIEW
            py = (i*31 + int(seconds*(48 if rain else 11))) % VIEW
            if rain:
                draw.line((px,py,px-1,py+3),fill='#9eb8ca')
            else:
                box(draw,px,py,1,1,'#e8f0e8')
    if bubble:
        speech(ImageDraw.Draw(frame),*bubble)
    return frame.resize((240,240), Image.Resampling.NEAREST)


def village_poster(home='lighthouse', look='wanderer', color='mint'):
    home = home if home in HOMES else 'lighthouse'
    x,y = PLACES[home]
    return {'profile': {'home': home, 'look': look if look in LOOKS else 'wanderer',
                        'color': color if color in COLORS else 'mint'},
            'minute': 640, 'day': 1, 'hour': 10, 'season': 0, 'position': (x-5,y+4), 'task': 'arrive', 'moving': False,
            'improvements': 0, 'garden': 10, 'lantern': False, 'weather': 'clear', 'active': None}
