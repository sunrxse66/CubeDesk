"""Public currency history with a local cache and background refresh."""
from __future__ import annotations

import datetime as dt
import json
import math
import re
import threading
import time
import urllib.parse
import urllib.request

from cubedesk.background import atomic_json

PAIR = re.compile(r'(crypto|fx):([A-Z0-9.]{2,12})/([A-Z0-9.]{2,12})')
CODE = re.compile(r'[A-Z0-9.]{2,12}')
PERIODS = {7: 60, 30: 240, 90: 1440}
MAX_PAIRS = 12
DEFAULTS = {
    'pairs': ['crypto:BTC/USD', 'crypto:ETH/USD', 'fx:USD/RUB', 'fx:EUR/RUB'],
    'days': 7, 'seconds': 8, 'selected': None,
}
DEFAULT_CRYPTO = ('BTC/USD', 'BTC/EUR', 'ETH/USD', 'ETH/EUR', 'SOL/USD', 'XRP/USD',
                  'DOGE/USD', 'ADA/USD', 'LTC/USD', 'LINK/USD', 'TON/USD', 'USDT/USD')
DEFAULT_FX = ('USD', 'EUR', 'RUB', 'GBP', 'CNY', 'JPY', 'CHF', 'CAD', 'AUD', 'KZT',
              'TRY', 'AED', 'INR', 'PLN', 'CZK', 'SEK', 'NOK', 'HKD')
KRAKEN = 'https://api.kraken.com/0/public/'
FRANKFURTER = 'https://api.frankfurter.dev/v2/'
ALIASES = {'XBT': 'BTC', 'XDG': 'DOGE'}


def validate_market(value):
    if not isinstance(value, dict):
        raise ValueError('Выберите пары и период графика')
    pairs = value.get('pairs')
    if not isinstance(pairs, list) or len(pairs) > MAX_PAIRS:
        raise ValueError(f'Можно выбрать до {MAX_PAIRS} пар')
    clean = []
    for pair in pairs:
        match = PAIR.fullmatch(pair) if isinstance(pair, str) else None
        if not match or match[2] == match[3] or pair in clean:
            raise ValueError('Укажите разные валюты и не добавляйте одну пару дважды')
        clean.append(pair)
    days, seconds, selected = value.get('days'), value.get('seconds'), value.get('selected')
    if type(days) is not int or days not in PERIODS or type(seconds) is not int or not 4 <= seconds <= 60:
        raise ValueError('Выберите период 7, 30 или 90 дней и интервал от 4 до 60 секунд')
    if selected is not None and selected not in clean:
        raise ValueError('Закреплённая пара должна быть в списке')
    return {'pairs': clean, 'days': days, 'seconds': seconds, 'selected': selected}


def _json(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'CubeDesk', 'Accept': 'application/json'})
    with urllib.request.urlopen(request, timeout=7) as response:
        data = response.read(2_000_001)
    if len(data) > 2_000_000:
        raise ValueError('Слишком большой ответ источника котировок')
    return json.loads(data)


def _points(rows):
    points = {}
    for timestamp, value in rows:
        try:
            timestamp, value = int(timestamp), float(value)
        except (TypeError, ValueError, OverflowError):
            continue
        if 0 < timestamp < 4_102_444_800 and 1e-14 <= value <= 1e15:
            points[timestamp] = value
    return sorted(points.items())[-240:]


class MarketService:
    def __init__(self, storage):
        self.path = storage / 'market-cache.json'
        self.lock = threading.RLock()
        self.records = {}
        self.attempts = {}
        self.errors = set()
        self.busy = False
        self.catalog_busy = False
        self.catalog_attempt = 0.0
        self.catalog_revision = 0
        self.crypto = {pair: pair.replace('/', '').replace('BTC', 'XBT').replace('DOGE', 'XDG')
                       for pair in DEFAULT_CRYPTO}
        self.fx = {code: code for code in DEFAULT_FX}
        try:
            saved = json.loads(self.path.read_text('utf8'))
            for key, record in list(saved.get('records', {}).items())[-48:]:
                points = _points(record['points'])
                stamp = float(record['fetched_at'])
                if points and math.isfinite(stamp):
                    self.records[key] = {'points': points, 'fetched_at': stamp}
        except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError):
            pass

    def catalog(self):
        with self.lock:
            return {'crypto': sorted(self.crypto), 'fx': dict(sorted(self.fx.items())),
                    'revision': self.catalog_revision}

    def refresh_catalog(self):
        with self.lock:
            now = time.monotonic()
            if self.catalog_busy or (self.catalog_attempt and now - self.catalog_attempt < 900):
                return
            self.catalog_busy, self.catalog_attempt = True, now

        def run():
            try:
                try:
                    result = _json(KRAKEN + 'AssetPairs')['result']
                    pairs = {}
                    for item in result.values():
                        name = item.get('wsname')
                        if not isinstance(name, str) or name.count('/') != 1:
                            continue
                        base, quote = name.split('/')
                        base, quote = ALIASES.get(base, base), ALIASES.get(quote, quote)
                        symbol = item.get('altname', '')
                        if (item.get('status') == 'online' and CODE.fullmatch(base) and CODE.fullmatch(quote)
                                and isinstance(symbol, str) and re.fullmatch(r'[A-Z0-9.]{4,24}', symbol)):
                            pairs[f'{base}/{quote}'] = symbol
                    if pairs:
                        with self.lock:
                            self.crypto.update(pairs)
                            self.catalog_revision += 1
                except (OSError, ValueError, KeyError, TypeError, AttributeError):
                    pass
                try:
                    currencies = _json(FRANKFURTER + 'currencies')
                    names = {item['iso_code']: item['name'] for item in currencies
                             if item.get('type') == 'fiat' and CODE.fullmatch(item['iso_code'])}
                    if names:
                        with self.lock:
                            self.fx.update(names)
                            self.catalog_revision += 1
                except (OSError, ValueError, KeyError, TypeError, AttributeError):
                    pass
            finally:
                with self.lock:
                    self.catalog_busy = False

        threading.Thread(target=run, daemon=True, name='CubeDesk-market-catalog').start()

    def _fetch(self, pair, days):
        kind, base, quote = PAIR.fullmatch(pair).groups()
        since = int(time.time()) - days * 86400
        if kind == 'crypto':
            with self.lock:
                symbol = self.crypto.get(f'{base}/{quote}')
            if symbol is None:
                reverse = {name: code for code, name in ALIASES.items()}
                symbol = reverse.get(base, base) + reverse.get(quote, quote)
            query = urllib.parse.urlencode({'pair': symbol, 'interval': PERIODS[days], 'since': since})
            response = _json(KRAKEN + 'OHLC?' + query)
            if response['error']:
                raise ValueError('Пара недоступна на Kraken')
            rows = next(rows for key, rows in response['result'].items() if key != 'last')
            points = _points((row[0], row[4]) for row in rows if len(row) >= 5)
        else:
            start = dt.datetime.fromtimestamp(since, dt.timezone.utc).date().isoformat()
            query = urllib.parse.urlencode({'base': base, 'quotes': quote, 'from': start})
            rows = _json(FRANKFURTER + 'rates?' + query)
            points = _points((dt.datetime.fromisoformat(row['date']).replace(tzinfo=dt.timezone.utc).timestamp(),
                              row['rate']) for row in rows if row.get('base') == base and row.get('quote') == quote)
        points = [(stamp, value) for stamp, value in points if stamp >= since - 86400]
        if not points:
            raise ValueError('История пары пока недоступна')
        return {'points': points, 'fetched_at': time.time()}

    def refresh(self, settings, force=False):
        days = settings['days']
        with self.lock:
            if self.busy:
                return
            now = time.time()
            due = []
            for pair in settings['pairs']:
                key = f'{days}/{pair}'
                ttl = 120 if pair.startswith('crypto:') else 1800
                if force or now - self.records.get(key, {}).get('fetched_at', 0) >= ttl:
                    if now - self.attempts.get(key, 0) >= 30:
                        due.append((key, pair))
            if not due:
                return
            self.busy = True

        def run():
            try:
                for key, pair in due:
                    with self.lock:
                        self.attempts[key] = time.time()
                    try:
                        record = self._fetch(pair, days)
                    except (OSError, ValueError, KeyError, TypeError, AttributeError, StopIteration, OverflowError):
                        with self.lock:
                            self.errors.add(key)
                        continue
                    with self.lock:
                        self.errors.discard(key)
                        self.records.pop(key, None)
                        self.records[key] = record
                with self.lock:
                    self.records = dict(list(self.records.items())[-48:])
                    self.attempts = dict(list(self.attempts.items())[-96:])
                    self.errors.intersection_update(self.attempts)
                    try:
                        atomic_json(self.path, {'records': self.records})
                    except OSError:
                        pass
            finally:
                with self.lock:
                    self.busy = False

        threading.Thread(target=run, daemon=True, name='CubeDesk-market-rates').start()

    def chart(self, pair, days):
        key = f'{days}/{pair}'
        with self.lock:
            record = self.records.get(key)
            points = record['points'] if record else []
            failed = key in self.errors
            ttl = 120 if pair and pair.startswith('crypto:') else 1800
            stale = bool(record and (failed or time.time() - record['fetched_at'] > ttl * 3))
            return {'pair': pair, 'days': days, 'points': points,
                    'updated_at': record['fetched_at'] if record else None,
                    'stale': stale, 'error': failed, 'loading': self.busy and not points}

    def snapshot(self, settings):
        with self.lock:
            items = []
            for pair in settings['pairs']:
                chart = self.chart(pair, settings['days'])
                points = chart.pop('points')
                chart['observed_at'] = points[-1][0] if points else None
                items.append(chart)
            return {'settings': settings, 'items': items, 'refreshing': self.busy,
                    'catalog_revision': self.catalog_revision}
