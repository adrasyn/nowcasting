"""Guard the critical wiring as well as the policy's behavioral tests."""
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]


class WorkflowContractTests(unittest.TestCase):
    def test_artifact_lookup_is_read_only_and_scoped_to_publication(self):
        workflow = (ROOT/'.github/workflows/deploy.yml').read_text()
        self.assertIn('permissions:\n  contents: read\n  pages: write\n  id-token: write', workflow)
        before_deploy, deploy = workflow.split('\n  deploy:\n')
        self.assertEqual(before_deploy.count('permissions:'), 1)
        self.assertNotIn('actions:', before_deploy)
        self.assertEqual(deploy.count('permissions:'), 1)
        self.assertIn('permissions:\n      contents: read\n      actions: read\n'
                      '      pages: write\n      id-token: write', deploy)
        self.assertNotIn('actions: write', workflow)
        lookup = deploy.split("      - name: Wait for this run's Pages artifact")[1].split(
            '      - name: Deploy to GitHub Pages')[0]
        self.assertIn("github.ref == 'refs/heads/main'", lookup)
        self.assertIn('steps.pages_upload.outputs.artifact_id', lookup)
        self.assertIn('run_id: context.runId, name', lookup)
        self.assertIn('a.id === artifactId && a.name === name && !a.expired', lookup)

    def test_model_dispatches_are_unchanged(self):
        for name in ['nowcast-weekly.yml', 'nowcast-v3-weekly.yml']:
            self.assertIn('gh workflow run deploy.yml --ref main', (ROOT/'.github/workflows'/name).read_text())

    def test_one_build_and_fail_closed_named_browser_gate(self):
        workflow = (ROOT/'.github/workflows/deploy.yml').read_text()
        action = (ROOT/'.github/actions/browser-qa/action.yml').read_text()
        self.assertEqual(workflow.count('run: npm run build'), 1)
        self.assertNotIn('npm run build', action)
        self.assertNotIn('npm test', action)
        self.assertIn('needs: [candidate, chromium, webkit]\n    if: always()', workflow)
        self.assertIn('scripts/ci/workflow_policy.py gate', workflow)
        for job in ['chromium', 'webkit']:
            block = re.search(r'\n  '+job+r':\n(.*?)(?=\n  [a-z_]+:|\Z)', workflow, re.S)[1]
            self.assertIn("if: needs.candidate.outputs.full_qa == 'true'", block)
        self.assertNotIn('continue-on-error', workflow+action)
        self.assertIn('NOWCAST_PREBUILT:', workflow)
        self.assertIn('NOWCAST_PREBUILT:', action)

    def test_sdk_image_matches_lock_and_full_suites_are_retained(self):
        workflow = (ROOT/'.github/workflows/deploy.yml').read_text()
        action = (ROOT/'.github/actions/browser-qa/action.yml').read_text()
        lock = json.loads((ROOT/'package-lock.json').read_text())
        version = lock['packages']['node_modules/@playwright/test']['version']
        self.assertIn(f'mcr.microsoft.com/playwright:v{version}-noble', workflow)
        self.assertIn(f'!== "{version}"', action)
        self.assertIn("cache: ${{ inputs.project == 'chromium' && 'pip' || '' }}", action)
        self.assertIn('git config --global --add safe.directory "$GITHUB_WORKSPACE"', action)
        self.assertNotIn('safe.directory "*"', action)
        config = (ROOT/'playwright.config.ts').read_text()
        for name in ['evolution-visibility', 'evolution-legend', 'evolution-axis']:
            self.assertIn(f'**/{name}.spec.ts', config)
        self.assertIn('name: "chromium"', config)
        self.assertIn('name: "webkit-iphone"', config)

    def test_publication_is_main_only_and_reuses_verified_export(self):
        workflow = (ROOT/'.github/workflows/deploy.yml').read_text()
        deploy = workflow.split('\n  deploy:\n')[1]
        self.assertNotIn('npm run build', deploy)
        self.assertIn('artifact-ids: ${{ needs.candidate.outputs.artifact_id }}', deploy)
        self.assertIn('candidate.py verify --commit "$GITHUB_SHA" --run "$GITHUB_RUN_ID"', deploy)
        self.assertIn("github.ref == 'refs/heads/main'", deploy)
        self.assertIn('--manifest ci-artifact/manifest.json', deploy)
        self.assertIn('name: pages-${{ github.run_id }}-${{ github.run_attempt }}', deploy)
        self.assertIn('artifact_name: pages-${{ github.run_id }}-${{ github.run_attempt }}', deploy)
