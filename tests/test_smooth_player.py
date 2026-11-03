import io
from pathlib import Path
import socket
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch

from PIL import Image
from cube_player import CubeConnection
from smooth_player import FrameSource, encode_jpeg, play


class SmoothTests(unittest.TestCase):
    def test_encoded_frame_respects_memory_and_alpha(self):
        data, quality = encode_jpeg(Image.new('RGBA', (80, 120), (255, 0, 0, 0)), 4096)
        self.assertLessEqual(len(data), 4096)
        self.assertGreaterEqual(quality, 15)
        with Image.open(io.BytesIO(data)) as image:
            self.assertEqual(image.size, (240, 240))
            self.assertEqual(image.mode, 'RGB')
            self.assertEqual(image.getpixel((120, 120)), (0, 0, 0))
        with self.assertRaises(ValueError):
            encode_jpeg(Image.new('RGB', (240, 240)), 20)
        data, _ = encode_jpeg(Image.new('RGB', (240, 240), 'red'), 8192, edge=120)
        with Image.open(io.BytesIO(data)) as image:
            self.assertEqual(image.size, (120, 120))

    def test_source_preserves_gif_presentation_times(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'clip.gif'
            frames = [Image.new('RGB', (240, 240), color) for color in ['red', 'blue', 'green']]
            frames[0].save(path, save_all=True, append_images=frames[1:], duration=[50,100,200])
            source = FrameSource(path, 12288, 5, threading.Event())
            try:
                output = [source.next() for _ in range(3)]
                self.assertIsNone(source.next())
            finally:
                source.close()
            self.assertAlmostEqual(output[0].pts, 0)
            self.assertAlmostEqual(output[1].pts, .05)
            self.assertAlmostEqual(output[2].pts, .15)
            self.assertAlmostEqual(output[-1].duration, .2)
            self.assertTrue(all(len(frame.data) <= 12288 for frame in output))
            self.assertFalse(source.thread.is_alive())

    def test_slow_link_drops_late_frames_instead_of_slow_motion(self):
        class Clock:
            now = 0.0
            def monotonic(self): return self.now
            def sleep(self, seconds): self.now += seconds
        clock = Clock()
        sent = []
        class Stop:
            def is_set(self): return False
            def wait(self, duration): clock.now += duration; return False
        class Link:
            max_jpeg, flags = 12288, 1
            def __init__(self, *args, **kwargs): pass
            def send_jpeg(self, data):
                sent.append(data);clock.now += .075
                return {'transport_ms':75,'draw_ms':20,'receive_ms':55,'free_heap':12000}
            def send(self): return {}
            def close(self): pass
        with tempfile.TemporaryDirectory() as directory:
            frames = [Image.new('RGB',(240,240),(i*20,0,0)) for i in range(10)]
            frames[0].save(Path(directory)/'clip.gif',save_all=True,append_images=frames[1:],duration=50)
            with patch('smooth_player.CubeConnection',Link), patch('smooth_player.time.monotonic',clock.monotonic), patch('smooth_player.time.sleep',clock.sleep):
                play('unused','secret',Path(directory),Stop(),report=lambda x:None,once=True,fps=30)
        self.assertGreater(len(sent), 4)
        self.assertLess(len(sent), 10)
        self.assertLess(clock.now, .65)

    def test_smooth_resolution_survives_multiple_files_and_photos_stay_sharp(self):
        sent = []
        class Link:
            max_jpeg, flags = 8192, 5
            def __init__(self, *args, **kwargs): pass
            def send_jpeg(self, data):
                with Image.open(io.BytesIO(data)) as image:
                    sent.append(image.size)
                return {'transport_ms': 1}
            def send(self): return {}
            def close(self): pass
        with tempfile.TemporaryDirectory() as directory:
            for name in ['a.gif', 'b.gif']:
                frames = [Image.new('RGB', (240,240), color) for color in ['red','blue']]
                frames[0].save(Path(directory)/name, save_all=True, append_images=frames[1:], duration=10)
            Image.new('RGB', (240,240), 'green').save(Path(directory)/'c.png')
            with patch('smooth_player.CubeConnection', Link):
                play('unused','secret',Path(directory),threading.Event(),report=lambda x:None,
                     once=True,fps=30,seconds=.01,detail='smooth')
        self.assertEqual(sent[-1], (240,240))
        self.assertGreaterEqual(len(sent[:-1]), 2)
        self.assertTrue(all(size == (80,80) for size in sent[:-1]))

    def test_selected_gif_repeats_without_playing_other_files(self):
        stop = threading.Event()
        reports, colors = [], []
        class Link:
            max_jpeg, flags = 8192, 5
            def __init__(self, *a, **kw): pass
            def send_jpeg(self, data):
                with Image.open(io.BytesIO(data)) as image:
                    colors.append(image.getpixel((40,40)))
                if len(colors) == 5: stop.set()
                return {'transport_ms': 1}
            def send(self): return {}
            def close(self): pass
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            Image.new('RGB',(240,240),'red').save(folder/'a.png')
            frames = [Image.new('RGB',(240,240),c) for c in ['blue','green']]
            selected = folder/'z.gif'
            frames[0].save(selected,save_all=True,append_images=frames[1:],duration=50)
            with patch('smooth_player.CubeConnection', Link):
                play('unused','secret',folder,stop,report=reports.append,selected_file=selected)
        self.assertEqual(reports, ['z.gif'] * 3)
        self.assertEqual(len(colors), 5)
        self.assertTrue(all(pixel[0] < 10 for pixel in colors), 'Unselected red photo was played')

    def test_selected_photo_is_sent_once_then_kept_visible(self):
        stop = threading.Event()
        sends, holds = [], []
        class Link:
            max_jpeg, flags = 8192, 5
            def __init__(self, *a, **kw): pass
            def send_jpeg(self, data): sends.append(data); return {'transport_ms': 1}
            def close(self): pass
        def holding(link, seconds, event):
            holds.append(seconds)
            if seconds == 3: event.set()
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            selected = folder/'photo.png'
            Image.new('RGB',(240,240),'red').save(selected)
            with patch('smooth_player.CubeConnection',Link), patch('smooth_player.hold',holding):
                play('unused','secret',folder,stop,report=lambda _:None,seconds=.01,selected_file=selected)
        self.assertEqual(len(sends),1)
        self.assertEqual(holds[-1],3)

    def test_modern_handshake_jpeg_and_profiling_ack(self):
        server=socket.socket();server.bind(('127.0.0.1',0));server.listen()
        errors=[]
        def read(sock,length):
            data=b''
            while len(data)<length:
                part=sock.recv(length-len(data))
                if not part:raise RuntimeError('EOF')
                data+=part
            return data
        def emulate():
            try:
                conn,_=server.accept()
                with conn:
                    self.assertEqual(read(conn,12),b'GMC2\x06\x00secret')
                    conn.sendall(b'OKJ2'+struct.pack('<II',12288,3))
                    self.assertEqual(struct.unpack('<4sII',read(conn,12)),(b'JPG1',1,8))
                    self.assertEqual(read(conn,8),b'jpegdata')
                    ack=struct.pack('<4sIIIII',b'ACK2',1,2000,3000,8,12345)
                    for byte in ack:conn.sendall(bytes([byte]))
            except BaseException as e:errors.append(e)
            finally:server.close()
        thread=threading.Thread(target=emulate,daemon=True);thread.start()
        link=CubeConnection('127.0.0.1','secret',server.getsockname()[1],modern=True)
        try:
            self.assertTrue(link.modern)
            self.assertEqual(link.max_jpeg,12288)
            with self.assertRaises(ValueError):link.send_jpeg(b'x'*12289)
            stats=link.send_jpeg(b'jpegdata')
            self.assertEqual(stats['receive_ms'],2)
            self.assertEqual(stats['draw_ms'],3)
            self.assertEqual(stats['free_heap'],12345)
        finally:link.close()
        thread.join(3)
        self.assertFalse(thread.is_alive())
        if errors:raise errors[0]


if __name__=='__main__':unittest.main()
