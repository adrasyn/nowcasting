import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from candidate import digest

spec = importlib.util.spec_from_file_location('check_deployed', Path(__file__).resolve().parents[1]/'check_deployed.py')
live = importlib.util.module_from_spec(spec); spec.loader.exec_module(live)
COMMIT = 'a' * 40


class LiveExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name)
        (self.data/'latest_combo.json').write_text(json.dumps({'status':'ok', 'as_of':'2026-11-16',
            'horizons':[{'months_with_data':3,'qoq_growth_pct':0.5}]}))
        (self.data/'indicators_combo.json').write_text('{"indicators":[]}')
        meta = f'<meta name="build-commit" content="{COMMIT}">'.encode()
        self.responses = {'/': meta+b'<main class="nowcast-monitor">Historical data +0.50%</main><script src="/_next/app.js"></script>',
            '/simple/': meta+b'simple', '/v2': b'legacy', '/v3': b'<main class="nowcast-monitor">alias</main>',
            '/_next/app.js': b'JavaScript', '/monitor/fonts/InstrumentSerif-Regular.ttf': b'font1',
            '/monitor/fonts/Inter.ttf': b'font2', '/monitor/NOTICE.txt': b'licences',
            '/simple/nowcast.gif': b'GIF89a-nowcast', '/simple/record.gif': b'GIF89a-record'}
        def name(path):
            path = path.lstrip('/')
            if not path or path.endswith('/'): return path+'index.html'
            return path+'/index.html' if path in {'v2', 'v3'} else path
        files = {name(p):hashlib.sha256(b).hexdigest() for p,b in self.responses.items()}
        self.manifest = {'commit':COMMIT, 'files':files, 'export_sha256':digest(files)}

    def verify(self, manifest=True):
        with patch.object(live, 'request', side_effect=lambda base,path,commit:self.responses[path]):
            return live.verify('https://example.invalid/', COMMIT, self.data, self.manifest if manifest else None)

    def test_live_routes_assets_and_gifs_match_the_tested_export(self):
        result = self.verify()
        self.assertTrue(result['exact_export_verified'])
        self.assertEqual(result['export_sha256'], self.manifest['export_sha256'])

    def test_same_commit_but_different_build_bytes_are_rejected(self):
        for path in ['/', '/simple/', '/v2', '/v3', '/_next/app.js', '/monitor/fonts/Inter.ttf', '/simple/record.gif']:
            with self.subTest(path=path):
                old = self.responses[path]; self.responses[path] += b'different build under same SHA'
                with self.assertRaises(ValueError): self.verify()
                self.responses[path] = old

    def test_wrong_manifest_commit_and_missing_inventory_are_rejected(self):
        self.manifest['commit'] = 'b'*40
        with self.assertRaises(ValueError): self.verify()
        self.manifest['commit'] = COMMIT; self.manifest['files'].pop('index.html')
        with self.assertRaises(ValueError): self.verify()

    def test_existing_no_manifest_cli_contract_still_works(self):
        self.assertEqual(self.verify(False)['result'], 'passed')

    def test_flat_next_export_routes_are_also_verified(self):
        for route in ['v2', 'v3']:
            self.manifest['files'][route+'.html'] = self.manifest['files'].pop(route+'/index.html')
        self.assertTrue(self.verify()['exact_export_verified'])
