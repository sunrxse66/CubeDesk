"""Local folder player for the PCStream GeekMagic firmware extension."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import queue
import socket
import struct
import threading
import time

from PIL import Image, ImageOps

SIZE = (240, 240)
FRAME_BYTES = 240 * 240 * 2
SUPPORTED = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
CONFIG = Path(__file__).with_name("cube-local.json")


def rgb565(image: Image.Image) -> bytes:
    """RGB565, most significant byte first, letterboxed on black."""
    rgba = ImageOps.exif_transpose(image).convert("RGBA")
    background = Image.new("RGBA", rgba.size, (0, 0, 0, 255))
    background.alpha_composite(rgba)
    canvas = ImageOps.pad(background.convert("RGB"), SIZE, color="black")
    output = bytearray(FRAME_BYTES)
    for i, (r, g, b) in enumerate(canvas.get_flattened_data()):
        value = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
        output[2 * i] = value >> 8
        output[2 * i + 1] = value & 255
    return bytes(output)


class CubeConnection:
    def __init__(self, host: str, token: str, port: int = 7777, modern: bool = False):
        encoded = token.encode("utf-8")
        if not 1 <= len(encoded) <= 128:
            raise ValueError("API token must contain 1 to 128 UTF-8 bytes")
        self.sequence = 0
        self.modern = False
        self.max_jpeg = 0
        self.flags = 0
        self.stats = {}
        for negotiate in ([True, False] if modern else [False]):
            self.sock = socket.create_connection((host, port), timeout=8)
            self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            try:
                self.sock.sendall((b"GMC2" if negotiate else b"GMC1") + struct.pack("<H", len(encoded)) + encoded)
                response = self.receive(4)
                if negotiate and response == b"OKJ2":
                    self.max_jpeg, self.flags = struct.unpack("<II", self.receive(8))
                    if self.max_jpeg > 65536:
                        raise ConnectionError("Invalid receiver buffer size")
                    self.modern = True
                    break
                if not negotiate and response == b"OKAY":
                    break
                raise ConnectionError("Firmware rejected authentication")
            except (OSError, ConnectionError):
                self.close()
                if not negotiate:
                    raise

    def receive(self, count: int) -> bytes:
        data = bytearray()
        while len(data) < count:
            part = self.sock.recv(count - len(data))
            if not part:
                raise ConnectionError("Cube disconnected; check firmware and API token")
            data.extend(part)
        return bytes(data)

    def send(self, pixels: bytes | None = None):
        if pixels is not None and len(pixels) != FRAME_BYTES:
            raise ValueError("Frame must contain exactly 115200 bytes")
        payload = pixels if pixels is not None else b""
        return self.send_packet(b"FRM1" if pixels is not None else b"PNG1", payload)

    def send_jpeg(self, payload: bytes):
        if not self.modern or not self.flags & 1 or not 4 <= len(payload) <= self.max_jpeg:
            raise ValueError("JPEG frame does not fit negotiated receiver buffer")
        return self.send_packet(b"JPG1", payload)

    def send_packet(self, magic: bytes, payload: bytes = b""):
        if magic not in (b"FRM1", b"PNG1", b"JPG1", b"RXD1", b"LCD1"):
            raise ValueError("Unknown stream packet")
        if magic in (b"RXD1", b"LCD1") and not self.modern:
            raise ValueError("Benchmark requires modern firmware")
        self.sequence = (self.sequence + 1) & 0xFFFFFFFF
        started = time.perf_counter()
        self.sock.sendall(struct.pack("<4sII", magic, self.sequence, len(payload)) + payload)
        response = self.receive(24 if self.modern else 8)
        if response[:8] != (b"ACK2" if self.modern else b"ACK1") + struct.pack("<I", self.sequence):
            raise ConnectionError("Invalid frame acknowledgement")
        self.stats = {"transport_ms": (time.perf_counter() - started) * 1000, "bytes": len(payload)}
        if self.modern:
            receive_us, draw_us, wire_bytes, free_heap = struct.unpack("<IIII", response[8:])
            self.stats.update(receive_ms=receive_us / 1000, draw_ms=draw_us / 1000,
                              bytes=wire_bytes, free_heap=free_heap)
        return self.stats

    def close(self):
        self.sock.close()


def hold(connection: CubeConnection, seconds: float, stop: threading.Event):
    end = time.monotonic() + seconds
    while not stop.is_set():
        remaining = end - time.monotonic()
        if remaining <= 0 or stop.wait(min(remaining, 3.0)):
            return
        connection.send()  # Keep static images connected without rewriting pixels.


def play(host: str, token: str, folder: Path, stop: threading.Event, report=print,
         fps: float = 8, seconds: float = 5, once: bool = False):
    if not folder.is_dir():
        raise ValueError("Select an existing folder")
    if not 0 < fps <= 30 or not 0 < seconds <= 86400:
        raise ValueError("FPS must be 0..30; image duration must be 0..86400 seconds")
    connection = None
    try:
        while not stop.is_set():
            paths = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED)
            if not paths:
                raise ValueError("Folder has no supported images or GIFs")
            for path in paths:
                if stop.is_set():
                    break
                report(path.name)
                try:
                    with Image.open(path) as image:
                        count = getattr(image, "n_frames", 1)
                        for index in range(count):
                            if stop.is_set():
                                break
                            image.seek(index)
                            started = time.monotonic()
                            pixels = rgb565(image)
                            delay = max(image.info.get("duration", 100) / 1000, 1 / fps) if count > 1 else seconds
                            while not stop.is_set():
                                try:
                                    if connection is None:
                                        connection = CubeConnection(host, token)
                                    connection.send(pixels)
                                    break
                                except (OSError, ConnectionError) as error:
                                    if connection:
                                        connection.close()
                                    connection = None
                                    report(f"Connection: {error}; retrying in 2 s")
                                    if once:
                                        raise
                                    stop.wait(2)
                            if not stop.is_set():
                                hold(connection, max(0, delay - (time.monotonic() - started)), stop)
                except OSError as error:
                    if once:
                        raise
                    report(f"Cannot play {path.name}: {error}")
                    stop.wait(1)
            if once:
                break
    finally:
        if connection:
            connection.close()


def gui():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    root = tk.Tk()
    root.title("GeekMagic — папка на ПК")
    root.geometry("600x410")
    root.minsize(520, 380)
    saved = {}
    if CONFIG.exists():
        try:
            saved = json.loads(CONFIG.read_text("utf-8"))
        except (OSError, ValueError):
            pass
    variables = {key: tk.StringVar(value=str(saved.get(key, default))) for key, default in
                 {"host": "", "token": "", "folder": "", "fps": 8, "seconds": 5}.items()}
    frame = ttk.Frame(root, padding=20)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="Картинки и анимации с ПК", font=("Segoe UI", 16)).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 15))
    for row, (key, label) in enumerate([("host", "IP кубика"), ("token", "API-токен"),
                                       ("folder", "Папка"), ("fps", "Максимум кадров/с"),
                                       ("seconds", "Секунд на картинку")], 1):
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=5)
        ttk.Entry(frame, textvariable=variables[key], show="*" if key == "token" else "").grid(row=row, column=1, sticky="ew", padx=10)
    ttk.Button(frame, text="Выбрать", command=lambda: variables["folder"].set(filedialog.askdirectory() or variables["folder"].get())).grid(row=3, column=2)
    frame.columnconfigure(1, weight=1)
    status = tk.StringVar(value="Требуется прошивка PCStream. Штатная V7.0.22 не поддерживается.")
    ttk.Label(frame, textvariable=status, wraplength=530).grid(row=7, column=0, columnspan=3, sticky="w", pady=18)
    messages = queue.Queue()
    stop = threading.Event()
    worker = None

    def start():
        nonlocal worker
        if worker and worker.is_alive():
            return
        values = {k: v.get().strip() for k, v in variables.items()}
        try:
            fps, seconds = float(values["fps"]), float(values["seconds"])
            if not 0 < fps <= 30 or not 0 < seconds <= 86400:
                raise ValueError("Укажите 0 < кадров/с ≤ 30 и 0 < секунд ≤ 86400")
            if not values["host"] or not values["token"] or not Path(values["folder"]).is_dir():
                raise ValueError("Укажите IP, API-токен и существующую папку")
        except ValueError as error:
            messagebox.showerror("Проверьте настройки", str(error))
            return
        CONFIG.write_text(json.dumps(values, ensure_ascii=False, indent=2), "utf-8")
        stop.clear()

        def run():
            try:
                play(values["host"], values["token"], Path(values["folder"]), stop,
                     messages.put, fps, seconds)
            except Exception as error:
                messages.put(str(error))
            finally:
                messages.put("Воспроизведение остановлено")
        worker = threading.Thread(target=run, daemon=True)
        worker.start()

    ttk.Button(frame, text="▶ Воспроизвести", command=start).grid(row=6, column=0, pady=15)
    ttk.Button(frame, text="■ Стоп", command=stop.set).grid(row=6, column=1, sticky="w", padx=10)

    def poll():
        while not messages.empty():
            status.set(messages.get_nowait())
        root.after(150, poll)

    def close():
        stop.set()
        root.destroy()
    root.protocol("WM_DELETE_WINDOW", close)
    poll()
    root.mainloop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host")
    parser.add_argument("--folder", type=Path)
    parser.add_argument("--fps", type=float, default=8)
    parser.add_argument("--seconds", type=float, default=5)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if args.folder is None:
        gui()
    else:
        if not args.host:
            parser.error('Укажите --host с IP-адресом кубика')
        try:
            play(args.host, os.environ.get("GEEKMAGIC_TOKEN", ""), args.folder,
                 threading.Event(), fps=args.fps, seconds=args.seconds, once=args.once)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
