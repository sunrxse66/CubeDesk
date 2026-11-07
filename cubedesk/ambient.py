"""Looping nature scenes drawn on the PC for the cube's optical display."""
from functools import cache
import math
import random

from PIL import Image, ImageChops, ImageDraw, ImageFilter


SCENES = {
    'storm': 'Гроза',
    'fireflies': 'Светлячки',
    'aurora': 'Северное сияние',
    'jellyfish': 'Медузы',
}
SIZE = (240, 240)
POSTER_TIMES = {'storm': 3.2, 'fireflies': 2.0, 'aurora': 0.0, 'jellyfish': 1.0}


def coords(*values):
    return tuple(round(2 * value) for value in values)


def path(points):
    return [coords(x, y) for x, y in points]


def oval(draw, x, y, rx, ry, color):
    draw.ellipse(coords(x-rx, y-ry, x+rx, y+ry), fill=color)


def over(image, layer, blur=0):
    if blur:
        layer = layer.filter(ImageFilter.GaussianBlur(2 * blur))
    image.paste(layer, mask=layer.getchannel('A'))


@cache
def particles(seed, count):
    rng = random.Random(seed)
    return tuple(tuple(rng.random() for _ in range(5)) for _ in range(count))


@cache
def vignette():
    mask = Image.new('L', SIZE)
    values = []
    for y in range(SIZE[1]):
        for x in range(SIZE[0]):
            radius = math.hypot((x - 120) / 119, (y - 120) / 120)
            fade = max(0, min(1, (1 - radius) / 0.36))
            values.append(round(255 * fade * fade * (3 - 2 * fade)))
    mask.putdata(values)
    return mask.convert('RGB')


@cache
def storm_clouds():
    layer = Image.new('RGBA', SIZE)
    draw = ImageDraw.Draw(layer)
    for x, y, rx, ry, color in [
        (54, 41, 47, 14, (25, 37, 74, 182)),
        (75, 35, 27, 13, (37, 50, 87, 172)),
        (43, 33, 22, 11, (49, 58, 102, 184)),
        (60, 47, 40, 8, (9, 13, 25, 225)),
    ]:
        oval(draw, x, y, rx, ry, color)
    return layer.filter(ImageFilter.GaussianBlur(8))


def storm(image, t):
    over(image, storm_clouds())
    flash_age = t % 12 - 3
    flash = max(0, min(flash_age / 0.16, (0.7 - flash_age) / 0.54, 1))
    if flash:
        rng = random.Random(44 + int(t // 12) % 12)
        bolt = [(60 + rng.uniform(-5, 5) + i * 0.85, 35 + i * 6) for i in range(9)]
        branch = [bolt[3], (56, 59), (48, 68), (46, 76)]
        light = Image.new('RGBA', SIZE)
        draw = ImageDraw.Draw(light)
        oval(draw, 64, 39, 32, 18, (94, 117, 203, round(108 * flash)))
        draw.line(path(bolt), fill=(137, 154, 255, round(205 * flash)), width=11, joint='curve')
        draw.line(path(branch), fill=(126, 148, 255, round(150 * flash)), width=5)
        over(image, light, 4)
        draw = ImageDraw.Draw(image, 'RGBA')
        draw.line(path(bolt), fill=(199, 224, 255, round(250 * flash)), width=3, joint='curve')
        draw.line(path(branch), fill=(165, 191, 248, round(220 * flash)), width=2)

    draw = ImageDraw.Draw(image, 'RGBA')
    for seed, count, speed, length, opacity in [(2, 54, 34, 4, 73), (9, 33, 62, 8, 143)]:
        for u, v, pace, brightness, _ in particles(seed, count):
            y = (v * 112 + t * (speed + pace * 14)) % 112 + 5
            x = (u * 114 + y * 0.26 + 2 * math.sin(t * 0.5)) % 120
            tail = length * (0.75 + pace * 0.5)
            alpha = round(opacity * (0.5 + brightness * 0.5))
            draw.line(coords(x, y, x + tail * 0.26, y + tail), fill=(94, 152, 210, alpha), width=2)
    for u, v, offset, _, _ in particles(37, 9):
        progress = (t * 0.78 + offset) % 1
        x, y = 19 + 82*u, 90 + 16*v
        rx = 1 + 8 * progress
        draw.ellipse(coords(x-rx, y-rx/4, x+rx, y+rx/4), outline=(102, 161, 202, round(95 * (1-progress))), width=2)


@cache
def forest():
    image = Image.new('RGB', SIZE)
    mist = Image.new('RGBA', SIZE)
    draw = ImageDraw.Draw(mist)
    oval(draw, 60, 77, 42, 33, (17, 66, 53, 205))
    oval(draw, 57, 102, 49, 11, (21, 71, 52, 180))
    over(image, mist, 10)
    draw = ImageDraw.Draw(image, 'RGBA')
    for u, v, depth, _, _ in particles(15, 27):
        x, y = 5 + 110*u, 53 + 32*v
        height = 23 + 37*depth
        width = height * 0.23
        tree = [(x, y), (x-width*.5, y+height*.5), (x-width*.25, y+height*.45),
                (x-width, y+height*.86), (x-1, y+height*.81), (x-1, y+height),
                (x+1, y+height), (x+1, y+height*.83), (x+width, y+height*.89),
                (x+width*.25, y+height*.44), (x+width*.51, y+height*.5)]
        draw.polygon(path(tree), fill=(0, 9, 9, round(70 + 120*depth)))
    return image


def fireflies(image, t):
    image.paste(forest())
    haze = Image.new('RGBA', SIZE)
    light = ImageDraw.Draw(haze)
    sparks = []
    for u, v, pace, depth, phase in particles(3, 39):
        angle = t * (0.25 + pace * 0.5) + phase * math.tau
        x = 12 + 96*u + (3 + 8*depth) * math.sin(angle)
        y = 22 + 79*v + (3 + 6*depth) * math.cos(angle * 1.25)
        pulse = (0.5 + 0.5 * math.sin(angle * 2.6 + phase * 7)) ** 2
        intensity = pulse * (0.38 + 0.62*depth)
        radius = 0.45 + depth * 1.05
        oval(light, x, y, radius * 5, radius * 5, (157, 229, 102, round(129 * intensity)))
        sparks.append((x, y, radius, round(249 * intensity)))
    over(image, haze, 2.8)
    draw = ImageDraw.Draw(image, 'RGBA')
    for x, y, radius, alpha in sparks:
        oval(draw, x, y, radius, radius, (236, 255, 163, alpha))


def aurora(image, t):
    draw = ImageDraw.Draw(image, 'RGBA')
    for u, v, pulse, size, _ in particles(48, 47):
        alpha = round(76 + 73 * (0.5 + 0.5 * math.sin(t * 0.73 + pulse * math.tau)))
        oval(draw, 5 + 110*u, 14 + 82*v, 0.32 + size*0.35, 0.32 + size*0.35, (177, 202, 250, alpha))

    sky = Image.new('RGBA', SIZE)
    ribbons = ImageDraw.Draw(sky)
    for index, color in enumerate([(104, 71, 204), (36, 157, 189), (42, 226, 157)]):
        base = 35 + index*13
        line = [(x, base + 9*math.sin(x*0.056 - t*0.28 + index*0.7)
                 + 6*math.sin(x*0.112 + t*0.37 + index)) for x in range(-8, 135, 3)]
        for step in range(7, 0, -1):
            thickness = step * (2.5 + index * 0.35)
            upper = [(x+thickness*0.18, y-thickness*(0.78+0.22*math.cos(x*0.31-t*0.7))) for x, y in line]
            ribbons.polygon(path([*line, *reversed(upper)]), fill=(*color, 14 + (7-step)*18))
        ribbons.line(path(line), fill=(*color, 135), width=2, joint='curve')
    over(image, sky, 1.6)

    draw.polygon(path([(0, 103), (20, 87), (29, 92), (43, 78), (57, 94), (67, 87),
                       (80, 97), (96, 83), (120, 103), (120, 120), (0, 120)]), fill=(12, 21, 38, 248))
    draw.polygon(path([(0, 110), (29, 99), (40, 106), (57, 95), (66, 103), (82, 95),
                       (100, 105), (120, 98), (120, 120), (0, 120)]), fill=(2, 5, 12, 250))


@cache
def water_light():
    layer = Image.new('RGBA', SIZE)
    draw = ImageDraw.Draw(layer)
    oval(draw, 62, 45, 39, 49, (13, 37, 64, 159))
    for points in [[(48, -4), (56, -4), (39, 88), (21, 96)],
                   [(68, -3), (75, -4), (88, 85), (66, 91)]]:
        draw.polygon(path(points), fill=(33, 83, 118, 66))
    return layer.filter(ImageFilter.GaussianBlur(11))


def jellyfish(image, t):
    over(image, water_light())
    draw = ImageDraw.Draw(image, 'RGBA')
    for u, v, pace, depth, _ in particles(62, 37):
        y = 10 + (110*v - t*(2 + 4*pace)) % 108
        x = 8 + 104*u + 2.4*math.sin(y*0.08 + pace*math.tau)
        oval(draw, x, y, 0.5 + depth*0.75, 0.5 + depth*0.75, (108, 194, 223, round(36 + 92*depth)))

    for x, y, size, color, offset in [
        (87, 42, 8, (166, 142, 239), 2.3),
        (29, 71, 9, (91, 173, 216), 4.2),
        (58, 50, 16, (112, 224, 230), 0.3),
    ]:
        phase = t * 1.22 + offset
        x += 4*math.sin(t*0.42 + offset)
        y += 5*math.cos(t*0.51 + offset)
        width = size * (0.93 + 0.07 * math.sin(phase))
        height = size * (0.71 - 0.08 * math.sin(phase))
        light = Image.new('RGBA', SIZE)
        oval(ImageDraw.Draw(light), x, y-height*0.25, width*1.1, height*0.87, (*color, 83))
        over(image, light, 3.4)
        for tentacle in range(6):
            drift = (tentacle - 2.5) * width * 0.28
            length = size * (1.53 + 0.3*math.sin(tentacle * 1.7))
            points = [(x+drift+size*0.19*(i/12)*math.sin(phase-i*0.53+tentacle), y+i*length/12)
                      for i in range(13)]
            draw.line(path(points), fill=(*color, 73 + (tentacle % 3)*28), width=2)
        dome = coords(x-width, y-height, x+width, y+height)
        draw.pieslice(dome, 180, 360, fill=(*color, 87))
        draw.arc(dome, 180, 360, fill=(*color, 202), width=2)
        draw.ellipse(coords(x-width, y-height*0.15, x+width, y+height*0.15), outline=(*color, 182), width=2)


RENDERERS = {'storm': storm, 'fireflies': fireflies, 'aurora': aurora, 'jellyfish': jellyfish}


def render_ambient(kind, elapsed=None):
    image = Image.new('RGB', SIZE)
    RENDERERS[kind](image, POSTER_TIMES[kind] if elapsed is None else elapsed)
    return ImageChops.multiply(image, vignette())
