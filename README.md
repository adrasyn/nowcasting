# nowcasting

Australian GDP nowcast website at **[nowcast.wlsn.me](https://nowcast.wlsn.me)**.

A weekly-updated single-page dashboard showing a nowcast of Australian GDP, the underlying
high-frequency indicators, and the model's track record.

## Two models

The repo runs **two independent nowcasting models** against the same target. Both are emitted
weekly and both appear on the site.

| | **v1** | **v2** |
|---|---|---|
| Location | `pipeline/` | `nowcasting_v2/` |
| Method | Component-based Dynamic Factor Model (3 factors, VAR(1), EM via Kalman filter) | RBA Monthly Activity Indicator → U-MIDAS |
| Lineage | NY Fed Staff Nowcast; Treasury WP *Nowcasting Australia's GDP* | **RBA RDP 2024-04**, Hartigan & Rosewall |
| Panel | 12 monthly indicators | ~31 candidates, cut to ~10 by targeted-predictor selection (Wald test vs GDP, α = 0.10 as per the paper) |
| Outputs | `data/latest.json`, `nowcasts.json`, `indicators.json`, `performance.json` | `data/latest_v2.json`, `vintages_v2.json`, `indicators_v2.json`, `performance_v2.json`, `backcasts.json` |

**v2's estimation code is vendored verbatim from the RBA's own replication files.** Everything in
`nowcasting_v2/R/methods/` is byte-identical to `nowcasting_v2/rba_paper/content/Code/methods/` —
do not edit it. Our adaptations live in the surrounding glue (`build_panel`, `transform_panel`,
`build_mai`, `nowcast_midas`, `emit_v2_json`).

v2 publishes two specifications: a **headline** (`v2_qa_a05`, stricter selection + quarter-average
regression) and a **stress/volatility** model (`v2_umidas_a20`, looser selection + unrestricted
regression). They use *different* selections of series and *different* regressions — not the same
panel with different weights.

## How it works

```
Mondays 02:00 UTC  →  GH Actions runs pipeline/run_complete_nowcast.R   (v1)
                   →  then nowcasting_v2 fetch + emit + indicators      (v2)
                   →  Emits JSON to data/
                   →  Commits to main
                   →  Triggers deploy workflow
                   →  Next.js static build published to GitHub Pages
```

A second cron runs in Mar/Jun/Sep/Dec, gated to fire only the day before an ABS GDP release. The v2
step is `continue-on-error` so a v2 failure cannot stale the v1 headline — it opens a `v2-failure`
issue instead.

The R pipelines and the website communicate only via JSON files under `data/`. Site and pipelines
can be developed, deployed, and moved independently.

## The published nowcast

The homepage figure is the equal-weight average of v2 and v3, the repo's second model
(`nowcasting_v3/`, a Python port of the NY Fed's Bayesian dynamic factor model). The average beats
either model alone: over 181 Monday vintages scored against the ABS's initial estimates, the
combination's MAE is 0.13pp against 0.19 for v2 and 0.17 for v3, because the two models' weekly
errors are close to uncorrelated. At the next-quarter horizon the same holds over 51 Mondays
(0.16pp against 0.24 and 0.19). See `docs/measurements/2026-09-12-v2-v3-weekly-combination.md` for
the full backtest. v2 now nowcasts the next quarter as well as the current one, the same two
horizons v3 already published: RDP 2024-04's U-MIDAS model, run on the next quarter's partial MAI
months and lagging into the completed current quarter, so the evolution chart carries both
horizons for both models.

The weekly flow runs the two models separately and combines their outputs at the end. The v2 job
runs at 02:00 UTC Monday on a Windows runner and writes `data/latest_v2.json`. The v3 job runs at
03:30 UTC, produces the nowcast and its track record, then runs `nowcasting_v3/tools/emit_combination.py`,
which pairs v3's fresh run with v2's latest run for the same quarter (at most a week old) and writes
`data/latest_combo.json`, `data/nowcast_history_combo.json` and `data/performance_combo.json` in
v3's schemas. The payload checker runs against the combination payload the same way it does against
v3's own. If v3 refuses to publish, the combination shows v3's refusal rather than half an average;
if v2's run is missing that week, last week's v2 run is carried for up to 7 days and the payload
records how old it is (`components.v2.stale_days`).

The published bands are empirical quantiles of the combination's own backtest errors, calculated
separately for the current and next-quarter horizons and stored in `pipeline/seed/ci_params_combo.json`.
They are refreshed by `nowcasting_v3/tools/combination_backtest.py`, not read off either model's own
interval.

## Local development

```bash
# Site (Next.js 15, Tailwind v4, Recharts)
npm install
npm run dev            # localhost:3000, hot-reload
npm run build          # static export to out/
npm run test           # unit tests (vitest)
npm run test:e2e       # Playwright smoke test

# v1 pipeline (R, pinned via renv)
cd pipeline
Rscript -e 'renv::restore()'   # one-off: install pinned packages
Rscript run_complete_nowcast.R # fetches data, estimates DFM, emits JSON

# v2 (run from nowcasting_v2/)
Rscript R/fetch/fetch_rba_panel.R
Rscript R/fetch/fetch_abs_panel.R
Rscript R/fetch_rt_gdp.R
Rscript R/emit_v2_json.R
python gen_indicators_v2.py
python gen_performance_v2.py
```

> **macOS note.** `R/_setup.R` contains only Windows library paths, so on macOS it silently no-ops
> and falls back to the system library. CI runs `windows-latest`, so this is not a production
> fault — but locally you must install the packages yourself. The renv lockfile pins R 4.5.1;
> `renv::restore()` fails against a newer local R, so install current CRAN binaries instead and
> never snapshot.

## Repository layout

```
nowcasting/
├── src/                          # Next.js app (pages, components, data loader)
├── data/                         # JSON artifacts (committed weekly by CI)
│   ├── latest.json  nowcasts.json  indicators.json  performance.json   # v1
│   ├── latest_v2.json  vintages_v2.json  indicators_v2.json            # v2
│   ├── performance_v2.json  backcasts.json                             # v2 track record
│   └── gdp.json                                                        # ABS actuals
├── pipeline/                     # v1 R pipeline + shared CI-band helpers
│   ├── run_complete_nowcast.R    # entry point (n_factors = 3, VAR(1))
│   ├── 03*.R 04*.R 05*.R 06*.R 08*.R   # ingest → calendar → estimate → nowcast → vintages
│   ├── ci_bands.R                # interval construction, shared with v2
│   ├── seed/ci_params*.json      # calibrated interval parameters
│   └── renv.lock                 # pinned R packages (R 4.5.1)
├── nowcasting_v2/                # v2 (RBA MAI + U-MIDAS)
│   ├── R/methods/                # VENDORED from the RBA — byte-identical, do not edit
│   ├── R/build_panel.R  transform_panel.R  build_mai.R  nowcast_midas.R
│   ├── R/emit_v2_json.R  backtest_v2.R  recalib_ci_v2.R  compute_ci_params_v2.R
│   ├── R/fetch/                  # ABS/RBA fetchers + NAB/ANZ/Westpac scrapers
│   ├── rba_paper/                # RDP 2024-04 PDF + the RBA's replication bundle
│   ├── seed/panel_info.csv       # candidate panel + transformation codes
│   └── data_raw/                 # per-series CSVs (source of truth for v2)
├── docs/
│   ├── reviews/                  # code / fidelity review reports
│   ├── todo.md                   # backlog
│   └── superpowers/{specs,plans} # historical design docs (point-in-time)
└── .github/workflows/            # nowcast-weekly.yml, deploy.yml
```

## Data sources

**v1 (12 indicators)**

| Group | Count | Source |
|---|---|---|
| Labour | 4 | ABS Labour Force Survey (employment, unemployment rate, participation, hours worked) |
| Consumer | 2 | ABS Household Spending + OECD Consumer Confidence (via FRED) |
| Business | 2 | ABS Building Approvals + NAB Business Confidence |
| External | 4 | ABS International Trade (goods/services × exports/imports) |

**v2 (~31 candidates)** — ABS labour / household spending / trade / approvals, RBA credit and
yield-spread series, and the NAB, ANZ-Roy Morgan and Westpac-Melbourne Institute surveys. The
authoritative list, with each series' transformation code, is `nowcasting_v2/seed/panel_info.csv`.

**Target** for both: ABS National Accounts (5206.0) quarterly chain volume GDP.

**v2 targets the ABS's *initial* estimate of each quarter, not the latest vintage** (since
2026-09). RDP 2024-04 estimates and evaluates on the figure the ABS published on the day, and for
v2 the target turned out to be most of the error: retrained on the initial estimates, bias against
the print falls +0.31 → +0.10pp and MAE 0.33 → 0.17pp, with correlation to the print rising 0.12 →
0.43 — see `docs/measurements/2026-09-11-v2-first-print-ab.md`. `R/fetch_rt_gdp.R` therefore builds
`data_raw/rt_dgdp_qtr.csv` from the first-release series the v3 pipeline maintains
(`nowcasting_v3/data/gdp_first_release.csv`) and appends any quarter newer than that file from the
live ABS fetch. That append matters on one day a quarter: the v2 step runs at 02:00 UTC and the v3
job that writes the new print runs at 03:30, and for a just-printed quarter the latest vintage is
the initial estimate.

Survey data (NAB, ANZ, Westpac) sits behind WAF-protected sites and cannot be fetched from CI. It
is refreshed by a separate local task — see `docs/cowork-weekly-refresh.md`.

## Accuracy

**Do not quote accuracy figures from this README** — they go stale. The live numbers are in
`data/performance.json` (v1) and `data/performance_v2.json` (v2).

Note that `performance_v2.json` is derived from **backtests**, not live nowcasts: the model was
re-run over past quarters using only the data published at the time. `data/backcasts.json` carries
the disclaimer, and the site labels the section accordingly.

Interval parameters are calibrated from pseudo-out-of-sample backtest errors, per within-quarter
information stage, on post-2020 quarters. Regenerate with `nowcasting_v2/R/recalib_ci_v2.R`
followed by `R/compute_ci_params_v2.R`.

## Phase-1 non-goals

This project deliberately does NOT include:
- A backend, database, or authentication
- Real-time data updates (weekly cron is enough)
- State-level nowcasts
- Interactive model drill-downs beyond the indicator detail cards
- Mobile-first design optimisation

If any of these are needed, they're Phase 2.

(Comparison against RBA forecasts *was* originally a non-goal but now ships — see the "Accuracy gap
vs RBA" tile and `pipeline/04a_fetch_somp.R`.)

## License

Personal research project. **Not an official forecast.**
