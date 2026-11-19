#!/usr/bin/env python3
"""Verify the actual public Pages responses after deployment, without models.

Also usable against a local export server. Requests are fresh, read-only and
limited to the site supplied by the caller. No credentials are sent.
"""
import argparse
import hashlib
import html
import json
from pathlib import Path
import re
import time
from urllib.parse import urljoin, urlencode
from urllib.request import Request, urlopen


def request(base, path, commit):
    url = urljoin(base.rstrip('/')+'/', path.lstrip('/'))
    url += ('&' if '?' in url else '?') + urlencode({'verify': commit, 'at': time.time_ns()})
    req = Request(url, headers={'Cache-Control': 'no-cache', 'User-Agent': 'nowcasting-deployment-check'})
    with urlopen(req, timeout=30) as response:
        body = response.read()
        if response.status != 200:
            raise ValueError(f'{path}: HTTP {response.status}')
        return body


def verify(base, commit, data, manifest=None):
    if manifest is not None and manifest.get('commit') != commit:
        raise ValueError('Export manifest belongs to a different commit')

    def fetch(path):
        body = request(base, path, commit)
        if manifest is not None:
            name = path.lstrip('/')
            if not name or name.endswith('/'):
                name += 'index.html'
            elif name in {'v2', 'v3'}:
                # Next's default export is v2.html; trailingSlash exports use
                # v2/index.html. Verify the actual candidate's route file.
                name = name + '.html' if name + '.html' in manifest.get('files', {}) else name + '/index.html'
            expected = manifest.get('files', {}).get(name)
            if not expected or hashlib.sha256(body).hexdigest() != expected:
                raise ValueError(f'{path}: live bytes differ from the smoke-tested export')
        return body

    root = fetch('/')
    simple = fetch('/simple/')
    for path, body in [('/', root), ('/simple/', simple)]:
        text = body.decode('utf-8')
        if not re.search(r'<meta[^>]*name="build-commit"[^>]*content="'+re.escape(commit)+r'"', text):
            raise ValueError(f'{path}: build-commit differs from {commit}')
    text = root.decode('utf-8')
    if 'class="nowcast-monitor"' not in text or 'Historical data' not in text:
        raise ValueError('Homepage layout or historical data missing')
    latest_path = data / ('latest_combo.json' if (data/'latest_combo.json').exists() else 'latest_v3.json')
    latest = json.loads(latest_path.read_text())
    panel_file = 'indicators_combo.json' if latest_path.stem == 'latest_combo' else 'indicators_v3.json'
    panel_path = data / panel_file
    count = len(json.loads(panel_path.read_text())['indicators']) if panel_path.exists() else 0
    if len(re.findall(r'<details[^>]*id="series-', text)) != count:
        raise ValueError('Homepage indicator count differs from selected production panel')
    # Fresh SSR HTML includes exact final values, even when entrance animation
    # subsequently paints intermediate digits in an aria-hidden layer.
    plain = html.unescape(re.sub('<[^>]+>', '', text)).replace('\u2212', '-')
    if latest.get('status') == 'ok':
        for horizon in latest.get('horizons', []):
            if horizon.get('months_with_data') == 0:
                continue
            value = horizon.get('qoq_growth_pct')
            if isinstance(value, (int, float)):
                formatted = f'{value:+.2f}%' if value != 0 else '0.00%'
                if formatted not in plain:
                    raise ValueError(f'Homepage missing published figure {formatted}')
    # Check actual local font assets and all exported JS/CSS references. Third
    # party analytics are deliberately not a dependency of publication health.
    assets = set(re.findall(r'(?:src|href)="([^"?]+\.(?:js|css))(?:\?[^\"]*)?"', text))
    assets = {a for a in assets if a.startswith('/_next/')}
    assets.update(['/monitor/fonts/InstrumentSerif-Regular.ttf', '/monitor/fonts/Inter.ttf', '/monitor/NOTICE.txt'])
    for path in sorted(assets):
        if not fetch(path):
            raise ValueError(f'Empty asset: {path}')
    for path in ['/v2', '/v3', '/simple/nowcast.gif', '/simple/record.gif']:
        body = fetch(path)
        if path.endswith('.gif') and not body.startswith(b'GIF'):
            raise ValueError(f'Invalid GIF: {path}')
        if path == '/v3' and b'class="nowcast-monitor"' not in body:
            raise ValueError('Homepage alias differs')
    return {'base': base, 'commit': commit, 'as_of': latest.get('as_of'),
            'indicator_count': count, 'homepage_sha256': hashlib.sha256(root).hexdigest(),
            'simple_sha256': hashlib.sha256(simple).hexdigest(),
            'checked_routes': ['/', '/simple/', '/v2', '/v3'],
            'assets_checked': len(assets)+2,
            'export_sha256': manifest.get('export_sha256') if manifest else None,
            'exact_export_verified': manifest is not None, 'result': 'passed'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', required=True)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--data', type=Path, default=Path('data'))
    parser.add_argument('--attempts', type=int, default=1)
    parser.add_argument('--manifest', type=Path)
    args = parser.parse_args()
    for attempt in range(args.attempts):
        try:
            manifest = json.loads(args.manifest.read_text()) if args.manifest else None
            result = verify(args.base, args.commit, args.data, manifest)
            print(json.dumps(result, indent=2))
            break
        except Exception as error:
            if attempt == args.attempts-1:
                raise
            print(f'Publication not yet verified (attempt {attempt+1}): {error}', flush=True)
            time.sleep(10)
