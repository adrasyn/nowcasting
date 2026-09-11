# Combination Nowcast Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The homepage publishes the equal-weight average of v2 and v3, with a full nowcast-evolution path for both the current quarter and the next quarter, the way v3 shows it today.

**Architecture:** v2 gains a next-quarter horizon (U-MIDAS on the next quarter's partial months, lagging into the complete current quarter) so it publishes the same two horizons as v3. Both models' weekly backtests record both horizons; a combination backtest scores the average against the ABS's initial estimates and calibrates empirical bands per horizon. A combination emitter runs at the end of the weekly v3 job, averages the two models' published payloads, and writes combination payloads in the v3 schemas; the homepage loader prefers them. Copy: the methodology section only.

**Tech Stack:** R (midasr, v2), Python 3.13 (v3, pandas/numpy), Next.js + vitest + Playwright (site), GitHub Actions.

**Spec:** the owner's instructions in this session (2026-09-12): "retarget v2 and do the weekly vintage combo backtest"; "i want nothing to change except the methodology section"; "wire up the v2 model so it behaves like the v3 model ie generating nowcasts for the next quarter once next quarter data starts coming in, before the current quarter is completed"; the measurement `docs/measurements/2026-09-12-v2-v3-weekly-combination.md` and the preview branch `preview/combination` (commit 4cdfd65: draft emitter `nowcasting_v3/tools/emit_combination.py`, loader fallback, methodology copy).

## Global Constraints

- User-facing wording: "initial estimate" for the ABS's first-published figure. Never "first print" on the site.
- No em-dashes in new user-facing copy; the methodology copy in commit 4cdfd65 is the approved text and is kept.
- v2's published current-quarter nowcast, its /v2 page, and its track record must be unchanged by this work (bit-identical `qoq_growth_pct` for the headline at any as-of). Only new fields and new rows are added to v2 payloads.
- Both models' backtests are pseudo-real-time: v2 uses `.truncate_panel`/`.truncate_gdp` (60-day GDP lag); v3 uses its vintage store with per-series publication lags. Do not invent a release calendar.
- Every scored figure is scored against `nowcasting_v3/data/gdp_first_release.csv` (the initial estimate). Year-ended figures stay on the latest vintage (`data/gdp.json`), as v3's track record does.
- The combination for a Monday and quarter exists only where BOTH models have a figure for that quarter at that Monday (v2's most recent run for that quarter at or before the Monday counts, at most 7 days old).
- Commits end with:
  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01SyVuNnQdjveYgZLXQj4Szt
  ```
- Never push. Never run `git clean`. The nowcasting_v3 full pytest suite takes 30 to 40 minutes; run only the test files a task names, plus `tests/test_check_payload.py` when the payload changes.
- Local R: readabs is not installed, so any live fetch path falls back. `Rscript` from `nowcasting_v2/`. Long R runs go under `caffeinate -i`, in the foreground, one at a time.
- Python for v3 tools: `nowcasting_v3/.venv/bin/python`, run from `nowcasting_v3/`.

---

## Background an implementer needs

**Quarters.** "Current quarter" = the earliest quarter the ABS has not printed (v2's `target_q`, v3's `t_now[0]`). "Next quarter" = the one after it. The ABS prints a quarter about 9 weeks after it ends (e.g. Q2 2026 printed 2 September 2026), so for roughly the first two months of a quarter the current quarter is the PREVIOUS calendar quarter, and the calendar quarter in progress is the next quarter.

**v3 today** (`nowcasting_v3/tools/run_au_nowcast.py`): `pad_to_next_quarter(panel)` extends the panel so `target_periods` returns two columns; horizon 0 is written with `kind: "nowcast"`, horizon 1 with `kind: "forecast"`. Both are recorded in `data/nowcast_history_v3.json` keyed `(run_date, target_quarter)`, except that a forecast with `months_with_data == 0` is not recorded. The site's `V3Evolution` draws both quarters, `V3NextQuarter` shows the forecast card.

**v2 today** (`nowcasting_v2/R/nowcast_midas.R`): target = quarter after the last released GDP; `jt` = MAI months inside it; complete quarter uses QA-UMIDAS, partial uses U-MIDAS with `mls(x_est, k = (3 - jt):5, m = 3)`; newdata is `c(x_new, NA pad)` appended after the estimation sample, whose last months are the quarter before the target. No lagged GDP regressor, so a next-quarter figure needs no unpublished GDP.

**v3 weekly backtest**: `nowcasting_v3/tools/plan_c_backtest.py` is monthly (`freq="MS"`); the weekly variant that produced `docs/measurements/2026-09-12-v3-weekly-vintage-first-print-seed{4,13,19}.csv` is a copy with `freq="W-MON"`, window `2023-01-02..2026-08-31`, one seed per process, parked at `.superpowers/sdd/v3-weekly-backtest/v3_weekly_backtest.py`. It does NOT pad, so `forecast_next_qq` is populated in only 8 of 189 rows.

**Combination draft** (`nowcasting_v3/tools/emit_combination.py` on branch `preview/combination`): reads `latest_v2.json`, `latest_v3.json`, `nowcast_history_v3.json`, `gdp.json`, the combination backtest CSV, the RBA SoMP CSV, and writes `latest_combo.json`, `nowcast_history_combo.json`, `performance_combo.json` in v3's schemas. It handles one horizon. Task 8 productionises it.

---

### Task 1: v2 next-quarter horizon in `nowcast_midas`

**Files:**
- Modify: `nowcasting_v2/R/nowcast_midas.R`
- Test: `nowcasting_v2/tests/test_nowcast_midas.R` (append a block)

**Interfaces:**
- Produces: `nowcast_midas(mai, gdp_growth, as_of = NULL, prev_level = NULL, model = c("qa","umidas"), qa_lag = 0L:1L, horizon = c("current","next"))`. Return list gains `horizon` ("current"|"next") and `current_quarter` (the "YYYY Qn" label of the current quarter; equals `target_quarter` when horizon is "current"). For `horizon = "next"`, `target_quarter` is the next quarter, `n_months_in_quarter` is its MAI month count `jt_next` (0..3), `model` is "UMIDAS-full" for `jt_next < 3` and "QA-UMIDAS" at 3 (same dispatch rule as today).
- Errors: `horizon = "next"` stops with message starting `nowcast_midas(): no MAI month beyond the current quarter` when the MAI has no month after `target_q` (the caller treats this as "no next-quarter nowcast yet"). It also stops if the current quarter's three MAI months are not all present (message starting `nowcast_midas(): current quarter incomplete`), which cannot happen with a contiguous MAI but is asserted.

- [ ] **Step 1: Write the failing test.** Append to `nowcasting_v2/tests/test_nowcast_midas.R` (it sources `R/_setup.R` and `R/nowcast_midas.R`; add `source(file.path(here, "backtest_v2.R"))` for `.truncate_gdp`):

```r
# ---- next-quarter horizon (2026-09-12) ------------------------------------
# as_of 2019-08-15 with the 60-day GDP lag: 2019 Q2 GDP prints ~29 Aug, so the
# CURRENT quarter is 2019 Q2 (complete, jt = 3) and the NEXT is 2019 Q3 with
# July (and possibly August) MAI months.
AS_OF_N <- as.Date("2019-08-15")
gdp_n <- .truncate_gdp(transform(gdp, date = as.Date(date)), AS_OF_N, gdp_lag = 60L)
cur <- nowcast_midas(mai, gdp_n, as_of = AS_OF_N, prev_level = PREV_LEVEL, horizon = "current")
nxt <- nowcast_midas(mai, gdp_n, as_of = AS_OF_N, prev_level = PREV_LEVEL, horizon = "next")
nxt2 <- nowcast_midas(mai, gdp_n, as_of = AS_OF_N, prev_level = PREV_LEVEL, horizon = "next")
check(identical(cur$target_quarter, "2019 Q2") && cur$n_months_in_quarter == 3L,
      "current horizon at 2019-08-15 is the complete 2019 Q2")
check(identical(cur$horizon, "current") && identical(cur$current_quarter, "2019 Q2"),
      "current horizon labels itself")
check(identical(nxt$target_quarter, "2019 Q3"), "next horizon targets 2019 Q3")
check(identical(nxt$horizon, "next") && identical(nxt$current_quarter, "2019 Q2"),
      "next horizon names the current quarter it lags into")
check(nxt$n_months_in_quarter %in% 1:2, sprintf("next horizon sees 1-2 months (saw %d)", nxt$n_months_in_quarter))
check(identical(nxt$model, "UMIDAS-full"), "partial next quarter routes to U-MIDAS")
check(is.finite(nxt$qoq_growth) && abs(nxt$qoq_growth) < 5, "next-quarter nowcast is finite and sane")
check(identical(nxt$qoq_growth, nxt2$qoq_growth), "next-quarter nowcast is reproducible")
check(abs(nxt$nowcast_level - PREV_LEVEL * (1 + nxt$qoq_growth / 100)) < 1e-6,
      "next-quarter level = prev_level * (1 + qoq/100) (prev_level is the CURRENT quarter's level, supplied by the caller)")
# The default is unchanged: the same call without `horizon` is the current quarter.
dflt <- nowcast_midas(mai, gdp_n, as_of = AS_OF_N, prev_level = PREV_LEVEL)
check(identical(dflt$qoq_growth, cur$qoq_growth), "default horizon is 'current' and bit-identical")
# No next-quarter month yet: as_of 2019-07-05 under the 60-day lag has current = 2019 Q2
# (June printed ~29 Aug) and the MAI may or may not reach July. Either the call
# succeeds with target 2019 Q3, or it stops with the documented message.
AS_OF_E <- as.Date("2019-07-05")
gdp_e <- .truncate_gdp(transform(gdp, date = as.Date(date)), AS_OF_E, gdp_lag = 60L)
r_e <- tryCatch(nowcast_midas(mai, gdp_e, as_of = AS_OF_E, horizon = "next"),
                error = function(e) conditionMessage(e))
check(is.list(r_e) && identical(r_e$target_quarter, "2019 Q3") ||
        (is.character(r_e) && startsWith(r_e, "nowcast_midas(): no MAI month beyond the current quarter")),
      "next horizon either nowcasts 2019 Q3 or refuses with the documented message")
```

- [ ] **Step 2: Run it, expect failure** (`unused argument (horizon = ...)`): from `nowcasting_v2/`, `Rscript tests/test_nowcast_midas.R`.

- [ ] **Step 3: Implement.** In `nowcast_midas`:
  - Add `horizon = c("current", "next")`, `horizon <- match.arg(horizon)`.
  - After `target_q` (the current quarter) is computed and the stale-file warning issued, set `current_q <- target_q`. If `horizon == "next"`: `cur_months <- m[.quarter_label(m$date) == current_q, , drop = FALSE]`; `if (nrow(cur_months) < mt) stop("nowcast_midas(): current quarter incomplete ...")`; `target_q <- seq(current_q, by = "3 months", length.out = 2L)[2L]`; `target_months <- m[.quarter_label(m$date) == target_q, , drop = FALSE]`; `if (nrow(target_months) == 0L) stop(sprintf("nowcast_midas(): no MAI month beyond the current quarter %s yet\n", .quarter_name(current_q)), call. = FALSE)`. Keep `jt <- nrow(target_months)`.
  - The estimation sample is built from months strictly before `current_q`'s quarter for BOTH horizons (`m_est_src <- m[m$date < current_q, ...]`), and GDP contiguity trimming is unchanged. (For "next", `y` has no row for `current_q` by construction, so this is also what the existing trim would produce; making it explicit keeps the two horizons on one sample.)
  - Forecast newdata for "next": the U-MIDAS lags `k = (3 - jt):5` reach up to five months back from the target quarter's last month, i.e. into the current quarter. So the newdata block is the current quarter's three months followed by the next quarter's partial months: `x_new <- c(as.numeric(cur_months$value), as.numeric(target_months$value))`, padded with `rep_len(NA_real_, mt - jt)`, and `forecast(...)$mean` then has TWO entries (current quarter, next quarter); take the LAST: `qoq_growth <- as.numeric(tail(um_fc$mean, 1L))`. For "current" the code path is exactly today's. For the QA branch with `horizon == "next"` and `jt == 3` (a complete next quarter, only possible if the ABS is late), `newdata = list(xm_est = c(mean(cur_months$value), mean(target_months$value)))` and again take the last forecast.
  - Return `horizon = horizon` and `current_quarter = .quarter_name(current_q)`.
  - Update the header comment: what the next horizon is, why it needs no GDP for the current quarter, and that `prev_level` for a next-quarter level is the CURRENT quarter's level, which is itself a nowcast; callers chain it.

- [ ] **Step 4: Run the test**, expect every `[PASS]` including the pre-existing checks (unchanged headline behaviour). Also run `Rscript tests/test_parity.R` if it exists and passes on main today (check first with `git stash`-free reasoning: run it before your change, then after).

- [ ] **Step 5: Commit** `feat(v2): next-quarter horizon for nowcast_midas`.

---

### Task 2: v2 backtest records the next quarter

**Files:**
- Modify: `nowcasting_v2/R/backtest_v2.R` (loop body around lines 272-320)

**Interfaces:**
- Produces: the results CSV keeps every existing column unchanged and gains, per as-of: `next_target_quarter` ("YYYY Qn" or NA), `next_target_quarter_date` (first day of that quarter's last month, or NA), `qoq_growth_forecast_next` (NA when no next-quarter month exists at that as-of), `qoq_actual_next` (from `gdp_full`, NA if unreleased), `n_months_in_next_quarter` (NA or 0..3).

- [ ] **Step 1:** After `nc <- nowcast_midas(...)` inside the `tryCatch`, add:

```r
      nc_next <- tryCatch(
        nowcast_midas(mai = mai, gdp_growth = gdp_t, as_of = as_of,
                      model = model, qa_lag = qa_lag, horizon = "next"),
        error = function(e) {
          msg <- conditionMessage(e)
          if (startsWith(msg, "nowcast_midas(): no MAI month beyond the current quarter")) NULL
          else stop(e)
        })
```
  and carry `nc_next` in the returned list. In the row-building block compute the next-quarter label/date/actual the same way the current one is computed, and add the five columns (NA when `nc_next` is NULL). Extend the verbose line with `next=%s` showing the next-quarter forecast or "NA".

- [ ] **Step 2: Smoke test** from `nowcasting_v2/`, one recent as-of, with the shipping configuration used by `R/recalib_ci_v2.R` (read that file for the exact arguments; keep `start_year` at 2026 and `as_of_freq = "weekly"` so it takes a few minutes): confirm rows for Mondays in July and August 2026 carry `next_target_quarter == "2026 Q3"` with `n_months_in_next_quarter` in 1:2, and Mondays right after a print (e.g. 2026-06-08, current = 2026 Q2 with 0 months of Q3... ) carry NA. Confirm `qoq_growth_forecast` for every row is bit-identical to `docs/measurements/2026-09-11-v2-backtest-first-release-target-shipping.csv` at the same as-of (compare in Python).

- [ ] **Step 3: Run the full shipping backtest**: `caffeinate -i Rscript R/recalib_ci_v2.R` from `nowcasting_v2/` (about 40 minutes; foreground). Copy the output `cache/ci_recalib/qa_a10_acc.csv` to `docs/measurements/2026-09-12-v2-backtest-initial-estimate-target-two-horizons.csv`.

- [ ] **Step 4: Commit** `feat(v2): backtest records the next-quarter nowcast` including the measurement CSV.

---

### Task 3: v2 interval parameters and emitter for the next quarter

**Files:**
- Modify: `nowcasting_v2/R/compute_ci_params_v2.R`, the function that reads the params (`ci_params_for_stage`, grep for its definition), `nowcasting_v2/R/emit_v2_json.R`
- Modify: `pipeline/seed/ci_params_v2.json` (regenerated)
- Modify: `src/lib/types.ts` (`LatestV2`, `V2Model`, `Vintage` gain optional fields)
- Test: `src/lib/data.test.ts` (one case), `nowcasting_v2/tests/test_emit_next.R` (new; smoke on the current data)

**Interfaces:**
- `ci_params_v2.json` gains a top-level `next` object: `{pooled: <same stats shape as the current pooled>, by_jt: {"0": ..., "1": ..., "2": ...}}` computed from the `qoq_growth_forecast_next` rows the same way (one observation per (next_target_quarter, stage), last as-of in each cell, post-2022 targets, `MIN_N` fallback to `next$pooled`). Existing fields unchanged.
- `ci_params_for_stage(ci, jt, horizon = "current")`: for `horizon = "next"` reads `ci$next`; if absent, falls back to the current pooled params and sets `stage = "pooled-current"`.
- `latest_v2.json`: `models$headline` unchanged; new `models$next_quarter` with the same fields as `headline` plus `horizon: "next"` and `current_quarter`; NULL (absent) when v2 has no next-quarter month yet. `vintages` rows gain `horizon` ("current"|"next"); the next-quarter rows have `target_quarter` = the next quarter. `data/vintages_v2.json` upsert key becomes `(run_date, target_quarter)`.
- The /v2 page must render exactly as before: `VintageChart` filters by `latest.target_quarter`, so next-quarter rows do not appear there. Add nothing to /v2.

- [ ] **Step 1:** Extend `compute_ci_params_v2.R` (usage in its header) to produce the `next` block; regenerate: `Rscript R/compute_ci_params_v2.R cache/ci_recalib/qa_a10_acc.csv ../pipeline/seed/ci_params_v2.json` (exact usage per the header). Check the current `pooled` and `by_jt` values are unchanged to four decimals versus the committed file.
- [ ] **Step 2:** `ci_params_for_stage` gains `horizon`. Write a tiny R check in `nowcasting_v2/tests/test_emit_next.R`: load the params, call for `("next", 1)` and `("next", 2)`, assert `sd_pp` finite and stage labelled; call `("current", 2)` and assert identical to before (compare to the JSON directly).
- [ ] **Step 3:** In `emit_v2_json.R`'s `mk()`, add an argument `horizon = "current"` passed to `nowcast_midas`, and for `"next"` use `prev_level = headline's level` (the current quarter's nowcast level) so the next-quarter level chains; bands from `ci_params_for_stage(ci, jt, horizon)`. Build `nq <- tryCatch(mk(..., horizon = "next"), error = function(e) if (startsWith(conditionMessage(e), "nowcast_midas(): no MAI month beyond")) NULL else stop(e))`. Add `models$next_quarter = nq` (omit when NULL). Write a second vintage row for the next quarter when `nq` exists (`horizon = "next"`), and change the upsert filter to key on `(run_date, target_quarter)`. `rebuild_vintages` gains the same second row per Monday.
- [ ] **Step 4:** Add `backfill_next = TRUE` to `emit_v2_json`: recompute ONLY next-quarter rows for every Monday in the cadence and upsert them (never touching rows with `horizon == "current"` or with no `horizon` field). Run it once locally from `nowcasting_v2/` so `data/vintages_v2.json` gains the next-quarter rows for the Mondays from 2026-06-01 (the cadence start) — these are what the combination's evolution chart draws for the weeks before each print. Note the local run refreshes `data/latest_v2.json` with the local panel (`cache/panel_vintage_latest.rds`, 23 Aug vintage); the headline value it writes must equal the committed one for 2026-09-07 (+0.61) or the task stops and reports; if the local panel is older than the committed payload's `data_through`, run with `mondays` ending at the last Monday the local panel supports and say so.
- [ ] **Step 5:** `src/lib/types.ts`: `V2Model` gains `horizon?: string; current_quarter?: string`; `LatestV2.models` gains `next_quarter?: V2Model`; `Vintage` gains `horizon?: string`. `src/lib/data.test.ts`: a case asserting that when `latest_v2.json` carries `models.next_quarter`, its `target_quarter` is the quarter after `models.headline.target_quarter`.
- [ ] **Step 6:** `npm test`, `npx eslint src tests`, `rm -rf .next && npm run build`. Commit `feat(v2): publish the next-quarter nowcast beside the headline`.

---

### Task 4: v3 backtest pads the panel and records the next quarter at weekly cadence

**Files:**
- Modify: `nowcasting_v3/nyfed/au/build.py` (move `pad_to_next_quarter` and `months_with_data` here from `tools/run_au_nowcast.py`; the tool imports them)
- Modify: `nowcasting_v3/tools/plan_c_backtest.py`
- Test: `nowcasting_v3/tests/test_au_next_quarter.py` (add a case that `build.pad_to_next_quarter` is the function the tool uses and behaves on a fixture panel)

**Interfaces:**
- `plan_c_backtest.py` gains `--freq {MS,W-MON}` (default MS), `--seeds 4,13,19` (default all three), `--first`/`--last` window overrides (defaults unchanged), and `--pad/--no-pad` (default pad). With padding, every row has `forecast_next_qq` populated, and the CSV gains `next_target` ("2026Q3" style), `next_first_print_qq`, `next_months_with_data`. Existing columns keep their meaning; `nowcast_qq` is the current quarter.
- The docstring records that padding moves the current-quarter nowcast by under a basis point (verify on one vintage in Step 2 and print the difference).

- [ ] **Step 1:** Move the two helpers into `build.py` (keep the docstrings), import them in `run_au_nowcast.py` (`from nyfed.au.build import pad_to_next_quarter, months_with_data`), run `pytest tests/test_au_next_quarter.py tests/test_au_end_to_end.py -x -q` (the end-to-end test is long; run only `tests/test_au_next_quarter.py` first, then the end-to-end once at the end of the task).
- [ ] **Step 2:** In `plan_c_backtest.py` after `build_panel`, `pad_to_next_quarter(panel)` (unless `--no-pad`), then `t_now = target_periods(panel)`; record `next_target`, `next_first_print_qq` (`FIRST.get(...)`), `next_months_with_data = months_with_data(panel, int(t_now[1]))` when `len(t_now) > 1`. Add the argparse options and the `pd.date_range(..., freq=args.freq)` loop. One vintage smoke: `--first 2026-08-03 --last 2026-08-03 --seeds 4` with and without `--no-pad`, print both current-quarter figures and their difference.
- [ ] **Step 3:** Run the weekly backtest, one process per seed in the background, from `nowcasting_v3/`:
  `for s in 4 13 19; do nohup caffeinate -i .venv/bin/python tools/plan_c_backtest.py ../docs/measurements/2026-09-12-v3-weekly-two-horizons-seed$s.csv --freq W-MON --first 2023-01-02 --last 2026-09-07 --seeds $s > /tmp/v3w_$s.log 2>&1 & done`
  About 2.5 hours in parallel. Poll with `tail -1 /tmp/v3w_*.log` no more often than every 10 minutes. (2026-08-31 is unbuildable because a panel series is stale at that as-of; that is expected and skipped.)
- [ ] **Step 4:** Commit the code first (`feat(v3): backtest pads the panel and records the next quarter; weekly cadence option`), then the three CSVs when they finish (`measure(v3): weekly two-horizon backtest, first-print target`).

---

### Task 5: combination backtest and band parameters

**Files:**
- Create: `nowcasting_v3/tools/combination_backtest.py`
- Create: `pipeline/seed/ci_params_combo.json`
- Create: `docs/measurements/2026-09-12-v2-v3-weekly-combination-two-horizons.csv`, update `docs/measurements/2026-09-12-v2-v3-weekly-combination.md` (append a "Two horizons" section; keep the existing content)
- Test: `nowcasting_v3/tests/test_combination_backtest.py` (pure functions on a tiny synthetic frame)

**Interfaces:**
- Consumes: the v2 CSV from Task 2 (`as_of, target_quarter, qoq_growth_forecast, next_target_quarter, qoq_growth_forecast_next, ...`), the three v3 seed CSVs from Task 4, `nowcasting_v3/data/first_print_misses.csv` via `nyfed.au.bias_correction.load_misses` / `rolling_miss` (backtest-source rows only, recursive, zero before four prints), `nowcasting_v3/data/gdp_first_release.csv`, `nyfed.au.emit.gdp_release_date`.
- Produces `ci_params_combo.json`:
  ```json
  {"schema": "combo-ci-1",
   "basis": "empirical absolute-error quantiles of the equal-weight v2+v3 average against the ABS's initial estimate, weekly vintages, targets 2022Q4 onward, centred on the point",
   "current": {"p68": 0.144, "p95": 0.351, "n": 181, "mae": 0.129, "bias": 0.059},
   "next":    {"p68": ..., "p95": ..., "n": ..., "mae": ..., "bias": ...},
   "source": {"v2": "...csv", "v3": ["...seed4.csv", ...]}, "computed_at": "..."}
  ```
  and the joined CSV with one row per (as_of, horizon): `as_of, horizon, target, first, v2, v3_raw, v3, combo, months_with_data_v2, months_with_data_v3, days_to_release`.
- Pure functions to test: `pair(v2_frame, v3_frame) -> frame`, `score(errors) -> dict`, `bands(errors) -> dict`.

- [ ] **Step 1:** Write the tests (synthetic: two Mondays, two quarters, hand-computed averages and quantiles), run, fail.
- [ ] **Step 2:** Implement; for the "current" horizon reproduce the numbers in the existing measurement doc to two decimals (MAE 0.13, bias +0.06, n 181) as a regression check printed by the tool. Report the "next" horizon's MAE/bias for v2, v3 and the combination, by `months_with_data`.
- [ ] **Step 3:** Append the two-horizon section to the measurement doc: table per horizon (v2, v3 raw, v3, combination: bias, MAE, RMSE, n), bands, and the same reading notes style. Commit `measure: v2 + v3 combination at both horizons; band parameters`.

---

### Task 6: production combination emitter

**Files:**
- Modify: `nowcasting_v3/tools/emit_combination.py` (from the draft on `preview/combination`; cherry-pick commit 4cdfd65 onto the working branch first, then edit)
- Create: `nowcasting_v3/nyfed/au/combination.py` (pure functions the tool calls; the tool does I/O only)
- Test: `nowcasting_v3/tests/test_au_combination.py`

**Interfaces:**
- `combination.pair_runs(v3_runs, v2_vintages, *, max_age_days=7) -> list[dict]`: for each v3 history row (either kind; a row lacking `kind` is a nowcast), find v2's latest vintage for the same `target_quarter` with `run_date <= v3 run_date` and not older than `max_age_days`; emit a combined row `{run_date, target_quarter, kind, qoq_growth_pct (mean, 4 dp), v2_qoq_growth_pct, v2_run_date, v3_qoq_growth_pct, months_with_data, data_through}`. Rows with no partner are dropped.
- `combination.with_bands(rows, params) -> rows`: adds `ci_68_low/high, ci_95_low/high` from `params["current"]` for rows whose target is the earliest unprinted quarter at that run date, else `params["next"]`; the tool passes a function `is_current(run_date, quarter)` built from `gdp_release_date`.
- `combination.latest_payload(rows, *, v3_latest, gdp_series, params, generated_at) -> dict` in the `LatestV3` shape: `schema "combo-1"`, `status "ok"`, `basis "abs_first_print"`, `target "first_print"`, `method "equal-weight average of v2 and v3"`, `horizons` = [current (kind nowcast), next (kind forecast) when present], `vintages` = all rows for those two quarters, `bias_correction` copied from v3, `ci_basis` text, `band_pp`, `components {v2: {as_of, run_date used}, v3: {as_of}}`, `prev_level`, `next_gdp_release_date`, `panel`, `diagnostics`, `estimate` copied from v3.
- `combination.track_record(backtest_rows, history_rows, gdp_series, first_release, somp) -> dict` in the `Performance` shape (as the draft), with a LIVE row replacing the backtest row for any printed quarter that has combination history rows before its release date (`is_live: true`, `live_run_date`, `model: "combination"`).
- Refusal: if v3's `latest_v3.json` has `status != "ok"`, write `latest_combo.json` with the same refusal (status, reason, detail) so the page shows v3's refusal. If v2's newest vintage for the current quarter is older than `max_age_days`, publish the current horizon from the most recent paired Monday (which exists) and set `components.v2.stale_days`; if there is no paired Monday at all for the current quarter, refuse with reason "no v2 figure for the current quarter".

- [ ] **Step 1:** Tests for the pure functions with small hand-built inputs: pairing picks the latest v2 run at or before the Monday and drops rows older than 7 days; a row without `kind` is a nowcast; bands come from the right horizon; the live row supersedes the backtest row; refusal passthrough.
- [ ] **Step 2:** Implement the module and rewrite the tool over it. The tool keeps `--asof` (drop later runs, for previews) and `--out`.
- [ ] **Step 3:** Run it on the real data; the printed summary names the current and next quarter figures and their components. Commit `feat(combination): production emitter for the equal-weight v2+v3 nowcast`.

---

### Task 7: payload check and weekly workflow

**Files:**
- Modify: `nowcasting_v3/tools/check_payload.py` (accept a `--file` argument; the combination payload passes the same invariants; add two combination-only invariants: `qoq_growth_pct` equals the mean of the two component figures to 4 dp on every horizon and vintage; `ci_68_low < qoq < ci_68_high`)
- Modify: `.github/workflows/nowcast-v3-weekly.yml`: after "Refresh the track record", a step `Combine with v2` running `python -u tools/emit_combination.py` (continue-on-error: false), then `Check the payload is coherent` also runs `python -u tools/check_payload.py --file ../data/latest_combo.json`; the Commit step adds `data/latest_combo.json data/nowcast_history_combo.json data/performance_combo.json`; the "Fail the job if ..." block gains a check that `latest_combo.json` changed on a Monday run.
- Test: `nowcasting_v3/tests/test_check_payload.py` (two cases for the new invariants)

- [ ] Steps: tests first, implement, run `pytest tests/test_check_payload.py -q`, run the checker on the real combo payload, commit `ci: emit and check the combination payload in the weekly job`.

---

### Task 8: site

**Files:**
- Modify: `src/lib/data.ts` (add `latestCombo`, `performanceCombo`, `historyCombo` readers; remove the preview fallback from commit 4cdfd65), `src/lib/types.ts` (`DashboardData` fields), `src/app/page.tsx` (use the combination when present, else v3 exactly as today), `src/components/V3MethodologyPanel.tsx` (the copy from commit 4cdfd65, unchanged), `src/lib/data.test.ts`, `tests/site.spec.ts` (the methodology assertion `/most recent average error/` becomes `/average error/`; add an assertion that the methodology mentions "Research Discussion Paper 2024-04")
- The rest of the page is not touched: headline, next-quarter card, evolution chart, indicators, track record, RBA tile all render the combination payloads through the existing components.

- [ ] Steps: cherry-pick 4cdfd65 (or apply its site hunks), replace the loader fallback with explicit fields, update tests, `npm test`, `npx eslint src tests`, `rm -rf .next && npm run build`, `npm run test:e2e` (kill any `http.server 300*` first, restart one on 3000 after against `out`). Commit `feat(site): the homepage publishes the v2+v3 combination`.

---

### Task 9: README and docs

- README: the v3/homepage section says the homepage figure is the equal-weight average, cites the measurement doc, describes the weekly flow (v2 02:00 UTC, v3 03:30 UTC, combination at the end of the v3 job) and the carry-forward rule. `docs/2026-09-09-unrevised-data-feasibility.md`: one closing line pointing at the combination doc. Commit `docs: the combination nowcast`.

---

## Self-review notes

- Task 1's newdata trick (six values, take the last forecast) is the one subtle piece; the test pins it against a known slice, and Task 2's bit-identity check on `qoq_growth_forecast` guards the current horizon.
- The combination's "next" bands depend on Tasks 2 and 4 finishing their long runs; Task 6 can be built and tested on synthetic inputs before Task 5 writes the real `ci_params_combo.json`.
- Nothing in v2's headline path changes value; Task 3 Step 4 checks this on the live payload.
