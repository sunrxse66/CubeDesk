import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from cubedesk.findings import PhotoFindings
from cubedesk.pet import PetState, FIND_TIMING


class FindingsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.storage=self.root/'profile';self.storage.mkdir()
        self.photos=self.root/'photos';self.photos.mkdir()
        self.findings=PhotoFindings(self.storage)

    def tearDown(self):self.temp.cleanup()

    def photo(self,name,color='red'):
        path=self.photos/name;path.parent.mkdir(parents=True,exist_ok=True)
        Image.new('RGB',(90,60),color).save(path)
        return path

    def test_explicit_folder_recurses_and_shuffles_without_repeat(self):
        self.photo('one.jpg');self.photo('nested/two.png','blue');self.photo('three.webp','green')
        (self.photos/'notes.txt').write_text('not a photograph')
        self.findings.choose(str(self.photos))
        self.assertEqual(self.findings.public()['count'],3)
        found=[self.findings.next()['id'] for _ in range(3)]
        self.assertEqual(len(set(found)),3)
        self.assertNotEqual(self.findings.next()['id'],found[-1])

    def test_bad_files_are_skipped_and_originals_unchanged(self):
        original=self.photo('good.jpg');before=original.read_bytes()
        (self.photos/'broken.png').write_bytes(b'not an image')
        self.findings.choose(str(self.photos))
        self.assertEqual(self.findings.next()['name'],'good.jpg')
        self.assertEqual(self.findings.next()['name'],'good.jpg')
        self.assertEqual(original.read_bytes(),before)
        self.assertEqual(set(p.name for p in self.storage.iterdir()),{'momo-findings.json'})

    def test_frame_and_selected_folder_survive_restart(self):
        self.photo('memory.jpg','blue')
        self.findings.choose(str(self.photos));photo=self.findings.next()
        self.findings.pin(photo['id'])
        restored=PhotoFindings(self.storage)
        self.assertEqual(restored.public()['frame']['id'],photo['id'])
        self.assertEqual(restored.preview('frame').getpixel((120,120)),(0,0,254))
        self.assertEqual(restored.public()['current']['name'],'memory.jpg')

    def test_invalid_folder_preserves_current_and_frame(self):
        self.photo('memory.png');self.findings.choose(str(self.photos))
        photo=self.findings.next();self.findings.pin(photo['id']);before=self.findings.public()
        for folder in (str(self.root/'missing'),str(self.storage)):
            with self.assertRaises(ValueError):self.findings.choose(folder)
            self.assertEqual(self.findings.public(),before)

    def test_open_and_pin_cannot_escape_selected_folder_or_use_stale_id(self):
        path=self.photo('memory.png');self.findings.choose(str(self.photos));photo=self.findings.next()
        with self.assertRaises(ValueError):self.findings.pin('../../settings.json')
        outside=self.root/'outside.png';Image.new('RGB',(2,2)).save(outside)
        self.findings.files[photo['id']]=outside
        with self.assertRaises(ValueError):self.findings.open_original(photo['id'])
        with self.assertRaises(ValueError):self.findings.pin(photo['id'])
        self.findings.files[photo['id']]=path
        with patch('cubedesk.findings.os.startfile',create=True) as opened:
            self.findings.open_original(photo['id']);opened.assert_called_once_with(str(path.resolve()),'open')

    def test_removed_source_is_handled_without_losing_cached_preview(self):
        path=self.photo('memory.png');self.findings.choose(str(self.photos));photo=self.findings.next()
        path.unlink()
        self.assertEqual(self.findings.preview('current').size,(240,240))
        with self.assertRaises(ValueError):self.findings.open_original(photo['id'])
        with self.assertRaises(ValueError):self.findings.next()

    def test_momo_finding_waits_for_stream_and_runs_complete_sequence(self):
        self.photo('memory.png');self.findings.choose(str(self.photos));photo=self.findings.next()
        pet=PetState(now=0,character='momo');pet.request_finding(photo)
        self.assertEqual(pet.pose(100)['phase'],'idle')
        pet.activate_pending(100)
        instant=100
        for phase,duration in zip(('departing','searching','bringing','presenting','returning_find'),FIND_TIMING):
            pose=pet.pose(instant+duration/2)
            self.assertEqual(pose['phase'],phase)
            frame=pet.image(instant+duration/2)
            self.assertEqual(frame.size,(240,240));self.assertEqual(frame.mode,'RGB')
            instant+=duration
        self.assertEqual(pet.pose(instant+.01)['phase'],'idle')
        pet.set_frame(photo['image'])
        before=pet.image(instant+.01)
        pet.reset()
        self.assertEqual(pet.image(instant+.01).tobytes(),before.tobytes())
        pet.select('moti');self.assertFalse(pet.finding_busy())

    def test_letterboxing_and_exif_orientation_are_applied(self):
        path=self.photos/'rotated.jpg'
        image=Image.new('RGB',(80,40),'green');exif=Image.Exif();exif[274]=6
        image.save(path,exif=exif)
        self.findings.choose(str(self.photos));photo=self.findings.next()
        self.assertEqual(photo['image'].size,(40,80))
        self.assertEqual(self.findings.preview('current').size,(240,240))


if __name__=='__main__':unittest.main()
