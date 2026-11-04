"""Publish only the allowlisted release directory. Intended for GitHub Actions."""
import json
from pathlib import Path
import subprocess
import os
import re
from cubedesk import VERSION, REPOSITORY


def gh(*arguments, check=True):
    return subprocess.run(['gh', *arguments], check=check, capture_output=True, text=True, encoding='utf8')


def release_notes(changelog, version):
    """Publish this version's changes; keep the historical changelog in the repo."""
    headings = list(re.finditer(r'^## CubeDesk (\d+\.\d+\.\d+)(?:[^\n]*)$', changelog, re.MULTILINE))
    for index, heading in enumerate(headings):
        if heading.group(1) == version:
            end = headings[index + 1].start() if index + 1 < len(headings) else len(changelog)
            notes = changelog[heading.end():end].strip()
            if notes:
                return notes + '\n'
            break
    raise ValueError('Missing release notes for CubeDesk ' + version)


def main():
    tag = 'v' + VERSION
    ref = os.environ.get('GITHUB_REF', '')
    if ref.startswith('refs/tags/') and ref != 'refs/tags/' + tag:
        raise ValueError('Git tag must match cubedesk.VERSION')
    head = subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
    existing = gh('release','view',tag,'--repo',REPOSITORY,'--json','isDraft,assets',check=False)
    if existing.returncode == 0:
        current = json.loads(existing.stdout)
        if not current['isDraft'] and any(a['name'] == 'update.json' for a in current['assets']):
            print('Published release already has its update manifest; assets will not be overwritten.')
            return
    notes = Path('.tools') / ('release-notes-' + VERSION + '.md')
    notes.parent.mkdir(parents=True, exist_ok=True)
    notes.write_text(release_notes(Path('CHANGELOG.md').read_text('utf8'), VERSION), 'utf8')
    if existing.returncode != 0:
        gh('release','create',tag,'--repo',REPOSITORY,'--draft','--target',head,
           '--title','CubeDesk '+VERSION+' · Windows + PCStream', '--notes-file',str(notes))
    else:
        gh('release','edit',tag,'--repo',REPOSITORY,'--notes-file',str(notes))
    directory = Path('dist/release')
    allowed = {'CubeDesk.exe','CubeDesk-Windows.zip','HelloCubic-PCStream-universal.bin','update.json',
               'QUICKSTART.txt','LICENSE','THIRD_PARTY.md','SHA256SUMS.txt'}
    if {p.name for p in directory.iterdir()} != allowed:
        raise ValueError('Public release directory has missing or unexpected files')
    # Draft retries can replace incomplete assets. Published complete releases above are immutable here.
    gh('release','upload',tag,'--repo',REPOSITORY,'--clobber',*[str(directory/name) for name in sorted(allowed)])
    gh('release','edit',tag,'--repo',REPOSITORY,'--draft=false','--latest')
    print('Published https://github.com/'+REPOSITORY+'/releases/tag/'+tag)


if __name__ == '__main__': main()
