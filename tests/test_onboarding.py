import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cubedesk.onboarding import FirstInstall, FirmwareForm, LocalTarget
from cubedesk.server import AppState

FORM = "<form method='POST' action='' enctype='multipart/form-data'><input type='file' name='firmware'></form>"


class StockHandler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass

    def reply(self, body, status=200):
        self.send_response(status)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.server.gets.append(self.path)
        if self.path == '/v.json' and not self.server.pcstream:
            self.reply(json.dumps({'m': self.server.model, 'v': self.server.version}).encode())
        elif self.path == '/update': self.reply(self.server.form.encode())
        elif self.path == '/' and self.server.pcstream: self.reply(b'<h1>pcstream-v1.8.1-release</h1>')
        else: self.reply(b'', 404)

    def do_POST(self):
        body = self.rfile.read(int(self.headers['Content-Length']))
        self.server.posts.append((self.path, body))
        if self.server.disconnect:
            self.connection.close()
            return
        self.reply(b'Update Success! Rebooting...')


class FirstInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.storage = Path(self.temp.name).resolve()
        self.service = FirstInstall(self.storage)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), StockHandler)
        self.server.model, self.server.version, self.server.form = 'HelloCubic-Lite', 'V7.0.22', FORM
        self.server.pcstream, self.server.disconnect = False, False
        self.server.posts, self.server.gets = [], []
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.target_patch = patch('cubedesk.onboarding.LocalTarget', side_effect=lambda host: LocalTarget(host, self.server.server_port))
        self.target_patch.start()
        self.image = b'\xe9' + b'pcstream-v1.8.1-release' + b'\0' * 100
        self.path = self.storage / 'firmware.bin'
        self.path.write_bytes(self.image)
        self.spec = dict(model='HelloCubic-Lite', chip='ESP8266', display='ST7789', width=240, height=240,
            flash_bytes=4194304, universal=True, size=len(self.image), sha256=hashlib.sha256(self.image).hexdigest(),
            version='1.8.1', build_id='pcstream-v1.8.1-release')

    def tearDown(self):
        self.target_patch.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        self.temp.cleanup()

    def ready(self):
        self.service.probe('127.0.0.1')
        self.probe_check_id = self.service.public()['check_id']
        updates = SimpleNamespace(check=lambda: None, worker=None, specs={'firmware': self.spec},
            public=lambda: {'busy': False}, download=lambda kind: None, prepared=lambda kind: (self.path, self.spec))
        self.service.prepare(updates)
        return {'confirmed': True, 'check_id': self.service.public()['check_id']}

    def test_checked_factory_form_is_read_only_until_explicit_consent(self):
        confirmation = self.ready()
        self.assertEqual(self.service.public()['phase'], 'ready')
        self.assertEqual(self.server.posts, [])
        for bad in ({}, {'confirmed': 'true'}, {'confirmed': True, 'check_id': 'stale'},
                    {'confirmed': True, 'check_id': self.probe_check_id}):
            with self.assertRaises(ValueError): self.service.install(bad)
        self.assertEqual(self.server.posts, [])
        self.service.install(confirmation)
        self.assertEqual(self.service.public()['phase'], 'waiting_setup')
        self.assertEqual(len(self.server.posts), 1)
        endpoint, body = self.server.posts[0]
        self.assertEqual(endpoint, '/update')
        self.assertIn(b'name="firmware"', body)
        self.assertIn(self.image, body)
        self.assertNotIn(b'filesystem', body)
        with self.assertRaises(ValueError): self.service.install(confirmation)
        self.assertEqual(len(self.server.posts), 1)
        self.assertEqual(FirstInstall(self.storage).public()['phase'], 'uncertain')

    def test_unknown_versions_models_and_wrong_forms_never_write(self):
        for model, version, form in [('OtherCube', 'V7.0.22', FORM), ('HelloCubic-Lite', 'V7.1.24', FORM),
                ('HelloCubic-Lite', 'V7.0.22', FORM.replace('firmware', 'filesystem')),
                ('HelloCubic-Lite', 'V7.0.22', FORM.replace("action=''", "action='http://example.com/update'"))]:
            with self.subTest(model=model, version=version, form=form):
                self.server.model, self.server.version, self.server.form = model, version, form
                self.service.probe('127.0.0.1')
                self.assertEqual(self.service.public()['phase'], 'unsupported')
                with self.assertRaises(ValueError): self.service.install({'confirmed': True})
        self.assertEqual(self.server.posts, [])

    def test_tampered_download_and_changed_device_are_rejected_before_post(self):
        confirmation = self.ready()
        self.path.write_bytes(self.image + b'changed')
        with self.assertRaises(ValueError): self.service.install(confirmation)
        self.path.write_bytes(self.image)
        self.server.model = 'Different model'
        with self.assertRaises(ValueError): self.service.install(confirmation)
        self.assertEqual(self.server.posts, [])

    def test_lost_response_is_uncertain_and_never_retried_after_restart(self):
        confirmation = self.ready()
        self.server.disconnect = True
        self.service.install(confirmation)
        self.assertEqual(self.service.public()['phase'], 'uncertain')
        resumed = FirstInstall(self.storage)
        self.assertEqual(resumed.public()['phase'], 'uncertain')
        with self.assertRaises(ValueError): resumed.install(confirmation)
        self.assertEqual(len(self.server.posts), 1)

    def test_existing_pcstream_goes_directly_to_pairing(self):
        self.server.pcstream = True
        self.service.probe('127.0.0.1')
        self.assertEqual(self.service.public()['phase'], 'needs_pairing')
        self.assertNotIn('/update', self.server.gets)
        self.assertEqual(self.server.posts, [])

    def test_commented_out_or_external_firmware_forms_are_not_accepted(self):
        for markup in ('<!--'+FORM+'-->', FORM.replace("action=''", "action='//example.com'"),
                       "<input type='file' name='firmware'>"):
            parser = FirmwareForm()
            parser.feed(markup)
            self.assertFalse(parser.valid)

    def test_wrong_image_hardware_is_not_accepted(self):
        for changes in ({'model': 'OtherCube'}, {'flash_bytes': 8388608}, {'display': 'ST7735'}, {'universal': False}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.service.validate_image(self.path, self.spec | changes)

    def test_only_verified_pairing_saves_credentials_and_finishes(self):
        app = AppState(self.storage)
        app.config.update(host='192.168.0.37', token='previous-secret')
        app.save()
        info = dict(kind='stream', model='HelloCubic-Lite', host='127.0.0.1', version='PCStream v1.8.1')
        with patch('cubedesk.server.LocalTarget') as target, patch('cubedesk.server.Device') as device:
            target.return_value.probe.return_value = {'kind': 'stream'}
            device.return_value.inspect.side_effect = ValueError('Ключ не подошёл')
            app.setup_pair({'host': '127.0.0.1', 'token': 'new-secret'})
            app.worker.join(2)
            self.assertEqual(app.config['token'], 'previous-secret')
            self.assertNotIn('new-secret', json.dumps(app.public()))
            device.return_value.inspect.side_effect = None
            device.return_value.inspect.return_value = info
            app.setup_pair({'host': '127.0.0.1', 'token': 'new-secret'})
            app.worker.join(2)
            self.assertEqual(app.onboarding.public()['phase'], 'complete')
            self.assertEqual(app.config['token'], 'new-secret')
            self.assertNotIn('new-secret', json.dumps(app.public()))
            self.assertNotIn('new-secret', app.onboarding.path.read_text('utf8'))
            self.assertEqual(AppState(self.storage).config['token'], 'new-secret')
            app.onboarding.reset_completed()
            self.assertEqual(app.onboarding.public()['phase'], 'idle')
            self.assertEqual(app.config['token'], 'new-secret')
            self.assertIsNone(app.onboarding.public()['firmware'])


if __name__ == '__main__': unittest.main()
