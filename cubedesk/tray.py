"""Windows notification-area controls. The web panel is optional."""
import threading
import webbrowser

from PIL import Image, ImageDraw


class Tray:
    def __init__(self, app, server, url):
        import pystray
        self.app, self.server, self.url = app, server, url
        self.ready = threading.Event()
        image = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((0, 0, 63, 63), radius=13, fill='#17243a')
        draw.polygon([(32, 8), (54, 20), (32, 33), (10, 20)], fill='#cebdff')
        draw.polygon([(10, 22), (30, 34), (30, 56), (10, 44)], fill='#a287ee')
        draw.polygon([(34, 34), (54, 22), (54, 44), (34, 56)], fill='#7658e9')
        item = pystray.MenuItem
        self.icon = pystray.Icon('CubeDesk', image, 'CubeDesk', pystray.Menu(
            item('Открыть CubeDesk', self.open, default=True),
            item(lambda _: 'Пауза' if app.job['running'] and app.job['kind'] == 'stream' else 'Продолжить показ',
                 self.toggle, enabled=lambda _: not app.job['running'] or app.job['kind'] == 'stream'),
            pystray.Menu.SEPARATOR,
            item('Запускать с Windows', self.startup, checked=lambda _: app.startup.enabled(),
                 enabled=lambda _: app.startup.supported),
            item('Выход', self.exit, enabled=lambda _: not (app.job['running'] and app.job['kind'] == 'firmware')),
        ))

    def open(self, *_):
        webbrowser.open(self.url)

    def _run(self, action):
        # A pending network connection must not freeze the tray's message loop.
        def run():
            try:
                action()
            except Exception as error:
                self.app.log(str(error))
                self.icon.notify(str(error), 'CubeDesk')
        threading.Thread(target=run, daemon=True).start()

    def toggle(self, *_):
        def action():
            if self.app.job['running'] and self.app.job['kind'] == 'stream':
                self.app.pause()
            else:
                self.app.resume_last()
        self._run(action)

    def startup(self, *_):
        self._run(lambda: self.app.background_settings({'startup_enabled': not self.app.startup.enabled()}))

    def exit(self, *_):
        def action():
            with self.app.control:
                if self.app.job['running'] and self.app.job['kind'] == 'firmware':
                    raise ValueError('Дождитесь завершения обновления прошивки')
                self.app.stop.set()  # Exit preserves intent; Pause deliberately does not.
                self.server.shutdown()
        self._run(action)

    def start(self):
        def setup(icon):
            icon.visible = True
            self.ready.set()
        threading.Thread(target=lambda: self.icon.run(setup), daemon=True, name='CubeDesk-tray').start()
        if not self.ready.wait(3):
            raise RuntimeError('Не удалось создать значок CubeDesk рядом с часами Windows')

    def stop(self):
        self.icon.stop()
