"""Local photographs explicitly entrusted to Momo. Originals stay in their folder."""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
from pathlib import Path
import random
import threading

from PIL import Image, ImageOps

PHOTO_TYPES = {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}
MAX_PHOTOS = 5000


def pick_photo_folder():
    """Run the Windows folder picker on this request's STA thread."""
    if os.name != 'nt':
        raise ValueError('Вставьте полный путь к папке в поле ниже.')
    from ctypes import wintypes as w
    class BrowseInfo(ctypes.Structure):
        _fields_ = [('owner', w.HWND), ('root', ctypes.c_void_p),
                    ('display', w.LPWSTR), ('title', w.LPCWSTR), ('flags', w.UINT),
                    ('callback', ctypes.c_void_p), ('data', w.LPARAM), ('icon', ctypes.c_int)]
    shell=ctypes.WinDLL('shell32',use_last_error=True)
    ole=ctypes.WinDLL('ole32',use_last_error=True)
    user=ctypes.WinDLL('user32',use_last_error=True)
    user.ShowWindow.argtypes=(w.HWND,ctypes.c_int)
    user.SetForegroundWindow.argtypes=(w.HWND,)
    @ctypes.WINFUNCTYPE(ctypes.c_int,w.HWND,w.UINT,w.LPARAM,w.LPARAM)
    def initialized_dialog(window,message,parameter,data):
        if message==1:
            # Updater-launched apps can inherit SW_HIDE. Consume that initial
            # show override, then explicitly show the user-requested picker.
            user.ShowWindow(window,5)
            user.ShowWindow(window,5)
            user.SetForegroundWindow(window)
        return 0
    ole.CoInitializeEx.argtypes=(ctypes.c_void_p,w.DWORD)
    ole.CoInitializeEx.restype=ctypes.c_long
    ole.CoTaskMemFree.argtypes=(ctypes.c_void_p,)
    shell.SHBrowseForFolderW.argtypes=(ctypes.POINTER(BrowseInfo),)
    shell.SHBrowseForFolderW.restype=ctypes.c_void_p
    shell.SHGetPathFromIDListEx.argtypes=(ctypes.c_void_p,w.LPWSTR,w.DWORD,w.DWORD)
    shell.SHGetPathFromIDListEx.restype=w.BOOL
    initialized=ole.CoInitializeEx(None,2)
    if initialized<0:raise ValueError('Не удалось открыть выбор папки. Вставьте путь вручную.')
    pidl=None
    try:
        display=ctypes.create_unicode_buffer(260)
        info=BrowseInfo(None,None,ctypes.cast(display,w.LPWSTR),
                        'Выберите папку с фотографиями для Момо',0x51,ctypes.cast(initialized_dialog,ctypes.c_void_p),0,0)
        pidl=shell.SHBrowseForFolderW(ctypes.byref(info))
        if not pidl:return None
        path=ctypes.create_unicode_buffer(32768)
        if not shell.SHGetPathFromIDListEx(pidl,path,len(path),0):
            raise ValueError('Выберите обычную папку на диске.')
        return path.value
    finally:
        if pidl:ole.CoTaskMemFree(pidl)
        ole.CoUninitialize()


class PhotoFindings:
    def __init__(self, storage):
        self.lock = threading.RLock()
        self.path = Path(storage) / 'momo-findings.json'
        self.root = None
        self.files = {}
        self.bag = []
        self.current = None
        self.frame = None
        self.revision = 0
        self.limited = False
        try:
            saved = json.loads(self.path.read_text('utf-8'))
            self.root, self.files, self.limited = self._scan(saved['folder'])
            for key in ('current', 'frame'):
                ident = saved.get(key)
                if ident in self.files:
                    try: setattr(self, key, self._photo(ident))
                    except (OSError, ValueError): pass
        except (OSError, ValueError, KeyError, TypeError):
            pass

    @staticmethod
    def _root(folder):
        if not isinstance(folder, str) or not folder.strip():
            raise ValueError('Выберите папку с фотографиями.')
        root = Path(folder).expanduser().resolve()
        if not root.is_dir():
            raise ValueError('Папка недоступна. Проверьте путь или подключите диск.')
        return root

    def _scan(self, folder):
        root = self._root(folder)
        files = {}
        limited = False
        visited = 0
        for directory, dirs, names in os.walk(root, followlinks=False):
            visited += 1
            # Never follow links/junctions into another, unselected folder.
            dirs[:] = sorted(d for d in dirs if not self._is_link(Path(directory) / d))
            for name in sorted(names):
                candidate = Path(directory) / name
                if candidate.suffix.lower() not in PHOTO_TYPES or self._is_link(candidate): continue
                try:
                    resolved = candidate.resolve()
                    if not resolved.is_relative_to(root) or not resolved.is_file(): continue
                except OSError:
                    continue
                ident = hashlib.sha256(str(resolved).encode()).hexdigest()[:24]
                files[ident] = resolved
                if len(files) >= MAX_PHOTOS: break
            if len(files) >= MAX_PHOTOS or visited >= MAX_PHOTOS:
                limited = True; break
        return root, files, limited

    @staticmethod
    def _is_link(path):
        try:
            return path.is_symlink() or bool(getattr(path, 'is_junction', lambda: False)()) or bool(
                getattr(path.lstat(), 'st_file_attributes', 0) & 0x400)
        except OSError:
            return True

    def choose(self, folder):
        root, files, limited = self._scan(folder)
        if not files:
            raise ValueError('В этой папке и её подпапках нет JPG, PNG, WebP или BMP.')
        with self.lock:
            same = root == self.root
            self.root, self.files, self.limited = root, files, limited
            self.bag = []
            if not same: self.current = self.frame = None
            else:
                if self.current and self.current['id'] not in files: self.current = None
                if self.frame and self.frame['id'] not in files: self.frame = None
            self.revision += 1
            self._save()
            return self.public()

    def _save(self):
        value = {'folder': str(self.root) if self.root else '',
                 'current': self.current['id'] if self.current else None,
                 'frame': self.frame['id'] if self.frame else None}
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(value, ensure_ascii=False), 'utf-8')
        temporary.replace(self.path)

    def _source(self, ident):
        path = self.files.get(ident)
        if not path or not self.root:
            raise ValueError('Находка недоступна. Попросите Момо принести другую.')
        resolved = path.resolve()
        if resolved.suffix.lower() not in PHOTO_TYPES or not resolved.is_relative_to(self.root) or not resolved.is_file():
            raise ValueError('Оригинал перемещён или удалён. Попросите другую находку.')
        return resolved

    def _photo(self, ident):
        source = self._source(ident)
        try:
            with Image.open(source) as image:
                if image.width * image.height > 80_000_000:
                    raise ValueError('Слишком большое изображение.')
                image = ImageOps.exif_transpose(image)
                image.thumbnail((640, 640), Image.Resampling.LANCZOS)
                rgba = image.convert('RGBA')
                background = Image.new('RGBA', rgba.size, '#f6f1e7')
                background.alpha_composite(rgba)
                image = background.convert('RGB')
        except (OSError, Image.DecompressionBombError) as error:
            raise ValueError('Фотографию не удалось прочитать.') from error
        return {'id': ident, 'name': source.name, 'image': image}

    def next(self):
        with self.lock:
            if not self.root: raise ValueError('Сначала выберите папку с фотографиями для Момо.')
            if not self.root.is_dir(): raise ValueError('Папка с фотографиями недоступна. Подключите диск или выберите другую.')
            attempted=set()
            while self.files:
                if not self.bag:
                    self.bag = [ident for ident in self.files if ident not in attempted]
                    if not self.bag:break
                    random.SystemRandom().shuffle(self.bag)
                    if len(self.bag) > 1 and self.current and self.bag[-1] == self.current['id']:
                        self.bag[0], self.bag[-1] = self.bag[-1], self.bag[0]
                ident = self.bag.pop()
                attempted.add(ident)
                try: photo = self._photo(ident)
                except (OSError, ValueError):
                    self.files.pop(ident,None)
                    continue
                self.current = photo
                self.revision += 1
                self._save()
                return photo
            raise ValueError('Не удалось прочитать фотографии. Обновите папку или выберите другую.')

    def pin(self, ident):
        with self.lock:
            if not self.current or ident != self.current['id']:
                raise ValueError('Находка уже изменилась. Попробуйте ещё раз.')
            self._source(ident)
            self.frame = self.current
            self.revision += 1
            self._save()
            return self.frame['image'].copy()

    def unpin(self):
        with self.lock:
            self.frame = None; self.revision += 1; self._save()

    def open_original(self, ident):
        with self.lock:
            if not self.current or ident != self.current['id']:
                raise ValueError('Находка уже изменилась. Попробуйте ещё раз.')
            source = self._source(ident)
        if os.name != 'nt': raise ValueError('Открытие оригинала поддерживается в Windows.')
        os.startfile(str(source), 'open')

    def preview(self, kind):
        with self.lock:
            if kind not in ('current', 'frame'): raise ValueError('Неизвестная находка.')
            photo = self.current if kind == 'current' else self.frame
            if not photo: raise ValueError('Момо ещё не принёс фотографию.')
            return ImageOps.pad(photo['image'], (240, 240), color='#f6f1e7')

    def public(self):
        with self.lock:
            def info(photo): return {k: photo[k] for k in ('id', 'name')} if photo else None
            return {'folder': str(self.root) if self.root else '', 'count': len(self.files),
                    'limited': self.limited, 'revision': self.revision,
                    'current': info(self.current), 'frame': info(self.frame)}
