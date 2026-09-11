# First-Print Model With a Rolling Miss — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The production v3 model is trained on first-print GDP, and the published nowcast is that model's estimate less a rolling mean of its own recent misses against the first print. One number, labelled the first-print nowcast, scored against the first print.

**Architecture:** The GDP series the model learns from becomes a chain index of first-release growth (`first_release_index`), applied inside `build_panel` after the vintage loads, so the registry, the recording and the fetchers are untouched. The collapse floor becomes target-specific: 1.0 for the revised target (unchanged, still tested on the legacy panel), a new measured value for the first-print target. A small pure module keeps a committed file of the model's final-nowcast misses per printed quarter (seeded from the backtest, appended live on print Mondays) and returns the rolling correction. The weekly payload, the history record, the track record and the site move from `revision_adjustment` to `bias_correction`. The quarterly estimate is re-run on the new target and committed; its workflow gains fetch retries, which is what failed on 10 September.

**Tech Stack:** Python 3.13 in `nowcasting_v3/.venv`; Next.js + TypeScript at the root; GitHub Actions.

**Spec:** the user's decision of 10 September 2026 ("I want to use the retrained model less its own rolling miss … add a short addition on the rolling miss to the methodology explanation … keep the row for Q2 2026 as is"), the measurements in `docs/measurements/2026-09-09-first-print-target-ab.md` (retrained target and the rolling-miss addendum), and the bias report's section 4.1 (`docs/2026-09-01-upside-bias-report.md`: rolling window, not expanding; eight quarters; retirement condition). Builds on branch `feat/first-print-scoring` at 17cf019.

## Global Constraints

- Python from `nowcasting_v3/` with `.venv/bin/python` / `.venv/bin/pytest`; `filterwarnings = ["error"]`. Run the focused test files each task names; the full suite (30 min) runs once before the final review. End-to-end tests that sample (`tests/test_au_end_to_end.py`) take minutes each; run only the ones a task names, with `-k`.
- `nyfed/au/emit.py` must not import `first_release` or `bias_correction`; the correction is duck-typed (`.pp`, `.as_dict()`).
- The recorded vintage `tests/fixtures/au/vintage/`, the registry `nyfed/au/sources.py`, and `model_spec_AU.csv` do not change. The first-print target is applied post-load.
- Names, everywhere: `target` is `"first_print"` or `"latest"`; `qoq_growth_pct` = published first-print nowcast = `model_qoq_growth_pct − bias_correction.pp`; `bias_correction` replaces `revision_adjustment` in every payload and every row written from now on. `revision_adjustment` survives only on history rows written before this plan (Q2 2026 and earlier), as a record.
- Rolling window: `BIAS_WINDOW_QUARTERS = 8`, `BIAS_MIN_QUARTERS = 4` (the report's window; v2's `apply_rt_bias_correction` used 4 or 8). The correction at date d uses quarters whose first print was released at or before d, the last eight of them, and needs at least four; otherwise the runner refuses.
- The Q2 2026 track-record row stays exactly as it is now (live call of the previous model, +0.54 after the revision adjustment, against +0.42), flagged as the previous model's.
- Copy: the site says "nowcast" for the first-print number only. The methodology panel gets one short paragraph on the rolling miss (Task 5 gives the text).
- Commit trailer:
```
Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SyVuNnQdjveYgZLXQj4Szt
```

---

### Task 1: The first-print target in the production build, with its own collapse floor

**Files:**
- Modify: `nowcasting_v3/nyfed/au/panel.py` (`Panel` gains `target: str = "latest"`)
- Modify: `nowcasting_v3/nyfed/au/build.py` (`build_panel(..., target="first_print")`, `collapse_floor()`, `state_space`, the constant)
- Modify: `nowcasting_v3/tools/plan_c_backtest.py` (use `build_panel(target=…)`; `--collapse-floor` sets `build.FLOOR_OVERRIDE`)
- Modify: `nowcasting_v3/tools/estimate_au.py` (meta records `target` and the floor), `nowcasting_v3/tools/run_au_nowcast.py` (refuse an estimate fitted on another target)
- Modify: `nowcasting_v3/tests/test_au_end_to_end.py` (fixtures pass `target="latest"`; new pinned first-print test), `nowcasting_v3/tests/test_au_panel.py` (Panel field)
- Test: `nowcasting_v3/tests/test_au_build_target.py` (new)

**Interfaces:**
- `build_panel(*, asof, start=DEFAULT_START, vintage=None, target="first_print") -> Panel`; `Panel.target` set accordingly. For `"first_print"`: after the vintage is loaded and before `as_of`, `series["gdp"] = first_release_index(load_first_release(), v.series["gdp"].dropna())` on a copied series dict. `"latest"` is the old behaviour.
- `COLLAPSED_GLOBAL_LOADING = 1.0` (unchanged name and value, the revised-target floor). New `COLLAPSED_GLOBAL_LOADING_FIRST_PRINT` = the value chosen in Step 3. `FLOOR_OVERRIDE: float | None = None`. `collapse_floor(target: str) -> float` returns the override if set, else by target. `state_space` uses `collapse_floor(panel.target)` and names the target in its error.
- `estimate_au.py` meta gains `"target": panel.target` and records `collapse_floor(panel.target)` under the existing `collapse_floor` key. `run_au_nowcast.py` returns 1 with a clear message if `meta.get("target", "latest") != panel.target`.

- [ ] **Step 1: Failing tests**

`tests/test_au_build_target.py`:

```python
"""The first-print target is applied inside build_panel, post-load."""
import numpy as np
import pandas as pd
import pytest

from nyfed.au import build
from nyfed.au.build import build_panel, collapse_floor, load_vintage
from nyfed.au.first_release import first_release_index, load_first_release

VINTAGE = load_vintage("tests/fixtures/au/vintage")
ASOF = "2026-06-01"


def test_the_default_target_is_the_first_print():
    p = build_panel(asof=ASOF, vintage=VINTAGE)
    assert p.target == "first_print"


def test_the_latest_target_is_still_available_and_unchanged():
    p = build_panel(asof=ASOF, vintage=VINTAGE, target="latest")
    assert p.target == "latest"
    g = VINTAGE.as_of(ASOF).series["gdp"].dropna()
    # the standardised GDP row's location/scale are those of the latest-vintage growth
    assert np.isfinite(p.Y[p.i_now]).sum() == (g.shape[0] - 1)


def test_the_first_print_target_changes_the_gdp_row_and_nothing_else():
    a = build_panel(asof=ASOF, vintage=VINTAGE, target="latest")
    b = build_panel(asof=ASOF, vintage=VINTAGE, target="first_print")
    assert a.Y.shape == b.Y.shape and a.i_now == b.i_now
    others = [i for i in range(a.Y.shape[0]) if i != a.i_now]
    assert np.allclose(np.nan_to_num(a.Y[others]), np.nan_to_num(b.Y[others]))
    assert not np.allclose(np.nan_to_num(a.Y[a.i_now]), np.nan_to_num(b.Y[b.i_now]))
    # the first-print row carries the first-print growth: compare its annualised growth to the index's
    fp = first_release_index(load_first_release(), VINTAGE.series["gdp"].dropna())
    assert fp.index[-1] == VINTAGE.series["gdp"].dropna().index[-1]


def test_an_unknown_target_is_refused():
    with pytest.raises(ValueError, match="target"):
        build_panel(asof=ASOF, vintage=VINTAGE, target="revised")


def test_the_floor_is_target_specific_and_overridable(monkeypatch):
    assert collapse_floor("latest") == build.COLLAPSED_GLOBAL_LOADING == 1.0
    assert collapse_floor("first_print") == build.COLLAPSED_GLOBAL_LOADING_FIRST_PRINT
    assert build.COLLAPSED_GLOBAL_LOADING_FIRST_PRINT < build.COLLAPSED_GLOBAL_LOADING
    monkeypatch.setattr(build, "FLOOR_OVERRIDE", -1.0)
    assert collapse_floor("first_print") == -1.0
```

In `tests/test_au_panel.py` add one test that `Panel(...)` constructed the way the file already does defaults to `target == "latest"`.

In `tests/test_au_end_to_end.py`: the `panel` and `legacy_panel` fixtures pass `target="latest"` with a comment that they are the regression record for the revised target (the thirty-seed lists above them were measured on it). Add:

```python
# THE FIRST-PRINT TARGET, MEASURED 2026-09-10 on the shipping panel at
# 2026-08-01 (the recording's last buildable month), thirty cold-start seeds,
# 200+100 sweeps, sorted:
#
#   <paste the sorted list from scratchpad seed_sweep_fp.json>
#
# One basin. The lowest chain sits <min> above zero and the distribution has no
# gap below it, so the floor for this target is placed at
# COLLAPSED_GLOBAL_LOADING_FIRST_PRINT, below every chain measured and above the
# collapsed basin the revised target showed (0.07..0.75 on the 1990 panel).
FIRST_PRINT_SEEDS_SORTED = [...]


def test_the_first_print_floor_sits_below_every_measured_chain():
    from nyfed.au.build import COLLAPSED_GLOBAL_LOADING_FIRST_PRINT
    assert COLLAPSED_GLOBAL_LOADING_FIRST_PRINT < min(FIRST_PRINT_SEEDS_SORTED)
    assert COLLAPSED_GLOBAL_LOADING_FIRST_PRINT > 0.1


def test_the_gate_runs_on_the_first_print_target_and_clears_its_floor():
    """One seed, the gate's own, on the shipping panel with the first-print target."""
    from nyfed.au.build import COLLAPSED_GLOBAL_LOADING_FIRST_PRINT, state_space
    p = build_panel(asof=ASOF, vintage=VINTAGE)             # default target
    assert p.target == "first_print"
    res = estimate_short(p, n_gs=N_GS, n_burn=N_BURN, seed=SEED)
    ssm = state_space(p, res)                              # must not raise
    spec = load_spec(SPEC_PATH); n, n_f = spec.blocks.shape
    loading = float(map_parameter(np.median(res.params, axis=1), (n, n_f, P_F, P_E)).Lambda[p.i_now, 0])
    assert loading > COLLAPSED_GLOBAL_LOADING_FIRST_PRINT
```

- [ ] **Step 2: Run them to see them fail**

`cd nowcasting_v3 && .venv/bin/pytest tests/test_au_build_target.py -q` — fails on the `target` keyword.

- [ ] **Step 3: Choose the floor from the sweep**

Read `/private/tmp/claude-501/-Users-James-Documents-Claude-Projects-nowcasting/6820a2d0-9542-4c08-b400-ff57f5713019/scratchpad/seed_sweep_fp.json` (thirty seeds, `loading` each). Sort them. If the minimum is above 0.6 and no gap wider than 0.15 exists below the median, set `COLLAPSED_GLOBAL_LOADING_FIRST_PRINT = 0.5`. If any seed is below 0.6, STOP and report the list; the floor needs a human ruling. Paste the sorted list into the end-to-end comment and `FIRST_PRINT_SEEDS_SORTED`.

- [ ] **Step 4: Implement**

`panel.py`: add `target: str = "latest"` to `Panel` after `deflator_skipped`, with a comment: which GDP series the row `i_now` carries.

`build.py`:

```python
COLLAPSED_GLOBAL_LOADING = 1.0                 # revised (latest-vintage) target; measured 2026-08-28/30, see tests
COLLAPSED_GLOBAL_LOADING_FIRST_PRINT = 0.5     # first-print target; measured 2026-09-10, see tests
FLOOR_OVERRIDE: float | None = None            # experiments only: tools/plan_c_backtest.py --collapse-floor
TARGETS = ("first_print", "latest")


def collapse_floor(target: str) -> float:
    if FLOOR_OVERRIDE is not None:
        return FLOOR_OVERRIDE
    if target == "first_print":
        return COLLAPSED_GLOBAL_LOADING_FIRST_PRINT
    if target == "latest":
        return COLLAPSED_GLOBAL_LOADING
    raise ValueError(f"unknown target {target!r}; expected one of {TARGETS}")
```

With a comment block above explaining why the floor is per target: the first-print series is noisier (mean absolute revision 0.45pp before 2020), GDP's loading on the common factor is lower for it (median 0.88 against 1.48 in the 40-vintage backtest; 83% of chains below 1.0, none below 0.59), and a single floor would refuse healthy chains on one target or admit collapsed ones on the other.

`build_panel`: add `target: str = "first_print"`; validate against `TARGETS`; after `v` is resolved and before `vintage_asof = v.as_of(asof_ts)`:

```python
    if target == "first_print":
        # THE MODEL LEARNS THE FIRST PRINT. Same dates, same release lags, same
        # level at the last quarter; only the growth path changes, to what the
        # ABS printed first. See first_release.first_release_index.
        series_fp = dict(v.series)
        series_fp["gdp"] = first_release_index(load_first_release(), v.series["gdp"].dropna())
        v = Vintage(series=series_fp, deflator_sources=v.deflator_sources, recorded_at=v.recorded_at)
```

(`first_release` imports `emit`; `build` importing `first_release` creates no cycle — check `emit` does not import `build`.) Set `panel.target = target` before returning. `state_space`: `floor = collapse_floor(panel.target)`; use it in the comparison and the message, naming the target.

`plan_c_backtest.py`: replace the manual substitution with `build_panel(asof=stamp, vintage=VINT, target=args.target)`; `--collapse-floor` sets `build_mod.FLOOR_OVERRIDE = args.collapse_floor` (default None) and the tool's own `collapsed` test uses `collapse_floor(args.target)`; `FIRST`/`first_release_index` imports go if unused. Default `--target` becomes `first_print` (the production target); say so in the docstring.

`estimate_au.py`: meta `"target": panel.target`, `"collapse_floor": collapse_floor(panel.target)`; log line prints the target. `run_au_nowcast.py`: after the panel builds, `if meta.get("target", "latest") != panel.target: print(...); return 1` with a message saying the saved estimate was fitted on the other target and the quarterly estimate must be re-run; the collapse check uses `collapse_floor(panel.target)`.

- [ ] **Step 5: Tests**

`cd nowcasting_v3 && .venv/bin/pytest tests/test_au_build_target.py tests/test_au_panel.py tests/test_au_first_release.py tests/test_au_emit.py tests/test_check_payload.py -q` then the sampling ones: `.venv/bin/pytest tests/test_au_end_to_end.py -q -k "floor or basin or collapsed or first_print or bimodal"` (several minutes). All pass.

- [ ] **Step 6: Commit** — `feat(v3): the model trains on the first print; the collapse floor is per target`.

---

### Task 2: The rolling miss

**Files:**
- Create: `nowcasting_v3/nyfed/au/bias_correction.py`
- Create: `nowcasting_v3/tools/build_first_print_misses.py`; generated `nowcasting_v3/data/first_print_misses.csv` (committed)
- Test: `nowcasting_v3/tests/test_au_bias_correction.py`

**Interfaces:**
- `MISSES_CSV = nowcasting_v3/data/first_print_misses.csv`, columns `quarter,release_date,model_qoq_pct,first_print_qoq_pct,miss_pp,source` (`quarter` `YYYYQn`; `source` `backtest` or `live`).
- `BIAS_WINDOW_QUARTERS = 8`, `BIAS_MIN_QUARTERS = 4`.
- `load_misses(path=MISSES_CSV) -> pd.DataFrame` sorted by `release_date`, refusing duplicate quarters.
- `BiasEstimate(pp, n, window_quarters, min_quarters, first_quarter, last_quarter)` with `as_dict()` (adds `basis`: "mean of the model's final nowcast minus the ABS first print over the last n printed quarters").
- `rolling_miss(misses, asof, *, window=8, min_n=4) -> BiasEstimate`: rows with `release_date <= asof`, last `window`, `ValueError` mentioning "fewer than" if under `min_n`; `pp = round(mean(miss_pp), 4)`.
- `append_miss(path, runs, first, *, asof) -> list[str]`: for every quarter in `first` (a `load_first_release` Series) whose release date (from `gdp_release_date`) is `<= asof` and not in the file: find the last history run row with `target_quarter == "YYYY Qn"`, not `backfilled`, `kind` nowcast or absent, `run_date < release_date`, carrying `model_qoq_growth_pct`; append `miss = model − first`, source `live`; return the labels appended. Quarters with no such row are skipped with a printed line (they cannot be reconstructed; the seed file covers the backtest era).
- `tools/build_first_print_misses.py`: from `docs/measurements/2026-09-09-plan-c-first-print-target.csv` and `docs/measurements/2026-09-10-plan-c-2026q2-extension-first_print.csv`: per `target`, the last `asof`'s median `nowcast_qq` over seeds is the model's final nowcast; miss = that − first print; `source = backtest`; release date from `gdp_release_date`. Writes 15 rows 2022Q4..2026Q2.

- [ ] **Step 1: Failing tests** (`tmp_path` for every write; helpers may copy `_first`/`_levels` style from `test_au_first_release.py`):

```python
def test_rolling_miss_uses_the_last_eight_printed_quarters():   # 12 misses, asof after all print -> mean of the last 8
def test_rolling_miss_ignores_quarters_not_yet_printed():        # asof before the last release -> that row excluded
def test_rolling_miss_needs_four_quarters():                    # 3 rows -> ValueError match "fewer than"
def test_append_miss_takes_the_last_live_nowcast_before_the_print(tmp_path):
    # runs: backfilled row (ignored), a forecast row (ignored), two nowcast rows before the print, one after (ignored)
    # -> appends the later of the two, model_qoq_growth_pct - first, source live; second call appends nothing
def test_append_miss_skips_a_quarter_with_no_live_row_and_says_so(tmp_path, capsys):
def test_load_misses_refuses_duplicates(tmp_path):
def test_the_committed_misses_file_covers_the_backtest_era():   # 2022Q4..2026Q2, 15 rows, source backtest, |miss| < 1
```

- [ ] **Step 2: Implement the module and the seed tool; run the tool; run the tests.** Check the seed file's 2026Q2 row: model final nowcast about +0.45 (the extension's last vintage median), first print +0.4195.

- [ ] **Step 3: Commit** — module, tests, tool, CSV: `feat(v3): the model's rolling miss against the first print, seeded from the backtest`.

---

### Task 3: The payload, the history and the checker use the rolling miss

**Files:**
- Modify: `nowcasting_v3/nyfed/au/emit.py`, `nowcasting_v3/tools/run_au_nowcast.py`, `nowcasting_v3/tools/check_payload.py`, `nowcasting_v3/tools/emit_backtest_json.py` (the append only; scoring is Task 4)
- Test: `nowcasting_v3/tests/test_au_emit.py`, `nowcasting_v3/tests/test_check_payload.py`, `nowcasting_v3/tests/test_au_next_quarter.py`

**Interfaces:**
- `nowcast_payload(..., correction)` (rename of `revision`; required; `.pp`, `.as_dict()`): top-level `bias_correction` (never null when ok), `target: "first_print"`, `schema: "v3-preview-3"`, `basis: "abs_first_print"`; per horizon `qoq_growth_pct = model − pp`, `model_qoq_growth_pct`, bands shifted by `−pp`. No `revision_adjustment` key.
- History rows written from now on: `bias_correction_pp`, `model_qoq_growth_pct`, `qoq_growth_pct` (first-print basis), `target: "first_print"`. Schema `v3-history-3`. Migration from `v3-history-2`: rows for quarters already printed at migration time are kept as they are (they record what was published), rows for unprinted quarters are DROPPED (they belong to the superseded model and would sit on the evolution chart beside the new model's), and the runner's `--backfill` rebuilds them. `migrate_history_runs_v3(runs, printed: set[str]) -> list[dict]` pure, tested.
- `check_payload`: ok payload must have `target == "first_print"`, `basis == "abs_first_print"`, `bias_correction.pp` a non-bool number within ±0.6, every horizon `qoq_growth_pct == model_qoq_growth_pct − pp` within 1e-3, no `revision_adjustment` and no `expected_first_print_pct` keys.
- Runner: loads `misses = load_misses()`, `correction = rolling_miss(misses, asof=asof)`; on `ValueError`/`FileNotFoundError`/malformed file → refusal `"no bias estimate"`; prints the estimate. `emit_backtest_json.py`: after `append_first_print`, call `append_miss(MISSES_CSV, runs_from_history, first, asof=today)` (import the history the same way it already does) and print what it appended; the revision-adjustment computation and the `revision_adjustment_pp` field go in Task 4.
- Weekly workflow `Commit` step stages `nowcasting_v3/data/first_print_misses.csv`.

- [ ] Tests first (rewrite the Task-1-of-plan-3 tests to `correction`/`bias_correction`; add the migration test; update `_ok()`); implement; replay `--vintage --quick --out /tmp/latest_v3_bc.json` (expect a refusal or a payload: the saved estimate was fitted on the latest target, so the runner now refuses with the target message — that is the expected result until Task 6; verify the message, then run again with `--estimate` pointing at a quick first-print estimate produced by `estimate_au.py --vintage --quick --out /tmp/est_fp_quick.npz` to see a real payload and run the checker on it); `git checkout data/nowcast_history_v3.json`; commit.

---

### Task 4: The track record on the new model

**Files:**
- Modify: `nowcasting_v3/tools/emit_backtest_json.py`

**Interfaces:**
- Reads the retrained backtest: `docs/measurements/2026-09-09-plan-c-first-print-target.csv` + `docs/measurements/2026-09-10-plan-c-2026q2-extension-first_print.csv` (concatenated), not the 2026-08-30 file. Per target quarter, the last vintage's median nowcast is the model figure.
- Correction per backtest row: `rolling_miss(misses_backtest_only, asof=vintage_date)` where the misses are the committed file's `backtest` rows (recursive: only quarters released by the vintage date); if fewer than 4, the row is published raw with `bias_correction_pp: null`.
- Live rows: a history row carrying `bias_correction_pp` is the new model's published figure, used as is. A live row carrying `revision_adjustment_pp` (Q2 2026) is the previous model's published figure: keep its `qoq_nowcast_pct` and `qoq_model_nowcast_pct` exactly as the current `performance_v3.json` has them (0.54 / 0.64), flag `model: "revised_target"`. All other rows `model: "first_print"`.
- Row fields: `qoq_nowcast_pct`, `qoq_model_nowcast_pct`, `bias_correction_pp` (nullable), `qoq_actual_pct` (first print), `qoq_error_pp`, `qoq_latest_vintage_pct`, `model`, `is_live`, `live_run_date`, YoY/RBA fields as before (hybrid basis, still documented). Top level: `basis`, `target: "first_print"`, `n`, `mae_pct`, `bias_pct`, `bias_window_quarters: 8`, `model_bias_vs_first_print_pct` (raw model), `model_mae_vs_first_print_pct`. Remove `revision_adjustment_pp`, `model_bias_vs_latest_pct`, `model_mae_vs_latest_pct`.
- `backtest_v3.json`: `v3` = corrected first-print model, `v3_model` = raw, `v2` as before, `first_print`, `actual`; scores against `first_print`; notes updated: what the model is, the rolling miss, the Q2 2026 row's provenance.
- Acceptance: on the 15 rows, `bias_pct` between −0.10 and +0.05 and `mae_pct` between 0.14 and 0.20 (the addendum measured −0.06 / 0.16 on 11 corrected quarters; the four uncorrected early quarters and the kept Q2 row move it).

- [ ] Implement; run; check with a one-liner; commit the emitter and both JSONs.

---

### Task 5: The site

**Files:** `src/lib/types.ts`, `src/components/V3MethodologyPanel.tsx`, `src/components/PerformanceSection.tsx` (row flag only), `src/app/page.tsx`, `src/lib/data.test.ts`, `tests/site.spec.ts`

- Types: `LatestV3.bias_correction?: {pp, n, window_quarters, min_quarters, first_quarter, last_quarter, basis} | null`, `LatestV3.target?`, drop `revision_adjustment`; `AccuracyError.bias_correction_pp?: number | null`, `model?: "first_print" | "revised_target"`; `Performance.bias_window_quarters?`, `model_bias_vs_first_print_pct?`, `model_mae_vs_first_print_pct?`, drop the three removed fields.
- `V3MethodologyPanel`: replace the revision-adjustment paragraph with this text, gated on the fields: "This is a nowcast of the figure the ABS will print first. The model is trained on first-print GDP rather than the later revised series, and the published number is the model's estimate less its own rolling miss: the average gap between its final nowcast and the first print over the last {window} printed quarters, currently {pp}pp over {n} quarters. The correction is re-estimated each week from quarters that have already printed, so it uses no information from the quarter being nowcast. The model's own estimate for this quarter is {model}%." Then the existing accuracy sentence on the first-print basis; drop the "latest revised figures" sentence.
- `PerformanceSection`: a row with `model === "revised_target"` gets a title attribute "Published by the previous model, trained on revised GDP, less the revision adjustment" and the legend gains one sentence for it when such a row exists.
- `page.tsx` notes: replace "Actual is the ABS's first print …" paragraph's second sentence if it mentions the revision adjustment; keep the rest.
- Tests: vitest asserts `target === "first_print"`, `bias_correction.pp` number when present, identity within 1e-3, every error row has `model`; Playwright unchanged (both eyebrows still present). `npm test`, `npx eslint src`, `rm -rf .next && npm run build`, `npm run test:e2e`.

---

### Task 6: The estimate, the data, the docs

- Re-estimate locally on the first-print target: `cd nowcasting_v3 && caffeinate -i .venv/bin/python -u tools/estimate_au.py` (PROD settings, about 95 minutes; live fetch). It must clear `COLLAPSED_GLOBAL_LOADING_FIRST_PRINT`; the log prints the loading. Commit `state/au_estimate.npz` — `state: v3 quarterly estimate 2026-09-10, first-print target`.
- Then the weekly path, live, with backfill: `.venv/bin/python -u tools/run_au_nowcast.py --backfill`; `.venv/bin/python -u tools/emit_indicators.py`; `.venv/bin/python -u tools/emit_backtest_json.py`; `.venv/bin/python tools/check_payload.py`. Commit `data/latest_v3.json data/nowcast_history_v3.json data/performance_v3.json data/backtest_v3.json data/indicators_v3.json nowcasting_v3/data/first_print_misses.csv nowcasting_v3/data/gdp_first_release.csv` (whichever changed) — `data: v3 nowcast 2026-09-10, first-print model`.
- README section "First prints and the revision adjustment" → "The first-print model and its rolling miss": what the target is, where the floor comes from, the misses file, the window and minimum, the refusal, the Q2 2026 row.
- Rebuild and serve the preview.

---

### Task 7: The quarterly estimate workflow

- `nyfed/au/build.py` `fetch_vintage`: wrap `_fetch_one` per series in up to three attempts with 30 s and 90 s waits, printing each retry; the 10 September failure was a single failed download of a 30 MB ABS zip that succeeds on retry.
- Test: `tests/test_au_fetch_retry.py` with a fetcher stub that fails twice then succeeds; and one that fails three times raises the last error.
- `.github/workflows/nowcast-v3-estimate.yml`: no structural change needed; add a comment that the fetch retries live in the code. After merge, dispatch it once (`gh workflow run nowcast-v3-estimate.yml`) so the committed estimate is refreshed by CI on the same target, and close the failure issue it opened.

## Acceptance

- `latest_v3.json`: `schema v3-preview-3`, `target first_print`, `bias_correction.pp` ≈ the mean of the last eight backtest misses (about −0.05 to +0.10), `qoq_growth_pct = model − pp`.
- `state/au_estimate.npz` meta `target: first_print`, loading above the first-print floor.
- Track record: 15 rows, the Q2 2026 row unchanged, `bias_pct` and `mae_pct` within the Task 4 bands.
- Site: one nowcast; the methodology paragraph on the rolling miss present; Playwright green.
- Quarterly workflow: fetch retries in place; the failed run's issue closed after a successful dispatch.
