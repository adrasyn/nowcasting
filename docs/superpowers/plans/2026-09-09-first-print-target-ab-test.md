# First-Print Target A/B Test Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure whether training v3 on first-release GDP instead of the latest vintage lowers its bias against first prints without raising its error, as one Plan C backtest re-run.

**Architecture:** A chain index built from first-release growth replaces the `gdp` series inside the recorded vintage before `build_panel` runs; nothing in the registry, spec or fixtures changes. The backtest tool gains a `--target` switch and always writes the first-print actual beside the latest one, so the baseline is rescored from the existing CSV and only the treatment is re-run. The result is a measurement document with a stated decision rule, not a shipped change.

**Tech Stack:** Python 3.13, pandas, numpy, pytest in `nowcasting_v3/.venv`. One run of about an hour on this Mac (`caffeinate`).

**Spec:** `docs/2026-09-09-unrevised-data-feasibility.md`, section 4 option C. Depends on Tasks 1 and 2 of `docs/superpowers/plans/2026-09-09-first-print-scoring-and-revision-adjusted-headline.md` (the first-release file and module) being merged.

## Global Constraints

- Everything from the parent plan's Global Constraints applies. In particular: do not touch `sources.py`, `model_spec_AU.csv`, the recorded vintage, the saved estimate, or the three seed constants in `tests/test_au_end_to_end.py`.
- The treatment is a substitution INSIDE the loaded `Vintage` object, made after `load_vintage` has accepted the recording. The manifest check is untouched.
- Do not run the treatment on the CI runner. It is a local, one-off measurement written to `docs/measurements/`.
- Decision rule (fixed before the run, do not move it after): adopt the first-print target only if, on the same 40 vintages and three seeds, (a) first-print bias falls by at least 0.05pp, (b) first-print MAE does not rise by more than 0.02pp, and (c) no vintage-seed collapses (`collapsed == 0` throughout). Otherwise record the result and keep the latest-vintage target.

---

### Task 1: The first-release chain index

**Files:**
- Modify: `nowcasting_v3/nyfed/au/first_release.py` (append one function)
- Test: `nowcasting_v3/tests/test_au_first_release.py` (append)

**Interfaces:**
- Produces: `first_release_index(first: pd.Series, anchor: pd.Series) -> pd.Series`. Returns a level series named `gdp`, dated like `anchor`, whose quarter-on-quarter growth equals `first` and whose value at the last quarter present in both equals `anchor` there. Quarters in `anchor` after the last first print are carried over unchanged from `anchor` (there should be none once the file is current).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_au_first_release.py`:

```python
from nyfed.au.first_release import first_release_index


def test_first_release_index_has_first_print_growth_and_the_anchor_level():
    first = _first("2020Q2", [1.0, 2.0, -1.0, 0.5])            # 2020Q2..2021Q1
    anchor = _levels("2020Q1", [0.9, 2.2, -0.8, 0.4], start=500.0)   # 2020Q1..2021Q1
    idx = first_release_index(first, anchor)
    assert idx.name == "gdp"
    assert list(idx.index) == list(anchor.index)
    g = latest_qoq(idx).dropna()
    assert g.to_numpy() == pytest.approx([1.0, 2.0, -1.0, 0.5])
    assert idx.iloc[-1] == pytest.approx(anchor.iloc[-1])


def test_first_release_index_starts_where_both_series_do():
    first = _first("2010Q1", [0.3] * 8)                        # 2010Q1..2011Q4
    anchor = _levels("2011Q1", [0.5] * 3, start=100.0)         # 2011Q1..2011Q4
    idx = first_release_index(first, anchor)
    assert idx.index[0] == anchor.index[0]
    assert len(idx) == 4


def test_first_release_index_refuses_a_gap():
    first = _first("2020Q2", [1.0, 2.0, 0.5])
    first = first.drop(first.index[1])
    anchor = _levels("2020Q1", [1.0, 2.0, 0.5])
    with pytest.raises(ValueError, match="gap"):
        first_release_index(first, anchor)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd nowcasting_v3 && .venv/bin/pytest tests/test_au_first_release.py -v -k index`
Expected: FAIL, `ImportError: cannot import name 'first_release_index'`.

- [ ] **Step 3: Write the function**

Append to `first_release.py`:

```python
def first_release_index(first: pd.Series, anchor: pd.Series) -> pd.Series:
    """A level series with first-print growth, on ``anchor``'s dates and scale.

    THE MODEL TAKES LEVELS. `gdp` enters the panel as chain-volume millions and
    is transformed to annualised growth there, so a first-print TARGET has to
    be handed over as a level series too. There is no such thing as a
    first-print level series (every release rebases), so this cumulates the
    first-print growth rates into an index and pins it to the latest vintage's
    level at the last quarter the two share. Growth is preserved exactly; the
    level is a scale factor the transformation removes.

    The index starts at the quarter BEFORE the first first-print (its base
    level, growth zero by construction) when ``anchor`` has it. Earlier
    quarters of ``anchor`` are dropped, because a level with no first-print
    growth behind it would be latest-vintage growth in disguise. Quarters after
    the last first-print are carried from ``anchor`` as they are.
    """
    a = anchor.dropna().sort_index()
    f = first.dropna().sort_index()
    if len(f) > 1:
        steps = {(b - a_).n for a_, b in zip(f.index.to_period("Q")[:-1],
                                            f.index.to_period("Q")[1:])}
        if steps != {1}:
            raise ValueError("first-release series has a gap; fill it before building an index")
    start = max(a.index[0], f.index[0] - pd.DateOffset(months=3))
    a = a[a.index >= start]
    common = a.index.intersection(f.index)
    if len(common) == 0:
        raise ValueError("no quarter is in both the first-release series and the anchor")
    last = common[-1]
    # Cumulate forward from 1.0, then rescale so the index equals the anchor at `last`.
    growth = f.reindex(a.index[a.index <= last])
    growth.iloc[0] = 0.0                           # the first level is the base
    idx = (1 + growth / 100).cumprod()
    idx = idx * (float(a[last]) / float(idx[last]))
    tail = a[a.index > last]
    out = pd.concat([idx, tail]).sort_index()
    out.name = "gdp"
    return out
```

- [ ] **Step 4: Run the tests**

Run: `cd nowcasting_v3 && .venv/bin/pytest tests/test_au_first_release.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add nowcasting_v3/nyfed/au/first_release.py nowcasting_v3/tests/test_au_first_release.py
git commit -m "feat(v3): a first-release chain index, for a first-print target experiment"
```

---

### Task 2: The `--target` switch and the first-print actual in the backtest tool

**Files:**
- Modify: `nowcasting_v3/tools/plan_c_backtest.py`

**Interfaces:**
- Consumes: `load_first_release`, `first_release_index`, `quarter_end_month` from `nyfed.au.first_release`.
- Produces: CSV columns as before plus `first_print_qq` and `error_first_print_qq`, and a `target_series` column (`latest` or `first_print`). Usage: `tools/plan_c_backtest.py OUT.csv [--target latest|first_print]`.

- [ ] **Step 1: Edit the tool**

Replace the module-level `VINT = load_vintage(...)` and the `FIELDS` list with:

```python
VINT = load_vintage(REPO / "tests/fixtures/au/vintage")
FIRST = load_first_release()

FIELDS = ["asof", "target", "target_date", "horizon_months", "seed",
          "target_series", "nowcast_qq", "forecast_next_qq", "actual_qq",
          "first_print_qq", "error_qq", "error_first_print_qq",
          "gdp_global_loading", "collapsed", "cols", "gdp_obs",
          "deflator_skipped", "seconds"]
```

Add to the imports:

```python
from nyfed.au.first_release import first_release_index, load_first_release
```

Rename the existing `FIRST, LAST = ...` window constants to `WINDOW_FIRST, WINDOW_LAST` (and update the one `pd.date_range(FIRST, LAST, ...)` call) so the name `FIRST` is free for the series.

Replace the start of `main()` through `actual_qq = ...` with:

```python
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--target", choices=("latest", "first_print"), default="latest",
                    help="which GDP series the model is TRAINED on. Scoring is "
                         "always reported against both.")
    args = ap.parse_args()
    out = Path(args.out); t0 = time.perf_counter()

    gdp = VINT.series["gdp"].dropna()
    actual_qq = (gdp / gdp.shift(1) - 1) * 100
    vint = VINT
    if args.target == "first_print":
        # THE TREATMENT. Same recording, same dates, same lags; only the
        # target's VALUES change, to what the ABS printed first. `gdi` and
        # `unit_labour_cost` stay latest-vintage: they are inputs, and the
        # panel is revision-blind by design (see build.py).
        vint = Vintage(series=dict(VINT.series), deflator_sources=VINT.deflator_sources,
                       recorded_at=VINT.recorded_at)
        vint.series["gdp"] = first_release_index(FIRST, gdp)
        print(f"target: first-print index, {vint.series['gdp'].index[0].date()}.."
              f"{vint.series['gdp'].index[-1].date()}", flush=True)
```

Add `import argparse` and `Vintage` to the `from nyfed.au.build import (...)` list. Change `build_panel(asof=stamp, vintage=VINT)` to `build_panel(asof=stamp, vintage=vint)`.

After `act = float(actual_qq.get(tgt, np.nan))` add:

```python
        fp = float(FIRST.get(tgt, np.nan))
```

In `w.writerow({...})` add `"target_series": args.target,`, `"first_print_qq": round(fp, 4),` and `"error_first_print_qq": round(nc - fp, 4) if nc != "" else "",`. In the per-vintage `print`, add `first {fp:6.3f}` after `actual {act:6.3f}`.

- [ ] **Step 2: Smoke it on two vintages**

Temporarily run with the window narrowed by environment rather than editing constants:

```bash
cd nowcasting_v3 && .venv/bin/python - <<'PY'
import tools.plan_c_backtest as b, sys
b.WINDOW_FIRST, b.WINDOW_LAST = "2024-03-01", "2024-04-01"
sys.argv = ["x", "/tmp/smoke_fp.csv", "--target", "first_print"]
b.main()
PY
head -3 /tmp/smoke_fp.csv
```

Expected: two as-ofs, three seeds each, `target_series == first_print`, `first_print_qq` for 2024Q1 equal to 0.1275, `collapsed == 0`. If `tools` is not importable as a package, run the file directly with the two constants edited and restored (do not commit the edit).

- [ ] **Step 3: Commit**

```bash
git add nowcasting_v3/tools/plan_c_backtest.py
git commit -m "feat(v3): plan C backtest can train on the first-print target, and always scores against both"
```

---

### Task 3: Baseline rescore, treatment run, and the measurement document

**Files:**
- Create: `docs/measurements/2026-09-XX-plan-c-first-print-target.csv` (the run; date it the day it runs)
- Create: `docs/measurements/2026-09-XX-first-print-target-ab.md`

- [ ] **Step 1: Rescore the baseline from the existing CSV**

```bash
cd nowcasting_v3 && .venv/bin/python - <<'PY'
import pandas as pd, numpy as np
from nyfed.au.first_release import load_first_release, quarter_end_month
fr = load_first_release()
b = pd.read_csv("../docs/measurements/2026-08-30-plan-c-backtest.csv")
b = b[b.collapsed == 0]; b["nowcast_qq"] = pd.to_numeric(b.nowcast_qq, errors="coerce")
b["first_print_qq"] = [fr[quarter_end_month(t)] for t in b.target]
m = b.groupby(["asof", "target"], as_index=False).agg(nowcast=("nowcast_qq", "median"),
        actual=("actual_qq", "first"), first=("first_print_qq", "first"))
for col in ("actual", "first"):
    e = m.nowcast - m[col]
    print(f"baseline vs {col:6s}: bias {e.mean():+.3f}  MAE {e.abs().mean():.3f}  n={len(m)}")
m.to_csv("/tmp/baseline_rescored.csv", index=False)
PY
```

Expected: `vs actual: bias +0.12 MAE 0.24`, `vs first: bias +0.20 MAE 0.24` (per-vintage medians, 40 as-ofs).

- [ ] **Step 2: Run the treatment**

```bash
cd nowcasting_v3 && caffeinate -i .venv/bin/python -u tools/plan_c_backtest.py \
  ../docs/measurements/$(date +%F)-plan-c-first-print-target.csv --target first_print 2>&1 | tee /tmp/fp_run.log
```

Expected: about 40 as-ofs at roughly 90 s each (three seeds), an hour in total. Every line should show `3/3 ok`. If any as-of prints `UNBUILDABLE` or a seed collapses, stop and report; condition (c) of the decision rule has failed.

- [ ] **Step 3: Score the treatment the same way**

```bash
cd nowcasting_v3 && .venv/bin/python - <<'PY'
import pandas as pd, glob
t = pd.read_csv(sorted(glob.glob("../docs/measurements/*-plan-c-first-print-target.csv"))[-1])
t = t[t.collapsed == 0]; t["nowcast_qq"] = pd.to_numeric(t.nowcast_qq, errors="coerce")
m = t.groupby(["asof", "target"], as_index=False).agg(nowcast=("nowcast_qq", "median"),
        actual=("actual_qq", "first"), first=("first_print_qq", "first"))
for col in ("actual", "first"):
    e = m.nowcast - m[col]
    print(f"treatment vs {col:6s}: bias {e.mean():+.3f}  MAE {e.abs().mean():.3f}  n={len(m)}")
b = pd.read_csv("/tmp/baseline_rescored.csv")
j = b.merge(m, on=["asof", "target"], suffixes=("_base", "_fp"))
print("paired as-ofs:", len(j), " mean loading:", t.gdp_global_loading.mean().round(3),
      " collapses:", int((pd.read_csv(sorted(glob.glob('../docs/measurements/*-plan-c-first-print-target.csv'))[-1]).collapsed == 1).sum()))
PY
```

- [ ] **Step 4: Write the measurement document**

`docs/measurements/<date>-first-print-target-ab.md`, in this shape (fill every number from Steps 1 and 3; no other prose is needed):

```markdown
# First-print target A/B, <date>

Same 40 vintages (2023-01 to 2026-05), same three seeds, same recording. Only the
GDP series the model is trained on changes. Decision rule fixed before the run
in docs/superpowers/plans/2026-09-09-first-print-target-ab-test.md.

| | bias vs first print | MAE vs first print | bias vs latest | MAE vs latest | collapses |
|---|---|---|---|---|---|
| baseline (latest-vintage target) | | | | | 0 |
| treatment (first-print target) | | | | | |

Decision: ADOPT / KEEP BASELINE, because <which conditions passed or failed>.

Mean GDP global loading: baseline <x>, treatment <y>.

Run log: /tmp/fp_run.log (not committed). Data:
docs/measurements/<date>-plan-c-first-print-target.csv.
```

- [ ] **Step 5: Commit**

```bash
git add docs/measurements/*-plan-c-first-print-target.csv docs/measurements/*-first-print-target-ab.md
git commit -m "measure(v3): first-print target A/B against the latest-vintage target"
```

---

## If the decision is ADOPT

Not part of this plan. It needs its own plan because it touches the shipping path: a registry-level switch or a `--target` flag on `tools/estimate_au.py` and `tools/run_au_nowcast.py`, a re-recorded vintage is NOT needed (the substitution is post-load), but the three seed constants in `tests/test_au_end_to_end.py` must be re-measured, `prev_level` in the payload must keep coming from the latest vintage, and the revision adjustment in the parent plan must be switched off (a model trained on first prints already predicts first prints). Write that plan only after the measurement document says ADOPT.
