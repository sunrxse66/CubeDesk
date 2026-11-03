"""Package the universal firmware only after checking for private boot data."""
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent


def main():
    image = (ROOT / 'firmware/.pio/build/esp12e/firmware.bin').read_bytes()
    metadata = json.loads((ROOT / 'firmware/version.json').read_text('utf8'))
    version = metadata['build_id']
    if image[0] != 0xE9 or version.encode() not in image:
        raise ValueError('Expected onboarding firmware not found')
    # These local files are optional, never copied into the release directory.
    secrets = []
    local = ROOT / 'cube-local.json'
    if local.exists():
        secrets.append(json.loads(local.read_text('utf8'))['token'])
    header = ROOT / 'firmware/include/pcstream_boot.h'
    if header.exists():
        for encoded in re.findall(r'"((?:\\x[0-9a-fA-F]{2})+)"', header.read_text('ascii')):
            secrets.append(bytes.fromhex(encoded.replace('\\x', '')).decode('utf8'))
    if any(value and value.encode('utf8') in image for value in secrets):
        raise ValueError('Private boot data detected: public artifact was not written')
    out = ROOT / 'dist/HelloCubic-PCStream-universal.bin'
    out.parent.mkdir(exist_ok=True)
    out.write_bytes(image)
    manifest = dict(version=version, bytes=len(image), sha256=hashlib.sha256(image).hexdigest(),
                    model='HelloCubic-Lite / ESP8266 / ST7789 240x240 / 4 MB',
                    no_private_defaults=True, preserves_saved_configuration=True)
    out.with_suffix('.json').write_text(json.dumps(manifest, indent=2), 'utf8')
    print(json.dumps(manifest))


if __name__ == '__main__':
    main()
