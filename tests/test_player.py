import socket
import struct
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
import cube_player as player


class PlayerTests(unittest.TestCase):
    def test_rgb565_primary_colors(self):
        for name, color in [("red", b"\xf8\x00"), ("lime", b"\x07\xe0"),
                            ("blue", b"\x00\x1f"), ("white", b"\xff\xff")]:
            with self.subTest(name=name):
                self.assertEqual(player.rgb565(Image.new("RGB", (240, 240), name)), color * 57600)

    def test_letterbox_and_transparency(self):
        data = player.rgb565(Image.new("RGB", (240, 120), "red"))
        self.assertEqual(data[:480 * 60], b"\0" * 480 * 60)
        self.assertEqual(data[480 * 60:480 * 180], b"\xf8\0" * 240 * 120)
        self.assertEqual(player.rgb565(Image.new("RGBA", (240, 240), (255, 0, 0, 0))), b"\0" * player.FRAME_BYTES)

    def test_stream_with_fragmented_acknowledgements(self):
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen()
        errors = []

        def receive(sock, size):
            result = bytearray()
            while len(result) < size:
                chunk = sock.recv(size - len(result))
                if not chunk:
                    raise RuntimeError("early EOF")
                result.extend(chunk)
            return bytes(result)

        def emulate():
            try:
                sock, _ = server.accept()
                with sock:
                    self.assertEqual(receive(sock, 6), b"GMC1\x06\0")
                    self.assertEqual(receive(sock, 6), b"secret")
                    for byte in b"OKAY":
                        sock.sendall(bytes([byte]))
                    for magic, sequence, length in [(b"FRM1", 1, player.FRAME_BYTES), (b"PNG1", 2, 0)]:
                        self.assertEqual(struct.unpack("<4sII", receive(sock, 12)), (magic, sequence, length))
                        self.assertEqual(receive(sock, length), b"\x12\x34" * (length // 2))
                        for byte in b"ACK1" + struct.pack("<I", sequence):
                            sock.sendall(bytes([byte]))
            except BaseException as error:
                errors.append(error)
            finally:
                server.close()
        thread = threading.Thread(target=emulate, daemon=True)
        thread.start()
        connection = player.CubeConnection("127.0.0.1", "secret", server.getsockname()[1])
        try:
            with self.assertRaises(ValueError):
                connection.send(b"bad")
            connection.send(b"\x12\x34" * 57600)
            connection.send()
        finally:
            connection.close()
        thread.join(5)
        self.assertFalse(thread.is_alive())
        if errors:
            raise errors[0]

    def test_gif_frames_and_original_delays(self):
        sent, delays = [], []
        class MockConnection:
            def __init__(self, *args): pass
            def send(self, pixels=None): sent.append(pixels)
            def close(self): pass
        with tempfile.TemporaryDirectory() as directory:
            first = Image.new("RGB", (240, 240), "red")
            second = Image.new("RGB", (240, 240), "blue")
            first.save(Path(directory) / "animation.gif", save_all=True,
                       append_images=[second], duration=[200, 300], loop=0)
            with patch.object(player, "CubeConnection", MockConnection), patch.object(
                player, "hold", side_effect=lambda connection, delay, stop: delays.append(delay)
            ):
                player.play("unused", "secret", Path(directory), threading.Event(),
                            report=lambda message: None, fps=30, once=True)
        self.assertEqual(len(sent), 2)
        self.assertEqual(sent[0], b"\xf8\0" * 57600)
        self.assertEqual(sent[1], b"\0\x1f" * 57600)
        self.assertTrue(0 < delays[0] <= .2)
        self.assertTrue(0 < delays[1] <= .3)

    def test_invalid_tokens_and_empty_folder(self):
        for token in ["", "a" * 129]:
            with self.assertRaises(ValueError):
                player.CubeConnection("unused", token)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                player.play("unused", "secret", Path(directory), threading.Event())


if __name__ == "__main__":
    unittest.main()
