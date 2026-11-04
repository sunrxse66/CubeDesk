"""First installation: a narrow stock profile, verified release, one explicit write."""
from __future__ import annotations

import http.client
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import secrets
import threading
import time
import urllib.request

from cubedesk.background import atomic_json
from cubedesk.device import validate_host
from cubedesk.updates import verify_file

MODEL = 'HelloCubic-Lite'
STOCK_VERSION = 'V7.0.22'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('Устройство перенаправляет запрос. Проверьте его IP; запись отменена.')


class FirmwareForm(HTMLParser):
    def __init__(self):
        super().__init__()
        self.form = None
        self.valid = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'form':
            self.form = (attrs.get('method', '').lower() == 'post' and
                         attrs.get('enctype', '').lower() == 'multipart/form-data' and
                         attrs.get('action', '') in ('', '/update'))
        elif tag == 'input' and self.form:
            if attrs.get('type', '').lower() == 'file' and attrs.get('name') == 'firmware':
                self.valid = True

    def handle_endtag(self, tag):
        if tag == 'form': self.form = None


class LocalTarget:
    def __init__(self, host, port=80):
        self.host, self.port = validate_host(host), port
        self.last_request = 0.0
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def read(self, path, maximum=16384):
        time.sleep(max(0, .35 - (time.monotonic() - self.last_request)))
        self.last_request = time.monotonic()
        with self.opener.open(f'http://{self.host}:{self.port}{path}', timeout=4) as response:
            data = response.read(maximum + 1)
        if len(data) > maximum:
            raise ValueError('Устройство вернуло слишком большой ответ')
        return data

    def probe(self):
        try:
            info = json.loads(self.read('/v.json', 8192))
        except (OSError, ValueError, TypeError):
            info = None
        if isinstance(info, dict) and 'm' in info:
            model, version = str(info.get('m', ''))[:80], str(info.get('v', ''))[:40]
            result = {'kind': 'stock', 'model': model, 'version': version, 'compatible': False}
            if model != MODEL or version != STOCK_VERSION:
                return result | {'message': 'Автоматическая первая установка проверена только для HelloCubic-Lite V7.0.22. Для этого устройства запись заблокирована.'}
            form = FirmwareForm()
            form.feed(self.read('/update').decode('utf8', errors='replace'))
            if not form.valid:
                return result | {'message': 'Заводская страница обновления отличается от проверенной. Автоматическая запись недоступна.'}
            return result | {'compatible': True, 'message': 'Модель, версия и страница обновления совпадают с проверенным вариантом.'}
        try:
            page = self.read('/')
            match = re.search(rb'pcstream-v(\d+\.\d+(?:\.\d+)?)(?:[-<\s])', page)
            if match:
                return {'kind': 'stream', 'model': MODEL, 'version': 'PCStream v' + match.group(1).decode(),
                        'compatible': False, 'message': 'PCStream уже установлена. Первая запись не нужна — подключим CubeDesk.'}
        except (OSError, ValueError):
            pass
        raise ValueError('Не удалось определить кубик. Проверьте IP, питание и общую домашнюю сеть.')

    def upload(self, image, report):
        time.sleep(max(0, .35 - (time.monotonic() - self.last_request)))
        boundary = 'CubeDesk' + secrets.token_hex(16)
        prefix = (f'--{boundary}\r\nContent-Disposition: form-data; name="firmware"; filename="firmware.bin"\r\n'
                  'Content-Type: application/octet-stream\r\n\r\n').encode()
        body = prefix + image + f'\r\n--{boundary}--\r\n'.encode()
        connection = http.client.HTTPConnection(self.host, self.port, timeout=50)
        sent = 0
        try:
            connection.putrequest('POST', '/update')
            connection.putheader('Content-Type', 'multipart/form-data; boundary=' + boundary)
            connection.putheader('Content-Length', str(len(body)))
            connection.putheader('Connection', 'close')
            connection.endheaders()
            for offset in range(0, len(body), 1024):
                block = body[offset:offset + 1024]
                connection.send(block)
                sent += len(block)
                report(min(99, int(sent * 100 / len(body))))
                time.sleep(.012)
            response = connection.getresponse()
            return response.status == 200 and b'Update Success!' in response.read(16384)
        except OSError:
            # Never resend after a lost response: flash may already have changed.
            return False
        finally:
            connection.close()


class FirstInstall:
    def __init__(self, storage):
        self.path = Path(storage) / 'onboarding.json'
        self.lock = threading.RLock()
        self.state = {'phase': 'idle', 'host': '', 'device': None, 'firmware': None,
                      'message': 'Начнём с адреса кубика в домашней сети.', 'progress': 0, 'check_id': ''}
        self.prepared = None
        try:
            saved = json.loads(self.path.read_text('utf8'))
            if saved.get('phase') in ('installing', 'waiting_setup', 'uncertain'):
                self.state.update(phase='uncertain', host=validate_host(saved['host']),
                    firmware=saved.get('firmware'),
                    message='Предыдущая установка ещё не проверена. Не повторяйте запись: проверьте экран кубика и завершите подключение.')
        except (OSError, ValueError, TypeError, AttributeError, KeyError):
            pass

    def public(self):
        with self.lock:
            return dict(self.state, device=dict(self.state['device']) if self.state['device'] else None,
                        firmware=dict(self.state['firmware']) if self.state['firmware'] else None)

    def set(self, **values):
        with self.lock:
            self.state.update(values)
            atomic_json(self.path, self.state)

    def probe(self, host):
        host = validate_host(host)
        self.prepared = None
        self.set(phase='checking', host=host, device=None, firmware=None, check_id='', progress=0,
                 message='Проверяем модель, версию и заводскую страницу обновления…')
        result = LocalTarget(host).probe()
        phase = 'compatible' if result['compatible'] else 'needs_pairing' if result['kind'] == 'stream' else 'unsupported'
        self.set(phase=phase, device=result, message=result['message'], check_id=secrets.token_urlsafe(24))

    def prepare(self, updates):
        if self.state['phase'] not in ('compatible', 'ready'):
            raise ValueError('Сначала проверьте совместимый заводской кубик')
        self.set(phase='preparing', message='Загружаем прошивку из официального репозитория CubeDesk и проверяем SHA-256…')
        updates.check()
        if updates.worker: updates.worker.join(45)
        if updates.public()['busy'] or not updates.specs.get('firmware'):
            raise ValueError('Не удалось получить релиз. Проверьте интернет и попробуйте ещё раз.')
        updates.download('firmware')
        if updates.worker: updates.worker.join(650)
        path, spec = updates.prepared('firmware')
        self.validate_image(path, spec)
        self.prepared = (path, spec)
        self.set(phase='ready', firmware={'version': spec['version'], 'size': spec['size']}, progress=100,
                 message='Прошивка загружена, размер и SHA-256 проверены. Теперь можно подтвердить установку.')

    @staticmethod
    def validate_image(path, spec):
        expected = {'model': MODEL, 'chip': 'ESP8266', 'display': 'ST7789', 'width': 240,
                    'height': 240, 'flash_bytes': 4194304, 'universal': True}
        if any(spec.get(k) != v for k, v in expected.items()):
            raise ValueError('Образ не соответствует проверенной плате HelloCubic-Lite')
        verify_file(path, spec, 'firmware')

    def validate_confirmation(self, data):
        if data.get('confirmed') is not True:
            raise ValueError('Подтвердите замену заводской прошивки и сохранение нужных картинок')
        if self.state['phase'] != 'ready' or not self.prepared:
            raise ValueError('Сначала проверьте устройство и загрузите прошивку')
        if not isinstance(data.get('check_id'), str) or not secrets.compare_digest(data['check_id'], self.state['check_id']):
            raise ValueError('Проверка устройства устарела. Проверьте кубик заново.')

    def progress(self, value):
        with self.lock:
            self.state['progress'] = value

    def install(self, data):
        self.validate_confirmation(data)
        path, spec = self.prepared
        self.validate_image(path, spec)
        image = Path(path).read_bytes()
        if len(image) != spec['size'] or hashlib.sha256(image).hexdigest() != spec['sha256']:
            raise ValueError('Файл прошивки изменился. Загрузите его заново.')
        target = LocalTarget(self.state['host'])
        fresh = target.probe()
        if not fresh.get('compatible'):
            raise ValueError('Устройство изменилось или стало недоступно. Запись отменена; проверьте его заново.')
        # Journal BEFORE the only POST. A crash/restart never schedules another upload.
        self.set(phase='installing', progress=0, message='Записываем PCStream. Не отключайте питание кубика.')
        confirmed = target.upload(image, self.progress)
        self.prepared = None
        self.set(phase='waiting_setup' if confirmed else 'uncertain', progress=100 if confirmed else self.state['progress'],
                 message=('Кубик подтвердил запись и перезапускается. Дождитесь QR или IP на экране.' if confirmed else
                          'Подтверждение записи не получено. Не повторяйте установку: дождитесь загрузки и проверьте экран кубика.'))

    def fail(self, error):
        phase = 'uncertain' if self.state['phase'] == 'installing' else 'error'
        self.set(phase=phase, message=str(error)[:300])

    def reset_completed(self):
        if self.state['phase'] != 'complete':
            raise ValueError('Сначала завершите текущую настройку или заново проверьте адрес кубика')
        self.prepared = None
        self.set(phase='idle', host='', device=None, firmware=None, check_id='', progress=0,
                 message='Введите адрес нового кубика. Текущее подключение CubeDesk сохранено.')
