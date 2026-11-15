"""Import Pixel Frog's CC0 Tiny Swords Update 010 archive into game resources.

Get 'TS_old version_CC0 Licensed' from https://pixelfrog-assets.itch.io/tiny-swords
then run: python prepare_village_tiles.py path/to/archive.zip
Only the old CC0 edition is used, not the differently licensed current edition.
"""
import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

from PIL import Image


DEST = Path(__file__).parent/'cubedesk/resources/village/tiles'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    args = parser.parse_args()
    digest = hashlib.sha256(args.archive.read_bytes()).hexdigest()
    if digest != 'e4d79bd4514bad153cfa1cc8f4c8d8bf10ed39bf69bd98b83bdc46c03d14bb9c':
        raise ValueError('Expected the original CC0 Update 010 archive, not another edition')
    DEST.mkdir(parents=True, exist_ok=True)
    sources = {
        'ground':'Terrain/Ground/Tilemap_Flat.png',
        'bridge':'Terrain/Bridge/Bridge_All.png',
        'tree':'Resources/Trees/Tree.png',
        'sheep':'Resources/Sheep/HappySheep_Idle.png',
        'worker':'Factions/Knights/Troops/Pawn/Blue/Pawn_Blue.png',
        'house-blue':'Factions/Knights/Buildings/House/House_Blue.png',
        'house-red':'Factions/Knights/Buildings/House/House_Red.png',
        'house-purple':'Factions/Knights/Buildings/House/House_Purple.png',
        'house-yellow':'Factions/Knights/Buildings/House/House_Yellow.png',
        'tower':'Factions/Knights/Buildings/Tower/Tower_Yellow.png',
        'inn':'Factions/Knights/Buildings/Castle/Castle_Blue.png',
        'workshop':'Factions/Goblins/Buildings/Wood_House/Goblin_House.png',
    }
    sources.update({f'deco-{i:02}':f'Deco/{i:02}.png' for i in range(1,19)})
    with ZipFile(args.archive) as archive:
        for name, source in sources.items():
            with archive.open('Tiny Swords (Update 010)/'+source) as stream:
                image = Image.open(stream).convert('RGBA')
                image.save(DEST/(name+'.png'), optimize=True)
    (DEST/'provenance.json').write_text(json.dumps({
        'author':'Pixel Frog', 'pack':'Tiny Swords Update 010 (old CC0 edition)',
        'source':'https://pixelfrog-assets.itch.io/tiny-swords',
        'download_label':'TS_old version_CC0 Licensed',
        'archive_sha256':digest, 'license':'CC0-1.0', 'files':sources,
    }, indent=2)+'\n', encoding='utf8')
    print(f'Imported {len(sources)} standalone sprite sheets')


if __name__ == '__main__':
    main()
