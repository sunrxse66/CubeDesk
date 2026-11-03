"""Prefetched compressed frames scheduled to the original animation clock."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import io
import math
from pathlib import Path
import queue
import statistics
import threading
import time

from PIL import Image, ImageOps
from cube_player import CubeConnection, SUPPORTED, hold, rgb565


def wait_frame(stop, seconds):
    """Use Python 3.11 high-resolution sleep near a frame deadline on Windows.

    Event.wait can round a 5-ms remainder to a whole scheduler tick, which
    repeatedly makes a 20-FPS stream late. Long waits remain interruptible.
    """
    deadline = time.monotonic() + max(0, seconds)
    while not stop.is_set():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        if remaining > .025:
            if stop.wait(remaining - .02):
                return True
        else:
            time.sleep(min(remaining, .005))
    return True


def canvas(image):
    rgba = ImageOps.exif_transpose(image).convert('RGBA')
    background = Image.new('RGBA', rgba.size, 'black')
    background.alpha_composite(rgba)
    return ImageOps.pad(background.convert('RGB'), (240, 240), color='black')


def encode_jpeg(image, maximum, quality=75, edge=240):
    image = canvas(image)
    if edge not in (80, 120, 240):
        raise ValueError('Unsupported frame dimensions')
    if edge < 240:
        image = image.resize((edge, edge), Image.Resampling.LANCZOS)
    for candidate in range(max(20, min(90, int(quality))), 14, -5):
        output = io.BytesIO()
        image.save(output, 'JPEG', quality=candidate, subsampling=2,
                   optimize=True, progressive=False)
        data = output.getvalue()
        if len(data) <= maximum:
            return data, candidate
    raise ValueError('Кадр не помещается в буфер приёмника даже после сжатия')


@dataclass
class Frame:
    pts: float
    duration: float
    data: bytes
    quality: int
    edge: int = 240


class FrameSource:
    """One decoder thread with bounded lookahead, regardless of GIF file size."""
    def __init__(self, path, jpeg_limit, seconds, stop, resolution=240, quality=75):
        self.path = Path(path)
        self.jpeg_limit = jpeg_limit
        self.seconds = seconds
        self.stop = stop
        self.closed = threading.Event()
        self.frames = queue.Queue(maxsize=8)
        self.quality = quality
        self.resolution = resolution
        self.animated = False
        self.thread = threading.Thread(target=self._produce, daemon=True)
        self.thread.start()

    def _put(self, item):
        while not self.stop.is_set() and not self.closed.is_set():
            try:
                self.frames.put(item, timeout=.1)
                return
            except queue.Full:
                pass

    def _produce(self):
        try:
            with Image.open(self.path) as image:
                count = getattr(image, 'n_frames', 1)
                self.animated = count > 1
                pts = 0.0
                for index in range(count):
                    if self.stop.is_set() or self.closed.is_set():
                        break
                    image.seek(index)
                    duration = max(.01, float(image.info.get('duration', 100)) / 1000) if count > 1 else self.seconds
                    if self.jpeg_limit:
                        data, quality = encode_jpeg(image, self.jpeg_limit, self.quality,
                                                   self.resolution if count > 1 else 240)
                    else:
                        data, quality = rgb565(image), 100
                    self._put(Frame(pts, duration, data, quality,
                                    self.resolution if self.jpeg_limit and count > 1 else 240))
                    pts += duration
        except Exception as error:
            self._put(error)
        finally:
            self._put(None)

    def next(self):
        while not self.stop.is_set() and not self.closed.is_set():
            try:
                item = self.frames.get(timeout=.1)
                if isinstance(item, Exception):
                    raise item
                return item
            except queue.Empty:
                pass
        return None

    def close(self):
        self.closed.set()
        self.thread.join(2)


def play(host, token, folder: Path, stop, report=print, fps=30, seconds=5,
         once=False, on_stats=None, detail='smooth', selected_file=None):
    folder = Path(folder)
    if not folder.is_dir():
        raise ValueError('Выберите существующую папку')
    if selected_file is not None:
        selected_file = Path(selected_file).resolve()
        if (not selected_file.is_file() or selected_file.suffix.lower() not in SUPPORTED or
                selected_file.parent != folder.resolve()):
            raise ValueError('Выбранный файл не найден в текущей медиатеке')
    if not all(math.isfinite(v) and v > 0 for v in (fps, seconds)) or fps > 30:
        raise ValueError('Укажите частоту от 1 до 30 кадров/с и положительное время показа')
    connection = None
    qualities = {}
    try:
        while not stop.is_set():
            paths = [selected_file] if selected_file else sorted(
                p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED)
            if not paths:
                raise ValueError('В папке нет поддерживаемых изображений')
            for path in paths:
                if stop.is_set():
                    break
                while connection is None and not stop.is_set():
                    try:
                        connection = CubeConnection(host, token, modern=True)
                    except OSError:
                        if once:
                            raise
                        report('Связь прервалась. Повторное подключение через 2 секунды…')
                        stop.wait(2)
                if connection is None:
                    break
                report(path.name)
                limit = connection.max_jpeg if connection.flags & 1 else 0
                resolution = {'smooth': 80, 'balanced': 120, 'sharp': 240}[detail]
                if resolution == 80 and not connection.flags & 4:
                    resolution = 120  # Older JPEG firmware supports only 120/240.
                source = FrameSource(path, limit, seconds, stop, resolution,
                                     qualities.get(path, 75))
                shown = dropped = 0
                samples = deque(maxlen=40)
                transfers = deque(maxlen=20)
                origin = None
                last_start = -math.inf
                last_stats = last_adapt = 0.0
                end_pts = 0.0
                try:
                    while not stop.is_set():
                        frame = source.next()
                        if frame is None:
                            break
                        now = time.monotonic()
                        if origin is None:
                            origin = now
                            last_stats = now
                        end_pts = frame.pts + frame.duration
                        allowed = max(now, last_start + 1 / fps)
                        # Late source frames are skipped; the GIF never turns into slow motion.
                        if shown and origin + end_pts <= allowed:
                            dropped += 1
                            continue
                        if wait_frame(stop, max(0, origin + frame.pts - now, last_start + 1 / fps - now)):
                            break
                        last_start = time.monotonic()
                        transport = connection.send_jpeg(frame.data) if limit else connection.send(frame.data)
                        now = time.monotonic()
                        shown += 1
                        samples.append(now)
                        transfers.append(transport['transport_ms'])
                        if now - last_stats >= .5:
                            last_stats = now
                            measured = (len(samples) - 1) / (samples[-1] - samples[0]) if len(samples) > 1 else 0
                            if on_stats:
                                on_stats({'fps': round(measured, 1), 'frames': shown, 'dropped': dropped,
                                          'codec': 'JPEG' if limit else 'RGB565', 'quality': frame.quality,
                                          'resolution': frame.edge,
                                          'frame_ms': round(statistics.mean(transfers), 1),
                                          'receive_ms': round(transport.get('receive_ms', 0), 1),
                                          'draw_ms': round(transport.get('draw_ms', 0), 1),
                                          'free_heap': transport.get('free_heap', 0)})
                        if limit and now - last_adapt >= 2 and len(transfers) >= 5:
                            last_adapt = now
                            target_ms = max(frame.duration, 1 / fps) * 1000
                            median = statistics.median(transfers)
                            if median > target_ms * 1.05:
                                source.quality = max(40, source.quality - 5)
                            elif median < target_ms * .65:
                                source.quality = min(75, source.quality + 2)
                    if origin is not None and not stop.is_set():
                        hold(connection, max(0, origin + end_pts - time.monotonic()), stop)
                    if selected_file is not None and not source.animated and not once:
                        while not stop.is_set():
                            hold(connection, 3, stop)
                except (OSError, ConnectionError) as error:
                    connection.close()
                    connection = None
                    if once:
                        raise
                    report('Связь прервалась. Повторное подключение через 2 секунды…')
                    stop.wait(2)
                finally:
                    qualities[path] = source.quality
                    source.close()
            if once:
                break
    finally:
        if connection:
            connection.close()
