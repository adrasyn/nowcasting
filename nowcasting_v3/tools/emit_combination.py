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
pair per horizon. It is required. This tool once fell back to the pooled
current-quarter band when the file was missing, from the weeks before the
backtest existed; the file has been committed since, so the fallback could only
ever fire on a broken checkout, where publishing a next-quarter band that
understates a forecast's uncertainty is worse than not publishing.

INPUTS
  data/indicators_v2.json                v2's input panel, for the merged one
  data/indicators_v3.json                v3's input panel
  data/latest_v2.json                    v2's published week (models + vintages)
  data/latest_v3.json                    v3's published week
  data/nowcast_history_v3.json           v3's weekly runs, both horizons
  data/gdp.json                          the ABS's latest vintage, for levels
  nowcasting_v3/data/gdp_first_release.csv   the target: initial estimates
  pipeline/rba_somp_forecasts_v2.csv     the RBA's year-ended comparison
  docs/measurements/2026-09-12-v2-v3-weekly-combination-two-horizons.csv
                                         the backtest behind the track record
  pipeline/seed/ci_params_combo.json     the bands
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from nyfed.au.combination import (HISTORY_SCHEMA, _spaced, fill_next_release,
                                  latest_payload, make_is_current,
                                  mark_updated, merge_indicators, pair_runs,
                                  quarter_shift, refusal_from_v3,
                                  refusal_payload, track_record,
                                  v2_vintage_rows, with_bands)
from nyfed.au.emit import gdp_release_date

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
BACKTEST = (ROOT /
            "docs/measurements/2026-09-12-v2-v3-weekly-combination-two-horizons.csv")
SOMP = ROOT / "pipeline/rba_somp_forecasts_v2.csv"
FIRST = ROOT / "nowcasting_v3/data/gdp_first_release.csv"
CI_PARAMS = ROOT / "pipeline/seed/ci_params_combo.json"


def read_backtest(path: Path = BACKTEST) -> list[dict]:
    """The combination backtest's CURRENT-horizon rows, one per weekly vintage.

    THE TWO-HORIZON CSV IS THE ONE THE BANDS WERE CALIBRATED ON, so the track
    record is read from it too rather than from the single-horizon file it
    superseded; two measurement files describing the same weeks is how they
    start to disagree.

    ONLY THE CURRENT HORIZON. The track record scores the last figure published
    before a quarter printed, and that figure is a current-quarter one by
    definition -- a next-horizon row for the same quarter was made before its
    predecessor had even printed, which is a different and much harder call.
    `combination._final_live_rows` applies exactly this rule to the live rows.

    THE RELEASE DATE IS DERIVED, not read: this CSV has no `release` column.
    `gdp_release_date` is the ABS's scheduling rule and reproduces the column
    the earlier file carried.
    """
    with open(path, newline="") as fh:
        rows = list(csv.DictReader(fh))
    out = []
    for r in rows:
        if not r.get("combo") or (r.get("horizon") or "current") != "current":
            continue
        target = _spaced(r["target"])
        out.append({"as_of": r["as_of"][:10], "target": target,
                    "release": gdp_release_date(target) or "",
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


def load_params(path: Path = CI_PARAMS) -> dict:
    """The per-horizon bands. The calibrated file is required.

    `tools/combination_backtest.py` writes it and it is committed. A missing
    file is a broken checkout, not a state to publish around: every band on the
    page would have to come from somewhere else, and the only "somewhere else"
    available is the current-quarter band, which understates a forecast's
    uncertainty on the horizon it would be reused for.
    """
    if not path.exists():
        raise SystemExit(
            f"{path.relative_to(ROOT)} is missing; it holds the published bands "
            "and is required. Run tools/combination_backtest.py to write it.")
    params = json.loads(path.read_text())
    missing = [h for h in ("current", "next") if h not in params]
    if missing:
        raise SystemExit(f"{path}: missing horizon block(s) {missing}")
    params.setdefault("source", {"file": str(path.relative_to(ROOT))})
    return params


def emit_indicators(out: Path, *, next_gdp_release_date: str | None = None) -> None:
    """Write `data/indicators_combo.json`: the union of the two input panels.

    WRITTEN BEFORE ANY REFUSAL CAN RETURN, and independently of whether the two
    models' figures pair this week. The panel describes what the models READ,
    which is a fact about the week's data even when no figure is published, and
    the homepage renders it from its own file -- so a refusal that skipped this
    would leave yesterday's merged panel beside today's refusal, or none.

    `next_gdp_release_date` comes from `latest_v3.json` -- v3's own next
    national-accounts target -- and is passed through to `fill_next_release`
    for the three series (`gdp`, `gdi`, `unit_labour_cost`) that print on that
    day. Every other v3-only series without a scraped date is filled by
    `fill_next_release`'s sibling or publication-schedule rules.

    THE "UPDATED THIS WEEK" DOT, FOR THE EIGHT v3-ONLY SERIES. v2's job stamps
    `updated_this_run` on its own 31 series; v3's emitter never has, so those
    eight could never show the dot even on the week their own release landed.
    `mark_updated` fixes that by comparing this run's merged panel against the
    file this run is about to overwrite -- i.e. LAST WEEK'S merged panel, on
    the weekly runner where the existing file is last Monday's commit. That is
    exactly the comparison wanted. A re-run on the same day instead compares
    against the same day's own file, so nothing looks newer and no dot shows;
    that is an acceptable gap, not a bug, since a same-day re-run means the
    input data hasn't changed either.
    """
    v3_path, v2_path = DATA / "indicators_v3.json", DATA / "indicators_v2.json"
    if not v3_path.exists():
        print(f"indicators: no {v3_path.name}; nothing to merge")
        return
    combo_path = out / "indicators_combo.json"
    previous = None
    if combo_path.exists():
        previous = (json.loads(combo_path.read_text()) or {}).get("indicators")
    v3 = json.loads(v3_path.read_text())
    v2 = json.loads(v2_path.read_text()) if v2_path.exists() else None
    merged = merge_indicators(v3, v2)
    merged["indicators"] = fill_next_release(
        merged["indicators"], next_gdp_release_date=next_gdp_release_date)
    merged["indicators"] = mark_updated(merged["indicators"], previous)
    combo_path.write_text(json.dumps(merged, indent=2) + "\n")
    n3 = len(v3.get("indicators") or [])
    n2 = len((v2 or {}).get("indicators") or [])
    n = len(merged["indicators"])
    missing = [i["id"] for i in merged["indicators"]
              if not i.get("next_release_estimate")]
    flagged = [i["id"] for i in merged["indicators"]
              if "v2" not in (i.get("models") or []) and i.get("updated_this_run")]
    print(f"indicators: v3 {n3} + v2 {n2} -> {n} published "
          f"({n3 + n2 - n} pair(s) merged as the same series)")
    print(f"indicators: {len(flagged)} v3-only series flagged updated_this_run "
          f"{flagged if flagged else ''}")
    if missing:
        print(f"indicators: no next_release_estimate for {missing}")


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

    v3 = json.loads((DATA / "latest_v3.json").read_text())

    emit_indicators(out, next_gdp_release_date=v3.get("next_gdp_release_date"))

    v2 = json.loads((DATA / "latest_v2.json").read_text())
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

    is_current = make_is_current()
    current_quarter = None
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
        # AND THE QUARTER IS THE PRETEND DATE'S, NOT THE PAYLOAD'S. A live run
        # takes the current quarter from v3's own `target_quarter`, which v3
        # derived from the data the ABS had actually released that morning. A
        # preview has no such payload -- `latest_v3.json` is today's -- so the
        # release calendar is the best available account of which quarter was
        # current then, the same rule every historical row's band uses.
        current_quarter = next(q for q in (quarter_shift(f"{asof[:4]} Q1", k)
                                           for k in range(-4, 8))
                               if is_current(asof, q))

    backtest = read_backtest()
    params = load_params()

    rows = with_bands(pair_runs(history, v2_vintage_rows(v2),
                                is_current=is_current),
                      params, is_current=is_current)
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
                                is_current=is_current,
                                current_quarter=current_quarter)
    except ValueError as exc:
        payload = refusal_payload(
            reason="no v2 figure for the current quarter", detail=str(exc),
            generated_at=generated_at, asof=v3["as_of"])
        (out / "latest_combo.json").write_text(json.dumps(payload, indent=2) + "\n")
        print(f"refused: {payload['refusal_detail']}")
        return 0

    perf = track_record(backtest, rows, gdp, read_first_release(), read_somp(),
                        is_current=is_current)

    (out / "latest_combo.json").write_text(json.dumps(latest, indent=2) + "\n")
    (out / "nowcast_history_combo.json").write_text(
        json.dumps({"schema": HISTORY_SCHEMA, "runs": rows}, indent=2) + "\n")
    (out / "performance_combo.json").write_text(json.dumps(perf, indent=2) + "\n")

    for h in latest["horizons"]:
        c = h["components"]
        if c["v2"] is None:
            # v3's own forecast, republished so the page keeps its next-quarter
            # card and its chart toggle. No figure reaches the reader.
            print(f"{h['quarter']} ({h['kind']}): v3 only {h['qoq_growth_pct']:+.3f}% "
                  f"-- no v2 figure for this quarter yet, so the page shows the "
                  f"waiting card ({h['v3_months_with_data']} v3 month(s) of data)")
            continue
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
