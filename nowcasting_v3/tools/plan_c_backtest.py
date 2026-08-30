"""Plan C, Phase 1: the recursive backtest.

One nowcast per monthly vintage across the evaluation window, scored against
ABS GDP. This is the measurement the whole of v3 exists to produce.

WINDOW: 2023-01 onward, NOT the 2022+ the spec originally called "the honest
post-COVID window". Phase 0 measured 2022 and it is not a fair test of the
model: the COVID factor is active to December 2021, so a 2022 vintage sits on
its edge, and the model is a quarter behind all the way through it -- it
predicted +0.7% while the real rebound ran at +3.6%, then +4.1% once growth had
already fallen back to +0.9%. Mean absolute error 2.12pp in 2022 against 0.45pp
in 2024. Scoring the model where its own design guarantees it cannot work tells
us nothing about the question this project is chasing.

NO WARM START, AND THAT IS A CHANGE. Phase 0 built its case for warm starting on
the cold-start collapse lottery: 28 of 75 cold chains landed usable, and no seed
could be trusted at the next vintage. Moving `DEFAULT_START` to 1980 removed the
lottery -- thirty seeds of thirty now land in the identified basin -- so a cold
fit per vintage is simpler, carries no path dependence between vintages, and
costs the same per sweep. The warm machinery stays in `plan_c_phase0.py` in case
a future panel needs it again.

THREE SEEDS PER VINTAGE, MEDIAN TAKEN. Within-basin sampler noise is ~0.078pp
q/q, which is a quarter of the error being measured. One seed per vintage would
report the sampler as much as the model.

WHAT THIS IS NOT: a true real-time backtest. The recorded vintage carries ABS's
CURRENT figures, so cutting it at an `asof` reproduces what was PUBLISHED by
then, not what those numbers LOOKED LIKE then. The model sees revised data and
is scored against revised outcomes. That flatters it, and the write-up says so.

Run:
    cd nowcasting_v3
    caffeinate -i .venv/bin/python -u tools/plan_c_backtest.py OUT.csv
"""
from __future__ import annotations

import csv, sys, time
from pathlib import Path

import numpy as np
import pandas as pd

from nyfed.au.build import (
    COLLAPSED_GLOBAL_LOADING, P_E, P_F, build_panel, estimate_short,
    load_vintage, state_space, target_periods,
)
from nyfed.au.emit import annualised_to_qoq
from nyfed.nowcast import point_nowcast
from nyfed.parameters import map_parameter
from nyfed.spec import load_spec

REPO = Path(__file__).resolve().parents[1]
SPEC = load_spec(REPO / "model_spec_AU.csv")
VINT = load_vintage(REPO / "tests/fixtures/au/vintage")

FIRST, LAST = "2023-01-01", "2026-05-01"
SEEDS = (4, 13, 19)
N_GS, N_BURN = 200, 100

FIELDS = ["asof", "target", "target_date", "horizon_months", "seed",
          "nowcast_qq", "forecast_next_qq", "actual_qq", "error_qq",
          "gdp_global_loading", "collapsed", "cols", "gdp_obs",
          "deflator_skipped", "seconds"]


def main() -> int:
    out = Path(sys.argv[1]); t0 = time.perf_counter()
    gdp = VINT.series["gdp"].dropna()
    actual_qq = (gdp / gdp.shift(1) - 1) * 100

    fh = out.open("w", newline=""); w = csv.DictWriter(fh, fieldnames=FIELDS)
    w.writeheader(); fh.flush()

    for asof in pd.date_range(FIRST, LAST, freq="MS"):
        stamp = str(asof.date())
        try:
            panel = build_panel(asof=stamp, vintage=VINT)
        except Exception as exc:                                # noqa: BLE001
            print(f"{stamp}  UNBUILDABLE {type(exc).__name__}: {str(exc)[:80]}",
                  flush=True)
            continue

        t_now = target_periods(panel)
        tgt = panel.dates[t_now[0]]
        label = f"{tgt.year}Q{(tgt.month - 1) // 3 + 1}"
        act = float(actual_qq.get(tgt, np.nan))
        # Months from the vintage to the END of the target quarter. Negative
        # means the quarter has not finished: a genuine forecast.
        horizon = (asof.year - tgt.year) * 12 + (asof.month - tgt.month)
        n, n_f = SPEC.blocks.shape
        rows = []

        for seed in SEEDS:
            s0 = time.perf_counter()
            res = estimate_short(panel, n_gs=N_GS, n_burn=N_BURN, seed=seed)
            secs = time.perf_counter() - s0
            par = map_parameter(np.median(res.params, axis=1), (n, n_f, P_F, P_E))
            loading = float(par.Lambda[panel.i_now, 0])
            collapsed = loading <= COLLAPSED_GLOBAL_LOADING
            nc = nxt = ""
            if not collapsed:
                # `state_space` is the guarded funnel; it re-checks the loading.
                ssm = state_space(panel, res)
                pt = point_nowcast(panel.Y, panel.Y, ssm, ssm, panel.i_now, t_now)
                loc = float(panel.y_location[panel.i_now, 0])
                scl = float(panel.y_scale[panel.i_now, 0])
                nc = float(annualised_to_qoq(loc + scl * float(pt.nowcast[3, 0])))
                if pt.nowcast.shape[1] > 1:
                    nxt = float(annualised_to_qoq(loc + scl * float(pt.nowcast[3, 1])))
            rows.append(nc)
            w.writerow({
                "asof": stamp, "target": label, "target_date": str(tgt.date()),
                "horizon_months": horizon, "seed": seed,
                "nowcast_qq": round(nc, 4) if nc != "" else "",
                "forecast_next_qq": round(nxt, 4) if nxt != "" else "",
                "actual_qq": round(act, 4), "error_qq":
                    round(nc - act, 4) if nc != "" else "",
                "gdp_global_loading": round(loading, 4),
                "collapsed": int(collapsed), "cols": panel.Y.shape[1],
                "gdp_obs": int(np.isfinite(panel.Y[panel.i_now]).sum()),
                "deflator_skipped": ";".join(sorted(panel.deflator_skipped)),
                "seconds": round(secs, 1)})
            fh.flush()

        good = [r for r in rows if r != ""]
        med = float(np.median(good)) if good else float("nan")
        print(f"{stamp}  {label}  h={horizon:+d}m  median {med:6.3f}  "
              f"actual {act:6.3f}  err {med - act:+6.3f}  "
              f"({len(good)}/{len(SEEDS)} ok, {(time.perf_counter()-t0)/60:.0f} min)",
              flush=True)

    fh.close()
    print(f"\nwrote {out} in {(time.perf_counter() - t0) / 60:.1f} min", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
