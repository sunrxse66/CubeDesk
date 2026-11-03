"""Open-Meteo city search and a bounded, asynchronous forecast cache."""
from __future__ import annotations

import json
import math
from pathlib import Path
import threading
import time
import urllib.parse
import urllib.request

TTL = 600
MAX_AGE = 3600


def _json(url):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(url, headers={'User-Agent': 'CubeDesk/1.4', 'Accept': 'application/json'})
    with opener.open(request, timeout=8) as response:
        data = response.read(512 * 1024 + 1)
    if len(data) > 512 * 1024:
        raise ValueError('Ответ сервиса погоды слишком велик')
    result=json.loads(data)
    if not isinstance(result,dict):
        raise ValueError('Некорректный ответ сервиса погоды')
    return result


def validate_city(city):
    if city is None:
        return None
    if not isinstance(city, dict):
        raise ValueError('Выберите город из результатов поиска')
    try:
        result = {key: str(city.get(key, '')).strip()[:120] for key in ('name', 'region', 'country')}
        result.update(id=int(city['id']), latitude=float(city['latitude']), longitude=float(city['longitude']))
        if (not result['name'] or result['id'] <= 0 or
                not math.isfinite(result['latitude']) or not -90 <= result['latitude'] <= 90 or
                not math.isfinite(result['longitude']) or not -180 <= result['longitude'] <= 180):
            raise ValueError()
        return result
    except (KeyError, TypeError, ValueError, OverflowError):
        raise ValueError('Выберите корректный город из результатов поиска') from None


def condition(code, is_day=True):
    if code == 0: return ('sun' if is_day else 'moon', 'Ясно')
    if code in (1, 2): return ('partly' if is_day else 'mooncloud', 'Переменная облачность')
    if code == 3: return ('cloud', 'Облачно')
    if code in (45, 48): return ('fog', 'Туман')
    if code in (51, 53, 55, 56, 57): return ('rain', 'Морось')
    if code in (61, 63, 65, 66, 67, 80, 81, 82): return ('rain', 'Дождь')
    if code in (71, 73, 75, 77, 85, 86): return ('snow', 'Снег')
    if code in (95, 96, 99): return ('storm', 'Гроза')
    return ('cloud', 'Погодные данные')


class WeatherService:
    def __init__(self, storage: Path):
        self.path = storage / 'weather-cache.json'
        self.lock = threading.RLock()
        self.records, self.known_cities = {}, {}
        self.inflight, self.last_attempt, self.errors = set(), {}, {}
        try:
            loaded = json.loads(self.path.read_text('utf8'))
            if isinstance(loaded.get('records'), dict):
                self.records = {str(key):record for key,record in loaded['records'].items()
                    if isinstance(record,dict) and isinstance(record.get('forecast'),dict)
                    and isinstance(record.get('updated_at'),(int,float)) and math.isfinite(record['updated_at'])}
        except (OSError, ValueError, TypeError):
            pass

    def search(self, query):
        query = str(query).strip()
        if not 2 <= len(query) <= 100:
            raise ValueError('Введите от 2 до 100 символов названия города')
        try:
            data = _json('https://geocoding-api.open-meteo.com/v1/search?' + urllib.parse.urlencode(
                {'name': query, 'count': 8, 'language': 'ru', 'format': 'json'}))
            cities = [validate_city({'id': item['id'], 'name': item['name'], 'region': item.get('admin1',''),
                       'country': item.get('country',''), 'latitude': item['latitude'], 'longitude': item['longitude']})
                      for item in data.get('results', [])]
        except (OSError, ValueError, KeyError, TypeError):
            raise ValueError('Не удалось найти город. Проверьте интернет и повторите.') from None
        with self.lock:
            self.known_cities.update({city['id']: city for city in cities})
            while len(self.known_cities) > 80:
                self.known_cities.pop(next(iter(self.known_cities)))
        return cities

    def selected(self, ident):
        try:
            with self.lock:
                return self.known_cities[int(ident)].copy()
        except (KeyError, TypeError, ValueError):
            raise ValueError('Сначала найдите город и выберите его в списке') from None

    def snapshot(self, city):
        if city is None:
            return {'city': None, 'phase': 'not_configured', 'forecast': None, 'updated_at': None, 'error': ''}
        key = str(city['id'])
        with self.lock:
            record = self.records.get(key, {})
            forecast = record.get('forecast')
            updated = record.get('updated_at')
            age = max(0, time.time() - updated) if isinstance(updated, (int,float)) else float('inf')
            error = self.errors.get(key, '')
            phase = ('stale' if age >= MAX_AGE or error else 'ready') if forecast else (
                'loading' if key in self.inflight else 'error' if error else 'empty')
            return {'city': city.copy(), 'phase': phase,
                    'forecast': forecast.copy() if isinstance(forecast, dict) else None,
                    'updated_at': updated, 'error': error, 'refreshing': key in self.inflight}

    def refresh(self, city, force=False):
        if city is None:
            return False
        key = str(city['id'])
        with self.lock:
            now = time.time()
            record = self.records.get(key, {})
            if key in self.inflight or now - self.last_attempt.get(key, 0) < (5 if force else 60):
                return False
            if not force and now - record.get('updated_at', 0) < TTL:
                return False
            self.inflight.add(key)
            self.last_attempt[key] = now
        threading.Thread(target=self._fetch, args=(city.copy(),), daemon=True).start()
        return True

    def _fetch(self, city):
        key = str(city['id'])
        try:
            data = _json('https://api.open-meteo.com/v1/forecast?' + urllib.parse.urlencode({
                'latitude': city['latitude'], 'longitude': city['longitude'],
                'current': 'temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,is_day,wind_speed_10m',
                'daily': 'temperature_2m_max,temperature_2m_min', 'forecast_days': 1,
                'timezone': 'auto', 'wind_speed_unit': 'ms', 'timeformat': 'unixtime'}))
            current, daily = data['current'], data.get('daily', {})
            def number(value):
                return float(value) if isinstance(value, (int,float)) and math.isfinite(value) else None
            def first(name):
                values = daily.get(name, [])
                return number(values[0]) if values else None
            forecast = {'temperature': number(current.get('temperature_2m')),
                'feels_like': number(current.get('apparent_temperature')),
                'humidity': number(current.get('relative_humidity_2m')),
                'wind': number(current.get('wind_speed_10m')), 'code': int(current['weather_code']),
                'is_day': bool(current.get('is_day', 1)), 'high': first('temperature_2m_max'),
                'low': first('temperature_2m_min')}
            if forecast['temperature'] is None:
                raise ValueError('Missing temperature')
            with self.lock:
                self.records[key] = {'forecast': forecast, 'updated_at': time.time()}
                self.errors.pop(key, None)
                while len(self.records) > 8:
                    self.records.pop(min(self.records, key=lambda k: self.records[k].get('updated_at',0)))
                temporary = self.path.with_suffix('.tmp')
                temporary.write_text(json.dumps({'records': self.records}), 'utf8')
                temporary.replace(self.path)
        except (OSError, ValueError, KeyError, TypeError):
            with self.lock:
                self.errors[key] = 'Погода временно недоступна. Проверьте интернет.'
        finally:
            with self.lock:
                self.inflight.discard(key)
