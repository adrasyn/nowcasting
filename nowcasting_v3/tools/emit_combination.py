"""Emit the combination payloads: the equal-weight average of v2 and v3.

Runs at the end of the weekly v3 job, after v3 has emitted and its track record
has been refreshed. Reads the two models' PUBLISHED payloads -- nothing is
re-estimated here -- and writes `data/latest_combo.json`,
`data/nowcast_history_combo.json` and `data/performance_combo.json` in v3's
schemas, so the homepage components render them unchanged.

Every rule lives in `nyfed.au.combination`, which is pure and tested on
hand-built inputs. This file is the I/O: which files, which columns, what to
print, and where the band parameters come from.

THE BAND PARAMETERS. `pipeline/seed/ci_params_combo.json` is the calibrated
file, written by `tools/combination_backtest.py`: an absolute-error quantile
pair per horizon. Until it exists, this tool computes the POOLED current-
quarter band from the combination measurement CSV and uses it for both
horizons, saying so on stderr and in the payload's `ci_basis`. A next-quarter
figure is built on less data than a current-quarter one, so its true band is
wider than the pooled one: the fallback is provisional and is labelled
provisional wherever it travels.

INPUTS
  data/latest_v2.json                    v2's published week (models + vintages)
  data/latest_v3.json                    v3's published week
  data/nowcast_history_v3.json           v3's weekly runs, both horizons
  data/gdp.json                          the ABS's latest vintage, for levels
  nowcasting_v3/data/gdp_first_release.csv   the target: initial estimates
  pipeline/rba_somp_forecasts_v2.csv     the RBA's year-ended comparison
  docs/measurements/2026-09-12-v2-v3-weekly-combination.csv   the backtest
  pipeline/seed/ci_params_combo.json     the bands, once Task 5 has written it
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from nyfed.au.combination import (HISTORY_SCHEMA, bands_from_errors,
                                  latest_payload, make_is_current, pair_runs,
                                  refusal_from_v3, refusal_payload,
                                  track_record, v2_vintage_rows, with_bands)

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
BACKTEST = ROOT / "docs/measurements/2026-09-12-v2-v3-weekly-combination.csv"
SOMP = ROOT / "pipeline/rba_somp_forecasts_v2.csv"
FIRST = ROOT / "nowcasting_v3/data/gdp_first_release.csv"
CI_PARAMS = ROOT / "pipeline/seed/ci_params_combo.json"

FALLBACK_BASIS = (
    "empirical absolute-error quantiles of the equal-weight v2+v3 average "
    "against the ABS's initial estimate, weekly vintages, pooled over the "
    "current-quarter horizon and centred on the point.")


def _spaced(label: str) -> str:
    """``2026Q2`` -> ``2026 Q2``."""
    return f"{label[:4]} Q{label[-1]}" if " " not in label else label


def read_backtest(path: Path = BACKTEST) -> list[dict]:
    """The combination backtest, one row per weekly vintage."""
    with open(path, newline="") as fh:
        rows = list(csv.DictReader(fh))
    out = []
    for r in rows:
        if not r.get("combo"):
            continue
        out.append({"as_of": r["as_of"][:10], "target": _spaced(r["target"]),
                    "release": (r.get("release") or "")[:10],
                    "first": float(r["first"]), "v2": float(r["v2"]),
                    "v3": float(r["v3"]), "combo": float(r["combo"])})
    return out


def read_first_release(path: Path = FIRST) -> dict:
    with open(path, newline="") as fh:
        return {_spaced(r["quarter"]): float(r["qoq_pct"])
                for r in csv.DictReader(fh) if r.get("qoq_pct")}


def read_somp(path: Path = SOMP) -> dict:
    with open(path, newline="") as fh:
        return {r["target_quarter"]: {"yoy_forecast_pct": float(r["yoy_forecast_pct"]),
                                      "somp_release": r["somp_release"]}
                for r in csv.DictReader(fh) if r.get("yoy_forecast_pct")}


def load_params(backtest: list[dict], path: Path = CI_PARAMS) -> dict:
    """The per-horizon bands: the calibrated file, or the pooled fallback.

    The fallback exists so the emitter runs before `tools/combination_backtest.py`
    has been written, and it is deliberately loud: a `next` band copied from the
    `current` horizon understates a forecast's uncertainty.
    """
    if path.exists():
        params = json.loads(path.read_text())
        missing = [h for h in ("current", "next") if h not in params]
        if missing:
            raise SystemExit(f"{path}: missing horizon block(s) {missing}")
        params.setdefault("source", {"file": str(path.relative_to(ROOT))})
        return params
    pooled = bands_from_errors(r["combo"] - r["first"] for r in backtest)
    print(f"WARNING: {path.relative_to(ROOT)} does not exist yet; the "
          f"next-quarter band is PROVISIONAL -- it reuses the pooled "
          f"current-quarter parameters (p68 {pooled['p68']}, p95 "
          f"{pooled['p95']}, n {pooled['n']}). Run tools/combination_backtest.py "
          f"to calibrate it.", file=sys.stderr, flush=True)
    return {"schema": "combo-ci-fallback-1", "basis": FALLBACK_BASIS,
            "current": pooled, "next": dict(pooled), "provisional_next": True,
            "source": {"backtest": str(BACKTEST.relative_to(ROOT))}}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--asof", default=None,
                    help="pretend today is this date (YYYY-MM-DD): drop later "
                         "runs, so the page shows the quarter in force then")
    ap.add_argument("--out", default=str(DATA))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    asof = args.asof

    v2 = json.loads((DATA / "latest_v2.json").read_text())
    v3 = json.loads((DATA / "latest_v3.json").read_text())
    history = json.loads((DATA / "nowcast_history_v3.json").read_text())["runs"]
    gdp = json.loads((DATA / "gdp.json").read_text())["series"]

    generated_at = (f"{asof}T00:00:00+00:00" if asof else
                    datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00"))

    # A refusal is an outcome, not an error: half a combination is v3 published
    # under another name, so the page declines for v3's reason.
    if v3.get("status") != "ok":
        payload = refusal_from_v3(v3, generated_at=generated_at)
        (out / "latest_combo.json").write_text(json.dumps(payload, indent=2) + "\n")
        print(f"refused: {payload['refusal_reason']} -- {payload['refusal_detail']}")
        return 0

    if asof:
        # PREVIEW MODE. Everything published after the pretend date is dropped,
        # including v2's own `models` block when its run postdates the date --
        # that block is a run, not a timeless field, and keeping it would put
        # next week's figure on this week's Monday.
        v3 = {**v3, "as_of": min(v3["as_of"], asof)}
        history = [r for r in history if r["run_date"] <= asof]
        models = {} if (v2.get("as_of") or "") > asof else v2.get("models") or {}
        v2 = {**v2, "as_of": min(v2.get("as_of") or asof, asof), "models": models,
              "vintages": [r for r in (v2.get("vintages") or [])
                           if r["run_date"] <= asof]}

    backtest = read_backtest()
    params = load_params(backtest)
    is_current = make_is_current()

    rows = with_bands(pair_runs(history, v2_vintage_rows(v2)), params,
                      is_current=is_current)
    if not rows:
        payload = refusal_payload(
            reason="no combination", generated_at=generated_at,
            detail="no run date has both models nowcasting the same quarter",
            asof=v3["as_of"])
        (out / "latest_combo.json").write_text(json.dumps(payload, indent=2) + "\n")
        print(f"refused: {payload['refusal_detail']}")
        return 0

    try:
        latest = latest_payload(rows, v3_latest=v3, v2_latest=v2, gdp_series=gdp,
                                params=params, generated_at=generated_at,
                                is_current=is_current)
    except ValueError as exc:
        payload = refusal_payload(
            reason="no v2 figure for the current quarter", detail=str(exc),
            generated_at=generated_at, asof=v3["as_of"])
        (out / "latest_combo.json").write_text(json.dumps(payload, indent=2) + "\n")
        print(f"refused: {payload['refusal_detail']}")
        return 0

    perf = track_record(backtest, rows, gdp, read_first_release(), read_somp())

    (out / "latest_combo.json").write_text(json.dumps(latest, indent=2) + "\n")
    (out / "nowcast_history_combo.json").write_text(
        json.dumps({"schema": HISTORY_SCHEMA, "runs": rows}, indent=2) + "\n")
    (out / "performance_combo.json").write_text(json.dumps(perf, indent=2) + "\n")

    for h in latest["horizons"]:
        c = h["components"]
        print(f"{h['quarter']} ({h['kind']}): combination {h['qoq_growth_pct']:+.3f}% "
              f"= mean(v2 {c['v2']:+.3f}, v3 {c['v3']:+.3f}); "
              f"68% band [{h['ci_68_low']:+.2f}, {h['ci_68_high']:+.2f}], "
              f"{h.get('months_with_data', '?')} month(s) of data")
    stale = latest["components"]["v2"].get("stale_days")
    print(f"as of {latest['as_of']} (v2 run {latest['components']['v2']['run_date']}"
          f"{f', {stale} days old' if stale else ''}, v3 run "
          f"{latest['components']['v3']['as_of']}); "
          f"{len(latest['horizons'])} horizon(s), {len(latest['vintages'])} vintages "
          f"for {latest['target_quarter']} and after, {len(rows)} paired runs")
    rba = perf["rba_comparison"]
    print(f"track record: {perf['n']} quarters ({perf['n_live']} live) "
          f"MAE {perf['mae_pct']} bias {perf['bias_pct']:+} "
          f"(v2 {perf['v2_mae_pct']}, v3 {perf['v3_mae_pct']}); "
          f"RBA n={rba['n']} ours {rba['ours_mae']} rba {rba['rba_mae']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
