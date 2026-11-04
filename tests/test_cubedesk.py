import io
import json
from pathlib import Path
import re
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from PIL import Image
from cubedesk.device import Device, prepare_stock_file, validate_host
from cubedesk.server import AppState, Server, existing_instance


class LocalAppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = AppState(Path(self.temp.name))
        self.app.config['token'] = 'secret-not-for-browser'
        self.server = Server(('127.0.0.1', 0), self.app)
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.app.stop.set()
        if self.app.worker:
            self.app.worker.join(2)
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def request(self, path, data=None, headers=None):
        request = urllib.request.Request(self.url + path, data=data, headers=headers or {})
        return urllib.request.urlopen(request, timeout=3)

    def post(self, path, data):
        return self.request(path, json.dumps(data).encode(), {'X-CubeDesk-Key': self.app.csrf})

    def test_state_polling_does_not_contact_device_or_expose_token(self):
        with patch('cubedesk.server.Device') as mock:
            with self.request('/api/state') as response:
                data = response.read()
            self.assertNotIn(b'secret-not-for-browser', data)
            self.assertTrue(json.loads(data)['settings']['has_token'])
            mock.assert_not_called()

    def test_background_preferences_require_csrf_and_pause_is_durable(self):
        for path in ('/api/background/settings', '/api/background/resume'):
            with self.subTest(path=path), self.assertRaises(urllib.error.HTTPError) as caught:
                self.request(path, b'{}')
            self.assertEqual(caught.exception.code, 403)
        with self.post('/api/background/settings', {'resume_on_start': False}) as response:
            self.assertFalse(json.load(response)['resume_on_start'])
        with self.assertRaises(urllib.error.HTTPError):
            self.post('/api/background/settings', {'resume_on_start': 'false'})
        with self.post('/api/stop', {}):
            pass
        reloaded = AppState(Path(self.temp.name))
        self.assertTrue(reloaded.memory.paused)
        self.assertFalse(reloaded.memory.enabled)

    def test_first_install_actions_require_csrf_and_a_checked_prepared_device(self):
        for path in ('probe', 'prepare', 'install', 'pair', 'reset'):
            with self.subTest(path=path):
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    self.request('/api/setup/' + path, b'{}')
                self.assertEqual(caught.exception.code, 403)
                caught.exception.read()
                caught.exception.close()
        for data in ({}, {'confirmed': True, 'check_id': 'not-checked'}):
            with self.assertRaises(urllib.error.HTTPError):
                self.post('/api/setup/install', data)
        self.assertFalse(self.app.job['running'])
        with self.request('/onboarding.js') as response:
            self.assertEqual(response.status, 200)
        with self.request('/onboarding.css') as response:
            self.assertEqual(response.status, 200)

    def test_updates_are_local_on_poll_and_require_csrf_for_install(self):
        with patch('cubedesk.updates.read_json') as network:
            with self.request('/api/updates') as response:
                body=response.read()
                self.assertNotIn(b'secret-not-for-browser',body)
            network.assert_not_called()
        for path in ('/api/updates/install-app','/api/updates/install-firmware','/api/updates/download'):
            with self.subTest(path=path),self.assertRaises(urllib.error.HTTPError) as caught:
                self.request(path,b'{}')
            self.assertEqual(caught.exception.code,403)

    def test_helper_failure_keeps_the_panel_and_stream_controller_running(self):
        with patch.object(self.app.updates,'install_app',side_effect=ValueError('helper failed')),patch.object(self.app,'_stop_stream') as stop:
            with self.assertRaises(urllib.error.HTTPError):self.post('/api/updates/install-app',{})
            stop.assert_not_called()
        with self.request('/api/health') as response:self.assertEqual(response.status,200)

    def test_shutdown_is_blocked_while_firmware_is_being_written(self):
        self.app.job.update(running=True,kind='firmware')
        with self.assertRaises(urllib.error.HTTPError):self.post('/api/shutdown',{})
        with self.request('/api/health') as response:self.assertEqual(response.status,200)
        self.app.job['running']=False

    def test_reopening_same_profile_reuses_only_a_verified_local_instance(self):
        self.assertTrue(existing_instance(self.server.server_port,self.app.storage))
        self.assertFalse(existing_instance(self.server.server_port,self.app.storage/'other-profile'))
        with self.request('/api/health') as response:
            self.assertNotIn(b'secret-not-for-browser',response.read())

    def test_cross_origin_and_rebinding_are_blocked(self):
        for headers in [{}, {'X-CubeDesk-Key': self.app.csrf, 'Origin': 'https://evil.example'},
                        {'X-CubeDesk-Key': self.app.csrf, 'Host': 'evil.example'}]:
            with self.subTest(headers=headers), self.assertRaises(urllib.error.HTTPError) as caught:
                self.request('/api/connect', b'{}', headers)
            self.assertEqual(caught.exception.code, 403)
        with self.request('/') as response:
            self.assertIn(self.app.csrf.encode(), response.read())
            self.assertIn("frame-ancestors 'none'", response.headers['Content-Security-Policy'])

    def test_import_keeps_paths_inside_managed_library(self):
        content = io.BytesIO()
        Image.new('RGB', (32, 16), 'red').save(content, 'PNG')
        headers = {'X-CubeDesk-Key': self.app.csrf}
        with self.request('/api/import?name=..%2F..%2Fexample.png', content.getvalue(), headers) as response:
            self.assertTrue(json.load(response)['ok'])
        files = list(self.app.imports.glob('*.png'))
        self.assertEqual(len(files), 1)
        with self.post('/api/settings', {'folder': str(self.app.imports)}):
            pass
        with self.request('/api/library') as response:
            items = json.load(response)['items']
        self.assertEqual(items[0]['width'], 32)
        with self.request('/api/thumbnail?id=' + items[0]['id']) as response:
            with Image.open(io.BytesIO(response.read())) as thumbnail:
                self.assertEqual(thumbnail.size, (240, 240))
        with self.assertRaises(urllib.error.HTTPError):
            self.request('/api/preview?id=../../settings.json')
        with self.assertRaises(urllib.error.HTTPError):
            self.request('/api/import?name=broken.png', b'not an image', headers)
        self.assertEqual(list(self.app.imports.glob('*.upload')), [])

    def test_invalid_settings_cannot_overwrite_working_config(self):
        initial = self.app.config.copy()
        for payload in [{'fps': float('nan')}, {'host': '8.8.8.8'}, {'folder': 'Z:/does-not-exist'}]:
            with self.assertRaises(urllib.error.HTTPError):
                self.post('/api/settings', payload)
            self.assertEqual(self.app.config, initial)

    def test_only_explicit_connect_starts_a_network_job(self):
        result = {'kind': 'stock', 'version': 'V7.0.22', 'model': 'HelloCubic-Lite'}
        with patch('cubedesk.server.Device') as mock:
            mock.return_value.inspect.return_value = result
            with self.post('/api/connect', {}):
                pass
            self.app.worker.join(2)
            self.assertEqual(self.app.public()['device']['version'], 'V7.0.22')
            self.assertFalse(self.app.job['running'])
            mock.return_value.inspect.assert_called_once()

    def test_selected_stream_switches_serially_and_folder_mode_is_explicit(self):
        for name in ('a.png', 'z.png'):
            Image.new('RGB', (32, 32), 'blue').save(self.app.imports / name)
        items = self.app.library()['items']
        self.app.device = {'kind': 'stream'}
        calls, active = [], []
        entered = threading.Event()
        def player(host, token, folder, stop, **kwargs):
            active.append(kwargs.get('selected_file'))
            self.assertEqual(len(active), 1, 'Two players own the cube at once')
            calls.append(kwargs.get('selected_file'))
            entered.set()
            stop.wait(3)
            active.pop()
        try:
            with patch('cubedesk.server.play', side_effect=player):
                # Pick the last item, not the alphabetically first file.
                with self.post('/api/show', {'id': items[-1]['id']}): pass
                self.assertTrue(entered.wait(1)); entered.clear()
                self.assertEqual(calls[-1], self.app.imports / 'z.png')
                self.assertEqual(self.app.job['file_id'], items[-1]['id'])
                self.assertEqual(self.app.job['scope'], 'file')
                with self.post('/api/show', {'id': items[0]['id']}): pass
                self.assertTrue(entered.wait(1)); entered.clear()
                self.assertEqual(calls[-1], self.app.imports / 'a.png')
                with self.post('/api/play', {'fps': 25, 'detail': 'balanced'}): pass
                self.assertTrue(entered.wait(1))
                self.assertIsNone(calls[-1])
                self.assertEqual(self.app.job['scope'], 'folder')
                self.assertEqual(self.app.config['fps'], 25)
                self.assertEqual(self.app.config['detail'], 'balanced')
                self.assertFalse(self.app.job['error'])
                self.app.stop.set(); self.app.worker.join(2)
        finally:
            self.app.stop.set()

    def test_bad_selection_or_options_does_not_interrupt_current_stream(self):
        Image.new('RGB', (32, 32), 'red').save(self.app.imports / 'a.png')
        ident = self.app.library()['items'][0]['id']
        self.app.device = {'kind': 'stream'}
        with patch('cubedesk.server.play', side_effect=lambda host, token, folder, stop, **kw: stop.wait(3)):
            with self.post('/api/show', {'id': ident}): pass
            worker = self.app.worker
            for payload in ({'id': '../../settings.json'}, {'id': ident, 'fps': -1}):
                with self.assertRaises(urllib.error.HTTPError):
                    self.post('/api/show', payload)
                self.assertIs(self.app.worker, worker)
                self.assertTrue(self.app.job['running'])
                self.assertFalse(self.app.stop.is_set())
            self.app.stop.set(); worker.join(2)

    def test_widgets_switch_from_files_and_validate_city_before_stopping(self):
        Image.new('RGB',(32,32),'red').save(self.app.imports/'a.png')
        ident=self.app.library()['items'][0]['id']
        self.app.device={'kind':'stream'}
        def stream(host,token,folder,stop,**kw):stop.wait(3)
        def widget(host,token,kind,stop,supplier,**kw):stop.wait(3)
        with patch('cubedesk.server.play',side_effect=stream),patch('cubedesk.server.play_widget',side_effect=widget):
            with self.post('/api/show',{'id':ident}):pass
            worker=self.app.worker
            with self.assertRaises(urllib.error.HTTPError):self.post('/api/widgets/show',{'kind':'weather'})
            self.assertIs(self.app.worker,worker)
            self.assertFalse(self.app.stop.is_set())
            with self.post('/api/widgets/show',{'kind':'clock'}):pass
            self.assertEqual(self.app.job['scope'],'widget')
            self.assertEqual(self.app.job['widget'],'clock')
            with self.post('/api/show',{'id':ident}):pass
            self.assertEqual(self.app.job['scope'],'file')
            self.assertFalse(self.app.job['error'])
            self.app.stop.set();self.app.worker.join(2)
        with self.request('/api/widgets/preview?kind=clock') as response:
            with Image.open(io.BytesIO(response.read())) as image:self.assertEqual(image.size,(240,240))
        with self.request('/api/widgets/state') as response:self.assertEqual(json.load(response)['phase'],'not_configured')

    def test_call_starts_pet_from_file_and_reuses_running_player(self):
        Image.new('RGB',(32,32),'red').save(self.app.imports/'a.png')
        ident=self.app.library()['items'][0]['id']
        self.app.device={'kind':'stream'}
        def stream(host,token,folder,stop,**kw):stop.wait(3)
        def pet_player(host,token,pet,stop,**kw):stop.wait(3)
        def widget_player(host,token,kind,stop,supplier,**kw):stop.wait(3)
        with patch('cubedesk.server.play',side_effect=stream),patch('cubedesk.server.play_pet',side_effect=pet_player) as player, patch('cubedesk.server.play_widget',side_effect=widget_player):
            with self.post('/api/show',{'id':ident}):pass
            old=self.app.worker
            with self.post('/api/pet/call',{}) as response:self.assertTrue(json.load(response)['ok'])
            self.assertFalse(old.is_alive())
            self.assertEqual(self.app.job['scope'],'pet')
            worker=self.app.worker
            self.assertTrue(self.app.pet.pending)
            with self.post('/api/pet/call',{}):pass
            self.assertIs(self.app.worker,worker)
            self.assertEqual(self.app.pet.calls,2)
            self.assertEqual(player.call_count,1)
            with self.request('/api/pet/preview') as response:
                with Image.open(io.BytesIO(response.read())) as image:self.assertEqual(image.size,(240,240))
            with self.request('/api/state') as response:self.assertTrue(json.load(response)['pet']['active'])

    def test_finding_actions_reuse_pet_player_and_pin_survives_restart(self):
        photos=Path(self.temp.name)/'photos';photos.mkdir()
        Image.new('RGB',(60,40),'blue').save(photos/'memory.png')
        self.app.device={'kind':'stream'}
        with self.post('/api/pet/findings/folder',{'folder':str(photos)}) as response:
            self.assertEqual(json.load(response)['count'],1)
        def player(host,token,pet,stop,**kw):stop.wait(3)
        with patch('cubedesk.server.play_pet',side_effect=player) as stream:
            with self.post('/api/pet/show',{}):pass
            worker=self.app.worker
            with self.post('/api/pet/findings/next',{}):pass
            self.assertIs(self.app.worker,worker);self.assertEqual(stream.call_count,1)
            self.assertEqual(self.app.pet.character,'momo')
            self.assertTrue(self.app.pet.finding_busy())
            with self.assertRaises(urllib.error.HTTPError):self.post('/api/pet/findings/next',{})
            ident=self.app.findings.current['id']
            with self.post('/api/pet/findings/pin',{'id':ident}):pass
            with self.request('/api/pet/findings/preview?kind=frame') as response:
                with Image.open(io.BytesIO(response.read())) as image:self.assertEqual(image.size,(240,240))
            restored=AppState(self.app.storage)
            self.assertEqual(restored.findings.public()['frame']['id'],ident)
            self.assertIsNotNone(restored.pet.framed_photo)
            with self.post('/api/pet/findings/unpin',{}):pass
            self.assertIsNone(self.app.pet.framed_photo)

    def test_finding_failure_does_not_stop_working_stream_and_mutations_require_csrf(self):
        self.app.device={'kind':'stream'}
        with patch('cubedesk.server.play_pet',side_effect=lambda host,token,pet,stop,**kw:stop.wait(3)):
            with self.post('/api/pet/show',{}):pass
            worker=self.app.worker
            with self.assertRaises(urllib.error.HTTPError):self.post('/api/pet/findings/next',{})
            self.assertIs(self.app.worker,worker);self.assertFalse(self.app.stop.is_set())
            for action in ('folder','browse','next','pin','unpin','open'):
                with self.subTest(action=action),self.assertRaises(urllib.error.HTTPError) as caught:
                    self.request('/api/pet/findings/'+action,b'{}')
                self.assertEqual(caught.exception.code,403)
        with patch('cubedesk.server.pick_photo_folder',return_value=None):
            with self.post('/api/pet/findings/browse',{}) as response:self.assertIsNone(json.load(response)['folder'])

    def test_pet_selection_persists_and_switches_running_pet_without_second_player(self):
        self.app.device={'kind':'stream'}
        def player(host,token,pet,stop,**kw):stop.wait(3)
        with patch('cubedesk.server.play_pet',side_effect=player) as stream:
            with self.post('/api/pet/show',{}):pass
            worker=self.app.worker
            with self.post('/api/pet/select',{'character':'momo'}) as response:
                self.assertEqual(json.load(response)['pet']['id'],'momo')
            self.assertIs(self.app.worker,worker)
            self.assertEqual(stream.call_count,1)
            loaded=AppState(self.app.storage)
            self.assertEqual(loaded.pet.character,'momo')
            with self.assertRaises(urllib.error.HTTPError):self.post('/api/pet/select',{'character':'invalid'})
            self.assertEqual(self.app.pet.character,'momo')
            self.app.stop.set();worker.join(2)
            with self.post('/api/widgets/show',{'kind':'clock'}):pass
            self.app.stop.set();self.app.worker.join(2)


class StockDeviceTests(unittest.TestCase):
    def test_stream_detection_and_actual_firmware_version(self):
        device = Device('127.0.0.1', 'secret')
        with patch.object(device, '_request', side_effect=[OSError('stock API absent'),
                b'<html>pcstream-v1.1-a0c2ddc</html>']), patch('cubedesk.device.CubeConnection') as connection:
            info = device.inspect()
        self.assertEqual(info['kind'], 'stream')
        self.assertEqual(info['version'], 'PCStream v1.1')
        connection.return_value.send.assert_called_once_with()
        connection.return_value.close.assert_called_once_with()

    def test_host_validation_and_image_preparation(self):
        self.assertEqual(validate_host(' 192.168.0.37 '), '192.168.0.37')
        for value in ['http://192.168.0.37', '8.8.8.8', '0.0.0.0', '224.0.0.1']:
            with self.assertRaises(ValueError):
                validate_host(value)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'photo.png'
            Image.new('RGBA', (100, 200), (255, 0, 0, 0)).save(path)
            data, extension, mime = prepare_stock_file(path)
            self.assertEqual((extension, mime), ('.jpg', 'image/jpeg'))
            with Image.open(io.BytesIO(data)) as prepared:
                self.assertEqual(prepared.size, (240, 240))
            gif = Path(directory) / 'wrong.gif'
            Image.new('RGB', (120, 120)).save(gif)
            with self.assertRaisesRegex(ValueError, '240'):
                prepare_stock_file(gif)

    def test_stock_upload_and_selection_protocol(self):
        calls, uploads = [], []
        class Firmware(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def answer(self, data):
                self.send_response(200)
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            def do_GET(self):
                calls.append(self.path)
                if self.path == '/v.json': data = b'{"m":"HelloCubic-Lite","v":"V7.0.22"}'
                elif self.path == '/space.json': data = b'{"total":3121152,"free":523788}'
                elif self.path.startswith('/filelist'): data = uploads[0].encode()
                else: data = b'OK'
                self.answer(data)
            def do_POST(self):
                calls.append(self.path)
                body = self.rfile.read(int(self.headers['Content-Length']))
                uploads.append(re.search(rb'filename="([^"]+)"', body).group(1).decode())
                self.answer(b'OK')
        server = ThreadingHTTPServer(('127.0.0.1', 0), Firmware)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            device = Device('127.0.0.1', port=server.server_port)
            self.assertEqual(device.inspect()['free'], 523788)
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'input.png'
                Image.new('RGB', (400, 200), 'lime').save(path)
                filename = device.show_stock(path)
            self.assertRegex(filename, r'^cube_[0-9a-f]{12}\.jpg$')
            self.assertIn('/doUpload?dir=/image', calls)
            self.assertIn('/set?theme=2', calls)
            self.assertTrue(calls[-1].startswith('/set?img=%2Fimage%2F'))
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
