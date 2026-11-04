import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from PIL import Image
from cubedesk.background import PlaybackMemory, ProfileLock, WindowsStartup
from cubedesk.server import AppState, running_port


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        # GitHub's Windows runner uses an 8.3 TEMP alias (RUNNER~1).
        # Compare canonical paths, as the application does when saving settings.
        self.storage = Path(self.temp.name).resolve()
        self.apps = []
        self.app = self.new_app()
        self.app.config.update(host='192.168.0.37', token='private-test-key')
        self.app.device = {'kind': 'stream', 'host': '192.168.0.37', 'version': 'PCStream v1.8.1', 'model': 'HelloCubic-Lite'}
        self.app.save()
        self.first = self.app.imports / 'a-first.png'
        self.selected = self.app.imports / 'z-selected.png'
        for path in (self.first, self.selected):
            Image.new('RGB', (10, 10)).save(path)

    def new_app(self):
        app = AppState(self.storage)
        self.apps.append(app)
        return app

    def tearDown(self):
        for app in self.apps:
            app.stop.set()
            if app.worker: app.worker.join(3)
        self.temp.cleanup()

    def choose(self):
        self.app.library()
        ident = next(key for key, value in self.app.files.items() if value == self.selected)
        with patch('cubedesk.server.play'):
            self.app.show(ident)
            self.app.worker.join(2)
        return ident

    def test_last_exact_file_survives_exit_and_pause_survives_restart(self):
        self.choose()
        restarted = self.new_app()
        with patch('cubedesk.server.CubeConnection') as connection, patch('cubedesk.server.play') as player:
            self.assertTrue(restarted.resume_last(automatic=True))
            restarted.worker.join(2)
            self.assertEqual(player.call_args.kwargs['selected_file'], self.selected)
            connection.assert_called_once()
            restarted.pause()
        paused = self.new_app()
        with patch('cubedesk.server.CubeConnection') as connection:
            self.assertFalse(paused.resume_last(automatic=True))
            connection.assert_not_called()
        self.assertNotIn('private-test-key', json.dumps(paused.public()))

    def test_missing_selected_file_waits_without_playing_first_file(self):
        self.choose()
        self.selected.unlink()
        restarted = self.new_app()
        with patch('cubedesk.server.play') as player, patch('cubedesk.server.CubeConnection') as connection:
            restarted.resume_last(automatic=True)
            restarted.pause()
            restarted.worker.join(2)
            player.assert_not_called()
            connection.assert_not_called()
        self.assertTrue(self.first.is_file())

    def test_missing_disk_is_preserved_and_other_settings_can_be_saved(self):
        external = self.storage / 'external-disk'
        self.app.imports.rename(external)
        self.app.config['folder'] = str(external)
        self.app.save()
        self.first, self.selected = external / self.first.name, external / self.selected.name
        self.choose()
        original = self.app.config['folder']
        Path(original).rename(self.storage / 'temporarily-unplugged')
        restarted = self.new_app()
        self.assertEqual(restarted.config['folder'], original)
        self.assertFalse(Path(original).exists())
        restarted.settings({'fps': 20})
        with patch('cubedesk.server.CubeConnection', side_effect=OSError('offline')):
            restarted.resume_last(automatic=True)
            restarted.background_settings({'resume_on_start': False})
            restarted.worker.join(2)
            self.assertFalse(restarted.worker.is_alive())

    def test_manual_selection_cancels_late_resume_probe(self):
        self.choose()
        restarted = self.new_app()
        entered, release = threading.Event(), threading.Event()
        def probe(*args, **kwargs):
            entered.set()
            release.wait(2)
            return MagicMock()
        with patch('cubedesk.server.CubeConnection', side_effect=probe), patch('cubedesk.server.play') as player:
            restarted.resume_last(automatic=True)
            self.assertTrue(entered.wait(1))
            restarted.pause()
            release.set()
            restarted.worker.join(2)
            player.assert_not_called()
            restarted.library()
            ident = next(key for key, value in restarted.files.items() if value == self.first)
            restarted.show(ident)
            restarted.worker.join(2)
            self.assertEqual(player.call_args.kwargs['selected_file'], self.first)
            self.assertEqual(PlaybackMemory(self.storage).selection['file_path'], str(self.first))

    def test_widget_and_pet_restore_without_browser(self):
        for scope in ('widget', 'pet'):
            with self.subTest(scope=scope), patch('cubedesk.server.play_widget'), patch('cubedesk.server.play_pet'):
                if scope == 'widget': self.app.widget('clock')
                else: self.app.show_pet()
                self.app.worker.join(2)
                restarted = self.new_app()
                with patch('cubedesk.server.CubeConnection'):
                    restarted.resume_last(automatic=True)
                    restarted.worker.join(2)
                self.assertEqual(restarted.job['scope'], scope)
                self.assertFalse(restarted.job['error'])


class DesktopIntegrationTests(unittest.TestCase):
    def test_profile_lock_is_exclusive_and_released(self):
        with tempfile.TemporaryDirectory() as storage:
            first, second = ProfileLock(storage), ProfileLock(storage)
            self.assertTrue(first.acquire())
            try:
                self.assertFalse(second.acquire())
                script = 'from cubedesk.background import ProfileLock; import sys; sys.exit(1 if ProfileLock(sys.argv[1]).acquire() else 0)'
                result = subprocess.run([sys.executable, '-c', script, storage], timeout=5, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))
            finally:
                first.close()
            self.assertTrue(second.acquire())
            second.close()

    def test_registry_command_quotes_executable_and_is_opt_in(self):
        registry = MagicMock()
        registry.QueryValueEx.side_effect = FileNotFoundError()
        startup = WindowsStartup(True, r'C:\My Apps\CubeDesk.exe', registry)
        self.assertFalse(startup.enabled())
        registry.SetValueEx.assert_not_called()
        startup.set(True)
        self.assertEqual(registry.SetValueEx.call_args.args[-1], '"C:\\My Apps\\CubeDesk.exe" --background')
        startup.set(False)
        registry.DeleteValue.assert_called_once()
        with self.assertRaises(ValueError): WindowsStartup().set(True)

    def test_dynamic_port_is_reused_only_after_profile_health_check(self):
        with tempfile.TemporaryDirectory() as storage:
            Path(storage, 'instance.json').write_text('{"port": 18765}')
            with patch('cubedesk.server.existing_instance', side_effect=lambda p, s: p == 18765):
                self.assertEqual(running_port(8765, storage), 18765)
            with patch('cubedesk.server.existing_instance', return_value=False):
                self.assertIsNone(running_port(8765, storage))


if __name__ == '__main__':
    unittest.main()
