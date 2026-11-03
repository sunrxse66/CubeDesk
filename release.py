"""Create an allowlisted public release. Never copy the whole dist/ directory."""
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

from cubedesk import VERSION, REPOSITORY
from cubedesk.updates import release_manifest, verify_file

ROOT = Path(__file__).resolve().parent


def digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def main():
    out = ROOT / 'dist/release'
    out.mkdir(parents=True, exist_ok=True)
    metadata = json.loads((ROOT / 'firmware/version.json').read_text('utf8'))
    public_fw = ROOT / 'dist/HelloCubic-PCStream-universal.bin'
    proof = json.loads(public_fw.with_suffix('.json').read_text('utf8'))
    if not proof['no_private_defaults'] or proof['sha256'] != digest(public_fw) or proof['version'] != metadata['build_id']:
        raise ValueError('Universal firmware verification failed')
    manifest = {'schema': 1, 'repository': REPOSITORY, 'version': VERSION}
    for kind, source, filename, version in [('app',ROOT/'dist/CubeDesk.exe','CubeDesk.exe',VERSION),
        ('firmware',public_fw,'HelloCubic-PCStream-universal.bin',metadata['version'])]:
        target = out / filename
        shutil.copyfile(source, target)
        spec = dict(version=version, asset=filename, size=target.stat().st_size, sha256=digest(target))
        if kind == 'firmware':
            spec.update(model='HelloCubic-Lite',chip='ESP8266',display='ST7789',width=240,height=240,
                        flash_bytes=4194304,universal=True,build_id=metadata['build_id'])
        manifest[kind] = spec
        verify_file(target, spec, kind)
    base = 'https://github.com/' + REPOSITORY + '/releases/'
    fake_release = dict(tag_name='v'+VERSION,html_url=base+'tag/v'+VERSION,assets=[
        dict(name=s['asset'],size=s['size'],state='uploaded',browser_download_url=base+'download/v'+VERSION+'/'+s['asset'])
        for s in (manifest['app'],manifest['firmware'])])
    release_manifest(fake_release,manifest)
    (out/'update.json').write_text(json.dumps(manifest,indent=2)+'\n','utf8')
    shutil.copyfile(ROOT/'QUICKSTART.txt',out/'QUICKSTART.txt')
    shutil.copyfile(ROOT/'LICENSE',out/'LICENSE')
    shutil.copyfile(ROOT/'THIRD_PARTY.md',out/'THIRD_PARTY.md')
    with zipfile.ZipFile(out/'CubeDesk-Windows.zip','w',zipfile.ZIP_DEFLATED) as archive:
        for name in ('CubeDesk.exe','QUICKSTART.txt','LICENSE','THIRD_PARTY.md'):
            archive.write(out/name,name)
    allowed = {'CubeDesk.exe','CubeDesk-Windows.zip','HelloCubic-PCStream-universal.bin','update.json','QUICKSTART.txt','LICENSE','THIRD_PARTY.md','SHA256SUMS.txt'}
    if any(p.name not in allowed or not p.is_file() for p in out.iterdir()):
        raise ValueError('Unexpected file in public release directory; inspect it before publishing')
    entries = sorted(p for p in out.iterdir() if p.name != 'SHA256SUMS.txt')
    (out/'SHA256SUMS.txt').write_text(''.join(digest(p)+'  '+p.name+'\n' for p in entries),'utf8')
    print('Public release:',REPOSITORY,'v'+VERSION)
    print('Assets:',', '.join(sorted(allowed)))


if __name__ == '__main__': main()
