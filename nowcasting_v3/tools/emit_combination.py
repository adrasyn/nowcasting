"""Emit the combination payloads: the equal-weight average of v2 and v3.

PREVIEW DRAFT (2026-09-12). Reads the two models' published payloads and writes
`data/latest_combo.json`, `data/nowcast_history_combo.json` and
`data/performance_combo.json` in the v3 schemas, so the homepage components
render them unchanged.

Rules:
  * A combination exists for a Monday and a target quarter only where BOTH
    models published a nowcast for that quarter. v2 nowcasts the latest
    unpublished quarter only, so the combination for a new quarter starts on
    the first Monday after the previous quarter's ABS print.
  * v2's figure for a Monday is its run at that date, or its most recent run
    before it for the same quarter (v2 skips the occasional Monday).
  * Bands are the empirical quantiles of the combination's own backtest error
    (docs/measurements/2026-09-12-v2-v3-weekly-combination.csv), pooled over
    horizons because the error barely varies with the horizon, centred on the
    point.
  * The track record is the backtest's final pre-print Monday for each quarter,
    on the same hybrid level basis as v3's (levels chained on gdp.json).
"""
from __future__ import annotations

import argparse, json
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
BACKTEST = ROOT / "docs/measurements/2026-09-12-v2-v3-weekly-combination.csv"
SOMP = ROOT / "pipeline/rba_somp_forecasts_v2.csv"
FIRST = ROOT / "nowcasting_v3/data/gdp_first_release.csv"
SCHEMA = "combo-preview-1"


def qlabel(q: str) -> str:            # "2026Q2" -> "2026 Q2"
    return f"{q[:4]} {q[4:]}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--asof", default=None, help="pretend today is this date (YYYY-MM-DD): "
                    "drop later runs, so the page shows the quarter in force then")
    ap.add_argument("--out", default=str(DATA))
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    asof = pd.Timestamp(args.asof) if args.asof else None

    v2 = json.load(open(DATA / "latest_v2.json"))
    v3 = json.load(open(DATA / "latest_v3.json"))
    hist = json.load(open(DATA / "nowcast_history_v3.json"))["runs"]
    gdp = json.load(open(DATA / "gdp.json"))["series"]
    lvl = {g["quarter"]: float(g["value"]) for g in gdp}
    quarters = [g["quarter"] for g in gdp]

    # ---- bands from the combination's own backtest errors ------------------
    bt = pd.read_csv(BACKTEST, parse_dates=["as_of"])
    err = bt.combo - bt["first"]
    q68, q95 = (float(np.percentile(err.abs(), p)) for p in (68, 95))
    ci_basis = (f"probability band: the range holding 68% and 95% of the combination's own "
                f"backtest misses against the ABS's initial estimate ({len(err)} weekly vintages, "
                f"2022Q4 to 2026Q2), pooled across horizons and centred on the point. "
                f"Not a posterior and not a confidence interval.")

    # ---- v2 runs: (run_date, quarter) -> qoq ----------------------------------
    v2_runs = {(r["run_date"], r["target_quarter"]): float(r["qoq_growth_pct"]) for r in v2["vintages"]}
    h = v2["models"]["headline"]
    v2_runs[(v2["as_of"], h["target_quarter"])] = float(h["qoq_growth_pct"])

    def v2_at(run_date: str, quarter: str):
        cands = [(d, q) for (d, q) in v2_runs if q == quarter and d <= run_date]
        if not cands:
            return None, None
        d = max(cands)[0]
        return v2_runs[(d, quarter)], d

    # ---- combination runs over v3's history -------------------------------
    runs = []
    for r in hist:
        # Rows written before the `kind` field exist; every one of them is a
        # nowcast (the forecast horizon was never recorded without it).
        if r.get("kind", "nowcast") != "nowcast":
            continue
        if asof is not None and pd.Timestamp(r["run_date"]) > asof:
            continue
        v2q, v2d = v2_at(r["run_date"], r["target_quarter"])
        if v2q is None:
            continue
        q = round((v2q + float(r["qoq_growth_pct"])) / 2, 4)
        runs.append({
            "run_date": r["run_date"], "target_quarter": r["target_quarter"], "kind": "nowcast",
            "qoq_growth_pct": q, "v2_qoq_growth_pct": round(v2q, 4), "v2_run_date": v2d,
            "v3_qoq_growth_pct": round(float(r["qoq_growth_pct"]), 4),
            "ci_68_low": round(q - q68, 4), "ci_68_high": round(q + q68, 4),
            "ci_95_low": round(q - q95, 4), "ci_95_high": round(q + q95, 4),
            "data_through": r["data_through"], "months_with_data": r.get("months_with_data"),
        })
    runs.sort(key=lambda x: (x["run_date"], x["target_quarter"]))
    if not runs:
        raise SystemExit("no Monday where both models nowcast the same quarter")
    latest_run = runs[-1]
    target = latest_run["target_quarter"]
    vintages = [r for r in runs if r["target_quarter"] == target]

    # ---- latest payload, v3 schema ---------------------------------------
    prev_q = quarters[quarters.index(target) - 1] if target in quarters else quarters[-1]
    prev_level = lvl[prev_q]
    q = latest_run["qoq_growth_pct"]
    nowcast = {
        "quarter": target, "kind": "nowcast", "qoq_growth_pct": q,
        "model_qoq_growth_pct": q,
        "annualised_growth_pct": round(((1 + q / 100) ** 4 - 1) * 100, 4),
        "ci_68_low": latest_run["ci_68_low"], "ci_68_high": latest_run["ci_68_high"],
        "ci_95_low": latest_run["ci_95_low"], "ci_95_high": latest_run["ci_95_high"],
        "months_with_data": latest_run["months_with_data"],
        "release_date": next((x["release_date"] for x in v3["horizons"] if x["quarter"] == target), v3.get("next_gdp_release_date")),
        "gdp_chain_volume_millions": round(prev_level * (1 + q / 100)),
        "components": {"v2": latest_run["v2_qoq_growth_pct"], "v3": latest_run["v3_qoq_growth_pct"]},
    }
    horizons = [nowcast]
    # v2 has no next-quarter forecast, so the forecast horizon is v3's alone.
    fc = next((x for x in v3["horizons"] if x["kind"] == "forecast"), None)
    if fc and asof is None:
        horizons.append({**fc, "source": "v3 only"})
    latest = {
        "schema": SCHEMA, "status": "ok", "basis": "abs_first_print", "target": "first_print",
        "method": "equal-weight average of v2 and v3",
        "generated_at": (asof.strftime("%Y-%m-%dT00:00:00+00:00") if asof is not None
                         else datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")),
        "as_of": latest_run["run_date"], "target_quarter": target,
        "data_through": latest_run["data_through"],
        "prev_level": {"value": prev_level, "quarter": prev_q},
        "horizons": horizons, "vintages": vintages,
        "next_gdp_release_date": nowcast["release_date"],
        "bias_correction": v3.get("bias_correction"),
        "ci_basis": ci_basis,
        "band_pp": {"p68": round(q68, 4), "p95": round(q95, 4), "n": int(len(err))},
        "panel": v3.get("panel"), "diagnostics": v3.get("diagnostics"), "estimate": v3.get("estimate"),
        "components": {"v2": {"as_of": latest_run["v2_run_date"], "schema": v2.get("schema")},
                       "v3": {"as_of": v3["as_of"], "schema": v3.get("schema")}},
    }
    (out / "latest_combo.json").write_text(json.dumps(latest, indent=2) + "\n")
    (out / "nowcast_history_combo.json").write_text(json.dumps({"schema": "combo-history-1", "runs": runs}, indent=2) + "\n")

    # ---- track record from the backtest's final pre-print Monday ------------
    first = pd.read_csv(FIRST); fp = {qlabel(r.quarter): float(r.qoq_pct) for r in first.itertuples()}
    somp = pd.read_csv(SOMP).set_index("target_quarter")
    bt["release"] = pd.to_datetime(bt["release"]) if "release" in bt else None
    errors = []
    for tq, g in bt.groupby("target"):
        label = qlabel(tq)
        g = g[g.as_of < g.release].sort_values("as_of") if g.release.notna().all() else g.sort_values("as_of")
        last = g.iloc[-1]
        i = quarters.index(label)
        base_prev = lvl[quarters[i - 1]]
        nc, ac = float(last.combo), fp[label]
        nowcast_lvl, actual_lvl = base_prev * (1 + nc / 100), base_prev * (1 + ac / 100)
        yoy_nc = yoy_ac = yoy_rba = edge = release = None
        if i >= 4:
            base = lvl[quarters[i - 4]]
            yoy_nc = round(100 * (nowcast_lvl / base - 1), 2); yoy_ac = round(100 * (actual_lvl / base - 1), 2)
            if label in somp.index:
                yoy_rba = float(somp.loc[label, "yoy_forecast_pct"]); release = str(somp.loc[label, "somp_release"])
                edge = round(abs(yoy_nc - yoy_ac) - abs(yoy_rba - yoy_ac), 2)
        errors.append({
            "target_quarter": label, "final_nowcast": round(nowcast_lvl), "actual": round(actual_lvl),
            "error_millions": round(nowcast_lvl - actual_lvl),
            "error_pct": round(100 * (nowcast_lvl - actual_lvl) / actual_lvl, 3),
            "qoq_nowcast_pct": round(nc, 2), "qoq_model_nowcast_pct": round(nc, 2),
            "bias_correction_pp": None, "qoq_actual_pct": round(ac, 2),
            "qoq_error_pp": round(nc - ac, 2),
            "qoq_latest_vintage_pct": next((x["qoq_pct"] for x in gdp if x["quarter"] == label), None),
            "v2_qoq_nowcast_pct": round(float(last.v2), 2), "v3_qoq_nowcast_pct": round(float(last.v3), 2),
            "model": "combination", "is_live": False, "live_run_date": None,
            "final_run_date": str(last.as_of.date()),
            "yoy_nowcast": yoy_nc, "yoy_actual": yoy_ac, "yoy_rba": yoy_rba, "somp_release": release, "edge_pp": edge,
        })
    errors.sort(key=lambda x: (int(x["target_quarter"][:4]), x["target_quarter"][-1]))
    e = pd.DataFrame(errors); er = e.qoq_nowcast_pct - e.qoq_actual_pct
    paired = pd.DataFrame([{"our": abs(x["yoy_nowcast"] - x["yoy_actual"]), "rba": abs(x["yoy_rba"] - x["yoy_actual"]), "edge": x["edge_pp"]}
                           for x in errors if x["edge_pp"] is not None])
    perf = {
        "basis": "abs_first_print", "target": "first_print", "method": "equal-weight average of v2 and v3",
        "n": len(errors), "mae_millions": round(float(e.error_millions.abs().mean())),
        "mae_pct": round(float(er.abs().mean()), 2), "bias_millions": round(float(e.error_millions.mean())),
        "bias_pct": round(float(er.mean()), 2),
        "v2_mae_pct": round(float((e.v2_qoq_nowcast_pct - e.qoq_actual_pct).abs().mean()), 2),
        "v3_mae_pct": round(float((e.v3_qoq_nowcast_pct - e.qoq_actual_pct).abs().mean()), 2),
        "rba_comparison": {"n": int(len(paired)), "avg_edge_pp": round(float(paired.edge.mean()), 2),
                           "ours_mae": round(float(paired.our.mean()), 2), "rba_mae": round(float(paired.rba.mean()), 2),
                           "we_were_closer": int((paired.our < paired.rba).sum())},
        "errors": errors,
    }
    (out / "performance_combo.json").write_text(json.dumps(perf, indent=2) + "\n")
    print(f"{target}: combination {q:+.3f} (v2 {latest_run['v2_qoq_growth_pct']:+.3f} at {latest_run['v2_run_date']}, "
          f"v3 {latest_run['v3_qoq_growth_pct']:+.3f}) band68 ±{q68:.3f} band95 ±{q95:.3f}; "
          f"{len(vintages)} vintages for {target}, {len(runs)} runs; track record {len(errors)} q MAE {perf['mae_pct']} bias {perf['bias_pct']:+} "
          f"(v2 {perf['v2_mae_pct']}, v3 {perf['v3_mae_pct']}); RBA n={perf['rba_comparison']['n']} ours {perf['rba_comparison']['ours_mae']} rba {perf['rba_comparison']['rba_mae']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
