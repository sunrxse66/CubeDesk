"""Durable playback intent, per-profile ownership and opt-in Windows startup."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


def atomic_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), 'utf8')
    temporary.replace(path)


class PlaybackMemory:
    def __init__(self, storage):
        self.path = Path(storage) / 'playback.json'
        self.enabled, self.paused, self.selection = True, False, None
        try:
            data = json.loads(self.path.read_text('utf8'))
            self.enabled = data.get('enabled', True) is True
            self.paused = data.get('paused', False) is True
            selection = data.get('selection')
            if isinstance(selection, dict) and selection.get('scope') in ('file', 'folder', 'widget', 'pet'):
                self.selection = selection
        except (OSError, ValueError, TypeError, AttributeError):
            pass

    def save(self):
        atomic_json(self.path, {'enabled': self.enabled, 'paused': self.paused, 'selection': self.selection})

    def remember(self, selection):
        self.selection, self.paused = selection, False
        self.save()

    def public(self):
        scene = self.selection or {}
        label = {'folder': 'Медиатека', 'pet': 'Питомец', 'widget': 'Виджет'}.get(scene.get('scope'), '')
        if scene.get('scope') == 'file':
            label = Path(scene.get('file_path', '')).name
        if scene.get('scope') == 'widget':
            from cubedesk.widgets import KINDS
            label = KINDS.get(scene.get('widget'), 'Виджет')
        return {'resume_on_start': self.enabled, 'paused': self.paused,
                'has_selection': bool(self.selection), 'last_scene': label}


class WindowsStartup:
    KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'
    NAME = 'CubeDesk'

    def __init__(self, supported=False, executable=None, registry=None):
        self.supported = supported
        self.executable = str(executable or sys.executable)
        self.registry = registry
        if supported and registry is None:
            import winreg
            self.registry = winreg

    def enabled(self):
        if not self.supported:
            return False
        r = self.registry
        try:
            with r.OpenKey(r.HKEY_CURRENT_USER, self.KEY) as key:
                value, kind = r.QueryValueEx(key, self.NAME)
            # Do not take over another program's registry value.
            return kind == r.REG_SZ and isinstance(value, str) and value.endswith(' --background')
        except OSError:
            return False

    def set(self, enabled):
        if not self.supported:
            raise ValueError('Автозапуск доступен в готовом CubeDesk.exe с обычной папкой настроек')
        command = subprocess.list2cmdline([self.executable, '--background'])
        if enabled and len(command) > 260:
            raise ValueError('Переместите CubeDesk.exe в папку с более коротким путём')
        r = self.registry
        with r.CreateKeyEx(r.HKEY_CURRENT_USER, self.KEY, 0, r.KEY_SET_VALUE) as key:
            if enabled:
                r.SetValueEx(key, self.NAME, 0, r.REG_SZ, command)
            else:
                try:
                    r.DeleteValue(key, self.NAME)
                except FileNotFoundError:
                    pass

    def public(self):
        return {'startup_supported': self.supported, 'startup_enabled': self.enabled()}


class ProfileLock:
    """An OS-released lock, not a stale PID file, owns a profile."""
    def __init__(self, storage):
        self.storage = Path(storage)
        self.handle = None

    def acquire(self):
        self.storage.mkdir(parents=True, exist_ok=True)
        handle = (self.storage / 'instance.lock').open('a+b')
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self.handle = handle
        return True

    def publish(self, port):
        atomic_json(self.storage / 'instance.json', {'pid': os.getpid(), 'port': port})

    def close(self):
        if self.handle:
            # Close releases the OS lock even after a process crash.
            if os.name == 'nt':
                import msvcrt
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            self.handle.close()
            self.handle = None
