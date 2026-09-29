# Nowcast pipeline (v1)

R pipeline that produces the **v1** JSON artifacts consumed by the website at
[nowcast.wlsn.me](https://nowcast.wlsn.me).

> **This is the legacy v1 model.** `nowcasting_v2/` implements RBA RDP 2024-04
> (Monthly Activity Indicator → U-MIDAS), while `nowcasting_v3/` ports the NY Fed's
> Bayesian dynamic factor model. The homepage publishes a v2/v3 combination; v1 still
> runs in the weekly v1/v2 workflow and supplies a fallback for `/v2`. See the
> [root README](../README.md). `ci_bands.R` and `seed/ci_params*.json` here are shared with v2.

## Run locally

From the repo root:

```bash
Rscript -e 'setwd("pipeline"); source("run_complete_nowcast.R")'
```

Or from inside `pipeline/`:

```bash
Rscript run_complete_nowcast.R
```

Outputs go to `../data/` (the repo-level `data/` directory consumed by Next.js).

## Dependencies

Pinned via `renv` (Task 13). Run `renv::restore()` once to install.

## Cache

Raw ABS/FRED data is cached under `.cache/` (gitignored). Safe to delete — will be refetched on next run.

## Entry point

`run_complete_nowcast.R` is the canonical entry point. It orchestrates:

1. Data fetch (ABS via `readabs`, FRED via CSV, NAB from `nab_business_confidence_raw.csv`)
2. Master dataset assembly
3. Vintage accuracy check (compares prior nowcasts against newly-released actuals)
4. DFM estimation (3-factor EM algorithm)
5. Nowcast generation + vintage snapshot save
6. JSON emission for the website (added in Task 14)

## Files

- `run_complete_nowcast.R` — top-level orchestrator
- `03_data_ingestion.R` — ABS fetcher via `readabs`
- `03b_fetch_fred_data.R` — FRED fetcher for OECD Consumer Confidence
- `03c_nab_business_confidence.R` — NAB CSV reader + freshness check
- `04_release_calendar.R` — ABS release-schedule metadata
- `05_estimate_model.R` — DFM estimation via the `nowcasting` package
- `06_generate_nowcast.R` — Kalman filter → nowcast
- `08_vintage_tracking.R` — vintage snapshot persistence + accuracy log
- `04_emit_json.R` — writes `../data/latest.json`, `nowcasts.json`, `indicators.json`, `performance.json`
- `04a_fetch_somp.R` — RBA Statement on Monetary Policy forecasts (the "Accuracy gap vs RBA" tile)
- `04b_release_calendar_fetch.R` — scrapes real ABS release dates (v2's indicator grid reuses these)
- `09_backtest_model.R`, `run_backtest_sweep.R` — pseudo-out-of-sample evaluation
- `ci_bands.R` — interval construction. **Shared with v2**; understands both the flat v1 params
  and v2's per-information-stage schema (`ci_params_for_stage()`).
- `compute_ci_params.R` — flat interval params for v1. v2 uses
  `nowcasting_v2/R/compute_ci_params_v2.R` instead, which calibrates per stage.
- `seed/component_metadata.rds` — indicator/component definitions (checked into the repo)
- `seed/ci_params.json` — v1 interval params; `seed/ci_params_v2*.json` — v2's (per stage)
- `nab_business_confidence_raw.csv` — monthly NAB index values, synced from v2's `data_raw/nab_conf.csv` by `03d_sync_nab_from_v2.R` in the weekly workflow
- `deploy_nowcast.R`, `reconstruct_q1_2026.R`, `recover_reconstruct.R`, `update_trans_codes.R` —
  one-off / operational scripts, not part of the weekly run

## Legacy code removed during migration

`install_nowcasting.R`, `run_backtest.R`, `run_nowcast.R`, `01_setup_nowcast.R`, the `archive/` directory, and assorted `test_*.R` / `fix_*.R` / `find_*.R` session scripts were dropped when this pipeline was migrated from `james-mess/code/project_nowcast/`. Their full history remains in the `james-mess` repository if ever needed.
