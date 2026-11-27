"""Generate /simple after Next's export, from the same committed JSON as /.

No model execution and no browser code. Only files inside the requested output
folder are written; normal pages and data artifacts are never modified.
"""
import argparse
import datetime as dt
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import html
import json
import os
from pathlib import Path
import re
import subprocess
from charts import build_charts


def esc(value):
    return html.escape(str(value))


def num(value):
    if value is None:
        return '-'
    value = format(Decimal(str(value)), 'f')
    return value.rstrip('0').rstrip('.') if '.' in value else value


def fixed(value):
    # JS toFixed(2), including binary-exact half ties; keep displayed figures in
    # agreement with formatPct on the main page.
    result = Decimal.from_float(float(value)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
    return format(result, '.2f')


def date(value):
    if not value:
        return '-'
    value = dt.date.fromisoformat(value[:10])
    return f'{value.day} {value:%b %Y}'


def quarter(value):
    year, q = value.split()
    return f'{q} {year}'


def cell(value):
    value = str(value)
    return f'<nobr>{value}</nobr>' if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value) else value


def table(headers, rows, name):
    def wrap(value, index, tag):
        align = 'left' if index == 0 else 'right'
        return f'<{tag} align="{align}"><tt>{value}</tt></{tag}>'
    return (f'<table cellpadding="2" cellspacing="0" id="{name}"><tr>'
            + ''.join(wrap(esc(h).replace('\n', '<br>'), j, 'th') for j, h in enumerate(headers))
            + '</tr>' + ''.join('<tr>' + ''.join(wrap(cell(v), j, 'td') for j, v in enumerate(row))
                               + '</tr>' for row in rows) + '</table>')


def year_on_year(horizon, level, observations):
    """Same implied-level ratio as the live components, keyed by target quarter."""
    year, q = horizon['quarter'].split()
    base = next((r['value'] for r in observations if r['quarter'] == f'{int(year)-1} {q}'), None)
    return (level / base - 1) * 100 if level is not None and base else None


def methodology(latest, errors, indicators, combo):
    bc = latest.get('bias_correction', {})
    correction = (f": {fixed(bc['pp'])}pp currently" if bc.get('pp') is not None else '')
    panel = latest.get('panel', {}).get('n_series', 14)
    current = next((h for h in latest.get('horizons', []) if h['kind'] == 'nowcast'), None)
    forecast = next((h for h in latest.get('horizons', []) if h['kind'] == 'forecast'), None)
    cur = quarter(current['quarter']) if current else 'The current-quarter estimate'
    nxt = quarter(forecast['quarter']) if forecast else 'The next-quarter estimate'
    v3_only = forecast and forecast.get('components', {}).get('v2') is None
    combination = ('Equal weights on the published v2 and v3 point estimates for the same quarter and horizon. '
                   'A recent v2 estimate can be carried forward for up to 7 days. '
                   + (f'{nxt} currently uses v3 alone because v2 has no estimate for that quarter. ' if v3_only else '')
                   + f'The {len(indicators)} displayed indicator series are the union of both panels.' if combo else
                   'This page currently uses v3 alone because no combination payload is available.')
    if combo:
        uncertainty = (f"{cur}'s 68% and 95% bands are quantiles of the combination's absolute backtest errors, "
                       'centred on its estimate. Calibration uses weekly vintages for targets from Q4 2022 onwards. ')
        if forecast and not v3_only:
            uncertainty += f'{nxt} also uses empirical error bands calibrated for its own horizon. '
        elif forecast:
            uncertainty += (f"{nxt}'s bands instead contain 68% and 95% of v3's posterior draws, shifted by "
                            'the same bias correction as its point estimate; they are not calibrated from past errors. ')
    else:
        uncertainty = ("The 68% and 95% bands contain the corresponding share of v3's posterior draws, shifted "
                       'by the same bias correction as its point estimate; they are not calibrated from past errors. ')
    live = sum(bool(r.get('is_live')) for r in errors)
    return (f'<a name="methodology"></a><h2>Methodology</h2>'
            '<p><b>Target.</b> Weekly estimates of Australian real GDP growth, quarter on quarter and seasonally '
            'adjusted. Both models target the ABS first release; the record above is scored against that release, '
            'not later revisions.</p><p><b>v3.</b> An Australian adaptation of the '
            '<a href="https://www.newyorkfed.org/research/policy/nowcast">New York Fed Staff Nowcast 2.0</a>: '
            f'a Bayesian dynamic factor model using {panel} monthly and quarterly series. Five factors represent '
            'global, soft, nominal and labour activity, plus COVID (March 2020 to December 2021). Changing volatility '
            'and outlier states accommodate large shocks. The estimate subtracts v3\'s average final-nowcast error '
            f"over the last {bc.get('window_quarters', 8)} printed quarters{correction}; at least "
            f"{bc.get('min_quarters', 4)} quarters are required.</p>"
            '<p><b>v2.</b> Follows <a href="https://www.rba.gov.au/publications/rdp/2024/2024-04.html">RBA RDP 2024-04</a>. '
            'A dynamic factor model combines monthly inputs into a monthly activity indicator. A quarter-average '
            'mixed-frequency regression (U-MIDAS) maps the available months onto quarterly GDP growth. Inputs are '
            're-selected each quarter by explanatory power. This project uses freely available inputs, so its panel '
            f"differs from the paper's.</p><p><b>Combination.</b> {combination}</p>"
            f'<p><b>Uncertainty.</b> {uncertainty}Neither type is a confidence interval or a guarantee.</p>'
            f'<p><b>Record.</b> {len(errors)-live} backtested quarters and {live} live quarters. The backtests replay '
            'later-vintage panels with publication-date cuts, rather than a complete real-time archive. '
            'Error = nowcast minus ABS first release; pp = percentage points. The GDP observations above are '
            'revised values. Year-on-year growth compares the implied GDP level with the same quarter a year '
            'earlier; the next-quarter rate chains the current nowcast and forecast. Estimates can change as '
            'new data arrive.</p><p><a href="#top">Top</a></p>')


def build_site(data_dir, output, commit=''):
    data_dir, output = Path(data_dir), Path(output)
    fingerprints = {}
    def read(name, default=None):
        p = data_dir / name
        if not p.exists():
            return default
        raw = p.read_bytes()
        fingerprints[name] = hashlib.sha256(raw).hexdigest()
        return json.loads(raw)
    combo = (data_dir / 'latest_combo.json').exists()
    latest = read('latest_combo.json' if combo else 'latest_v3.json', {})
    indicators = read('indicators_combo.json', None)
    if indicators is None:
        indicators = read('indicators_v3.json', {'indicators': []})
    indicators = indicators['indicators']
    perf = read('performance_combo.json', None)
    if perf is None:
        perf = read('performance_v3.json', {'errors': []})
    errors = perf.get('errors', [])
    history = read('nowcast_history_combo.json' if combo else 'nowcast_history_v3.json', {'runs': []}).get('runs', [])
    gdp = read('gdp.json', {'series': []})['series']
    as_of = latest.get('as_of') or latest.get('generated_at', '')[:10]
    output.mkdir(parents=True, exist_ok=True)
    for name in ['index.html', 'nowcast.gif', 'record.gif']:
        (output / name).unlink(missing_ok=True)
    geometry = build_charts(output, latest, errors)
    # Refresh chart URLs only when their bytes change, avoiding a stale GIF
    # when a newer HTML page arrives while the old image is still cached.
    def image_src(name):
        digest = hashlib.sha256((output/name).read_bytes()).hexdigest()[:12]
        return f'/simple/{name}?v={digest}'
    parts = ['<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" '
             'content="width=device-width,initial-scale=1"><title>Australian GDP nowcast</title>'
             f'<meta name="build-commit" content="{esc(commit)}"><link rel="icon" href="data:,">'
             '<body><a name="top"></a><h1>Australian GDP nowcast</h1>'
             f'<p><b>{date(as_of)}</b></p><p><a href="#indicators">Indicators</a> | '
             '<a href="#history">History</a> | <a href="#series">Indicator history</a> | '
             '<a href="#methodology">Methodology</a></p><h2>Real GDP growth</h2>'
             '<p>Growth (%), seasonally adjusted. Bands: q/q.</p>']
    horizons = latest.get('horizons', []) if latest.get('status') == 'ok' else []
    a = next((h for h in horizons if h['kind'] == 'nowcast'), None)
    b = next((h for h in horizons if h['kind'] == 'forecast'), None)
    yoy = []
    if a:
        shown = [a] + ([b] if b else [])
        level = a.get('gdp_chain_volume_millions')
        levels = [level] + ([level * (1 + b['qoq_growth_pct']/100) if level is not None else None] if b else [])
        # Match the live next-quarter component: a zero-month trend anchor is not
        # published as an observed-data forecast. Retain its quarter and coverage.
        has_data = [h is a or h.get('months_with_data') != 0 for h in shown]
        yoy = [year_on_year(h, lv, gdp) if ready else None for h, lv, ready in zip(shown, levels, has_data)]
        pct = lambda x: fixed(x)+'%' if x is not None else '-'
        rows = [['Growth q/q'] + [pct(h['qoq_growth_pct']) if ready else 'No data' for h, ready in zip(shown, has_data)], ['Growth y/y'] + [pct(v) for v in yoy]]
        for n in [68, 95]:
            rows.append([f'{n}% band'] + [fixed(h[f'ci_{n}_low'])+' to '+fixed(h[f'ci_{n}_high']) if ready else '-' for h, ready in zip(shown, has_data)])
        rows += [['Complete months'] + [
            f"{len(set(h['complete_months']))}/3" if isinstance(h.get('complete_months'), list)
            else '—' for h in shown],
                 ['ABS release'] + [date(h.get('release_date') or (latest.get('next_gdp_release_date') if h is a else None)) for h in shown]]
        parts.append(table([''] + [quarter(h['quarter'])+'\n'+h['kind'] for h in shown], rows, 'estimates'))
        if b and b.get('months_with_data') != 0:
            parts.append(f"<p>{b['quarter'].split()[1]} y/y uses {a['quarter'].split()[1]}'s nowcast.</p>")
    else:
        parts.append('<p>No nowcast published. '+esc(latest.get('refusal_detail') or latest.get('refusal_reason') or 'Estimate unavailable.')+'</p>')
    if 'nowcast.gif' in geometry:
        release = geometry['nowcast.gif']['date_axis']['release_date']
        first, last = geometry['nowcast.gif']['source_points'][0], geometry['nowcast.gif']['source_points'][-1]
        parts.append(f'<h2>{a["quarter"].split()[1]} estimate history</h2><p><img src="{image_src("nowcast.gif")}" '
                     f'width="288" height="144" alt="{esc(a["quarter"])} nowcast: {fixed(first['qoq_growth_pct'])}% on '
                     f'{date(first["run_date"])} to {fixed(last['qoq_growth_pct'])}% on {date(last["run_date"])}; '
                     f'GDP release {date(release)}."></p><p>Solid: nowcast. Dashed: 68% '
                     + ('error band.' if combo else 'probability band.') + '</p>')
    if 'record.gif' in geometry:
        parts.append(f'<h2>Nowcast and actual GDP</h2><p><img src="{image_src("record.gif")}" width="288" height="144" '
                     'alt="Quarterly GDP growth, final nowcast versus ABS first release. Values below."></p>'
                     '<p>Solid: ABS first release. Dashed: final nowcast.</p>')
    parts.append('<a name="indicators"></a><h2>Indicators</h2>')
    parts.append(table(['Indicator / unit', 'Latest', 'Period'], [
        (f'<a href="#i{j}">{esc(i["name"])}</a><br>{esc(i["unit"])}',
         f'{i["series"][-1]["value"]:.6g}' if i['series'] else '-',
         esc(i['series'][-1]['date'])+(' (prov.)' if i['series'][-1].get('provisional') else '') if i['series'] else '-')
        for j, i in enumerate(indicators)], 'latest-indicators'))
    parts.append('<p><a href="#top">Top</a></p><a name="history"></a><h2>History</h2>'
                 '<h3>Final nowcast and ABS first release</h3><p>Quarterly growth (%).</p>')
    parts.append(table(['Quarter', 'Nowcast %', 'ABS %', 'Error pp'], [
        (esc(i['target_quarter']), num(i['qoq_nowcast_pct']), num(i['qoq_actual_pct']), num(i['qoq_error_pp'])) for i in errors], 'track-record'))
    parts.append('<h3>Weekly nowcasts</h3><p>Growth (%); 68% and 95% '
                 + ('historical error bands.' if combo else 'model probability bands.') + '</p>')
    for q in dict.fromkeys(i['target_quarter'] for i in history):
        parts.append('<h4>'+esc(q)+'</h4>')
        parts.append(table(['Date', 'Growth %', '68% band', '95% band'], [
            (i['run_date'], num(i['qoq_growth_pct']), num(i['ci_68_low'])+' to '+num(i['ci_68_high']),
             num(i['ci_95_low'])+' to '+num(i['ci_95_high'])) for i in history if i['target_quarter'] == q], 'weekly-'+q.replace(' ', '')))
    parts.append('<h3>GDP observations</h3><p>Chain-volume $m. Growth: quarterly and annual (%). '
                 'Revised observations; track record above uses first releases. - = unavailable.</p>')
    parts.append(table(['Quarter', '$m', 'Quarter %', 'Year %'], [
        (esc(i['quarter']), num(i['value']), num(i['qoq_pct']), num(i['yoy_pct'])) for i in gdp], 'gdp-history'))
    observations = sum(len(i['series']) for i in indicators)
    parts.append('<p><a href="#top">Top</a></p><a name="series"></a><h2>Indicator history</h2>'
                 f'<p>All {len(indicators)} series; {observations:,} observations. Values, units and signs as supplied to the models.</p>')
    for j, i in enumerate(indicators):
        parts.append(f'<a name="i{j}"></a><h3>{esc(i["name"])}</h3><p>{esc(i["unit"])}. Source: {esc(i["source"])}.</p>')
        if i.get('last_release_date'):
            parts.append('<p>Released '+esc(i['last_release_date'])+('. Next (estimate): '+esc(i['next_release_estimate']) if i.get('next_release_estimate') else '')+'.</p>')
        if i.get('source_checked_at'):
            parts.append('<p>Source checked '+esc(date(i['source_checked_at']))+'. This is a retrieval date, not an observation or release date.</p>')
        if i.get('data_note'):
            parts.append('<p>'+esc(i['data_note'])+'</p>')
        provisional = [r['date'] for r in i['series'] if r.get('provisional')]
        if provisional:
            parts.append('<p>Provisional periods: '+esc(', '.join(provisional))+'.</p>')
        parts.append('<pre>Period   Value\n'+''.join(esc(r['date'])+'  '+num(r['value'])+'\n' for r in i['series'])+'</pre><p><a href="#indicators">Indicators</a></p>')
    parts.append(methodology(latest, errors, indicators, combo))
    parts.append('<hr><p><a href="/">Main nowcast</a> | <a href="https://home.wlsn.me/">James Wilson</a></p></body></html>\n')
    (output/'index.html').write_text(''.join(parts))
    return {'as_of': as_of, 'commit': commit, 'combo': combo, 'source_files': fingerprints,
            'series': len(indicators), 'observations': observations, 'gdp_rows': len(gdp),
            'weekly_rows': len(history), 'track_record_rows': len(errors), 'yoy': yoy, 'charts': geometry}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, default=Path('data'))
    parser.add_argument('--output', type=Path, default=Path('out/simple'))
    args = parser.parse_args()
    commit = os.environ.get('GITHUB_SHA') or subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    report = build_site(args.data_dir, args.output, commit)
    print(f"Generated {args.output}: {report['as_of']}, {report['series']} series, {report['observations']} observations")
