"""Native-resolution CubeDesk screens, rendered identically for preview and cube."""
from __future__ import annotations

import datetime as dt
from functools import lru_cache
import math
import os
from pathlib import Path
import time

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from cube_player import CubeConnection, rgb565
from smooth_player import encode_jpeg
from cubedesk.weather import condition

KINDS = {'clock': 'Часы', 'weather': 'Погода', 'combined': 'Часы и погода'}
S = 2
INK = '#24364d'
MUTED = '#64768b'
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


@lru_cache(maxsize=3)
def background(kind):
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


def render(kind, weather=None, now=None):
    if kind not in KINDS:raise ValueError('Неизвестный виджет')
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
    try:
        while not stop.is_set():
            started=time.monotonic()
            try:
                if connection is None:
                    connection=CubeConnection(host,token,modern=True)
                    last_data=None
                    report('Виджет · '+KINDS[kind])
                image=render(kind,supplier())
                data=encode_jpeg(image,connection.max_jpeg,85)[0] if connection.flags & 1 else rgb565(image)
                if data!=last_data:
                    stats=connection.send_jpeg(data) if connection.flags & 1 else connection.send(data)
                    last_data=data;sent+=1;last_ack=time.monotonic()
                    if on_stats:on_stats(dict(stats,widget=kind,frames=sent,resolution=240,updated_at=time.time()))
                elif time.monotonic()-last_ack>=3:
                    connection.send();last_ack=time.monotonic()
                stop.wait(max(0,1-(time.monotonic()-started)))
            except OSError:
                if connection:connection.close()
                connection=None
                report('Связь прервалась. Повторное подключение через 2 секунды…')
                stop.wait(2)
    finally:
        if connection:connection.close()
