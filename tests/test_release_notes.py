import unittest

from publish_release import release_notes


class ReleaseNotesTests(unittest.TestCase):
    def test_only_requested_release_is_published(self):
        changelog = '# History\n\n## CubeDesk 1.8.1 · PCStream 1.8.1\n\n- New fix.\n\n## CubeDesk 1.8.0 · PCStream 1.7.0\n\n- Old feature.\n'
        self.assertEqual(release_notes(changelog, '1.8.1'), '- New fix.\n')
        self.assertEqual(release_notes(changelog, '1.8.0'), '- Old feature.\n')

    def test_sections_inside_notes_are_preserved(self):
        changelog = '## CubeDesk 1.8.1\n\n- Fix.\n\n## Updating\nKeep settings.\n\n## CubeDesk 1.8.0\nOld.\n'
        self.assertEqual(release_notes(changelog, '1.8.1'), '- Fix.\n\n## Updating\nKeep settings.\n')

    def test_missing_or_empty_notes_stop_publication(self):
        for changelog in ('## CubeDesk 1.8.0\nOld.\n', '## CubeDesk 1.8.1\n\n## CubeDesk 1.8.0\nOld.\n'):
            with self.subTest(changelog=changelog), self.assertRaises(ValueError):
                release_notes(changelog, '1.8.1')
