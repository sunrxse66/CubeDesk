import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cubedesk import REPOSITORY, VERSION
from cubedesk.updates import UpdateService, release_manifest, verify_file, version_tuple, flash_firmware, SafeRedirect


def fixture(version='9.0.0'):
    app = b'MZ' + b'test executable'
    firmware = b'\xe9' + b'pcstream-v1.7-onboarding'
    manifest = {'schema': 1, 'repository': REPOSITORY, 'version': version}
    manifest['app'] = dict(version=version, asset='CubeDesk.exe', size=len(app), sha256=hashlib.sha256(app).hexdigest())
    manifest['firmware'] = dict(version='1.7.0', asset='HelloCubic-PCStream-universal.bin', size=len(firmware),
        sha256=hashlib.sha256(firmware).hexdigest(), model='HelloCubic-Lite', chip='ESP8266', display='ST7789',
        width=240, height=240, flash_bytes=4194304, universal=True, build_id='pcstream-v1.7-onboarding')
    base = f'https://github.com/{REPOSITORY}/releases/'
    release = dict(tag_name='v'+version, html_url=base+'tag/v'+version, draft=False, prerelease=False,
                   body='Release notes', assets=[])
    for kind in ('app', 'firmware'):
        spec = manifest[kind]
        release['assets'].append(dict(name=spec['asset'], size=spec['size'], state='uploaded',
            digest='sha256:'+spec['sha256'], browser_download_url=base+'download/v'+version+'/'+spec['asset']))
    return release, manifest, app, firmware


class UpdateTests(unittest.TestCase):
    def test_last_install_result_is_visible_without_private_exception_details(self):
        with tempfile.TemporaryDirectory() as directory:
            service=UpdateService(Path(directory));service.directory.mkdir()
            result=service.directory/'update-result.json'
            result.write_text(json.dumps({'status':'rolled_back','version':'1.6.1','message':'private local exception path'}),'utf-8-sig')
            state=service.public()
            self.assertEqual(state['last_install'],{'status':'rolled_back','version':'1.6.1'})
            self.assertNotIn('private local exception',json.dumps(state))
            result.write_text('broken','utf8')
            self.assertIsNone(service.public()['last_install'])

    def test_version_comparison_is_numeric_and_rejects_unstable_tags(self):
        self.assertGreater(version_tuple('1.10.0'), version_tuple('1.9.9'))
        self.assertEqual(version_tuple('PCStream v1.7'), (1,7,0))
        for bad in ('latest', '1.7-beta', 'v1;echo', None):
            with self.assertRaises(ValueError): version_tuple(bad)

    def test_release_binds_tag_repository_hash_and_hardware(self):
        r,m,_,_=fixture()
        self.assertEqual(release_manifest(r,m)['app']['version'], '9.0.0')
        for mutation in ('prerelease','repo','host','digest','size','hardware','duplicate','tag'):
            with self.subTest(mutation=mutation):
                r,m,_,_=fixture()
                if mutation=='prerelease':r['prerelease']=True
                if mutation=='repo':m['repository']='attacker/project'
                if mutation=='host':r['assets'][0]['browser_download_url']='https://evil.example/CubeDesk.exe'
                if mutation=='digest':r['assets'][0]['digest']='sha256:'+'0'*64
                if mutation=='size':m['app']['size']=200*1024*1024
                if mutation=='hardware':m['firmware']['chip']='ESP32'
                if mutation=='duplicate':r['assets'].append(r['assets'][0].copy())
                if mutation=='tag':r['tag_name']='v1.0.0'
                with self.assertRaises(ValueError):release_manifest(r,m)

    def test_check_and_polling_keep_tokens_and_device_out_of_requests(self):
        r,m,_,_=fixture()
        with tempfile.TemporaryDirectory() as directory, patch('cubedesk.updates.read_json', side_effect=[r,m]) as network:
            service=UpdateService(Path(directory))
            service.check();service.worker.join(2)
            self.assertTrue(service.public()['available'])
            self.assertEqual(service.public()['notes'],'Release notes')
            for _ in range(10):service.public()
            service.check()
            self.assertEqual(network.call_count,2)

    def test_bad_download_cannot_replace_an_existing_verified_file(self):
        r,m,app,_=fixture()
        with tempfile.TemporaryDirectory() as directory:
            service=UpdateService(Path(directory));service.specs=release_manifest(r,m)
            folder=service.directory/'9.0.0';folder.mkdir(parents=True)
            target=folder/'CubeDesk.exe';target.write_bytes(app)
            response=io.BytesIO(b'xx'+app[2:]);response.headers={}
            with patch('cubedesk.updates.open_public',return_value=response):
                service.download('app');service.worker.join(2)
            self.assertEqual(service.public()['status'],'error')
            self.assertEqual(target.read_bytes(),app)
            self.assertFalse(target.with_suffix('.part').exists())
            self.assertNotIn('app',service.staged)

    def test_truncated_download_is_rejected_and_complete_download_is_staged(self):
        r,m,app,_=fixture()
        with tempfile.TemporaryDirectory() as directory:
            service=UpdateService(Path(directory));service.specs=release_manifest(r,m)
            for content,expected in [(app[:3],'error'),(app,'ready')]:
                response=io.BytesIO(content);response.headers={}
                with patch('cubedesk.updates.open_public',return_value=response):
                    service.download('app');service.worker.join(2)
                self.assertEqual(service.public()['status'],expected)
            self.assertEqual(service.prepared('app')[0].read_bytes(),app)
            service.staged['app'].write_bytes(b'MZbad')
            with self.assertRaises(ValueError):service.prepared('app')

    def test_redirects_cannot_send_update_download_to_http_or_arbitrary_hosts(self):
        for url in ('http://github.com/file','https://evil.example/file','https://user:password@github.com/file'):
            with self.assertRaises(ValueError):SafeRedirect().redirect_request(None,None,302,'',{},url)

    def test_firmware_cannot_downgrade_or_touch_stock_devices(self):
        r,m,_,fw=fixture();spec=release_manifest(r,m)['firmware']
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'firmware.bin';path.write_bytes(fw)
            for info in [dict(kind='stock',model='HelloCubic-Lite',version='V7.0.22'),
                         dict(kind='stream',model='Other',version='PCStream v1.6'),
                         dict(kind='stream',model='HelloCubic-Lite',version='PCStream v1.7')]:
                with patch('cubedesk.device.Device') as device,patch('cubedesk.updates.http.client.HTTPConnection') as connection:
                    device.return_value.inspect.return_value=info
                    with self.assertRaises(ValueError):flash_firmware('192.168.1.10','local-token',path,spec)
                    connection.assert_not_called()

    def test_firmware_uses_auth_and_never_uploads_filesystem(self):
        r,m,_,fw=fixture();spec=release_manifest(r,m)['firmware']
        info=dict(kind='stream',model='HelloCubic-Lite',version='PCStream v1.6')
        after=dict(connected=True,saved_network=True,loaded_saved_network=True,stored_ssid_matches=True,
                   stored_password_matches=True,stored_token_matches=True)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'firmware.bin';path.write_bytes(fw)
            with patch('cubedesk.device.Device') as device,patch('cubedesk.updates.http.client.HTTPConnection') as connection,patch('cubedesk.updates.time.sleep'):
                device.return_value.inspect.return_value=info
                device.return_value._request.side_effect=[json.dumps(after).encode(),b'pcstream-v1.7-onboarding',json.dumps(after).encode()]
                connection.return_value.getresponse.return_value.status=200
                connection.return_value.getresponse.return_value.read.return_value=b'Update Success!'
                flash_firmware('192.168.1.10','local-token',path,spec)
                connection.return_value.putrequest.assert_called_once_with('POST','/legacyupdate')
                self.assertEqual(device.return_value._request.call_args_list[0].kwargs['headers']['Authorization'],'Bearer local-token')
                self.assertIn('Basic ',str(connection.return_value.putheader.call_args_list))


if __name__=='__main__':unittest.main()
