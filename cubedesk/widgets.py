"""Native-resolution CubeDesk screens, rendered identically for preview and cube."""
from __future__ import annotations

import datetime as dt
from functools import lru_cache
import math
import os
from pathlib import Path
import time

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont
from cube_player import CubeConnection, rgb565
from smooth_player import encode_jpeg, wait_frame
from cubedesk.ambient import SCENES, render_ambient
from cubedesk.village_art import render_village
from cubedesk.weather import condition

KINDS = {'clock': 'Часы', 'weather': 'Погода', 'combined': 'Часы и погода', 'markets': 'Курсы валют',
         'village': 'Жизнь за стеклом', **SCENES}
S = 2
INK = '#24364d'
MUTED = '#64768b'
MARKET_ANIMATION_SECONDS = 3.2
MONTHS = ('января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря')
DAYS = ('Понедельник','Вторник','Среда','Четверг','Пятница','Суббота','Воскресенье')


@lru_cache(maxsize=64)
def font(size, weight='regular'):
    name = {'regular':'segoeui.ttf','bold':'segoeuib.ttf','light':'segoeuil.ttf'}[weight]
    paths = [Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/name, Path('DejaVuSans.ttf')]
    for path in paths:
        try: return ImageFont.truetype(str(path),round(size*S))
        except OSError: pass
    return ImageFont.load_default(size=round(size*S))


@lru_cache(maxsize=4)
def background(kind):
    if kind == 'markets':
        return Image.new('RGBA', (240*S, 240*S), '#101a2d')
    colors = {'clock':((234,222,252),(198,224,245)), 'weather':((218,244,235),(213,227,251)),
              'combined':((252,228,214),(221,216,250))}[kind]
    image = Image.new('RGBA',(240*S,240*S))
    draw = ImageDraw.Draw(image)
    for y in range(240*S):
        t=y/(240*S-1)
        color=tuple(round(a*(1-t)+b*t) for a,b in zip(*colors))
        draw.line((0,y,240*S,y),fill=color)
    glow=Image.new('RGBA',image.size,(255,255,255,0))
    d=ImageDraw.Draw(glow)
    d.ellipse((110*S,-65*S,310*S,125*S),fill=(255,255,255,160))
    d.ellipse((-80*S,130*S,105*S,310*S),fill=(255,255,255,105))
    return Image.alpha_composite(image,glow.filter(ImageFilter.GaussianBlur(28*S)))


class Canvas:
    def __init__(self, kind):
        self.image=background(kind).copy()
        self.draw=ImageDraw.Draw(self.image)

    def text(self, xy, value, size=12, color=INK, weight='regular', width=None):
        value=str(value)
        chosen=font(size,weight)
        if width is not None:
            while self.draw.textlength(value,font=chosen)>width*S and size>9:
                size-=1;chosen=font(size,weight)
            if self.draw.textlength(value,font=chosen)>width*S:
                while value and self.draw.textlength(value+'…',font=chosen)>width*S:value=value[:-1]
                value+='…'
        # Anchor at the actual glyph top, so text heights are predictable.
        self.draw.text((xy[0]*S,xy[1]*S),value,font=chosen,fill=color,anchor='lt')

    def pill(self, bounds, fill=(255,255,255,145), radius=14):
        overlay=Image.new('RGBA',self.image.size)
        ImageDraw.Draw(overlay).rounded_rectangle(tuple(round(v*S) for v in bounds),radius=radius*S,fill=fill,
                                                  outline=(255,255,255,185),width=S)
        self.image=Image.alpha_composite(self.image,overlay)
        self.draw=ImageDraw.Draw(self.image)

    def finish(self):
        return self.image.convert('RGB').resize((240,240),Image.Resampling.LANCZOS)


def weather_icon(canvas, kind, center, size):
    """Our own vector-like sun, cloud, rain, snow and moon artwork."""
    layer=Image.new('RGBA',canvas.image.size)
    d=ImageDraw.Draw(layer)
    cx,cy=center;scale=size/80
    def rect(x0,y0,x1,y1):return tuple(round(v*S) for v in (cx+x0*scale,cy+y0*scale,cx+x1*scale,cy+y1*scale))
    def ellipse(b,color):d.ellipse(rect(*b),fill=color)
    def line(points,color,width=2):
        coords=[((cx+x*scale)*S,(cy+y*scale)*S) for x,y in points]
        d.line(coords,fill=color,width=max(1,round(width*scale*S)))
        for point in (coords[0],coords[-1]):
            r=width*scale*S/2;d.ellipse((point[0]-r,point[1]-r,point[0]+r,point[1]+r),fill=color)
    if kind in ('sun','partly'):
        ox,oy=(0,0) if kind=='sun' else (-13,-12)
        for i in range(8):
            angle=i*math.pi/4
            line([(ox+math.cos(angle)*27,oy+math.sin(angle)*27),
                  (ox+math.cos(angle)*33,oy+math.sin(angle)*33)],'#edb45c',2.5)
        ellipse((ox-20,oy-20,ox+20,oy+20),'#edb878')
        ellipse((ox-19,oy-23,ox+19,oy+15),'#ffe2a0')
        ellipse((ox-12,oy-20,ox+11,oy-5),(255,245,213,170))
    if kind in ('moon','mooncloud'):
        ellipse((-23,-29,21,15),'#95a5dc')
        ellipse((-15,-33,25,5),'#dce5f5')
        ellipse((24,-24,28,-20),'#d6ba77')
        if kind=='moon':ellipse((-30,20,-26,24),'#aeb7db')
    if kind not in ('sun','moon'):
        # Lifted, soft shadow, then three rounded cloud lobes.
        shadow=Image.new('RGBA',layer.size);sd=ImageDraw.Draw(shadow)
        sd.ellipse(rect(-31,10,34,26),fill=(89,123,159,55))
        layer=Image.alpha_composite(layer,shadow.filter(ImageFilter.GaussianBlur(3*S)))
        d=ImageDraw.Draw(layer)
        ellipse((-32,-2,7,27),'#f6fbff')
        ellipse((-13,-17,29,26),'#fbfdff')
        ellipse((9,-1,37,26),'#e9f1fb')
        d.rounded_rectangle(rect(-23,5,26,28),radius=10*S,fill='#f5faff')
        if kind in ('rain','storm'):
            for x,y in [(-20,34),(0,39),(20,34)]:line([(x,y),(x-4,y+9)],'#81a9d5',3)
        if kind=='storm':
            points=[(-3,20),(-12,40),(-2,38),(-7,53),(13,30),(2,32),(9,20)]
            d.polygon([((cx+x*scale)*S,(cy+y*scale)*S) for x,y in points],fill='#e6bf75')
        if kind=='snow':
            for x in (-19,3,24):
                line([(x,34),(x,45)],'#8eaccb',1.8)
                line([(x-5,37),(x+5,42)],'#8eaccb',1.8)
                line([(x-5,42),(x+5,37)],'#8eaccb',1.8)
        if kind=='fog':
            line([(-31,34),(26,34)],'#9db4c6',2)
            line([(-18,42),(36,42)],'#a7becb',2)
    canvas.image=Image.alpha_composite(canvas.image,layer)
    canvas.draw=ImageDraw.Draw(canvas.image)


def temperature(value):
    return '—°' if value is None else f'{round(value):d}°'.replace('-','−')


@lru_cache(maxsize=3)
def market_fill(accent, size):
    fill = Image.new('RGBA', size)
    draw = ImageDraw.Draw(fill)
    width, height = size
    for y in range(height):
        alpha = round(64 * (1 - y / (height - 1)) ** 1.4)
        draw.line((0, y, width - 1, y), fill=f'{accent}{alpha:02x}')
    return fill


def draw_market_graph(canvas, path, bounds, accent, phase):
    x0, y0, x1, y1 = bounds
    for y in (y0, (y0 + y1) // 2, y1):
        canvas.draw.line((x0, y, x1, y), fill='#273852', width=S)

    if len(path) > 1:
        size = (x1 - x0 + 1, y1 - y0 + 1)
        plot = [(x - x0, y - y0) for x, y in path]
        mask = Image.new('L', size)
        ImageDraw.Draw(mask).polygon([(plot[0][0], size[1] - 1), *plot, (plot[-1][0], size[1] - 1)], fill=255)
        fill = market_fill(accent, size)
        region = canvas.image.crop((x0, y0, x1 + 1, y1 + 1))
        canvas.image.paste(Image.alpha_composite(region, fill), (x0, y0), mask)
        canvas.draw.line(path, fill=accent, width=2*S, joint='curve')
        if phase is not None:
            draw_market_shimmer(canvas.image, plot, size, (x0, y0), accent, phase)

    x, y = path[-1]
    radius = 3*S
    pulse = 0 if phase is None else (1 - math.cos(math.tau * phase)) / 2
    halo = round((4 + 3 * pulse) * S)
    center = halo + 3*S
    glow = Image.new('RGBA', (center * 2 + 1,) * 2)
    ImageDraw.Draw(glow).ellipse((center-halo, center-halo, center+halo, center+halo), fill=accent+'60')
    canvas.image.alpha_composite(glow.filter(ImageFilter.GaussianBlur(1.5*S)), (x - center, y - center))
    canvas.draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=accent)


def draw_market_shimmer(image, path, size, origin, accent, phase):
    width, height = size
    reach = 38*S
    center = phase * (width + 2*reach) - reach
    falloff = [round(255 * max(0, 1 - abs(x - center) / reach) ** 2) for x in range(width)]
    band = Image.new('L', (width, 1))
    band.putdata(falloff)
    band = band.resize((width, height), Image.Resampling.NEAREST)

    glow = Image.new('L', size)
    ImageDraw.Draw(glow).line(path, fill=200, width=7*S, joint='curve')
    glow = glow.filter(ImageFilter.GaussianBlur(2.4*S))
    layer = Image.new('RGBA', size, accent)
    layer.putalpha(ImageChops.multiply(glow, band))
    image.alpha_composite(layer, origin)

    shine = Image.new('L', size)
    ImageDraw.Draw(shine).line(path, fill=240, width=2*S, joint='curve')
    layer = Image.new('RGBA', size, '#ffffff')
    layer.putalpha(ImageChops.multiply(shine, band))
    image.alpha_composite(layer, origin)


def render_market(chart, phase=None):
    canvas = Canvas('markets')
    pair = chart.get('pair')
    if not pair:
        canvas.text((16, 20), 'Курсы валют', 23, '#f1f5ff', 'bold')
        canvas.text((16, 83), 'Добавьте валютную пару', 14, '#a9b8cf', width=208)
        return canvas.finish()

    kind, name = pair.split(':', 1)
    muted = '#a9b8cf'
    canvas.text((16, 17), name, 24, '#f1f5ff', 'bold', width=164)
    canvas.text((183, 23), f"{chart['days']} Д", 12, muted, width=42)
    canvas.text((17, 47), 'КРИПТОВАЛЮТА' if kind == 'crypto' else 'ОБЫЧНАЯ ВАЛЮТА', 10, muted)
    points = chart.get('points') or []
    if not points:
        message = 'Источник недоступен' if chart.get('error') else 'Загружаем котировки…' if chart.get('loading') else 'Котировки ещё не загружены'
        canvas.text((17, 94), message, 14, muted, width=206)
        canvas.text((17, 212), 'KRAKEN' if kind == 'crypto' else 'FRANKFURTER', 10, muted)
        return canvas.finish()

    first, last = points[0][1], points[-1][1]
    change = (last / first - 1) * 100
    change = 0 if abs(change) < 0.005 else change
    accent = '#68ead0' if change > 0 else '#ff97a3' if change < 0 else '#a1bafe'
    decimals = 2 if last >= 100 else 4 if last >= 1 else min(14, max(4, 3 - math.floor(math.log10(last))))
    price = f'{last:,.{decimals}f}'.rstrip('0').rstrip('.').replace(',', ' ').replace('.', ',')
    canvas.text((16, 66), price, 30, '#f1f5ff', 'bold', width=208)
    if len(points) > 1:
        percent = f'{change:+.2f} %' if change else '0,00 %'
        canvas.text((17, 105), percent.replace('.', ',').replace('-', '−'), 14, accent, 'bold', width=115)
        canvas.text((137, 108), 'за период', 10, muted)
    else:
        canvas.text((17, 105), 'Одна точка за период', 12, muted)

    x0, x1, y0, y1 = 18*S, 222*S, 137*S, 194*S
    low, high = min(p[1] for p in points), max(p[1] for p in points)
    span = max(high-low, last * 0.00005)
    duration = max(1, points[-1][0] - points[0][0])
    center = (low+high)/2
    path = [(round(x0+(x1-x0)*(stamp-points[0][0])/duration) if len(points) > 1 else (x0+x1)//2,
             round((y0+y1)/2-(y1-y0-8*S)*(value-center)/span)) for stamp, value in points]
    draw_market_graph(canvas, path, (x0, y0, x1, y1), accent, phase)
    zone = dt.timezone.utc if kind == 'fx' else None
    date = dt.datetime.fromtimestamp(points[-1][0], zone).strftime('%d.%m' if kind == 'fx' else '%d.%m %H:%M')
    source = 'KRAKEN' if kind == 'crypto' else 'FRANKFURTER'
    canvas.text((17, 213), f'{source} · {date}', 10, muted, width=160)
    if chart.get('stale'):
        canvas.text((183, 213), 'КЭШ', 10, '#ffd094')
    return canvas.finish()


def save_market_animation(chart, output):
    frame_count = 32
    frames = [render_market(chart, frame / frame_count) for frame in range(frame_count)]
    frames[0].save(output, 'PNG', save_all=True, append_images=frames[1:], loop=0,
                   duration=round(1000 * MARKET_ANIMATION_SECONDS / frame_count))


def render(kind, weather=None, now=None):
    if kind not in KINDS:raise ValueError('Неизвестный виджет')
    if kind in SCENES:
        return render_ambient(kind)
    if kind == 'village':
        return render_village(weather)
    if kind == 'markets':
        return render_market(weather or {})
    now=now or dt.datetime.now().astimezone()
    weather=weather or {'city':None,'forecast':None,'phase':'not_configured'}
    forecast=weather.get('forecast') or {}
    city=weather.get('city')
    icon,description=condition(forecast.get('code',3),forecast.get('is_day',True))
    if not forecast:description='Выберите город' if not city else 'Ожидаем погоду'
    date=f'{now.day} {MONTHS[now.month-1]}'
    c=Canvas(kind)
    if kind=='clock':
        c.text((20,20),'C U B E D E S K',9,MUTED)
        c.text((20,45),DAYS[now.weekday()],18,weight='bold',width=200)
        c.text((15,87),now.strftime('%H:%M'),72,weight='light',width=210)
        c.pill((19,180,78,211),radius=13)
        c.text((31,188),now.strftime('%S')+' сек',12)
        c.text((92,180),date,15,width=130)
        c.text((92,202),'Время вашего ПК',9,MUTED)
    elif kind=='weather':
        c.text((17,18),city['name'] if city else 'Ваш город',17,weight='bold',width=151)
        c.text((184,23),now.strftime('%H:%M'),11,MUTED)
        c.text((17,47),description,12,MUTED,width=206)
        c.text((13,77),temperature(forecast.get('temperature')),65,weight='light',width=138)
        weather_icon(c,icon,(181,108),73)
        c.text((18,148),'Ощущается '+temperature(forecast.get('feels_like')),12,MUTED)
        c.text((18,170),'Макс. '+temperature(forecast.get('high'))+'   Мин. '+temperature(forecast.get('low')),11,MUTED)
        c.pill((15,194,225,226),radius=13)
        if weather.get('phase')=='stale':c.text((29,204),'Сохранённый прогноз',11,MUTED,width=184)
        elif not forecast:c.text((30,204),'Город — в настройках',11,MUTED,width=185)
        else:
            wind=forecast.get('wind');humidity=forecast.get('humidity')
            c.text((28,204),('—' if wind is None else f'{wind:.1f}'.replace('.',','))+' м/с',11)
            c.text((128,204),('—' if humidity is None else str(round(humidity)))+'% влажн.',11)
    else:
        c.text((18,20),DAYS[now.weekday()]+', '+date,13,MUTED,width=206)
        c.text((18,50),city['name'] if city else 'Ваш маленький экран',15,weight='bold',width=204)
        c.text((15,77),now.strftime('%H:%M'),61,weight='light',width=207)
        c.pill((15,153,225,225),radius=19)
        weather_icon(c,icon,(48,185),49)
        c.text((86,164),temperature(forecast.get('temperature')),28,weight='light')
        c.text((86,199),description if weather.get('phase')!='stale' else 'Прогноз сохранён',10,MUTED,width=126)
        # Tiny seconds keep this screen visibly live without distracting motion.
        c.text((200,132),now.strftime('%S'),9,MUTED)
    return c.finish()


def play_widget(host, token, kind, stop, supplier, report=print, on_stats=None):
    connection=None
    last_data=None
    sent=0
    last_ack=0.0
    ambient = kind in SCENES
    animated_scene = ambient or kind == 'village'
    scene_started = time.monotonic()
    try:
        while not stop.is_set():
            started=time.monotonic()
            try:
                if connection is None:
                    connection=CubeConnection(host,token,modern=True)
                    last_data=None
                    report('Виджет · '+KINDS[kind])
                snapshot = None if ambient else supplier()
                interval = 1
                jpeg = bool(connection.flags & 1)
                edge = 240
                if animated_scene:
                    image = render_ambient(kind, started - scene_started) if ambient else render_village(snapshot)
                    edge = 120 if jpeg else 240
                    interval = 1 / ((16 if ambient else 14) if jpeg else 3)
                elif kind == 'markets' and jpeg and len(snapshot['points']) > 1:
                    phase = (time.monotonic() % MARKET_ANIMATION_SECONDS) / MARKET_ANIMATION_SECONDS
                    image = render_market(snapshot, phase)
                    interval = 1 / 12
                else:
                    image = render(kind, snapshot)
                data=encode_jpeg(image,connection.max_jpeg,85,edge=edge)[0] if jpeg else rgb565(image)
                if data!=last_data:
                    stats=connection.send_jpeg(data) if jpeg else connection.send(data)
                    last_data=data;sent+=1;last_ack=time.monotonic()
                    if on_stats:
                        details = dict(stats, widget=kind, frames=sent, resolution=edge, updated_at=time.time())
                        if kind == 'markets':
                            details['market_pair'] = snapshot.get('pair')
                        on_stats(details)
                elif time.monotonic()-last_ack>=3:
                    connection.send();last_ack=time.monotonic()
                remaining = max(0, interval - (time.monotonic() - started))
                if animated_scene:
                    wait_frame(stop, remaining)
                else:
                    stop.wait(remaining)
            except OSError:
                if connection:connection.close()
                connection=None
                report('Связь прервалась. Повторное подключение через 2 секунды…')
                stop.wait(2)
    finally:
        if connection:connection.close()
