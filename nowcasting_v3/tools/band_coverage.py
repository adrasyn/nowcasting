"""Do v3's bands contain the answer as often as they claim?

THE SITE'S OWN RULE, from `src/components/NowcastHeadline.tsx`:

    The ci_* fields remain in the payload for the record. Do not render them
    as a confidence level without re-measuring coverage first.

That rule exists because v2's band was drawn and then measured: labelled "about
a 2-in-3 chance", it contained the eventual figure in 7 of 17 quarters (41%).
Not because the width was wrong but because v2 runs ~0.34pp high, so a symmetric
interval around a biased point sits off-centre. The band was removed rather than
shifted. v3 may not repeat that -- its bias is +0.12pp against v2's +0.27 -- but
"may not" is not a measurement.

TWO OUTPUTS, from the same machinery:

  coverage   the backtest vintages, where the answer is known. Each gets a fit,
             a point and 500 density draws; the question is how often the actual
             falls inside 68% and 95%.

  evolution  the CURRENT quarter, week by week, for the site's chart. Here the
             parameters are estimated ONCE and every week is replayed through
             the SAME state space, so the line moves because DATA arrived and
             not because the sampler was re-run. That is the argument
             `test_later_months_move_the_nowcast_far_less...` already makes for
             holding the state space fixed across arms.

    cd nowcasting_v3
    caffeinate -i .venv/bin/python -u tools/band_coverage.py OUT_DIR
"""
from __future__ import annotations

import csv, sys, time
from pathlib import Path

import numpy as np
import pandas as pd

from nyfed.au.build import (
    P_E, P_F, Panel, build_panel, estimate_short, load_vintage, state_space,
    target_periods,
)
from nyfed.au.emit import annualised_to_qoq
from nyfed.nowcast import density_nowcast, point_nowcast
from nyfed.spec import load_spec

REPO = Path(__file__).resolve().parents[1]
SPEC = load_spec(REPO / "model_spec_AU.csv")
VINT = load_vintage(REPO / "tests/fixtures/au/vintage")
N_DRAW = 500
SEED = 4


def _band(draws_ann: np.ndarray) -> dict:
    q = np.nanpercentile(annualised_to_qoq(draws_ann), [2.5, 16, 84, 97.5])
    return {"ci_95_low": q[0], "ci_68_low": q[1],
            "ci_68_high": q[2], "ci_95_high": q[3]}


def _nowcast(panel: Panel, ssm, t_now, rng) -> tuple[float, dict]:
    loc = float(panel.y_location[panel.i_now, 0])
    scl = float(panel.y_scale[panel.i_now, 0])
    pt = point_nowcast(panel.Y, panel.Y, ssm, ssm, panel.i_now, t_now)
    point = float(annualised_to_qoq(loc + scl * float(pt.nowcast[3, 0])))
    draws = np.array([
        loc + scl * density_nowcast(panel.Y, ssm, panel.i_now, t_now, rng)[0]
        for _ in range(N_DRAW)])
    return point, _band(draws)


def main() -> int:
    out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    gdp = VINT.series["gdp"].dropna()
    actual = (gdp / gdp.shift(1) - 1) * 100

    # ---- 1. coverage, on quarters whose answer is known --------------------
    f = (out / "coverage.csv").open("w", newline="")
    w = csv.writer(f)
    w.writerow(["asof", "target", "point", "ci_68_low", "ci_68_high",
                "ci_95_low", "ci_95_high", "actual", "in68", "in95"])
    rng = np.random.default_rng(SEED)
    for asof in pd.date_range("2023-01-01", "2026-05-01", freq="MS"):
        try:
            panel = build_panel(asof=str(asof.date()), vintage=VINT)
        except Exception:                                       # noqa: BLE001
            continue
        res = estimate_short(panel, n_gs=200, n_burn=100, seed=SEED)
        try:
            ssm = state_space(panel, res)
        except Exception as exc:                                # noqa: BLE001
            print(f"{asof.date()}  refused: {type(exc).__name__}", flush=True)
            continue
        t_now = target_periods(panel)
        tgt = panel.dates[t_now[0]]
        a = float(actual.get(tgt, np.nan))
        point, b = _nowcast(panel, ssm, t_now, rng)
        in68 = int(b["ci_68_low"] <= a <= b["ci_68_high"])
        in95 = int(b["ci_95_low"] <= a <= b["ci_95_high"])
        w.writerow([str(asof.date()), f"{tgt.year}Q{(tgt.month-1)//3+1}",
                    round(point, 4), *[round(b[k], 4) for k in
                    ("ci_68_low","ci_68_high","ci_95_low","ci_95_high")],
                    round(a, 4), in68, in95]); f.flush()
        print(f"{asof.date()}  {point:+.2f} [{b['ci_68_low']:+.2f},"
              f"{b['ci_68_high']:+.2f}]  actual {a:+.2f}  "
              f"{'IN' if in68 else 'out':3s}  ({(time.perf_counter()-t0)/60:.0f}m)",
              flush=True)
    f.close()

    d = pd.read_csv(out / "coverage.csv")
    print(f"\nCOVERAGE  n={len(d)}   68% band: {d.in68.mean():.0%}   "
          f"95% band: {d.in95.mean():.0%}", flush=True)

    # ---- 2. this quarter, week by week, one state space -------------------
    latest = "2026-08-31"
    base = build_panel(asof=latest, vintage=VINT)
    res = estimate_short(base, n_gs=200, n_burn=100, seed=SEED)
    ssm = state_space(base, res)
    t_now = target_periods(base)
    tgt = base.dates[t_now[0]]
    label = f"{tgt.year} Q{(tgt.month-1)//3+1}"
    print(f"\nevolution for {label}, parameters fixed at {latest}", flush=True)

    g = (out / "evolution.csv").open("w", newline="")
    wv = csv.writer(g)
    wv.writerow(["run_date", "target_quarter", "qoq_growth_pct", "ci_68_low",
                 "ci_68_high", "ci_95_low", "ci_95_high", "data_through"])
    for d0 in pd.date_range("2026-06-01", "2026-08-24", freq="W-MON"):
        try:
            pv = build_panel(asof=str(d0.date()), vintage=VINT)
        except Exception:                                       # noqa: BLE001
            continue
        # Same shape and same standardisation as the estimation panel; only the
        # observations differ. `_with_data`'s rule: never re-standardise, or the
        # line moves because the scale moved.
        Y = np.full_like(base.Y, np.nan)
        Y[:, :pv.Y.shape[1]] = pv.Y[:, :base.Y.shape[1]]
        vp = Panel(Y=Y, y_location=base.y_location, y_scale=base.y_scale,
                   dates=base.dates, series_id=base.series_id, i_now=base.i_now)
        point, b = _nowcast(vp, ssm, t_now, rng)
        last = pd.DatetimeIndex(pv.dates)[np.isfinite(pv.Y).any(axis=0)][-1]
        wv.writerow([str(d0.date()), label, round(point, 4),
                     *[round(b[k], 4) for k in ("ci_68_low","ci_68_high",
                       "ci_95_low","ci_95_high")], str(last.date())[:7]])
        g.flush()
        print(f"  {d0.date()}  {point:+.3f}  68% [{b['ci_68_low']:+.3f},"
              f"{b['ci_68_high']:+.3f}]  width {b['ci_68_high']-b['ci_68_low']:.3f}",
              flush=True)
    g.close()
    print(f"\nwrote {out} in {(time.perf_counter()-t0)/60:.1f} min", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
