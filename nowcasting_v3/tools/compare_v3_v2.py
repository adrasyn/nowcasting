"""Score v3's backtest against v2's production backtest and the naive benchmarks.

v2's comparison file is `nowcasting_v2/cache/ci_recalib/qa_a10_acc.csv` -- the
SHIPPING configuration (weekly as-of, historically accurate publication lags,
the B3_nab_wmi panel), not one of the diagnostic variants beside it. The
`_leaky` variant in the same directory carries a known look-ahead leak and
comparing against it would flatter v3.

Pairs each v3 vintage with v2's most recent as-of at or before it, same target
quarter. The choice of pairing rule does not matter: before/after/nearest all
give v3 28-29% lower MAE.
"""
import numpy as np, pandas as pd
from pathlib import Path

ROOT = Path("/Users/James/Documents/Claude/Projects/nowcasting")
v3 = pd.read_csv(ROOT / "docs/measurements/2026-08-30-plan-c-backtest.csv",
                 parse_dates=["asof", "target_date"])
v3 = v3[v3["collapsed"] == 0].copy()
v3["nowcast_qq"] = pd.to_numeric(v3["nowcast_qq"], errors="coerce")
# median across seeds -> one number per vintage
m = (v3.groupby(["asof", "target", "target_date", "horizon_months", "actual_qq"],
                as_index=False)["nowcast_qq"].median())
m["err"] = (m["nowcast_qq"] - m["actual_qq"]).abs()
m = m.dropna(subset=["actual_qq"])

v2 = pd.read_csv(ROOT / "nowcasting_v2/cache/ci_recalib/qa_a10_acc.csv",
                 parse_dates=["as_of", "target_quarter_date"])
v2 = v2.dropna(subset=["qoq_actual"])

# pair each v3 vintage with v2's latest as-of at or before it, same target
pairs = []
for _, r in m.iterrows():
    c = v2[(v2["target_quarter_date"] == r["target_date"]) & (v2["as_of"] <= r["asof"])]
    if len(c):
        c = c.sort_values("as_of").iloc[-1]
        pairs.append((r["asof"], r["target"], r["horizon_months"], r["actual_qq"],
                      r["nowcast_qq"], float(c["qoq_growth_forecast"]),
                      (r["asof"] - c["as_of"]).days))
p = pd.DataFrame(pairs, columns=["asof","target","h","actual","v3","v2","lag_days"])

from nyfed.au.build import load_vintage
gdp = load_vintage(ROOT / "nowcasting_v3/tests/fixtures/au/vintage").series["gdp"].dropna()
qq = (gdp / gdp.shift(1) - 1) * 100
tmap = {t: pd.Timestamp(d) for t, d in zip(m["target"], m["target_date"])}
p["target_date"] = p["target"].map(tmap)
p["no_change"] = [float(qq[qq.index < d].iloc[-1]) for d in p["target_date"]]
p["mean10y"]   = [float(qq[qq.index < d].tail(40).mean()) for d in p["target_date"]]

print(f"paired on {len(p)} vintages, {p.target.nunique()} target quarters "
      f"({p.target.min()}..{p.target.max()})")
print(f"v2 as-of lags behind v3's by {p.lag_days.mean():.1f} days on average\n")
print("HEAD TO HEAD, pp quarter-on-quarter")
print(f"{'model':<12}{'MAE':>7}{'RMSE':>8}{'bias':>8}{'dir %':>7}")
for c in ["v3", "v2", "no_change", "mean10y"]:
    e = p[c] - p["actual"]
    d = (np.sign(p[c] - p["no_change"]) == np.sign(p["actual"] - p["no_change"]))
    print(f"{c:<12}{e.abs().mean():7.3f}{np.sqrt((e**2).mean()):8.3f}"
          f"{e.mean():+8.3f}{100*d.mean():7.0f}")

print("\nSPREAD of each model's own answers (actual spread "
      f"{p.actual.min():.2f}..{p.actual.max():.2f})")
for c in ["v3", "v2"]:
    print(f"  {c}: {p[c].min():.2f}..{p[c].max():.2f}   sd {p[c].std():.3f}"
          f"   (actual sd {p.actual.std():.3f})")

print("\nBY TARGET QUARTER")
g = p.groupby("target").agg(n=("v3","size"), actual=("actual","first"),
                            v3=("v3","mean"), v2=("v2","mean"))
g["v3_err"] = (g["v3"]-g["actual"]).abs(); g["v2_err"] = (g["v2"]-g["actual"]).abs()
g["winner"] = np.where(g.v3_err < g.v2_err, "v3", "v2")
print(g.round(3).to_string())
print(f"\nv3 closer on {(g.winner=='v3').sum()} of {len(g)} quarters")

print("\nBY HORIZON (months from vintage to end of target quarter)")
h = p.groupby("h").apply(lambda d: pd.Series({
    "n": len(d), "v3_mae": (d.v3-d.actual).abs().mean(),
    "v2_mae": (d.v2-d.actual).abs().mean()}), include_groups=False)
print(h.round(3).to_string())
