"""Public GitHub Releases updates. Downloads are bounded and hash-checked before use."""
from __future__ import annotations

import base64
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from cubedesk import VERSION, REPOSITORY

ASSET_NAMES = {'app': 'CubeDesk.exe', 'firmware': 'HelloCubic-PCStream-universal.bin'}
LIMITS = {'app': 100 * 1024 * 1024, 'firmware': 1044464}
DOWNLOAD_HOSTS = {'github.com', 'release-assets.githubusercontent.com', 'objects.githubusercontent.com'}


def version_tuple(value):
    match = re.fullmatch(r'(?:v|PCStream v)?(\d+)\.(\d+)(?:\.(\d+))?', str(value))
    if not match:
        raise ValueError('Некорректный номер версии')
    return tuple(int(n or 0) for n in match.groups())


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlsplit(newurl)
        if parsed.scheme != 'https' or parsed.hostname not in DOWNLOAD_HOSTS or parsed.username or parsed.password or parsed.port not in (None, 443):
            raise ValueError('GitHub вернул недопустимый адрес загрузки')
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def open_public(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname not in DOWNLOAD_HOSTS | {'api.github.com'}:
        raise ValueError('Недопустимый источник обновления')
    request = urllib.request.Request(url, headers={'User-Agent': 'CubeDesk/' + VERSION,
                                                   'Accept': 'application/vnd.github+json' if parsed.hostname == 'api.github.com' else 'application/octet-stream'})
    return urllib.request.build_opener(SafeRedirect()).open(request, timeout=20)


def read_json(url, maximum=65536):
    with open_public(url) as response:
        data = response.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError('Ответ GitHub слишком большой')
    return json.loads(data)


def release_manifest(release, manifest):
    """Validate the complete binding: repository -> stable tag -> manifest -> assets."""
    if not isinstance(release, dict) or not isinstance(manifest, dict):
        raise ValueError('Некорректный формат релиза')
    ver = manifest.get('version', '')
    if not re.fullmatch(r'\d+\.\d+\.\d+', str(ver)):
        raise ValueError('Некорректная версия релиза')
    tag = 'v' + ver
    base = 'https://github.com/' + REPOSITORY
    if (release.get('draft') or release.get('prerelease') or release.get('tag_name') != tag or
        release.get('html_url') != base + '/releases/tag/' + tag or
        manifest.get('schema') != 1 or manifest.get('repository') != REPOSITORY):
        raise ValueError('Релиз не соответствует репозиторию CubeDesk')
    assets = release.get('assets', [])
    result = {}
    for kind, name in ASSET_NAMES.items():
        spec = manifest.get(kind)
        if not isinstance(spec, dict):
            raise ValueError('В релизе отсутствует компонент ' + kind)
        asset = [a for a in assets if a.get('name') == name and a.get('state') == 'uploaded']
        if len(asset) != 1:
            raise ValueError('Файл релиза отсутствует или дублируется: ' + name)
        asset = asset[0]
        url = base + '/releases/download/' + tag + '/' + name
        size = spec.get('size')
        digest = spec.get('sha256', '')
        version_tuple(spec.get('version', ''))
        if (spec.get('asset') != name or asset.get('browser_download_url') != url or
            not isinstance(size, int) or isinstance(size, bool) or not 0 < size <= LIMITS[kind] or
            asset.get('size') != size or not re.fullmatch('[a-f0-9]{64}', digest)):
            raise ValueError('Проверка файла релиза не пройдена: ' + name)
        if asset.get('digest') and asset['digest'] != 'sha256:' + digest:
            raise ValueError('SHA-256 GitHub и манифеста не совпадают')
        result[kind] = dict(spec, url=url)
    if result['app']['version'] != ver:
        raise ValueError('Версия приложения не совпадает с тегом')
    fw = result['firmware']
    if (fw.get('model') != 'HelloCubic-Lite' or fw.get('chip') != 'ESP8266' or
        fw.get('flash_bytes') != 4194304 or fw.get('display') != 'ST7789' or
        fw.get('width') != 240 or fw.get('height') != 240 or not fw.get('universal') or
        not re.fullmatch(r'pcstream-v[0-9.]+-[a-z0-9-]+', fw.get('build_id', ''))):
        raise ValueError('Прошивка не подходит для HelloCubic-Lite')
    return result


def verify_file(path, spec, kind):
    if path.stat().st_size != spec['size']:
        raise ValueError('Размер загруженного файла не совпадает')
    with path.open('rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    if not secrets.compare_digest(digest, spec['sha256']):
        raise ValueError('SHA-256 не совпадает. Установка отменена.')
    with path.open('rb') as source:
        header = source.read(2)
        if kind == 'app' and header != b'MZ':
            raise ValueError('Файл не является приложением Windows')
        if kind == 'firmware':
            source.seek(0)
            image = source.read(LIMITS[kind] + 1)
            if image[:1] != b'\xe9' or spec['build_id'].encode() not in image:
                raise ValueError('Заголовок или версия прошивки не совпадают')


class UpdateService:
    def __init__(self, storage):
        self.directory = Path(storage) / 'updates'
        self.lock = threading.RLock()
        self.specs = {}
        self.staged = {}
        self.worker = None
        self.last_check = 0.0
        self.shutdown = threading.Event()
        self.state = {'status': 'idle', 'message': 'Проверим GitHub Releases на новые версии.',
                      'current_version': VERSION, 'latest_version': None, 'release_url': 'https://github.com/' + REPOSITORY + '/releases',
                      'checked_at': None, 'progress': 0, 'available': False, 'firmware': None,
                      'notes': '', 'ready': [], 'busy': False}

    def public(self):
        last_install = None
        try:
            result = json.loads((self.directory / 'update-result.json').read_text('utf-8-sig'))
            if isinstance(result, dict) and result.get('status') in ('installed', 'rolled_back', 'error'):
                last_install = {'status': result['status'], 'version': str(result.get('version', ''))[:30]}
        except (OSError, ValueError, TypeError):
            pass
        with self.lock:
            return dict(self.state, ready=list(self.staged), last_install=last_install,
                        install_supported=os.name == 'nt' and bool(getattr(sys, 'frozen', False)))

    def _run(self, status, action):
        with self.lock:
            if self.state['busy']:
                raise ValueError('Обновление уже выполняется')
            self.state.update(status=status, busy=True, progress=0)
            self.state['message'] = 'Проверяем GitHub Releases…' if status == 'checking' else 'Загружаем обновление…'
        def work():
            try:
                action()
            except urllib.error.HTTPError as error:
                with self.lock:
                    self.state.update(status='error', message=('Публичный релиз пока не опубликован.' if error.code == 404 else
                        'GitHub временно недоступен или ограничил запросы. Попробуйте позже.'))
            except (OSError, ValueError, TypeError, KeyError) as error:
                with self.lock:
                    self.state.update(status='error', message='Не удалось обновить: ' + str(error)[:250])
            finally:
                with self.lock:
                    self.state['busy'] = False
        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def check(self, automatic=False):
        with self.lock:
            if self.state['busy'] or (self.last_check and time.monotonic() - self.last_check < (3600 if automatic else 30)):
                return
            self.last_check = time.monotonic()
        def action():
            release = read_json('https://api.github.com/repos/' + REPOSITORY + '/releases/latest', 1024 * 1024)
            if not isinstance(release, dict):
                raise ValueError('Некорректный ответ GitHub')
            tag = release.get('tag_name', '')
            if not re.fullmatch(r'v\d+\.\d+\.\d+', tag) or release.get('draft') or release.get('prerelease'):
                raise ValueError('Нет подходящего стабильного релиза')
            url = 'https://github.com/' + REPOSITORY + '/releases/download/' + tag + '/update.json'
            specs = release_manifest(release, read_json(url))
            available = version_tuple(specs['app']['version']) > version_tuple(VERSION)
            with self.lock:
                # A cached download belongs to a particular manifest, never to a mutable latest tag.
                if specs != self.specs:
                    self.staged.clear()
                self.specs = specs
                self.state.update(status='available' if available else 'up_to_date', available=available,
                    latest_version=specs['app']['version'], firmware={k: specs['firmware'][k] for k in ('version', 'model')},
                    release_url=release['html_url'], checked_at=time.time(), notes=str(release.get('body') or '')[:6000],
                    message='Доступна новая версия CubeDesk.' if available else 'У вас актуальная версия CubeDesk.')
        self._run('checking', action)

    def start_polling(self):
        self.check(automatic=True)
        def repeat():
            while not self.shutdown.wait(3600):
                self.check(automatic=True)
        threading.Thread(target=repeat, daemon=True).start()

    def download(self, kind):
        if kind not in ASSET_NAMES:
            raise ValueError('Неизвестный компонент обновления')
        with self.lock:
            if kind not in self.specs:
                raise ValueError('Сначала проверьте обновления')
            spec = self.specs[kind].copy()
            if kind == 'app' and version_tuple(spec['version']) <= version_tuple(VERSION):
                raise ValueError('Более новая версия приложения не найдена')
        def action():
            self.directory.mkdir(parents=True, exist_ok=True)
            directory = self.directory / self.specs['app']['version']
            directory.mkdir(exist_ok=True)
            target = directory / ASSET_NAMES[kind]
            temporary = target.with_suffix('.part')
            try:
                received = 0
                with open_public(spec['url']) as source, temporary.open('wb') as output:
                    declared = source.headers.get('Content-Length')
                    if declared and int(declared) != spec['size']:
                        raise ValueError('Сервер вернул другой размер файла')
                    started = time.monotonic()
                    while block := source.read(65536):
                        received += len(block)
                        if received > spec['size'] or time.monotonic() - started > 600:
                            raise ValueError('Превышен размер или время загрузки')
                        output.write(block)
                        with self.lock:
                            self.state.update(progress=round(received * 100 / spec['size']), message='Загружаем и проверяем ' + ASSET_NAMES[kind])
                verify_file(temporary, spec, kind)
                temporary.replace(target)
                with self.lock:
                    self.staged[kind] = target
                    self.state.update(status='ready', progress=100, message='Файл проверен. Можно установить обновление.')
            finally:
                temporary.unlink(missing_ok=True)
        self._run('downloading', action)

    def prepared(self, kind):
        with self.lock:
            if self.state['busy'] or kind not in self.staged:
                raise ValueError('Сначала загрузите и проверьте обновление')
            path, spec = self.staged[kind], self.specs[kind].copy()
        verify_file(path, spec, kind)
        return path, spec

    def install_app(self, port, storage):
        if os.name != 'nt' or not getattr(sys, 'frozen', False):
            raise ValueError('Установка из панели доступна в готовом CubeDesk.exe для Windows. Для исходников используйте git pull.')
        candidate, spec = self.prepared('app')
        target = Path(sys.executable).resolve()
        # Fail before stopping playback if the installed folder is read-only.
        probe = target.parent / ('.cubedesk-write-' + secrets.token_hex(8))
        try:
            with probe.open('xb') as output:
                output.write(b'')
        finally:
            probe.unlink(missing_ok=True)
        script = self.directory / 'install-update.ps1'
        shutil.copyfile(Path(__file__).parent / 'resources/install-update.ps1', script)
        nonce = secrets.token_hex(24)
        command = ['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(script),
                   '-ParentPid', str(os.getpid()), '-Target', str(target), '-Candidate', str(candidate),
                   '-Sha256', spec['sha256'], '-ExpectedVersion', spec['version'], '-HealthToken', nonce,
                   '-Port', str(port), '-DataDir', str(Path(storage).resolve())]
        environment = {k: v for k, v in os.environ.items() if not k.startswith('_PYI_') and k != '_MEIPASS2'}
        environment['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
        subprocess.Popen(command, creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS, env=environment,
                         close_fds=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with self.lock:
            self.state.update(status='installing', message='Устанавливаем обновление. Панель откроется после перезапуска.')


def flash_firmware(host, token, path, spec, report=lambda value: None):
    """Explicit OTA only. No filesystem writes, config reset, or automatic upload retry."""
    from cubedesk.device import Device
    verify_file(path, spec, 'firmware')
    device = Device(host, token)
    info = device.inspect()
    if info.get('kind') != 'stream' or info.get('model') != spec['model'] or version_tuple(info['version']) < (1, 6, 0):
        raise ValueError('Обновление поддерживается только для HelloCubic-Lite с PCStream 1.6 или новее')
    if version_tuple(info['version']) >= version_tuple(spec['version']):
        raise ValueError('На кубике уже установлена эта или более новая прошивка')
    auth_headers = {'Authorization': 'Bearer ' + token}
    wifi = json.loads(device._request('/api/v1/wifi/status', headers=auth_headers))
    if not wifi.get('connected') or not wifi.get('saved_network') or not wifi.get('stored_token_matches'):
        raise ValueError('Перед обновлением кубик должен работать в сохранённой домашней сети')
    image = path.read_bytes()
    boundary = 'CubeDesk' + secrets.token_hex(16)
    prefix = (f'--{boundary}\r\nContent-Disposition: form-data; name="firmware"; filename="firmware.bin"\r\n'
              'Content-Type: application/octet-stream\r\n\r\n').encode()
    body = prefix + image + f'\r\n--{boundary}--\r\n'.encode()
    connection = http.client.HTTPConnection(host, 80, timeout=50)
    report('Записываем прошивку. Не отключайте питание кубика.')
    confirmed = False
    try:
        connection.putrequest('POST', '/legacyupdate')
        connection.putheader('Authorization', 'Basic ' + base64.b64encode(('cubedesk:' + token).encode()).decode())
        connection.putheader('Content-Type', 'multipart/form-data; boundary=' + boundary)
        connection.putheader('Content-Length', str(len(body)))
        connection.putheader('Connection', 'close')
        connection.endheaders()
        for offset in range(0, len(body), 1024):
            connection.send(body[offset:offset + 1024])
            time.sleep(.012)
        response = connection.getresponse()
        confirmed = response.status == 200 and b'Update Success!' in response.read(16384)
    except OSError:
        # A reboot can interrupt the response. Read back the version, never re-upload blindly.
        pass
    finally:
        connection.close()
    report('Ожидаем возвращения кубика в домашнюю сеть…')
    deadline = time.monotonic() + 100
    while time.monotonic() < deadline:
        time.sleep(2)
        try:
            page = device._request('/', timeout=3, maximum=16000)
            after = json.loads(device._request('/api/v1/wifi/status', headers=auth_headers, timeout=3))
            if spec['build_id'].encode() in page and all(after.get(k) for k in ('connected', 'loaded_saved_network', 'stored_ssid_matches', 'stored_password_matches', 'stored_token_matches')):
                report('Прошивка обновлена. Домашняя сеть и ключ подключения сохранены.')
                return device.inspect()
        except (OSError, ValueError):
            continue
    raise ValueError(('Кубик подтвердил запись, но не вернулся по прежнему IP. ' if confirmed else 'Подтверждение обновления не получено. ') +
                     'Проверьте экран кубика и его IP. Повторная запись автоматически не выполнялась.')
