import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import workflow_policy as policy

MAIN = "refs/heads/main"
BASE = "a" * 40


class CoverageTests(unittest.TestCase):
    def test_every_pr_requires_both_browsers(self):
        for paths in [[], ["data/latest_combo.json"], ["README.md"], ["src/app/page.tsx"]]:
            p = policy.choose("pull_request", "refs/pull/55/merge", base=BASE, paths=paths)
            self.assertEqual((p['full_qa'], p['publish']), ('true', 'false'))

    def test_routine_push_and_weekly_dispatch_use_the_same_data_policy(self):
        paths = ["data/latest_combo.json", "data/gdp.json", "nowcasting_v2/data_raw/anz_sent.meta.json",
                 "nowcasting_v3/data/first_print_misses.csv", "pipeline/nab_business_confidence_raw.csv"]
        for event in ['push', 'workflow_dispatch']:
            for changes in [[], paths, paths + ['docs/reviews/notes.md']]:
                p = policy.choose(event, MAIN, base=BASE, paths=changes)
                self.assertEqual((p['full_qa'], p['publish']), ('false', 'true'))

    def test_unpublished_code_and_unknown_paths_always_require_full(self):
        for path in ['src/app/page.tsx', 'public/monitor/fonts/Inter.ttf', 'tests/site.spec.ts',
                     'scripts/check_deployed.py', '.github/workflows/deploy.yml',
                     'package-lock.json', 'data/executable.js', 'nowcasting_v3/state/au_estimate.npz',
                     'docs/unsafe.py', 'unknown']:
            for event in ['push', 'workflow_dispatch']:
                p = policy.choose(event, MAIN, base=BASE, paths=['data/latest_combo.json', path])
                self.assertEqual(p['full_qa'], 'true', path)

    def test_manual_full_cannot_be_downgraded_by_data_only_diff(self):
        p = policy.choose('workflow_dispatch', MAIN, 'full', BASE, ['data/latest_combo.json'])
        self.assertEqual((p['full_qa'], p['publish']), ('true', 'true'))

    def test_nonmain_dispatch_is_full_verification_and_never_publication(self):
        for ref in ['refs/heads/codex/fast-pages', 'refs/tags/v1']:
            p = policy.choose('workflow_dispatch', ref, base=BASE, paths=[])
            self.assertEqual((p['full_qa'], p['publish']), ('true', 'false'))

    def test_unknown_or_unavailable_baseline_fails_closed(self):
        for base, paths in [(None, []), (None, None), (BASE, None), ('invalid SHA', [])]:
            self.assertEqual(policy.choose('workflow_dispatch', MAIN, base=base, paths=paths)['full_qa'], 'true')
        self.assertEqual(policy.choose('workflow_run', MAIN, base=BASE, paths=[])['publish'], 'false')
        with self.assertRaises(ValueError):
            policy.choose('workflow_dispatch', MAIN, 'smoke')

    def test_network_failure_emits_full_plan_not_a_smoke_override(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'output'
            env = {'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_REF': MAIN,
                   'GITHUB_SHA': BASE, 'GITHUB_OUTPUT': str(output), 'VERIFICATION': 'auto'}
            with patch.dict(os.environ, env), patch.object(policy, 'published_commit', side_effect=TimeoutError):
                result = policy.plan()
            self.assertEqual(result['full_qa'], 'true')
            self.assertIn('full_qa=true', output.read_text())


class GateTests(unittest.TestCase):
    def needs(self, full='true', chromium='success', webkit='success'):
        return {'candidate': {'result': 'success', 'outputs': {'full_qa': full, 'publish': 'true', 'artifact_id':'42'}},
                'chromium': {'result': chromium}, 'webkit': {'result': webkit}}

    def test_required_qa_never_accepts_skipped_failed_missing_or_cancelled(self):
        for job in ['chromium', 'webkit']:
            for result in ['skipped', 'failure', 'cancelled', None]:
                needs = self.needs(); needs[job]['result'] = result
                with self.assertRaises(ValueError): policy.gate(needs, 'push', MAIN)

    def test_explicit_smoke_plan_accepts_intentionally_skipped_full_qa(self):
        self.assertEqual(policy.gate(self.needs('false', 'skipped', 'skipped'), 'push', MAIN)['result'], 'passed')
        self.assertEqual(policy.gate(self.needs(), 'push', MAIN)['result'], 'passed')

    def test_bad_candidate_missing_plan_and_wrong_publication_context_fail(self):
        for result in ['failure', 'skipped', 'cancelled', None]:
            needs = self.needs(); needs['candidate']['result'] = result
            with self.assertRaises(ValueError): policy.gate(needs, 'push', MAIN)
        for value in ['', None, 'yes']:
            needs = self.needs(value)
            with self.assertRaises(ValueError): policy.gate(needs, 'push', MAIN)
        needs = self.needs(); needs['candidate']['outputs'].pop('artifact_id')
        with self.assertRaises(ValueError): policy.gate(needs, 'push', MAIN)
        with self.assertRaises(ValueError): policy.gate(self.needs(), 'pull_request', 'refs/pull/55/merge')


class GitRangeTests(unittest.TestCase):
    def test_diff_uses_published_baseline_and_catches_renamed_code(self):
        with tempfile.TemporaryDirectory() as directory:
            cwd = Path.cwd()
            try:
                os.chdir(directory)
                def git(*args): return subprocess.check_output(['git', *args], stderr=subprocess.DEVNULL).decode().strip()
                git('init'); git('config', 'user.name', 'CI test'); git('config', 'user.email', 'ci@example.invalid')
                Path('src').mkdir(); Path('src/ui.ts').write_text('original')
                git('add', '.'); git('commit', '-m', 'published'); base = git('rev-parse', 'HEAD')
                Path('src/ui.ts').write_text('unpublished change')
                git('commit', '-am', 'code'); code = git('rev-parse', 'HEAD')
                Path('data').mkdir(); Path('data/latest.json').write_text('{}')
                git('add', '.'); git('commit', '-m', 'data'); head = git('rev-parse', 'HEAD')
                # Looking only at the most recent data push would miss the code.
                self.assertEqual(policy.changed_paths(code, head), ['data/latest.json'])
                self.assertIn('src/ui.ts', policy.changed_paths(base, head))
                self.assertEqual(policy.choose('workflow_dispatch', MAIN, base=base,
                                 paths=policy.changed_paths(base, head))['full_qa'], 'true')
                git('mv', 'src/ui.ts', 'data/ui.json'); git('commit', '-m', 'rename')
                self.assertIn('src/ui.ts', policy.changed_paths(head, git('rev-parse', 'HEAD')))
                with self.assertRaises(subprocess.CalledProcessError): policy.changed_paths(head, base)
            finally:
                os.chdir(cwd)
