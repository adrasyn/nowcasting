"""Does the model get better with longer data? Measured, not argued.

We cannot lengthen `job_ads` -- ANZ-Indeed starts 2021-01 and that is that. But
the question is about a DERIVATIVE, and the derivative can be measured in the
direction we can move: if making a series shorter hurts, making it longer helps,
and by roughly the same slope.

Four arms, all at the same five recent vintages:

  baseline    as shipped: panel from 1990, job_ads from 2021-01
  ads_2024    job_ads cut back to 2024-01 -- 40 fewer months on the newest row
  nab_2021    nab_conditions (a LONG series, from 1997) cut back to 2021-01, so
              it is exactly as short as job_ads. If shortness is what costs us,
              this arm should lose the most: it discards 24 years.
  start_1960  the panel window opened from 1990 to 1960, giving the long series
              30 more years. Does MORE history help?

Eight cold seeds per cell because ~60% of cold chains collapse; collapsed chains
are recorded and excluded from the arm's median rather than silently retried.
"""
import csv, sys, time
from pathlib import Path

import numpy as np
import pandas as pd

from nyfed.au.build import (
    COLLAPSED_GLOBAL_LOADING, P_E, P_F, build_panel, estimate_short,
    load_vintage, target_periods,
)
from nyfed.model import Latent, construct_ssm
from nyfed.au.restrict import build_restrict
from nyfed.nowcast import point_nowcast
from nyfed.parameters import map_parameter
from nyfed.spec import load_spec

REPO = Path("/Users/James/Documents/Claude/Projects/nowcasting/nowcasting_v3")
SPEC = load_spec(REPO / "model_spec_AU.csv")
BASE = load_vintage(REPO / "tests/fixtures/au/vintage")
VINTAGES = ["2026-01-01", "2026-02-01", "2026-03-01", "2026-04-01", "2026-05-01"]
SEEDS = (4, 13, 19, 22, 27, 16, 18, 26)

def truncated(key, first):
    v = load_vintage(REPO / "tests/fixtures/au/vintage")
    v.series[key] = v.series[key][v.series[key].index >= pd.Timestamp(first)]
    return v

ARMS = {
    "baseline":   (BASE, "1990-01-01"),
    "ads_2024":   (truncated("job_ads", "2024-01-01"), "1990-01-01"),
    "nab_2021":   (truncated("nab_conditions", "2021-01-01"), "1990-01-01"),
    "start_1960": (BASE, "1960-01-01"),
}

out = Path(sys.argv[1]); started = time.perf_counter()
fh = out.open("w", newline="")
w = csv.writer(fh)
w.writerow(["arm","asof","seed","rows","cols","obs_job_ads","obs_nab",
            "loading","collapsed","nowcast_ann"]); fh.flush()

for arm, (vint, start) in ARMS.items():
    for asof in VINTAGES:
        panel = build_panel(asof=asof, start=start, vintage=vint)
        restrict = build_restrict(panel, SPEC, p_f=P_F)
        t_now = target_periods(panel)
        n, n_f = SPEC.blocks.shape
        i_ads = panel.series_id.index("job_ads")
        i_nab = panel.series_id.index("nab_conditions")
        n_ads = int(np.isfinite(panel.Y[i_ads]).sum())
        n_nab = int(np.isfinite(panel.Y[i_nab]).sum())
        for seed in SEEDS:
            r = estimate_short(panel, n_gs=200, n_burn=100, seed=seed)
            p = map_parameter(np.median(r.params, axis=1), (n, n_f, P_F, P_E))
            lo = float(p.Lambda[panel.i_now, 0])
            col = lo <= COLLAPSED_GLOBAL_LOADING
            nc = ""
            if not col:
                lat = Latent(sigma=r.sigmas.mean(axis=2), s=r.ss.mean(axis=2))
                pt = point_nowcast(panel.Y, panel.Y, construct_ssm(p, lat, restrict),
                                   construct_ssm(p, lat, restrict), panel.i_now, t_now)
                nc = (float(panel.y_location[panel.i_now, 0])
                      + float(panel.y_scale[panel.i_now, 0]) * float(pt.nowcast[3, 0]))
            w.writerow([arm, asof, seed, panel.Y.shape[0], panel.Y.shape[1],
                        n_ads, n_nab, round(lo, 4), int(col), nc]); fh.flush()
        print(f"{arm:11s} {asof}  cols={panel.Y.shape[1]:4d} "
              f"job_ads={n_ads:3d} nab={n_nab:4d}  done "
              f"({(time.perf_counter()-started)/60:.0f} min)", flush=True)
fh.close()
print(f"wrote {out} in {(time.perf_counter()-started)/60:.1f} min", flush=True)
