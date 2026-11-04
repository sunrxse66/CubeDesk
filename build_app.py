"""Build a standalone local browser app; never bundle private device settings."""
from pathlib import Path
import subprocess
import sys
import argparse
from cubedesk import VERSION

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dist-dir', type=Path, default=ROOT / 'dist')
    args = parser.parse_args()
    assets = ROOT / 'app-assets'
    assets.mkdir(exist_ok=True)
    image = Image.new('RGBA', (256, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, 255, 255), radius=55, fill='#17243a')
    draw.polygon([(128, 33), (216, 81), (128, 132), (40, 81)], fill='#cebdff')
    draw.polygon([(40, 88), (121, 137), (121, 225), (40, 176)], fill='#a287ee')
    draw.polygon([(135, 137), (216, 88), (216, 176), (135, 225)], fill='#7658e9')
    image.save(assets / 'cube.ico', sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (256, 256)])
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onefile', '--windowed',
                    '--name', 'CubeDesk', '--icon', str(assets / 'cube.ico'),
                    '--distpath', str(args.dist_dir.resolve()), '--workpath', str(ROOT / '.tools/app-build'),
                    '--specpath', str(ROOT / '.tools'), '--paths', str(ROOT),
                    '--hidden-import', 'pystray._win32',
                    '--add-data', str(ROOT / 'web') + ';web',
                    '--add-data', str(ROOT / 'cubedesk/resources') + ';cubedesk/resources',
                    '--exclude-module', 'PySide6', '--exclude-module', 'PyQt5',
                    '--exclude-module', 'PyQt6', '--exclude-module', 'tkinter',
                    '--exclude-module', 'matplotlib', '--exclude-module', 'numpy',
                    str(ROOT / 'start_cubedesk.py')], cwd=ROOT, check=True)


if __name__ == '__main__':
    main()
