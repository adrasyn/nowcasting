#!/usr/bin/env python3
"""Generate data/performance_v2.json (the v2 backtest track record) reproducibly.

Inputs (repo root):
  data/backcasts.json            v2 headline qa nowcast per quarter (qoq)
  data/gdp.json                  realised GDP levels + qoq/yoy actuals
  pipeline/rba_somp_forecasts_v2.csv   RBA SoMP year-ended GDP forecasts (Q2/Q4)

Output: data/performance_v2.json in the v1 Performance schema, so the existing
PerformanceSection renders it. $-level figures are level-based; the RBA gap is a
year-ended comparison for the Jun/Dec quarters that have an RBA SoMP forecast.

THE QUARTERLY SCORE IS AGAINST THE ABS'S INITIAL ESTIMATE. From 2026-09 v2 is
estimated on the initial estimates rather than the latest vintage, so the
backcast's `qoq_actual_pct` is the figure the ABS first published. The $-level
actual is therefore the level that growth rate implies, not gdp.json's revised
level -- otherwise the MAE/Bias tiles would score the model against a series it
is no longer aimed at, and would disagree with the error column of the table
directly below them, which is exactly what happened on 2026-08-08.

The YEAR-ENDED comparison against the RBA stays on gdp.json's revised levels.
It is a four-quarter growth rate and there is no first-release level series to
compute one from; the RBA's own forecast is judged the same way.

Run from repo root:  python nowcasting_v2/gen_performance_v2.py
Re-run whenever the backcast or the RBA forecast set changes (addresses the
'not reproducible' finding in the 2026-06-11 Fable review).
"""
import json, csv, statistics as st, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def p(*a): return os.path.join(ROOT, *a)

gdp_series = json.load(open(p("data", "gdp.json")))["series"]
gdp = {x["quarter"]: x for x in gdp_series}
gq = [x["quarter"] for x in gdp_series]
bc = {b["target_quarter"]: b for b in json.load(open(p("data", "backcasts.json")))["backcasts"]}

rba = {}
with open(p("pipeline", "rba_somp_forecasts_v2.csv")) as f:
    for r in csv.DictReader(f):
        rba[r["target_quarter"]] = (float(r["yoy_forecast_pct"]), r["somp_release"])

def lvl(q):  # realised GDP level ($m) for a quarter
    return gdp[q]["value"]

errors, edges = [], []
# Only score quarters present in BOTH the backcast set and realised GDP, in GDP
# order (avoids the 1e9 sort-key collision for quarters missing from gdp.json).
for q in sorted(set(bc) & set(gq), key=gq.index):
    i = gq.index(q)
    prev = lvl(gq[i - 1]) if i > 0 else lvl(q) / (1 + bc[q]["qoq_actual_pct"] / 100)
    fc_level = round(prev * (1 + bc[q]["qoq_forecast_pct"] / 100))
    # The level the ABS's INITIAL estimate of this quarter's growth implies --
    # the target v2 is now estimated on. Built the same way as fc_level so the
    # $ error is exactly the growth error, and the tiles agree with the table.
    actual = round(prev * (1 + bc[q]["qoq_actual_pct"] / 100))
    em = fc_level - actual
    row = {
        "target_quarter": q, "final_nowcast": fc_level, "actual": actual,
        "error_millions": em, "error_pct": round(em / actual * 100, 2),
        # QoQ growth is what the site's table shows, and what the model actually
        # forecasts -- the levels above are derived from it via `prev`. Carrying
        # the growth figures through means the table's error column is literally
        # the difference of its own two adjacent columns, which a reader can check.
        "qoq_nowcast_pct": bc[q]["qoq_forecast_pct"],
        "qoq_actual_pct":  bc[q]["qoq_actual_pct"],
        "qoq_error_pp":    round(bc[q]["qoq_forecast_pct"] - bc[q]["qoq_actual_pct"], 2),
        "yoy_nowcast": None, "yoy_actual": None, "yoy_rba": None,
        "somp_release": None, "edge_pp": None,
    }
    # Year-ended RBA comparison, only where we have both an RBA forecast and Q-4.
    if q in rba and i >= 4:
        base = lvl(gq[i - 4])
        ye_now = round(fc_level / base * 100 - 100, 2)     # level-based (exact)
        # Year-ended actual stays on the revised level: a four-quarter growth
        # rate has no first-release counterpart, and the RBA forecast beside it
        # is judged against the same series.
        ye_act = round(lvl(q) / base * 100 - 100, 2)
        ye_rba, somp = rba[q]
        edge = round(abs(ye_now - ye_act) - abs(ye_rba - ye_act), 2)  # <0 => v2 closer
        row.update(yoy_nowcast=ye_now, yoy_actual=ye_act, yoy_rba=ye_rba,
                   somp_release=somp, edge_pp=edge)
        edges.append(edge)
    errors.append(row)

mae = st.mean(abs(e["error_millions"]) for e in errors)
bias = st.mean(e["error_millions"] for e in errors)
meanact = st.mean(e["actual"] for e in errors)
out = {
    "mae_millions": round(mae), "mae_pct": round(mae / meanact * 100, 2),
    "bias_millions": round(bias), "bias_pct": round(bias / meanact * 100, 2),
    "rba_comparison": {"n": len(edges),
                       "avg_edge_pp": round(st.mean(edges), 2) if edges else None},
    "errors": errors,
}
json.dump(out, open(p("data", "performance_v2.json"), "w"), indent=2)
print(f"performance_v2.json: {len(errors)} quarters, MAE ${out['mae_millions']}M, "
      f"RBA n={len(edges)} avg_edge={out['rba_comparison']['avg_edge_pp']}")
for e in errors:
    if e["edge_pp"] is not None:
        print(f"  {e['target_quarter']}: v2 YE {e['yoy_nowcast']:+.2f} | RBA {e['yoy_rba']:+.2f} "
              f"| actual {e['yoy_actual']:+.2f} | edge {e['edge_pp']:+.2f}")
