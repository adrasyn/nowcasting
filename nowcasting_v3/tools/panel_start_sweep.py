"""Is the 1960 panel a real fix, or arithmetic dilution?

Opening the window from 1990 to 1960 took the identification rate from 28% to
98%. Two explanations fit that, and they have opposite implications.

  INFORMATION.  More pre-COVID history means COVID is a smaller share of what
                GDP has ever done (64.5% -> 23.1%), so the COVID factor stops
                being able to explain the target on its own. A real fix.

  DILUTION.     1960-1969 contains ZERO monthly indicators -- only GDP and GDI,
                which are near-identical. If the Global factor over that stretch
                is defined by GDP alone, then "GDP loads Global" is guaranteed by
                construction rather than earned, and the guard passes for the
                wrong reason. A fake fix, and worse than no fix.

THE DISCRIMINATOR is whether the MONTHLY series still load the Global factor.
If Global is a real common factor, they do. If it has quietly become GDP's own
trend, GDP's loading rises while theirs falls. That ratio is recorded per fit.

Intermediate starts separate the two directly: 1980 and 1985 buy most of the
extra history WITHOUT the empty era. If they capture the benefit, information is
doing the work. If only 1960 works, it is dilution.
"""
import csv, sys, time
from pathlib import Path
import numpy as np, pandas as pd

from nyfed.au.build import (
    COLLAPSED_GLOBAL_LOADING, P_E, P_F, build_panel, estimate_short,
    load_vintage, target_periods,
)
from nyfed.au.restrict import COVID_END, COVID_START, build_restrict
from nyfed.model import Latent, construct_ssm
from nyfed.nowcast import point_nowcast
from nyfed.parameters import map_parameter
from nyfed.spec import load_spec

REPO = Path("/Users/James/Documents/Claude/Projects/nowcasting/nowcasting_v3")
SPEC = load_spec(REPO / "model_spec_AU.csv")
V = load_vintage(REPO / "tests/fixtures/au/vintage")
STARTS = ["1960-01-01", "1970-01-01", "1980-01-01", "1985-01-01", "1990-01-01"]
VINTAGES = ["2026-01-01", "2026-02-01", "2026-03-01", "2026-04-01", "2026-05-01"]
SEEDS = (4, 13, 19, 22, 27, 16)
ACT = {"2026-01-01": .87, "2026-02-01": .87, "2026-03-01": .87,
       "2026-04-01": .27, "2026-05-01": .27}

out = Path(sys.argv[1]); t0 = time.perf_counter()
fh = out.open("w", newline=""); w = csv.writer(fh)
w.writerow(["start","asof","seed","cols","gdp_obs","covid_share","seconds",
            "gdp_global","monthly_global_mean","ratio","collapsed",
            "nowcast_qq","actual_qq"]); fh.flush()

MONTHLY = [k for k in SPEC.series_id if k not in ("gdp", "gdi", "unit_labour_cost")]

for start in STARTS:
    for asof in VINTAGES:
        p = build_panel(asof=asof, start=start, vintage=V)
        restrict = build_restrict(p, SPEC, p_f=P_F)
        t_now = target_periods(p)
        n, n_f = SPEC.blocks.shape
        i_gdp = p.i_now
        rows_m = [p.series_id.index(k) for k in MONTHLY]
        obs = np.isfinite(p.Y[i_gdp])
        win = (p.dates >= COVID_START) & (p.dates <= COVID_END)
        share = float(np.nansum(p.Y[i_gdp][obs & win]**2) / np.nansum(p.Y[i_gdp][obs]**2))
        for seed in SEEDS:
            s0 = time.perf_counter()
            r = estimate_short(p, n_gs=200, n_burn=100, seed=seed)
            secs = time.perf_counter() - s0
            par = map_parameter(np.median(r.params, axis=1), (n, n_f, P_F, P_E))
            gl = float(par.Lambda[i_gdp, 0])
            mg = float(np.abs(par.Lambda[rows_m, 0]).mean())
            col = gl <= COLLAPSED_GLOBAL_LOADING
            nc = ""
            if not col:
                lat = Latent(sigma=r.sigmas.mean(axis=2), s=r.ss.mean(axis=2))
                ssm = construct_ssm(par, lat, restrict)
                pt = point_nowcast(p.Y, p.Y, ssm, ssm, i_gdp, t_now)
                nc = (float(p.y_location[i_gdp, 0])
                      + float(p.y_scale[i_gdp, 0]) * float(pt.nowcast[3, 0])) / 4
            w.writerow([start[:4], asof, seed, p.Y.shape[1], int(obs.sum()),
                        round(share, 4), round(secs, 1), round(gl, 4),
                        round(mg, 4), round(gl / mg, 3) if mg else "",
                        int(col), nc, ACT[asof]]); fh.flush()
        print(f"{start[:4]}  {asof}  cols={p.Y.shape[1]:4d} covid_share={share:5.1%}"
              f"  ({(time.perf_counter()-t0)/60:.0f} min)", flush=True)
fh.close()
print(f"wrote {out} in {(time.perf_counter()-t0)/60:.1f} min", flush=True)
