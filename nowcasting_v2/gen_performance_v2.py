#!/usr/bin/env python3
"""Generate data/performance_v2.json (the v2 backtest track record) reproducibly.

Inputs (repo root):
  data/backcasts.json            v2 headline qa nowcast per quarter (qoq)
  data/gdp.json                  realised GDP levels + qoq/yoy actuals
  pipeline/rba_somp_forecasts_v2.csv   RBA SoMP year-ended GDP forecasts (Q2/Q4)

Output: data/performance_v2.json in the v1 Performance schema, so the existing
PerformanceSection renders it. $-level figures are level-based; the RBA gap is a
year-ended comparison for the Jun/Dec quarters that have an RBA SoMP forecast.

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
for q in sorted(bc, key=lambda x: gq.index(x) if x in gq else 1e9):
    if q not in gdp:
        continue
    i = gq.index(q)
    prev = lvl(gq[i - 1]) if i > 0 else lvl(q) / (1 + bc[q]["qoq_actual_pct"] / 100)
    fc_level = round(prev * (1 + bc[q]["qoq_forecast_pct"] / 100))
    actual = lvl(q)
    em = fc_level - actual
    row = {
        "target_quarter": q, "final_nowcast": fc_level, "actual": actual,
        "error_millions": em, "error_pct": round(em / actual * 100, 2),
        "yoy_nowcast": None, "yoy_actual": None, "yoy_rba": None,
        "somp_release": None, "edge_pp": None,
    }
    # Year-ended RBA comparison, only where we have both an RBA forecast and Q-4.
    if q in rba and i >= 4:
        base = lvl(gq[i - 4])
        ye_now = round(fc_level / base * 100 - 100, 2)     # level-based (exact)
        ye_act = round(actual / base * 100 - 100, 2)
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
