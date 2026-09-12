# Unrevised (first-release) data for v3: feasibility

Written 9 September 2026 in answer to `unrevised_data_request.md`.
Measurements: `docs/measurements/2026-09-09-gdp-first-release-vs-latest-2019q2-2026q2.csv`.

## Verdict

1. **The claim is correct.** ABS revises quarterly GDP growth upward on average. First print to
   latest vintage: **+0.107pp** per quarter over 1980Q1 to 2022Q2 (n=170, t=2.3) and **+0.107pp**
   over 2019Q2 to 2026Q1 (n=28, t=3.3). Every decade since 1980 is positive (+0.06 to +0.13).
2. **It is a real part of v3's bias, and the bias report understated it.** Rescoring the Plan C
   backtest against first prints moves v3's bias from **+0.12pp (t=1.8) to +0.20pp (t=3.9)**.
   On print day, which is what the site shows, v3 has been running about 0.2pp hot. Revisions
   are roughly 40% of that; the productivity break in the bias report is the other 60%.
3. **The data is feasible, and the hard part is already done.** A first-release GDP growth series
   from 1959Q4 to 2022Q2 is already in the repo
   (`nowcasting_v2/rba_paper/content/Data/rt_dgdp_qtr.csv`, RBA RDP 2024-04). It matches the ABS
   vintage spreadsheets on all 13 overlapping quarters. This session extended it to 2026Q2 from
   the 29 archived releases. No archive scraping is needed for the GDP target.
4. **Recommendation:** score against first prints and apply a revision-aware correction to the
   headline. Do not retrain v3 on first-print GDP as the first move, and do not build real-time
   vintages of the panel. Details in "Options".

## 1. Are ABS GDP revisions upward?

Sources: RBA Bulletin March 2013 (Bishop, Gill and Lancaster), the three ABS historical-revision
articles, and the vintage spreadsheets downloaded here.

| Sample (first print vs Jun-2026 vintage) | n | mean revision | mean abs revision | up / down |
|---|---|---|---|---|
| 1980Q1 to 2022Q2 (RBA file) | 170 | +0.107 | 0.45 | 101 / 69 |
| 1980s | 40 | +0.094 | 0.71 | 19 / 21 |
| 1990s | 40 | +0.124 | 0.58 | 23 / 17 |
| 2000s | 40 | +0.124 | 0.37 | 25 / 15 |
| 2010s | 40 | +0.064 | 0.19 | 24 / 16 |
| 2019Q2 to 2026Q1 (ABS vintages) | 28 | +0.107 | 0.16 | 18 / 5 |
| v3 window 2023Q1 to 2026Q1 | 13 | +0.065 | 0.15 | 7 / 3 |

Notes:
- RBA 2013 found +0.1pp over 1998 to 2008, significant at 10%. That sample is now +0.134 against
  the current vintage.
- Most of the revision arrives at the **next** quarterly release: first to second estimate is
  +0.064 (2019 to 2026). The annual benchmark in the September release adds the rest.
- The ABS historical-revision articles confirm the direction for recent years: 2021-22 +0.73pp
  (2023 article), 2022-23 +0.42pp (2024), 2022-23 +0.2 and 2023-24 +0.1 (2025). Drivers are
  late-arriving data on household consumption, digital imports and rent.
- Revisions were smaller in the 2010s than in earlier decades, and are noisy (sd 0.17 recent,
  0.6 historic). The mean is stable; individual quarters are not.

## 2. What it does to v3's bias

The Plan C backtest (`nowcasting_v3/tools/plan_c_backtest.py`) scores against the 2026-08-26
vintage. `data/backtest_v3.json` and `data/performance_v3.json` both use revised actuals. The
bias report's Mechanism 4 said revisions were "small" and "run the other way": they make the
measured error smaller, so the live bias is larger. That is right in sign but was never
measured. Measured:

| Scored against | v3 bias | v3 MAE | t | v2 bias | v2 MAE |
|---|---|---|---|---|---|
| latest vintage (as shipped) | +0.119 | 0.242 | 1.8 | +0.276 | 0.337 |
| first print | **+0.196** | 0.235 | **3.9** | +0.354 | 0.378 |

(14 target quarters 2022Q4 to 2026Q1, quarter-average nowcasts. Per-vintage rows: +0.123 vs
+0.196; the first-print bias is flat across horizons: 1m +0.22, 2m +0.17, 3m +0.20.)

So the honest number for the live product is +0.2pp, not +0.12, and it clears a t-test easily.
The extra +0.08 is the mean revision in the window. It is not caused by the model; it is caused by
training on a target that is systematically higher than the number the site is judged against.

## 3. Where unrevised data can come from

**GDP (target)**
- 1959Q4 to 2022Q2: `nowcasting_v2/rba_paper/content/Data/rt_dgdp_qtr.csv` (first-release q/q
  growth, Koenig-Dolmas-Piger convention: growth from the first vintage that contains quarter t).
  Verified against the ABS vintages on 2019Q2 to 2022Q2.
- 2019Q2 onward: one spreadsheet per release at a fixed URL,
  `.../australian-national-accounts-national-income-expenditure-and-product/{mon-yyyy}/5206001_Key_Aggregates.xlsx`
  (`.xls` before Dec 2021, filename case varies). All 29 downloaded and parsed this session.
- Jun 2006 to Mar 2019: archived. The listing page and the per-release Downloads page
  (`https://www.abs.gov.au/AUSSTATS/abs@.nsf/DetailsPage/5206.0{Mon YYYY}?OpenDocument`) serve
  their links only with a browser `User-Agent` header. With one they are scriptable: the
  Downloads page holds a `log?openagent&5206001_key_aggregates.xls&...` link that redirects to
  `ausstats.abs.gov.au` and returns the file. Not needed for GDP because the RBA file covers it.

**Tools**
- R `readabs::read_abs(release_date=)` only rewrites `latest-release` to `mon-yyyy` in the URL.
  It works from mid-2019 and fails before that, as the docs say. `read_abs_url()` takes any URL.
- Python `readabs` 0.2.6 (what v3 uses, `nowcasting_v3/nyfed/au/fetch_abs.py`) has no release
  argument, but `read_abs_series(cat, series_id, url=<vintage landing page>)` works: tested on
  the Mar 2024 page, returns 2024Q1 at 610298 (q/q +0.127, the first print). The `.xls` releases
  (Jun 2019 to Sep 2021) need `xlrd` in the venv; it is not installed.
- ABS Data API (SDMX) and Indicator API serve the latest vintage only. No version, asOf or
  release parameter exists. Not useful here.

**Panel series (10 of 14 are ABS)**
- Measured for labour force (6202.0), 43 releases Jan 2023 to Jul 2026, first print vs the Jul 2026
  vintage (`docs/measurements/2026-09-09-labour-force-first-release-vs-latest-2023-2026.csv`):

  | Series | mean revision | t | up / down |
  |---|---|---|---|
  | Employment growth, q/q (quarter averages, n=14) | -0.070pp | -1.9 | 4 / 10 |
  | Employment growth, m/m (n=42) | -0.033pp | -1.9 | 14 / 28 |
  | Unemployment rate, pp (n=42) | +0.016 | +3.1 | 28 / 14 |

  First print to next month is zero for employment growth (-0.002). The revision arrives with the
  annual seasonal reanalysis and the population rebenchmark, so part of it is a benchmark shift.
  The sign matters: the model learns revised employment (weaker) to revised GDP (stronger). Live,
  it sees first-print employment, which has run about 0.07pp/qtr stronger than what it trained on.
  That adds to the upward bias, and the pseudo-real-time backtest cannot see it. Rough size on
  the nowcast: a few hundredths of a point, after the GDP loading dilutes it. Trade, building
  approvals and household spending are not measured; household spending is the one to check
  next, since the ABS benchmarks it to quarterly consumption, which the 2024 article revised up.

- Vintage spreadsheets exist at the same URL pattern for labour force (6202.0), trade (5368.0),
  building approvals (8731.0) and the household spending indicator (5682.0), tested for 2023 and
  2025 releases. The monthly CPI (6401.0) does not follow the pattern and its history is split
  across a ceased catalogue.
- A true real-time panel for the v3 window needs about 10 series x 41 monthly as-ofs of
  downloads, plus a per-series vintage store and a change to `build.py` so `Vintage.as_of`
  selects values by release rather than truncating dates. It is a data-engineering task, not a
  research one, and it does not address bias (see below).

## 4. Options, ranked

**A. Score against first prints (do this).** Add a `first_release_qoq` column to the backtest
and the track record, and publish both actuals. Cost: an afternoon. It needs only the CSV in
`docs/measurements` plus the RBA file. Effect: the site stops flattering itself by 0.08pp, and the
bias correction in the bias report's section 4.1 then targets the right number.

**B. Revision-aware headline (do this with A).** Report "expected first print" as the model
nowcast minus a rolling mean revision (about 0.07 to 0.11pp, positive in every decade since
1980). This is the section 4.1 bias correction fitted against first prints. It removes the
revision term without touching the model. Keep the raw nowcast as "expected final GDP".

**C. Retrain v3 on a first-release target (test, do not assume).** Build a chain index from the
first-release growth series (RBA file + extension), feed it as `gdp` in place of `A2304402X`,
and re-run Plan C as an A/B. In expectation it removes the same 0.08pp as B, but it also changes
the factor loadings: first prints are noisier than revised data (mean abs revision 0.45 pre-2020),
so the GDP loading weakens. The NY Fed and most of the literature train on the latest vintage and
evaluate against the advance estimate; they do not do C. Costs: new fetch path, fixture
regeneration, re-measuring the three seed constants (memory: panel-dependent), one full backtest
(hours, not days). Worth one experiment after A and B are in.

**D. Real-time panel vintages (defer, but now with a reason to return).** Revisions to the
predictors change the backtest's honesty about dispersion, and they change its bias only if the
predictor revisions are themselves biased. For employment they are (section 3): first prints run
stronger than the revised series, in the direction that adds to the bias. The effect is second
order next to the target, so it stays behind A to C. The v3 window can be served entirely from
the 2019+ URL pattern. Note the labour force filename changed to `62020001.xlsx` from Apr 2026.

## 5. What this does not fix

The +0.12pp that remains after first-print scoring is the stale labour-to-GDP anchor in the bias
report. Unrevised data cannot move it. Options A to C change what the model is judged against
and where its intercept sits; they do not teach it that output per hour has stopped growing.

## 6. Inputs for an implementation plan

- First-release growth 1959Q4 to 2022Q2: `nowcasting_v2/rba_paper/content/Data/rt_dgdp_qtr.csv`.
- First-release growth 2019Q2 to 2026Q2 with revisions:
  `docs/measurements/2026-09-09-gdp-first-release-vs-latest-2019q2-2026q2.csv` (unrounded, from
  `A2304402X` levels in each release).
- Backtest scorer to extend: `nowcasting_v3/tools/plan_c_backtest.py:69` (actual from the
  recorded vintage) and `nowcasting_v3/tools/emit_backtest_json.py`.
- Track record: `data/performance_v3.json` uses revised actuals (fixed in #36 to grow; the actual
  source is still the latest vintage).
- Trap: `nowcasting_v2/data_raw/rt_dgdp_qtr.csv` is named "rt" but is the latest vintage
  (`nowcasting_v2/R/fetch_rt_gdp.R:5`). Use the `rba_paper` file.
- Trap: the Plan C design spec section 6 said the target was first-print GDP; the implementation
  scores on the revised vintage. The spec and code disagree.
- New quarter each release: first print = the q/q growth in the release for that quarter, which
  is one `read_abs_series(..., url=<that release page>)` call, or the weekly job can store the
  print on the day it lands.

See `docs/measurements/2026-09-12-v2-v3-weekly-combination.md` for what scoring both models
against these initial estimates enabled: an equal-weight combination that beats either model
alone.
