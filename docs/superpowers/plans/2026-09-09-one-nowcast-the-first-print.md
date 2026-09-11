# One Nowcast, the First Print — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The site and the v3 payloads present exactly one GDP nowcast, defined as the nowcast of the ABS's first print, and score it against the first print only.

**Architecture:** The model is unchanged. The published `qoq_growth_pct` becomes the first-print nowcast: the model's estimate less the rolling mean revision (`revision_adjustment.pp`, about 0.10pp). The model's own figure is kept beside it as `model_qoq_growth_pct` for provenance, never as a second headline. Bands, levels, the history record and the track record all move to that basis in one change. A missing revision estimate is a refusal, not a silent fallback to the model figure.

**Tech Stack:** Python 3.13 in `nowcasting_v3/.venv`; Next.js + TypeScript at the root.

**Spec (decision and evidence):** the user's instruction of 9 September 2026 ("I don't want to present two GDP nowcasts. I'm only interested in nowcasting the first print") and `docs/measurements/2026-09-09-first-print-target-ab.md`, which shows the model less the adjustment is the best first-print nowcast available (bias +0.09pp, MAE 0.18pp vs first prints over 40 vintages; the retrained first-print target reaches +0.13 / 0.19). Builds on branch `feat/first-print-scoring` at b556904.

## Global Constraints

- Python from `nowcasting_v3/` with `.venv/bin/python` / `.venv/bin/pytest`; `filterwarnings = ["error"]`. Run the focused test files named in each task; the full suite (30 min) runs once before the final review.
- `nyfed/au/emit.py` must not import `first_release`; `revision` stays duck-typed (`.pp`, `.as_dict()`).
- Do not change `nyfed/au/sources.py`, `model_spec_AU.csv`, `tests/fixtures/au/vintage/`, `state/au_estimate.npz`, `docs/measurements/`.
- Field semantics after this plan, everywhere: `qoq_growth_pct` = first-print nowcast; `model_qoq_growth_pct` = the model's own estimate; `revision_adjustment.pp` = the difference. `expected_first_print_pct` no longer exists anywhere.
- Site copy: the word "nowcast" refers to the first-print number. Never show the model figure as a second nowcast; it may appear once, in the methodology panel, as provenance.
- Commit trailer:
```
Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01SyVuNnQdjveYgZLXQj4Szt
```
- `data/latest_v3.json` in the working tree is a local preview; regenerate it locally to test but never commit a regenerated copy. `data/nowcast_history_v3.json` is committed state: the migration in Task 1 runs in the weekly job, so a local run that migrates it must be reverted with `git checkout` before committing.

---

### Task 1: The payload and the history record move to the first-print basis

**Files:**
- Modify: `nowcasting_v3/nyfed/au/emit.py` (`nowcast_payload`, `SCHEMA`, new `migrate_history_runs`)
- Modify: `nowcasting_v3/tools/run_au_nowcast.py` (revision is required; history rows; `_record` migrates)
- Modify: `nowcasting_v3/tools/check_payload.py` (invariants)
- Test: `nowcasting_v3/tests/test_au_emit.py`, `nowcasting_v3/tests/test_check_payload.py`

**Interfaces:**
- Produces in `data/latest_v3.json`: `schema: "v3-preview-2"`, `basis: "abs_first_print"`, top-level `revision_adjustment` (never null when status ok); per horizon `qoq_growth_pct` (first-print nowcast), `model_qoq_growth_pct`, `annualised_growth_pct` (the model's own, unchanged), bands `ci_*` shifted by `-pp`, `gdp_chain_volume_millions` from the first-print nowcast. No `expected_first_print_pct`.
- Produces in `data/nowcast_history_v3.json`: `schema: "v3-history-2"`; every run row has `qoq_growth_pct` (first-print basis), `model_qoq_growth_pct`, `ci_*` on the first-print basis, `revision_adjustment_pp`; rows migrated from v3-history-1 carry `adjusted_retroactively: true`.
- `migrate_history_runs(runs: list[dict], pp: float) -> list[dict]` in `emit.py`: for each row lacking `model_qoq_growth_pct`, set `model_qoq_growth_pct = qoq_growth_pct`, `qoq_growth_pct = round(model - pp, 4)`, shift each present `ci_*` by `-pp` (4 dp), set `revision_adjustment_pp = pp`, `adjusted_retroactively = True`, and delete `expected_first_print_pct`. Rows that already have `model_qoq_growth_pct` are returned unchanged.
- A refusal with `refusal_reason = "no revision estimate"` when `mean_revision` fails or the file is unusable.

- [ ] **Step 1: Write the failing tests**

In `tests/test_au_emit.py`, replace the two Task-4 tests (`test_the_expected_first_print_is_the_nowcast_less_the_mean_revision`, `test_without_a_revision_estimate_the_payload_carries_neither_field`) with:

```python
def test_the_published_nowcast_is_the_first_print_basis(panel_stub):
    p = nowcast_payload(panel=panel_stub, horizons=[("2026 Q3", 2.0), ("2026 Q4", 2.4)],
                        draws=np.full((30, 2), 2.0), prev_level=700000.0,
                        prev_quarter="2026 Q2", generated_at="t", asof="2026-09-07",
                        gdp_global_loading=1.4, collapse_floor=0.3,
                        n_gs=10, n_burn=5, seed=4, revision=_revision())
    assert p["schema"] == "v3-preview-2"
    assert p["basis"] == "abs_first_print"
    assert p["revision_adjustment"]["pp"] == 0.0834
    for h in p["horizons"]:
        model = float(annualised_to_qoq(h["annualised_growth_pct"]))
        assert h["model_qoq_growth_pct"] == pytest.approx(model, abs=1e-4)
        assert h["qoq_growth_pct"] == pytest.approx(model - 0.0834, abs=1e-4)
        assert "expected_first_print_pct" not in h
        for k in ("ci_68_low", "ci_68_high", "ci_95_low", "ci_95_high"):
            assert h[k] == pytest.approx(model - 0.0834, abs=1e-3)   # constant draws
    nc = p["horizons"][0]
    assert nc["gdp_chain_volume_millions"] == round(700000.0 * (1 + nc["qoq_growth_pct"] / 100))


def test_a_payload_cannot_be_built_without_a_revision_estimate(panel_stub):
    with pytest.raises(ValueError, match="revision"):
        nowcast_payload(panel=panel_stub, horizons=[("2026 Q3", 2.0)],
                        draws=np.full((30, 1), 2.0), prev_level=700000.0,
                        prev_quarter="2026 Q2", generated_at="t", asof="2026-09-07",
                        gdp_global_loading=1.4, collapse_floor=0.3,
                        n_gs=10, n_burn=5, seed=4)


def test_migrate_history_runs_moves_old_rows_to_the_first_print_basis():
    old = [{"run_date": "2026-08-31", "target_quarter": "2026 Q2", "qoq_growth_pct": 0.6354,
            "ci_68_low": 0.3, "ci_68_high": 0.9, "ci_95_low": 0.0, "ci_95_high": 1.2,
            "expected_first_print_pct": None},
           {"run_date": "2026-09-14", "target_quarter": "2026 Q3", "qoq_growth_pct": 0.64,
            "model_qoq_growth_pct": 0.74, "revision_adjustment_pp": 0.1}]
    new = migrate_history_runs(old, 0.0989)
    a, b = new
    assert a["model_qoq_growth_pct"] == 0.6354
    assert a["qoq_growth_pct"] == pytest.approx(0.6354 - 0.0989, abs=1e-4)
    assert a["ci_68_low"] == pytest.approx(0.3 - 0.0989, abs=1e-4)
    assert a["revision_adjustment_pp"] == 0.0989 and a["adjusted_retroactively"] is True
    assert "expected_first_print_pct" not in a
    assert b == old[1]                          # already on the new basis: untouched
    assert old[0]["qoq_growth_pct"] == 0.6354   # input not mutated
```

Add `migrate_history_runs` to the import from `nyfed.au.emit`. In the refusal test's banned-key list replace `"expected_first_print_pct"` with `"model_qoq_growth_pct"` and keep `"revision_adjustment"`.

In `tests/test_check_payload.py`: update `_ok()` so each horizon carries `model_qoq_growth_pct` and `qoq_growth_pct = model - 0.08`, no `expected_first_print_pct`, top-level `revision_adjustment: {"pp": 0.08}`, `basis: "abs_first_print"`. Replace the three Task-5 tests with:

```python
def test_a_nowcast_that_is_not_the_model_less_the_adjustment_is_a_bug():
    d = _ok()
    d["horizons"][0]["qoq_growth_pct"] = d["horizons"][0]["model_qoq_growth_pct"] + 1.0
    assert any("model_qoq_growth_pct" in p for p in check_payload(d, today="2026-09-07"))


def test_an_ok_payload_without_an_adjustment_is_incoherent():
    d = _ok()
    d["revision_adjustment"] = None
    assert any("revision_adjustment" in p for p in check_payload(d, today="2026-09-07"))


def test_an_implausible_adjustment_is_refused():
    d = _ok()
    d["revision_adjustment"]["pp"] = 0.9
    for h in d["horizons"]:
        h["qoq_growth_pct"] = h["model_qoq_growth_pct"] - 0.9
    assert any("revision_adjustment" in p for p in check_payload(d, today="2026-09-07"))


def test_a_leftover_expected_first_print_field_is_a_bug():
    d = _ok()
    d["horizons"][0]["expected_first_print_pct"] = 0.5
    assert any("expected_first_print_pct" in p for p in check_payload(d, today="2026-09-07"))
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd nowcasting_v3 && .venv/bin/pytest tests/test_au_emit.py tests/test_check_payload.py -q`
Expected: failures on `migrate_history_runs` import, `basis`, `model_qoq_growth_pct`, and the invariants.

- [ ] **Step 3: emit.py**

Set `SCHEMA = "v3-preview-2"`. In `nowcast_payload`, `revision` stays the last keyword parameter but is required in effect:

```python
    if revision is None:
        raise ValueError(
            "no revision estimate: the published figure is the nowcast of the "
            "ABS first print, which is the model's estimate less the mean "
            "revision. Without that estimate there is no first-print number to "
            "publish; refuse rather than print the model's figure under that name.")
    pp = float(revision.pp)
```

In the horizon loop: `model = float(annualised_to_qoq(ann))`, `qoq = model - pp`; bands: `q = np.nanpercentile(annualised_to_qoq(col[np.isfinite(col)]), [...]) - pp`; entry gets `"qoq_growth_pct": _pct(qoq), "model_qoq_growth_pct": _pct(model), "annualised_growth_pct": _pct(ann)`; drop the `expected_first_print_pct` line; `gdp_chain_volume_millions` uses `qoq`. Top level: add `"basis": "abs_first_print",` after `"status"`, keep `"revision_adjustment": revision.as_dict()`. Update the module comment block: the published figure is the first-print nowcast; the model's own figure travels beside it as provenance.

Add:

```python
def migrate_history_runs(runs: list[dict], pp: float) -> list[dict]:
    """Move v3-history-1 rows onto the first-print basis. Pure; returns new dicts.

    A row written before 2026-09-09 holds the MODEL's figure in `qoq_growth_pct`.
    Since then `qoq_growth_pct` is the first-print nowcast (model less the mean
    revision) and the model's figure lives in `model_qoq_growth_pct`. Old rows
    are shifted by TODAY's adjustment and say so, because the adjustment they
    would have carried on the day was never computed. Rows already on the new
    basis pass through untouched.
    """
    out = []
    for r in runs:
        if "model_qoq_growth_pct" in r:
            out.append(dict(r)); continue
        n = dict(r)
        model = float(n["qoq_growth_pct"])
        n["model_qoq_growth_pct"] = round(model, 4)
        n["qoq_growth_pct"] = round(model - pp, 4)
        for k in ("ci_68_low", "ci_68_high", "ci_95_low", "ci_95_high"):
            if k in n and n[k] is not None:
                n[k] = round(float(n[k]) - pp, 4)
        n.pop("expected_first_print_pct", None)
        n["revision_adjustment_pp"] = round(pp, 4)
        n["adjusted_retroactively"] = True
        out.append(n)
    return out
```

- [ ] **Step 4: run_au_nowcast.py**

The revision block: on failure write `refusal_payload(reason="no revision estimate", detail=str(exc)[:400], ...)` and `return 0` (a refusal is a successful run). Both `written.append` dicts: `"qoq_growth_pct": round(model - revision.pp, 4)`, `"model_qoq_growth_pct": round(model, 4)`, the four `ci_*` values shifted by `-revision.pp`, `"revision_adjustment_pp": round(revision.pp, 4)`; remove `expected_first_print_pct`. `_record` gains a `pp: float` parameter: after loading `hist`, if `hist.get("schema") != "v3-history-2"`, set `hist["runs"] = migrate_history_runs(hist["runs"], pp)` and `hist["schema"] = "v3-history-2"`, printing how many rows were migrated. Pass `revision.pp` at the call site.

- [ ] **Step 5: check_payload.py**

Replace the Task-5 block with:

```python
    adj = d.get("revision_adjustment")
    if adj is None:
        bad.append("status is 'ok' but revision_adjustment is absent: the published "
                   "figure is the first-print nowcast and needs the adjustment that made it")
    else:
        pp = adj.get("pp")
        if not isinstance(pp, (int, float)) or isinstance(pp, bool) or abs(pp) > 0.5:
            bad.append(f"revision_adjustment.pp is {pp!r}; expected a number within +-0.5")
        else:
            for h in horizons:
                if "expected_first_print_pct" in h:
                    bad.append(f"{h['quarter']} carries expected_first_print_pct, a field "
                               "retired when qoq_growth_pct became the first-print nowcast")
                model = h.get("model_qoq_growth_pct")
                if model is None or abs(h["qoq_growth_pct"] - (model - pp)) > 1e-3:
                    bad.append(f"{h['quarter']}: qoq_growth_pct {h['qoq_growth_pct']!r} is not "
                               f"model_qoq_growth_pct - revision_adjustment.pp ({model!r} - {pp})")
```

- [ ] **Step 6: Tests, replay, commit**

Run: `cd nowcasting_v3 && .venv/bin/pytest tests/test_au_emit.py tests/test_check_payload.py tests/test_au_first_release.py -q` — all pass. Then `.venv/bin/python -u tools/run_au_nowcast.py --vintage --quick --out /tmp/latest_v3_fp.json && .venv/bin/python tools/check_payload.py /tmp/latest_v3_fp.json` — exit 0; the log shows the migration count; then `git checkout data/nowcast_history_v3.json`. Commit the four files:

```bash
git commit -m "feat(v3): the published nowcast is the first-print nowcast; the model's figure rides beside it"
```

---

### Task 2: The track record scores the first-print nowcast against the first print

**Files:**
- Modify: `nowcasting_v3/tools/emit_backtest_json.py`

**Interfaces:**
- Produces in `data/performance_v3.json`: per row `qoq_nowcast_pct` (first-print basis: backtest rows are the backtest median less today's `pp`; live rows are the history row's `qoq_growth_pct`, already on that basis after Task 1's migration), `qoq_model_nowcast_pct`, `qoq_actual_pct` (the ABS first print), `qoq_error_pp` (nowcast minus first print), `qoq_latest_vintage_pct` (reference only), `adjusted_retroactively` (bool, from the live row), plus the existing `is_live`, `live_run_date`, YoY and RBA fields unchanged. Top level: `basis: "abs_first_print"`, `mae_pct` and `bias_pct` on that basis, `revision_adjustment_pp`, `model_bias_vs_latest_pct` and `model_mae_vs_latest_pct` (the model's own figure against the latest vintage, for the methodology fine print), `n`. Remove `qoq_first_print_pct`, `qoq_error_first_print_pp`, `n_first_print`, `mae_first_print_pct`, `bias_first_print_pct`, `bias_first_print_adjusted_pct`.
- `data/backtest_v3.json`: `by_quarter` rows carry `v3` (first-print basis), `v3_model`, `v2`, `first_print`, `actual` (latest); `scores.v3` is against `first_print`; `scores.v3_model` and `scores.v2` against both; `notes.basis` explains.

- [ ] **Step 1: Rewrite the scoring**

`revision` is required here too: if `mean_revision` fails, print `::error::` and `return 1` (a track record on the wrong basis must not be published). `pp = revision.pp`. For each `last` row: `model_qq = published["model_qoq_growth_pct"] if published else float(r.nowcast_qq)`; `nowcast_qq = published["qoq_growth_pct"] if published else model_qq - pp`; `fp = first[quarter_end_month(r.target)]` (raise with the quarter named if absent: every scored quarter must have a first print); `actual_qq = fp`; `latest_qq = float(r.actual_qq)`. Levels: `nowcast_lvl = lvl * (1 + nowcast_qq/100)`, `actual_lvl = lvl * (1 + fp/100)`. Aggregates as named above. The v2 block: `v3 = m.nowcast_qq - pp`, `v3_model = m.nowcast_qq`; scores for `v3` against `first_print`, for `v3_model` and `v2` against both `first_print` and `actual`.

- [ ] **Step 2: Run and check**

`cd nowcasting_v3 && .venv/bin/python tools/emit_backtest_json.py` then:
```bash
cd .. && python3 -c "
import json; p=json.load(open('data/performance_v3.json'))
print(p['basis'], p['bias_pct'], p['mae_pct'], p['revision_adjustment_pp'], p['model_bias_vs_latest_pct'])
assert all('qoq_first_print_pct' not in e for e in p['errors'])
print(p['errors'][-1])"
```
Expected: `abs_first_print`, bias about 0.10, MAE about 0.19, adjustment about 0.10, model bias vs latest 0.12. Commit `emit_backtest_json.py`, `data/performance_v3.json`, `data/backtest_v3.json`.

---

### Task 3: The site shows one nowcast

**Files:**
- Modify: `src/lib/types.ts`, `src/components/PerformanceSection.tsx`, `src/components/V3Headline.tsx`, `src/components/V3MethodologyPanel.tsx`, `src/app/page.tsx`, `src/lib/data.test.ts`, `tests/site.spec.ts`

- [ ] **Step 1: Types.** `V3Horizon`: remove `expected_first_print_pct`, add `model_qoq_growth_pct?: number`. `LatestV3`: add `basis?: string`; `revision_adjustment` stays. `AccuracyError`: remove `qoq_first_print_pct`/`qoq_error_first_print_pp`; add `qoq_model_nowcast_pct?`, `qoq_latest_vintage_pct?`, `adjusted_retroactively?`. `Performance`: remove the five `*first_print*` fields; add `basis?`, `revision_adjustment_pp?`, `model_bias_vs_latest_pct?`, `model_mae_vs_latest_pct?`, `n?`.
- [ ] **Step 2: PerformanceSection.** Remove the `firstPrint` dual rendering. Keep one prop, `actualLabel?: string` (default `"Actual"`), used for the actual column header; the tiles read `mae_pct`/`bias_pct` as before with `tileBasis` in the sub. The error cell goes back to `e.qoq_error_pp ?? e.error_pct`. Table min-width back to 440px and the comment restored to its 2026-09 wording minus the eight-column paragraph. v1 and v2 pages render as before.
- [ ] **Step 3: page.tsx.** `actualLabel="First print"`, `tileBasis="vs the ABS first print"`, notes: `"Actual is the ABS's first print of the quarter, the number this nowcast is built to match. MAE (mean absolute error) is the average size of the miss, ignoring direction. Bias is the average signed miss, so a positive value means the nowcast tends to come in high. The RBA column shows the RBA's forecast published mid-quarter for each June and December quarter."` Remove `firstPrint`.
- [ ] **Step 4: V3Headline.** Eyebrow: `{formatQuarterLabel(nowcast.quarter)}: GDP nowcast, first print`. Remove the companion paragraph. Nothing else changes (the bars and the YoY already read `qoq_growth_pct`, which is now the first-print figure).
- [ ] **Step 5: V3MethodologyPanel.** One sentence block: `This is a nowcast of the figure the ABS will print first, which it later revises up by about {revision_adjustment_pp}pp on average; the model's own estimate for this quarter is {model_qoq_growth_pct}%, and the published number is that less the adjustment. Over the last {n} quarters the published nowcast has missed the first print by {mae_pct}pp on average{, and has run {bias}pp high|low}. The model's own figure against the latest revised data misses by {model_mae_vs_latest_pct}pp with a bias of {model_bias_vs_latest_pct}pp.` (Pass `latest` into the panel if it does not already receive it; otherwise read the nowcast horizon from props as `V3Headline` does.) Gate each clause on its field being present.
- [ ] **Step 6: Tests.** `data.test.ts`: assert `basis === "abs_first_print"`, `typeof bias_pct === "number"`, every error has `qoq_model_nowcast_pct` and `qoq_actual_pct` numbers, and, when `latestV3.revision_adjustment` is present, the nowcast horizon has `model_qoq_growth_pct` and `qoq_growth_pct ≈ model − pp` within 1e-3. `site.spec.ts`: keep `"First print"` visible; add `await expect(page.getByText("GDP nowcast, first print")).toBeVisible();`. Run `npm test`, `npx eslint src`, `rm -rf .next && npm run build`, Playwright if browsers are present (they are). Commit.

---

### Task 4: Docs and the local preview

- [ ] `nowcasting_v3/README.md` "First prints and the revision adjustment" section: rewrite to say the published nowcast IS the first-print nowcast (model less adjustment), where the model's figure lives, that a missing estimate is a refusal, and that history rows before 2026-09-09 were shifted retroactively and flagged.
- [ ] Regenerate the local preview: `cd nowcasting_v3 && .venv/bin/python -u tools/run_au_nowcast.py --quick` (live), `.venv/bin/python tools/emit_backtest_json.py`, `cd .. && git checkout data/nowcast_history_v3.json`, `rm -rf .next && npm run build`, restart `python3 -m http.server 3000 -d out`. Do not commit `data/latest_v3.json`. Commit the README.

## Acceptance

- The homepage shows one nowcast number, labelled as the first-print nowcast, and no "expected first print" line.
- `latest_v3.json` has `basis`, `model_qoq_growth_pct` per horizon, and `qoq_growth_pct = model − pp` within 1e-3; `check_payload` enforces it and refuses an ok payload without an adjustment.
- `performance_v3.json` `bias_pct` is about +0.10 and `mae_pct` about 0.19 against first prints.
- `nowcast_history_v3.json` is `v3-history-2` after the next weekly run, with old rows flagged `adjusted_retroactively`.
