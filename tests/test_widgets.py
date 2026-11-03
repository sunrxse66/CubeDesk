import datetime as dt
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from PIL import Image
from cubedesk.weather import WeatherService, condition, validate_city
from cubedesk.widgets import render, play_widget

CITY={'id':2950159,'name':'Берлин','region':'Берлин','country':'Германия','latitude':52.52,'longitude':13.41}
API={'current':{'temperature_2m':8.2,'apparent_temperature':6.1,'weather_code':61,'is_day':1,
               'relative_humidity_2m':76,'wind_speed_10m':3.4},
     'daily':{'temperature_2m_max':[11.2],'temperature_2m_min':[4.5]}}


class WeatherTests(unittest.TestCase):
    def test_city_search_and_selection_are_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            service=WeatherService(Path(directory))
            with patch('cubedesk.weather._json',return_value={'results':[dict(CITY,admin1='Берлин')]} ) as fetch:
                cities=service.search('Берлин')
            self.assertEqual(cities[0]['id'],CITY['id'])
            self.assertIn('language=ru',fetch.call_args.args[0])
            self.assertEqual(service.selected(CITY['id'])['name'],'Берлин')
            with self.assertRaises(ValueError):service.selected(999)
            with self.assertRaises(ValueError):validate_city(dict(CITY,latitude=float('nan')))
            with self.assertRaises(ValueError):service.search('a')

    def test_forecast_survives_network_error_and_process_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            service=WeatherService(Path(directory))
            with patch('cubedesk.weather._json',return_value=API):service._fetch(CITY)
            self.assertEqual(service.snapshot(CITY)['phase'],'ready')
            self.assertEqual(service.snapshot(CITY)['forecast']['temperature'],8.2)
            service=WeatherService(Path(directory))
            self.assertEqual(service.snapshot(CITY)['forecast']['wind'],3.4)
            with patch('cubedesk.weather._json',side_effect=OSError('offline')):service._fetch(CITY)
            state=service.snapshot(CITY)
            self.assertEqual(state['phase'],'stale')
            self.assertEqual(state['forecast']['temperature'],8.2)
            self.assertTrue(state['error'])
            self.assertIsNone(service.snapshot(None)['forecast'])
            self.assertEqual(service.snapshot(dict(CITY,id=999))['phase'],'empty')

    def test_refresh_deduplicates_and_limits_background_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            service=WeatherService(Path(directory))
            entered,release=threading.Event(),threading.Event()
            def fetch(url):entered.set();release.wait(2);return API
            with patch('cubedesk.weather._json',side_effect=fetch) as network:
                self.assertTrue(service.refresh(CITY))
                self.assertTrue(entered.wait(1))
                self.assertFalse(service.refresh(CITY,force=True))
                release.set()
                for _ in range(100):
                    if not service.snapshot(CITY).get('refreshing'):break
                    time.sleep(.01)
                self.assertEqual(service.snapshot(CITY)['phase'],'ready')
                self.assertFalse(service.refresh(CITY))
                network.assert_called_once()


class RendererTests(unittest.TestCase):
    def test_all_screens_render_native_resolution_and_seconds_are_live(self):
        now=dt.datetime(2026,11,3,12,34,56)
        state={'city':dict(CITY,name='Петропавловск-Камчатский'),'phase':'ready',
               'forecast':{'temperature':-28,'feels_like':-34,'high':-22,'low':-35,
                           'code':75,'is_day':False,'humidity':80,'wind':12.4}}
        for kind in ('clock','weather','combined'):
            with self.subTest(kind=kind):
                image=render(kind,state,now)
                self.assertEqual(image.size,(240,240))
                self.assertEqual(image.mode,'RGB')
                self.assertGreater(len(set(image.get_flattened_data())),100)
                self.assertEqual(render(kind,now=now).size,(240,240))
        self.assertNotEqual(render('clock',now=now).tobytes(),render('clock',now=now+dt.timedelta(seconds=1)).tobytes())
        for code in (0,1,3,45,51,61,71,95):
            self.assertTrue(condition(code)[0])
        with self.assertRaises(ValueError):render('unknown')

    def test_widget_stream_sends_native_jpeg_and_releases_connection(self):
        stop=threading.Event();sent=[];closed=[]
        class Link:
            max_jpeg,flags=8192,7
            def __init__(self,*a,**kw):pass
            def send_jpeg(self,data):sent.append(data);stop.set();return {'transport_ms':10}
            def close(self):closed.append(True)
        stats=[]
        with patch('cubedesk.widgets.CubeConnection',Link):
            play_widget('unused','secret','clock',stop,lambda: {'city':None},report=lambda _:None,on_stats=stats.append)
        self.assertEqual(len(sent),1)
        with Image.open(io.BytesIO(sent[0])) as frame:self.assertEqual(frame.size,(240,240))
        self.assertEqual(stats[0]['widget'],'clock')
        self.assertEqual(closed,[True])
