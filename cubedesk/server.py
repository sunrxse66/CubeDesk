"""Loopback-only server. Device access is explicit; state polling is local."""
from __future__ import annotations

import argparse
import datetime
import hashlib
import io
import json
import math
import mimetypes
import os
from pathlib import Path
import secrets
import sys
import threading
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PIL import Image, ImageOps
from cube_player import SUPPORTED
from smooth_player import play
from cubedesk.device import Device, validate_host
from cubedesk.weather import WeatherService, validate_city
from cubedesk.widgets import KINDS, render as render_widget, play_widget
from cubedesk.pet import PetState, play_pet, validate_character
from cubedesk.findings import PhotoFindings, pick_photo_folder
from cubedesk import VERSION
from cubedesk.updates import UpdateService, flash_firmware

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "web"
MAX_UPLOAD = 256 * 1024 * 1024


class AppState:
    def __init__(self, storage: Path, migrate: Path | None = None):
        self.storage = storage
        storage.mkdir(parents=True, exist_ok=True)
        self.imports = storage / "Медиатека"
        self.imports.mkdir(exist_ok=True)
        self.config_path = storage / "settings.json"
        self.lock = threading.RLock()
        self.control = threading.RLock()
        self.config = {"host": "", "token": "", "folder": str(self.imports), "fps": 30, "seconds": 5, "detail": "smooth", "widget_city": None, "pet_character":"moti"}
        source = self.config_path if self.config_path.exists() else migrate
        if source and source.is_file():
            try:
                loaded = json.loads(source.read_text("utf-8"))
                for key in self.config:
                    if key in loaded:
                        self.config[key] = loaded[key]
                if self.config['host']: validate_host(self.config["host"])
                if not Path(self.config["folder"]).is_dir():
                    self.config["folder"] = str(self.imports)
            except (OSError, ValueError, TypeError):
                self.config.update(host="", folder=str(self.imports), token="")
        try:
            self.config['widget_city'] = validate_city(self.config['widget_city'])
        except ValueError:
            self.config['widget_city'] = None
        self.weather = WeatherService(storage)
        try:self.config['pet_character']=validate_character(self.config['pet_character'])
        except ValueError:self.config['pet_character']='moti'
        self.pet = PetState(character=self.config['pet_character'])
        self.findings = PhotoFindings(storage)
        self.pet.set_frame(self.findings.frame['image'] if self.findings.frame else None)
        self.updates = UpdateService(storage)
        self.device = {"kind": "unknown", "host": self.config["host"]}
        self.job = {"running": False, "kind": "", "message": "Готов к подключению", "error": False}
        self.events = []
        self.files = {}
        self.stop = threading.Event()
        self.worker = None
        self.playback = {}
        self.csrf = secrets.token_urlsafe(32)
        self.save()

    def save(self):
        temporary = self.config_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.config, ensure_ascii=False, indent=2), "utf-8")
        temporary.replace(self.config_path)

    def log(self, message):
        with self.lock:
            self.events.append({"time": datetime.datetime.now().strftime("%H:%M:%S"), "message": str(message)})
            self.events = self.events[-40:]
            self.job["message"] = str(message)

    def public(self):
        with self.lock:
            return {"settings": {k: v for k, v in self.config.items() if k != "token"} |
                    {"has_token": bool(self.config["token"])}, "device": self.device.copy(),
                    "job": self.job.copy(), "playback": self.playback.copy(),
                    "pet": self.pet.status() | {'active': self.job['running'] and self.job.get('scope') == 'pet'},
                    "findings": self.findings.public(),
                    "events": list(self.events), "version": VERSION}

    def _validated_settings(self, data):
        with self.lock:
            updated = self.config.copy()
            for key in updated:
                if key in data:
                    updated[key] = data[key]
            updated["host"] = validate_host(updated["host"]) if updated['host'] else ''
            if updated['detail'] not in ('smooth', 'balanced', 'sharp'):
                raise ValueError('Выберите режим «Плавно», «Баланс» или «Чётко»')
            folder = Path(str(updated["folder"])).expanduser()
            if not folder.is_dir():
                raise ValueError("Папка не найдена на этом компьютере. Вставьте полный путь из Проводника.")
            updated["folder"] = str(folder.resolve())
            for key, maximum in [("fps", 30), ("seconds", 86400)]:
                updated[key] = float(updated[key])
                if not math.isfinite(updated[key]) or not 0 < updated[key] <= maximum:
                    raise ValueError("Кадров/с: от 1 до 30. Время показа: больше 0 и до 86400 секунд.")
            if not isinstance(updated["token"], str) or len(updated["token"].encode()) > 128:
                raise ValueError("API-токен должен содержать не более 128 байт")
            updated['widget_city'] = validate_city(updated['widget_city'])
            updated['pet_character'] = validate_character(updated['pet_character'])
            return updated

    def settings(self, data):
        with self.control, self.lock:
            if self.job["running"]:
                raise ValueError("Сначала остановите текущую операцию")
            updated = self._validated_settings(data)
            if updated["host"] != self.config["host"] or updated["token"] != self.config["token"]:
                self.device = {"kind": "unknown", "host": updated["host"]}
            self.config = updated
            self.save()
            self.pet.select(updated['pet_character'])
        return self.public()

    def library(self):
        with self.lock:
            folder = Path(self.config["folder"])
        if not folder.is_dir():
            raise ValueError("Папка медиатеки недоступна. Подключите её снова.")
        files = {}
        items = []
        for path in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
            if not path.is_file() or path.suffix.lower() not in SUPPORTED:
                continue
            ident = hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:24]
            try:
                with Image.open(path) as image:
                    width, height = image.size
                    frames = getattr(image, "n_frames", 1)
                item = {"id": ident, "name": path.name, "bytes": path.stat().st_size,
                        "width": width, "height": height, "frames": frames, "error": ""}
            except (OSError, ValueError) as error:
                item = {"id": ident, "name": path.name, "bytes": path.stat().st_size,
                        "width": 0, "height": 0, "frames": 0, "error": "Файл не удалось прочитать"}
            files[ident] = path
            items.append(item)
            if len(items) >= 1000:
                break
        with self.lock:
            self.files = files
        return {"items": items, "folder": str(folder), "limit": 1000}

    def file(self, ident):
        with self.lock:
            path = self.files.get(ident)
        if not path or not path.is_file():
            raise ValueError("Файл не найден. Обновите медиатеку.")
        return path

    def begin(self, kind, action, **metadata):
        with self.control:
            self._begin(kind, action, metadata)

    def _begin(self, kind, action, metadata):
        with self.lock:
            if self.job["running"]:
                raise ValueError("Дождитесь завершения текущей операции")
            self.stop.clear()
            self.job = {"running": True, "kind": kind, "message": "Подождите…", "error": False, **metadata}
            config = self.config.copy()

        def run():
            try:
                action(config)
            except Exception as error:
                self.log(str(error))
                with self.lock:
                    self.job["error"] = True
                    if kind == "connect":
                        self.device = {"kind": "offline", "host": config["host"]}
            finally:
                with self.lock:
                    self.job["running"] = False
        self.worker = threading.Thread(target=run, daemon=True)
        self.worker.start()

    def connect(self):
        def action(config):
            self.log("Проверяю подключение к кубику…")
            result = Device(config["host"], config["token"]).inspect()
            with self.lock:
                self.device = result
            self.log("Кубик подключён · " + result["version"])
        self.begin("connect", action)

    def stream(self, selected_file=None, selected_id=None, options=None):
        with self.control:
            self._stream(selected_file, selected_id, options or {})

    def _stream(self, selected_file, selected_id, options):
        if self.device.get("kind") != "stream":
            raise ValueError("Потоковое воспроизведение требует PCStream. На штатной прошивке используйте кнопку «Показать» на файле.")
        if not self.library()["items"]:
            raise ValueError("Сначала добавьте изображения или подключите папку")
        options = {key: options[key] for key in ('fps', 'seconds', 'detail') if key in options}
        updated = self._validated_settings(options)
        if selected_file is not None and selected_file.resolve().parent != Path(updated['folder']).resolve():
            raise ValueError("Файл больше не находится в текущей медиатеке. Обновите список.")
        self._stop_stream()
        self.settings(options)
        def action(config):
            with self.lock:
                self.playback = {}
            def report(message):
                if str(message).startswith("Connection:"):
                    message = "Связь прервалась. Повторное подключение через 2 секунды…"
                self.log(message)
            def stats(detail):
                with self.lock:
                    self.playback = detail.copy()
            play(config["host"], config["token"], Path(config["folder"]), self.stop,
                 report=report, fps=config["fps"], seconds=config["seconds"], on_stats=stats,
                 detail=config['detail'], selected_file=selected_file)
            self.log("Воспроизведение остановлено. Последний кадр остаётся на кубике.")
        self.begin("stream", action, scope='file' if selected_file is not None else 'folder', file_id=selected_id)

    def _stop_stream(self):
        with self.lock:
            running, kind = self.job['running'], self.job['kind']
        if running:
            if kind != 'stream':
                raise ValueError("Дождитесь завершения текущей операции")
            self.stop.set()
            self.worker.join(10)
            if self.worker.is_alive():
                raise ValueError("Предыдущий поток ещё останавливается. Повторите через несколько секунд.")

    def widget_state(self):
        with self.lock:
            city = self.config['widget_city']
        return self.weather.snapshot(city)

    def choose_city(self, ident):
        city = self.weather.selected(ident)
        with self.control, self.lock:
            self.config['widget_city'] = city
            self.save()
        self.weather.refresh(city, force=True)
        return self.widget_state()

    def widget(self, kind):
        with self.control:
            if kind not in KINDS:
                raise ValueError('Выберите часы, погоду или общий экран')
            if self.device.get('kind') != 'stream':
                raise ValueError('Сначала подключите кубик с PCStream')
            if kind != 'clock' and not self.config['widget_city']:
                raise ValueError('Сначала выберите город для погоды')
            self._stop_stream()
            def action(config):
                with self.lock:
                    self.playback = {}
                def supplier():
                    with self.lock:
                        city = self.config['widget_city']
                    if kind != 'clock':
                        self.weather.refresh(city)
                    return self.weather.snapshot(city)
                def stats(value):
                    with self.lock:
                        self.playback = value.copy()
                play_widget(config['host'],config['token'],kind,self.stop,supplier,
                            report=self.log,on_stats=stats)
                self.log('Виджет остановлен. Последний экран остаётся на кубике.')
            self.begin('stream',action,scope='widget',widget=kind,file_id=None)

    def show(self, ident, options=None):
        if self.device.get('kind') == 'stream':
            path = self.file(ident)
            self.stream(path, ident, options)
            return
        if self.device.get("kind") != "stock":
            raise ValueError("Сначала подключите кубик со штатной прошивкой")
        path = self.file(ident)
        def action(config):
            self.log("Передаю «" + path.name + "» в память кубика…")
            Device(config["host"], config["token"]).show_stock(path)
            self.log("Файл загружен и выбран на кубике · " + path.name)
            # Status is refreshed only on demand, not by a background poll.
            with self.lock:
                self.device["free"] = None
        self.begin("upload", action)

    def select_pet(self, character):
        character=validate_character(character)
        with self.control,self.lock:
            if self.job['running'] and self.job['kind']!='stream':
                raise ValueError('Дождитесь завершения текущей операции')
            self.config['pet_character']=character
            self.save()
            self.pet.select(character)
        return self.public()['pet']

    def show_pet(self, call=False):
        with self.control:
            if self.device.get('kind') != 'stream':
                raise ValueError('Сначала подключите кубик с PCStream')
            with self.lock:
                active = self.job['running'] and self.job.get('scope') == 'pet'
            if active:
                if call:self.pet.request_call()
                return
            self._stop_stream()
            self.pet.reset()
            if call:self.pet.request_call()
            def action(config):
                with self.lock:
                    self.playback = {}
                def stats(value):
                    with self.lock:self.playback = value.copy()
                play_pet(config['host'],config['token'],self.pet,self.stop,report=self.log,on_stats=stats)
                self.log('Питомец отдыхает. Последний кадр остаётся на кубике.')
            self.begin('stream',action,scope='pet',widget='pet',file_id=None)

    def photo_folder(self, folder):
        with self.control:
            with self.lock:
                if self.job['running'] and self.job['kind']!='stream':
                    raise ValueError('Дождитесь завершения текущей операции')
            result=self.findings.choose(folder)
            self.pet.reset()
            self.pet.set_frame(self.findings.frame['image'] if self.findings.frame else None)
            return result

    def find_photo(self):
        with self.control:
            with self.lock:
                if self.device.get('kind')!='stream':raise ValueError('Сначала подключите кубик с PCStream.')
                if self.job['running'] and self.job['kind']!='stream':raise ValueError('Дождитесь завершения текущей операции')
                active=self.job['running'] and self.job.get('scope')=='pet'
            if active and self.pet.finding_busy():raise ValueError('Момо уже ищет находку. Подождите его возвращения.')
            photo=self.findings.next()
            self.select_pet('momo')
            self.show_pet()
            self.pet.request_finding(photo)

    def pin_photo(self, ident):
        with self.control:
            self.pet.set_frame(self.findings.pin(ident))
            return self.findings.public()

    def unpin_photo(self):
        with self.control:
            self.findings.unpin()
            self.pet.set_frame(None)
            return self.findings.public()


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, state):
        self.app = state
        self.update_nonce = ''
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    server_version = 'CubeDesk/' + VERSION

    def log_message(self, *args):
        pass  # Do not log tokens, file paths, or raw request bodies.

    def guard(self, mutation=False):
        allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        if self.headers.get("Host") not in allowed:
            self.send_error(403)
            return False
        if mutation:
            origin = self.headers.get("Origin")
            if origin and origin not in {"http://" + host for host in allowed}:
                self.send_error(403)
                return False
            if not secrets.compare_digest(self.headers.get("X-CubeDesk-Key", ""), self.server.app.csrf):
                self.send_error(403)
                return False
        return True

    def reply(self, data, content_type="application/json; charset=utf-8", status=200):
        if not isinstance(data, bytes):
            data = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' blob:; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self.guard():
            return
        url = urllib.parse.urlsplit(self.path)
        app = self.server.app
        try:
            if url.path == '/api/health':
                self.reply({'app': 'CubeDesk', 'version': VERSION, 'update_nonce': self.server.update_nonce,
                            'profile_id': profile_id(app.storage)})
            elif url.path == '/api/updates':
                self.reply(app.updates.public())
            elif url.path == "/api/state":
                self.reply(app.public())
            elif url.path == "/api/library":
                self.reply(app.library())
            elif url.path == '/api/widgets/state':
                self.reply(app.widget_state())
            elif url.path == '/api/pet/preview':
                output = io.BytesIO()
                app.pet.image().save(output,'PNG')
                self.reply(output.getvalue(),'image/png')
            elif url.path == '/api/pet/state':
                self.reply(app.public()['pet'])
            elif url.path == '/api/pet/findings/preview':
                kind=urllib.parse.parse_qs(url.query).get('kind',['current'])[0]
                output=io.BytesIO()
                app.findings.preview(kind).save(output,'JPEG',quality=88)
                self.reply(output.getvalue(),'image/jpeg')
            elif url.path == '/api/widgets/preview':
                kind = urllib.parse.parse_qs(url.query).get('kind',['clock'])[0]
                output = io.BytesIO()
                render_widget(kind,app.widget_state()).save(output,'PNG')
                self.reply(output.getvalue(),'image/png')
            elif url.path in ("/api/thumbnail", "/api/preview"):
                ident = urllib.parse.parse_qs(url.query).get("id", [""])[0]
                path = app.file(ident)
                if url.path == "/api/preview":
                    size = path.stat().st_size
                    self.send_response(200)
                    self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
                    self.send_header("Content-Length", str(size))
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    with path.open("rb") as source:
                        while block := source.read(65536):
                            self.wfile.write(block)
                else:
                    with Image.open(path) as source:
                        image = ImageOps.exif_transpose(source).convert("RGBA")
                        background = Image.new("RGBA", image.size, "black")
                        background.alpha_composite(image)
                        image = ImageOps.pad(background.convert("RGB"), (240, 240), color="black")
                        output = io.BytesIO()
                        image.save(output, "JPEG", quality=85)
                    self.reply(output.getvalue(), "image/jpeg")
            elif url.path in ("/", "/index.html"):
                data = (ASSETS / "index.html").read_text("utf-8").replace("__CSRF__", app.csrf).replace('__VERSION__', VERSION)
                self.reply(data.encode(), "text/html; charset=utf-8")
            elif url.path in ("/app.js", "/widgets.js", "/pet.js", "/updates.js", "/style.css", "/findings.css", "/cube.svg"):
                path = ASSETS / url.path[1:]
                self.reply(path.read_bytes(), mimetypes.guess_type(path.name)[0] or "application/octet-stream")
            elif url.path == "/favicon.ico":
                self.reply(b"", "image/x-icon", 204)
            else:
                self.reply({"error": "Страница не найдена"}, status=404)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as error:
            self.reply({"error": str(error)}, status=400)

    def do_POST(self):
        if not self.guard(mutation=True):
            return
        app = self.server.app
        url = urllib.parse.urlsplit(self.path)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 <= length <= (MAX_UPLOAD if url.path == "/api/import" else 65536):
                self.reply({"error": "Файл больше 256 МБ или запрос слишком велик"}, status=413)
                return
            self.connection.settimeout(30)
            if url.path == "/api/import":
                name = urllib.parse.parse_qs(url.query).get("name", [""])[0]
                # Store a generated filename; browser paths never become filesystem paths.
                name = Path(name.replace("\\", "/")).name
                if not name or Path(name).suffix.lower() not in SUPPORTED:
                    raise ValueError("Поддерживаются JPG, PNG, GIF, WebP и BMP")
                stem = "".join(c for c in Path(name).stem if c.isalnum() or c in " _-")[:80] or "image"
                destination = app.imports / (secrets.token_hex(4) + "_" + stem + Path(name).suffix.lower())
                temporary = destination.with_suffix(".upload")
                try:
                    remaining = length
                    with temporary.open("wb") as output:
                        while remaining:
                            block = self.rfile.read(min(remaining, 65536))
                            if not block:
                                raise ValueError("Передача файла прервалась")
                            output.write(block)
                            remaining -= len(block)
                    with Image.open(temporary) as image:
                        image.verify()
                    temporary.replace(destination)
                finally:
                    temporary.unlink(missing_ok=True)
                self.reply({"ok": True, "folder": str(app.imports)})
                return
            body = self.rfile.read(length)
            if len(body) != length:
                raise ValueError("Неполный запрос")
            data = json.loads(body or b"{}")
            if not isinstance(data, dict):
                raise ValueError("Неверный запрос")
            if url.path == "/api/settings":
                result = app.settings(data)
            elif url.path == "/api/connect":
                app.connect()
                result = {"ok": True}
            elif url.path == "/api/play":
                app.stream(options=data)
                result = {"ok": True}
            elif url.path == "/api/show":
                app.show(data.get("id", ""), options=data)
                result = {"ok": True}
            elif url.path == '/api/widgets/search':
                result = {'cities': app.weather.search(data.get('query',''))}
            elif url.path == '/api/widgets/city':
                result = app.choose_city(data.get('id'))
            elif url.path == '/api/widgets/refresh':
                with app.lock:
                    city = app.config['widget_city']
                app.weather.refresh(city,force=bool(data.get('force',False)))
                result = app.widget_state()
            elif url.path == '/api/widgets/show':
                app.widget(data.get('kind'))
                result = {'ok':True}
            elif url.path in ('/api/pet/show','/api/pet/call'):
                app.show_pet(call=url.path.endswith('/call'))
                result = {'ok':True,'pet':app.public()['pet']}
            elif url.path == '/api/pet/select':
                result = {'ok':True,'pet':app.select_pet(data.get('character'))}
            elif url.path == '/api/pet/findings/folder':
                result = app.photo_folder(data.get('folder'))
            elif url.path == '/api/pet/findings/browse':
                result = {'folder':pick_photo_folder()}
            elif url.path == '/api/pet/findings/next':
                app.find_photo()
                result = {'ok':True}
            elif url.path == '/api/pet/findings/pin':
                result = app.pin_photo(data.get('id'))
            elif url.path == '/api/pet/findings/unpin':
                result = app.unpin_photo()
            elif url.path == '/api/pet/findings/open':
                app.findings.open_original(data.get('id'))
                result = {'ok':True}
            elif url.path == '/api/updates/check':
                app.updates.check()
                result = app.updates.public()
            elif url.path == '/api/updates/download':
                app.updates.download(data.get('kind'))
                result = app.updates.public()
            elif url.path == '/api/updates/install-app':
                with app.control:
                    if app.job['running'] and app.job['kind'] != 'stream':
                        raise ValueError('Дождитесь завершения текущей операции')
                    resume = {k: app.job[k] for k in ('scope', 'widget', 'file_id') if k in app.job} if app.job['running'] else {}
                    # Verify and start the detached helper before stopping the working stream.
                    app.updates.install_app(self.server.server_port, app.storage)
                    (app.storage / 'update-resume.json').write_text(json.dumps(resume), 'utf8')
                    app._stop_stream()
                    threading.Timer(.8, self.server.shutdown).start()
                result = {'ok': True, 'restarting': True}
            elif url.path == '/api/updates/install-firmware':
                with app.control:
                    path, spec = app.updates.prepared('firmware')
                    if app.device.get('kind') != 'stream' or app.device.get('model') != spec['model']:
                        raise ValueError('Сначала подключите совместимый HelloCubic-Lite с PCStream')
                    app._stop_stream()
                    def update_firmware(config):
                        info = flash_firmware(config['host'], config['token'], path, spec, app.log)
                        with app.lock:
                            app.device = info
                    app.begin('firmware', update_firmware)
                result = {'ok': True}
            elif url.path == "/api/stop":
                app.stop.set()
                result = {"ok": True}
            elif url.path == "/api/shutdown":
                if app.job['running'] and app.job['kind'] == 'firmware':
                    raise ValueError('Дождитесь завершения обновления прошивки')
                app.stop.set()
                result = {"ok": True}
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            else:
                self.reply({"error": "Действие не найдено"}, status=404)
                return
            self.reply(result)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as error:
            self.reply({"error": str(error)}, status=400)


def profile_id(storage):
    return hashlib.sha256(str(Path(storage).resolve()).encode()).hexdigest()[:16]


def existing_instance(port, storage):
    if not port:
        return False
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f'http://127.0.0.1:{port}/api/health', timeout=.6) as response:
            result = json.loads(response.read(2048))
        return isinstance(result, dict) and result.get('app') == 'CubeDesk' and result.get('profile_id') == profile_id(storage)
    except (OSError, ValueError, TypeError):
        return False


def main():
    parser = argparse.ArgumentParser(description="CubeDesk — локальное приложение для GeekMagic")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument('--update-health', default='', help=argparse.SUPPRESS)
    args = parser.parse_args()
    storage = args.data_dir or Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "CubeDesk"
    if not args.update_health and existing_instance(args.port, storage):
        if not args.no_browser:
            webbrowser.open(f'http://127.0.0.1:{args.port}')
        return
    migrate = (Path(sys.executable).parent if getattr(sys, "frozen", False) else ROOT) / "cube-local.json"
    app = AppState(storage, migrate)
    try:
        server = Server(("127.0.0.1", args.port), app)
    except OSError:
        if args.update_health:
            raise  # The updater must health-check the requested port, not an unrelated fallback.
        # Do not navigate to an unknown service occupying the preferred port.
        server = Server(("127.0.0.1", 0), app)
    server.update_nonce = args.update_health
    app.updates.start_polling()
    resume_path = storage / 'update-resume.json'
    if resume_path.is_file():
        try:
            resume = json.loads(resume_path.read_text('utf8'))
            resume_path.unlink()
            def restore():
                try:
                    result = Device(app.config['host'], app.config['token']).inspect()
                    with app.lock:
                        app.device = result
                    if resume.get('scope') == 'widget': app.widget(resume.get('widget'))
                    elif resume.get('scope') == 'pet': app.show_pet()
                    elif resume.get('scope') == 'file':
                        app.library()
                        ident = resume.get('file_id')
                        app.stream(app.file(ident), ident)
                    elif resume.get('scope') == 'folder': app.stream()
                except Exception as error:
                    app.log('Автовозврат к воспроизведению: ' + str(error))
            if resume:
                threading.Thread(target=restore, daemon=True).start()
        except (OSError, ValueError, TypeError):
            pass
    url = f"http://127.0.0.1:{server.server_port}"
    try:
        print("CubeDesk:", url, flush=True)
    except (AttributeError, OSError):
        pass  # Windowless packaged .exe has no console.
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=.25)
    except KeyboardInterrupt:
        pass
    finally:
        app.stop.set()
        app.updates.shutdown.set()
        server.server_close()


if __name__ == "__main__":
    main()
