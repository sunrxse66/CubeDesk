"""Serialized access to the small stock firmware HTTP server."""
from __future__ import annotations

import gzip
import io
import ipaddress
import json
import re
import threading
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from PIL import Image, ImageOps
from cube_player import CubeConnection


def validate_host(value: str) -> str:
    try:
        address = ipaddress.IPv4Address(value.strip())
    except (ValueError, AttributeError) as error:
        raise ValueError("Введите IP кубика, например 192.168.0.37, без http://") from error
    if not address.is_private or address.is_unspecified or address.is_multicast or address.is_reserved:
        raise ValueError("Нужен адрес кубика в вашей локальной сети")
    return str(address)


def prepare_stock_file(path: Path) -> tuple[bytes, str, str]:
    with Image.open(path) as image:
        if image.format == "GIF":
            if image.size != (240, 240):
                raise ValueError("Для штатной прошивки нужен GIF размером 240×240. Измените размер GIF или используйте потоковую прошивку.")
            return path.read_bytes(), ".gif", "image/gif"
        if getattr(image, "n_frames", 1) > 1:
            raise ValueError("Штатная прошивка воспроизводит анимацию в формате GIF. Для этого файла используйте потоковый режим.")
        rgba = ImageOps.exif_transpose(image).convert("RGBA")
        background = Image.new("RGBA", rgba.size, "black")
        background.alpha_composite(rgba)
        canvas = ImageOps.pad(background.convert("RGB"), (240, 240), color="black")
        output = io.BytesIO()
        canvas.save(output, format="JPEG", quality=90)
        return output.getvalue(), ".jpg", "image/jpeg"


class Device:
    def __init__(self, host: str, token: str = "", port: int = 80):
        self.host = validate_host(host)
        self.token = token
        self.port = port
        self.lock = threading.Lock()
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.last_request = 0.0

    def _request(self, path, data=None, headers=None, timeout=4, maximum=250000):
        # Never send parallel requests to the ESP8266, even for status checks.
        time.sleep(max(0, .35 - (time.monotonic() - self.last_request)))
        self.last_request = time.monotonic()
        request = urllib.request.Request(f"http://{self.host}:{self.port}{path}", data=data, headers=headers or {})
        with self.opener.open(request, timeout=timeout) as response:
            result = response.read(maximum + 1)
        if len(result) > maximum:
            raise ValueError("Слишком большой ответ устройства")
        if result.startswith(b"\x1f\x8b"):
            result = gzip.decompress(result)
            if len(result) > maximum:
                raise ValueError("Слишком большой ответ устройства")
        return result

    def inspect(self):
        with self.lock:
            stock_error = None
            try:
                info = json.loads(self._request("/v.json", maximum=8192))
                if not isinstance(info, dict) or info.get("m") != "HelloCubic-Lite":
                    raise ValueError("По этому адресу не подтверждён HelloCubic-Lite")
                result = {"kind": "stock", "model": info["m"], "version": str(info.get("v", "")),
                          "host": self.host, "total": None, "free": None}
                try:
                    memory = json.loads(self._request("/space.json", maximum=8192))
                    total, free = int(memory["total"]), int(memory["free"])
                    if total > 0 and 0 <= free <= total:
                        result.update(total=total, free=free)
                except (OSError, ValueError, KeyError, TypeError):
                    pass  # Identification succeeds even if optional memory status is unavailable.
                return result
            except (OSError, ValueError, TypeError) as error:
                stock_error = error
            if self.token:
                try:
                    connection = CubeConnection(self.host, self.token)
                    try:
                        connection.send()
                    finally:
                        connection.close()
                    version = "PCStream v1"
                    try:
                        page = self._request("/", timeout=2, maximum=16000)
                        match = re.search(rb"pcstream-v([0-9]+(?:\.[0-9]+)*)", page)
                        if match:
                            version = "PCStream v" + match.group(1).decode("ascii")
                    except (OSError, ValueError):
                        pass
                    return {"kind": "stream", "model": "HelloCubic-Lite", "version": version,
                            "host": self.host, "total": None, "free": None}
                except (OSError, ValueError):
                    pass
            raise ConnectionError("Кубик не ответил. Проверьте IP и питание. Если на экране есть картинка, отключите питание на 5 секунд и повторите. Для PCStream также нужен API-токен.") from stock_error

    def show_stock(self, path: Path):
        payload, extension, mime = prepare_stock_file(path)
        filename = "cube_" + uuid.uuid4().hex[:12] + extension
        with self.lock:
            memory = json.loads(self._request("/space.json", maximum=8192))
            if len(payload) + 8192 > int(memory.get("free", 0)):
                raise ValueError("В памяти кубика недостаточно места. Удалите ненужные файлы через его страницу «Pictures» или используйте потоковую прошивку.")
            boundary = "CubeDesk" + uuid.uuid4().hex
            body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
                    f"Content-Type: {mime}\r\n\r\n").encode() + payload + f"\r\n--{boundary}--\r\n".encode()
            result = self._request("/doUpload?dir=/image", body,
                                   {"Content-Type": f"multipart/form-data; boundary={boundary}"}, timeout=20)
            if result.strip().upper() in (b"FAIL", b"FAILED", b"ERROR"):
                raise ConnectionError("Кубик отклонил загрузку файла")
            listing = self._request("/filelist?dir=/image")
            if filename.encode() not in listing:
                raise ConnectionError("Передача закончилась, но кубик не подтвердил наличие файла. Проверьте страницу Pictures; повторную загрузку автоматически не выполняю.")
            for query in [{"theme": 2}, {"img": "/image/" + filename}]:
                result = self._request("/set?" + urllib.parse.urlencode(query), maximum=8192)
                if result.strip() != b"OK":
                    raise ConnectionError("Файл загружен, но переключение экрана не подтверждено. Выберите его на странице Pictures.")
        return filename
