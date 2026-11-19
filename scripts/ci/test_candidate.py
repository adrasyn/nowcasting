import copy
from pathlib import Path
import tempfile
import unittest
from candidate import create, verify
from candidate import validate_checkout
from unittest.mock import patch

COMMIT = 'a' * 40


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.site = self.root/'out'; self.fixtures = self.root/'fixtures'
        (self.site/'simple').mkdir(parents=True); self.fixtures.mkdir()
        for name in ['index.html', 'simple/index.html']:
            (self.site/name).write_text(f'<meta name="build-commit" content="{COMMIT}">')
        (self.site/'.nojekyll').write_text('')
        (self.fixtures/'monitor.json').write_text('{"fixture":"only QA, never Pages"}')
        self.manifest = create(self.site, self.fixtures, COMMIT, '42')

    def test_exact_candidate_and_hidden_export_files_are_retained(self):
        self.assertIn('.nojekyll', self.manifest['files'])
        self.assertEqual(verify(self.manifest, self.site, self.fixtures, COMMIT, '42')['result'], 'passed')

    def test_wrong_sha_and_cross_run_artifact_are_rejected(self):
        for commit, run in [('b'*40, '42'), (COMMIT, '43')]:
            with self.assertRaises(ValueError): verify(self.manifest, self.site, self.fixtures, commit, run)
        with patch('candidate.subprocess.check_output', return_value='b'*40):
            with self.assertRaises(ValueError): validate_checkout(COMMIT)

    def test_modified_added_removed_or_symlinked_export_fails(self):
        for change in ['modify', 'add', 'remove', 'symlink']:
            with self.subTest(change=change):
                file = self.site/'index.html'; original = file.read_bytes()
                if change == 'modify': file.write_bytes(original + b'changed after smoke')
                if change == 'add': (self.site/'extra').write_text('new')
                if change == 'remove': file.unlink()
                if change == 'symlink': (self.site/'link').symlink_to(file)
                with self.assertRaises((ValueError, FileNotFoundError)):
                    verify(self.manifest, self.site, self.fixtures, COMMIT, '42')
                file.write_bytes(original)
                for name in ['extra', 'link']: (self.site/name).unlink(missing_ok=True)

    def test_fixture_tampering_or_wrong_commit_html_is_rejected(self):
        (self.fixtures/'monitor.json').write_text('{}')
        with self.assertRaises(ValueError): verify(self.manifest, self.site, self.fixtures, COMMIT, '42')
        with self.assertRaises(ValueError): create(self.site, self.fixtures, 'b'*40, '42')
        corrupt = copy.deepcopy(self.manifest); corrupt['export_sha256'] = 'not the export'
        with self.assertRaises(ValueError): verify(corrupt, self.site, self.fixtures, COMMIT, '42')
