"""Real modular terrain and sprite assets for the coastal village.

Source PNGs are independent CC0 tiles/sprites, never crops of a map illustration.
The cached ground is assembled from world.json; objects remain separate layers.
"""
from functools import lru_cache
import colorsys
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps


ROOT = Path(__file__).with_name('resources')/'village'/'tiles'
TILE = 16
SEA = ('#2998b2', '#239fba', '#4e96a8', '#72a5b9')
PROPS = {'stall-mint','stall-rose','fountain','planter','lamp','sign','bench',
         'flowerbed','mailbox','crate','barrel','woodpile','fence','rowboat',
         'fishing-gear','well','orchard-tree'}


@lru_cache(maxsize=40)
def sheet(name):
    with Image.open(ROOT/(name+'.png')) as image:
        return image.convert('RGBA')


@lru_cache(maxsize=256)
def seasonal(image_name, season):
    image = sheet(image_name).copy()
    # Palette substitutions preserve the original pixel shading and transparency.
    palette = {}
    for color in set(image.getdata()):
        r,g,b,a = color
        if not a:
            palette[color] = color
            continue
        hue,sat,value = colorsys.rgb_to_hsv(r/255,g/255,b/255)
        if image_name == 'ground' and .10 < hue < .20 and sat > .22:
            # Warm soil instead of the source pack's bright yellow sand.
            r,g,b = (round(v*255) for v in colorsys.hsv_to_rgb(.108,sat*.72,min(1,value*.98)))
        elif .18 < hue < .49 and sat > .18:
            if season == 3:
                r,g,b = (round(v*255) for v in colorsys.hsv_to_rgb(.48,sat*.17,min(1,value*.66+.37)))
            elif season == 2:
                r,g,b = (round(v*255) for v in colorsys.hsv_to_rgb(.075+(hue-.18)*.12,sat*.85,value*.95))
            else:
                r,g,b = (round(v*255) for v in colorsys.hsv_to_rgb(hue+.008,min(1,sat*.98),min(1,value*1.05+.015)))
        elif value>.25 and season!=3:
            r,g,b = (round(v*255) for v in colorsys.hsv_to_rgb(hue,min(1,sat*1.07),min(1,value*1.04+.012)))
        palette[color] = r,g,b,a
    image.putdata([palette[color] for color in image.getdata()])
    return image


@lru_cache(maxsize=512)
def asset_sprite(name, season=0, frame=0):
    if name in PROPS:
        return handmade(name, season)
    image = seasonal(name,season)
    if name == 'tree':
        # Four original, aligned frames of the wind-blown tree.
        union = image.crop((0,0,192,192)).getbbox()
        image = image.crop((frame%4*192,0,(frame%4+1)*192,192)).crop(union)
        factor = .46
    elif name == 'sheep':
        image = image.crop((frame%6*128,0,(frame%6+1)*128,128))
        image = image.crop((32,35,96,96))
        factor = .36
    else:
        image = image.crop(image.getbbox())
        factor = .50 if name.startswith('house-') else .42 if name=='inn' else .43 if name=='tower' else .44
        if name.startswith('deco-'):
            factor = .6
    return image.resize((max(1,round(image.width*factor)),max(1,round(image.height*factor))),Image.Resampling.NEAREST)


@lru_cache(maxsize=96)
def handmade(name, season):
    """Small original props, authored independently in the pack's pixel palette."""
    sizes={'stall-mint':(40,32),'stall-rose':(40,32),'fountain':(34,25),
           'planter':(13,12),'lamp':(9,30),'sign':(17,20),'bench':(25,17),
           'flowerbed':(24,14),'mailbox':(16,23),'crate':(17,15),'barrel':(16,21),
           'woodpile':(24,16),'fence':(32,15),'rowboat':(41,23),
           'fishing-gear':(25,23),'well':(28,35),'orchard-tree':(44,54)}
    image=Image.new('RGBA',sizes[name]); d=ImageDraw.Draw(image)
    dark='#574c46';wood='#a3734e';light='#e3bd85'
    if name.startswith('stall'):
        cloth='#76ad97' if name.endswith('mint') else '#be8396'
        for x in (3,34):d.rectangle((x,8,x+2,30),fill=dark);d.rectangle((x,9,x+1,29),fill=wood)
        d.polygon([(5,0),(33,0),(39,12),(0,12)],fill=dark)
        for x in range(2,38,7):d.polygon([(max(5,x),1),(min(33,x+6),1),(x+6,11),(x,11)],fill=cloth if x%14==2 else '#ead4a2')
        d.rectangle((1,12,38,14),fill=dark)
        d.rectangle((4,22,35,29),fill=dark);d.rectangle((5,23,34,28),fill=wood)
        for x,c in [(9,'#e29c64'),(17,'#96ae64'),(25,'#d57573')]:
            d.rectangle((x,19,x+5,23),fill=c);d.point((x+1,19),fill='#f3dba1')
        d.line((6,25,33,25),fill=light)
    elif name=='fountain':
        d.ellipse((0,8,33,24),fill=dark);d.ellipse((1,6,32,22),fill='#a3aaa0')
        d.ellipse((4,9,29,19),fill='#447d91');d.arc((5,10,28,18),0,170,fill='#a2d9d2',width=2)
        d.rectangle((14,2,19,16),fill=dark);d.rectangle((15,1,18,14),fill='#c4c6a4')
        d.ellipse((10,0,23,5),fill='#c4c6a4');d.line((11,2,22,2),fill='#eff0ca')
    elif name=='lamp':
        d.rectangle((3,8,5,29),fill=dark);d.rectangle((2,27,6,29),fill=wood)
        d.rectangle((0,2,8,10),fill=dark);d.rectangle((2,3,6,8),fill='#f6d78b')
        d.line((1,1,7,1),fill=light)
    elif name=='sign':
        d.rectangle((7,6,9,19),fill=dark);d.rectangle((0,0,16,10),fill=dark)
        d.rectangle((1,1,15,8),fill=wood);d.line((3,3,12,3),fill=light);d.line((3,6,10,6),fill=light)
    elif name=='bench':
        d.rectangle((0,0,24,6),fill=dark);d.rectangle((1,1,23,5),fill=wood)
        d.rectangle((2,7,22,11),fill=dark);d.line((3,8,21,8),fill=light,width=2)
        for x in (4,19):d.rectangle((x,10,x+1,16),fill=dark)
    elif name=='flowerbed':
        petals=(('#f5a6c8','#b99ce9','#ffdc75'),('#e994bb','#d8b4f3','#fff0bb'),
                ('#edb35c','#d77e6d','#e0ac89'),('#dbeef0','#e4d4e7','#c4757b'))[season]
        for i in range(8):
            x=2+(i*7)%20;y=3+(i*5)%8
            d.line((x,y+2,x,y+4),fill='#4f8d57' if season!=3 else '#8aa9a1')
            d.rectangle((x-1,y,x+1,y+2),fill=petals[i%3]);d.point((x,y+1),fill='#fff3be')
    elif name=='mailbox':
        d.rectangle((6,11,8,22),fill=dark);d.rectangle((7,11,8,21),fill=wood)
        d.rounded_rectangle((0,2,14,13),3,fill='#425562');d.rectangle((1,4,13,11),fill='#69aeb1')
        d.line((3,7,9,7),fill='#345562',width=2);d.line((13,3,13,9),fill=light)
        d.rectangle((12,0,15,3),fill='#ed9b75')
    elif name=='crate':
        d.rectangle((0,1,16,14),fill=dark);d.rectangle((1,2,15,13),fill=wood)
        for y in (3,8,12):d.line((1,y,15,y),fill=light)
        d.line((2,2,14,13),fill='#d3a66d',width=2)
        for x in (2,14):d.line((x,2,x,13),fill='#73533e')
    elif name=='barrel':
        d.rounded_rectangle((1,1,14,20),4,fill=dark)
        d.rounded_rectangle((2,2,13,19),3,fill='#b18356')
        for x in (5,9):d.line((x,3,x,17),fill='#805b42')
        for y in (5,14):d.rectangle((1,y,14,y+2),fill='#718c8c')
        d.ellipse((2,0,13,4),fill='#c29b64',outline=dark)
    elif name=='woodpile':
        for x,y in ((0,7),(8,7),(16,7),(4,1),(12,1)):
            d.rectangle((x,y,x+7,y+7),fill='#6e513b')
            d.ellipse((x,y,x+6,y+7),fill='#c59762',outline=dark)
            d.ellipse((x+2,y+2,x+4,y+5),outline='#966b43')
    elif name=='fence':
        for y in (5,10):
            d.rectangle((0,y,31,y+2),fill=dark);d.line((0,y,31,y),fill='#d4ae73')
        for x in (2,16,28):
            d.polygon([(x-2,14),(x-2,2),(x,0),(x+2,2),(x+2,14)],fill=dark)
            d.line((x,2,x,13),fill='#d8b37a',width=2)
    elif name=='rowboat':
        d.ellipse((0,14,40,22),fill=(31,96,119,130))
        d.polygon([(0,8),(8,2),(34,2),(40,8),(33,18),(8,18)],fill=dark)
        d.polygon([(3,8),(9,4),(33,4),(37,8),(31,15),(10,15)],fill='#b27d50')
        d.polygon([(6,8),(11,6),(31,6),(34,8),(29,12),(12,12)],fill='#71513c')
        for x in (13,27):d.line((x,5,x,14),fill='#ddad71',width=2)
        d.line((5,1,30,17),fill='#dec191',width=2);d.line((28,15,33,19),fill='#ebd4a0',width=3)
    elif name=='fishing-gear':
        for x in range(1,21,4):d.line((x,3,min(24,x+8),19),fill='#c7b58a')
        for y in range(4,20,4):d.line((1,y,23,y),fill='#c7b58a')
        for x,color in ((4,'#f1d3a3'),(15,'#df8979')):
            d.ellipse((x,1,x+7,9),fill=dark);d.ellipse((x+1,2,x+6,8),fill=color)
        d.arc((4,12,21,22),0,320,fill='#b78c59',width=2)
    elif name=='well':
        d.ellipse((2,20,26,34),fill=dark);d.rectangle((3,21,25,28),fill='#a4b1a0')
        d.ellipse((3,17,25,28),fill='#c9d0ae',outline=dark)
        d.ellipse((6,20,22,26),fill='#356a80')
        for x in (5,22):d.rectangle((x,6,x+2,23),fill=dark);d.line((x+1,7,x+1,22),fill=wood)
        d.polygon([(0,9),(13,0),(27,9),(24,12),(3,12)],fill=dark)
        d.polygon([(2,8),(13,2),(25,8),(23,10),(4,10)],fill='#d78c70')
        d.line((8,9,20,9),fill='#f0b58a');d.line((15,12,15,23),fill='#e4ca8b')
    elif name=='orchard-tree':
        d.ellipse((7,45,38,53),fill=(65,88,58,100))
        d.rectangle((19,26,25,50),fill='#674b3c');d.line((21,28,21,48),fill='#aa7e51',width=2)
        patch=seasonal('deco-09',season);patch=patch.crop(patch.getbbox()).resize((32,28),Image.Resampling.NEAREST)
        for x,y in ((0,13),(12,13),(6,0)):image.alpha_composite(patch,(x,y))
        d=ImageDraw.Draw(image)
        if season!=3:
            for i,(x,y) in enumerate(((9,24),(20,13),(30,26),(15,33),(33,18),(12,16))):
                color=('#f4c580','#e9917d','#e5aa5c')[season%3]
                d.rectangle((x,y,x+2,y+2),fill=color);d.point((x,y),fill='#fff0bd')
    else:
        d.rectangle((1,6,11,11),fill=dark);d.rectangle((2,7,10,10),fill=wood)
        for x in (3,6,9):
            d.line((x,7,x,2),fill='#5a9652');d.rectangle((x-1,1,x+1,3),fill='#f5a6c8' if season!=3 else '#deede5')
    return image


@lru_cache(maxsize=256)
def ground_tile(material, col, row, season):
    image=seasonal('ground',season)
    offset=5 if material in ('sand','road') else 0
    tile=image.crop(((offset+col)*64,row*64,(offset+col+1)*64,(row+1)*64))
    if material=='road':
        # Reuse genuine sand edge tiles with an earthy path palette.
        tile=Image.blend(tile,Image.new('RGBA',tile.size,(177,142,98,255)),.23)
    elif material=='grass':
        alpha=tile.getchannel('A')
        grass=('#82bb60','#87b750','#c8a066','#deece7')[season]
        tile=Image.blend(tile,Image.new('RGBA',tile.size,grass),.27)
        tile.putalpha(alpha)
    return tile.resize((TILE,TILE),Image.Resampling.NEAREST)


def adjacent(rows,x,y,members):
    return 0<=y<len(rows) and 0<=x<len(rows[0]) and rows[y][x] in members


def nine_slice(rows,x,y,members):
    l,r,u,b=(adjacent(rows,x+dx,y+dy,members) for dx,dy in ((-1,0),(1,0),(0,-1),(0,1)))
    return (0 if not l else 2 if not r else 1),(0 if not u else 2 if not b else 1)


@lru_cache(maxsize=4)
def ground_layer(season):
    from cubedesk.village_map import game_map, SIZE
    rows=game_map().tiles
    image=Image.new('RGBA',SIZE,SEA[season]);d=ImageDraw.Draw(image)
    # Water texture is composed from repeating small pixels, not a world image.
    for y in range(2,SIZE[1],16):
        for x in range((y*7)%23,SIZE[0],37):
            d.line((x,y,x+5,y),fill=('#4aafbf','#4cb4c7','#70aeba','#8dbbca')[season])
    land=set('GSPCFBD')
    for y,row in enumerate(rows):
        for x,char in enumerate(row):
            if char not in land:continue
            if char in 'BD':continue
            material='sand' if char=='S' else 'grass'
            members=land if material=='sand' else land-{'S'}
            col,r=nine_slice(rows,x,y,members)
            image.alpha_composite(ground_tile(material,col,r,season),(x*TILE,y*TILE))
    # Paths and plaza are separate overlay tiles placed over the ground grid.
    for y,row in enumerate(rows):
        for x,char in enumerate(row):
            if char=='P':
                col,r=nine_slice(rows,x,y,set('PCBD'))
                image.alpha_composite(ground_tile('road',col,r,season),(x*TILE,y*TILE))
            elif char=='C':
                xx,yy=x*TILE,y*TILE
                d=ImageDraw.Draw(image)
                for py in range(yy,yy+TILE,4):
                    for px in range(xx-(2 if py%8 else 0),xx+TILE,8):
                        d.rounded_rectangle((max(xx,px),py,min(xx+15,px+6),py+2),1,fill='#b6ad89',outline='#9d9d7b')
            elif char=='F':
                xx,yy=x*TILE,y*TILE;d=ImageDraw.Draw(image)
                d.rectangle((xx,yy,xx+15,yy+15),fill='#946741')
                for py in range(yy+2,yy+TILE,5):d.line((xx,py,xx+15,py),fill='#bb8d57')
            elif char in 'BD':
                # A wooden deck tile, cut from the author's modular bridge set.
                area=(64,9,128,55) if char=='B' else (7,128,56,192)
                bridge=sheet('bridge').crop(area).resize((16,16),Image.Resampling.NEAREST)
                image.alpha_composite(bridge,(x*TILE,y*TILE))
    return image.convert('RGB')


@lru_cache(maxsize=1536)
def worker_sprite(look, color, moving, frame, facing):
    image=sheet('worker')
    row=1 if moving else 0
    image=image.crop((frame%6*192,row*192,(frame%6+1)*192,(row+1)*192))
    image=image.crop((57,61,135,135)).resize((27,26),Image.Resampling.NEAREST)
    # Preserve the frame's authored skin/hat shading; recolor only blue clothing.
    from PIL import ImageColor
    target=ImageColor.getrgb(color)
    pixels=[]
    for r,g,b,a in image.getdata():
        if b>r*1.10 and b>g*.97 and a:
            shade=(r+g+b)/(3*170)
            pixels.append((*[min(255,round(v*shade)) for v in target],a))
        else:pixels.append((r,g,b,a))
    image.putdata(pixels)
    if facing=='left':image=ImageOps.mirror(image)
    if look in ('fox','cat'):
        d=ImageDraw.Draw(image);fur='#c98b62' if look=='fox' else '#af8d7b'
        for x in (7,18):
            d.polygon([(x,8),(x+1,2),(x+5,8)],fill='#51453f');d.polygon([(x+1,7),(x+2,4),(x+4,7)],fill=fur)
        d.line((22,20,25,18,26,14),fill=fur,width=2)
    return image
