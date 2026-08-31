"""Quarterly: re-estimate the model and save the fitted state for weekly reuse.

THE SPLIT THIS CREATES, AND WHY. `run_au_nowcast.py` used to re-estimate on every
run -- 18,000 sweeps, ~95 minutes locally and likely 3-5 hours on a GitHub
runner, against a 6-hour job limit. Every Monday, to redo work the model does not
need redone weekly.

The NY Fed do not do that either: "the model parameters are re-estimated every
quarter (on the first Wednesday of the quarter), and the Staff Nowcast is updated
each Friday" (Staff Nowcast 2.0, p2). This tool is the quarterly half. The weekly
half loads what it writes and runs the Kalman filter over the new month's data,
which is minutes.

WHAT IS SAVED, AND WHAT IS NOT. `state_space` needs three things from a sampler
run: the median parameter draw, and the mean of the stored `sigma` and `s`
latents. Not the chains -- those are hundreds of megabytes and nothing downstream
reads them. Roughly 170 KB of float64, committed, so the weekly job has no
artifact store to depend on and a reader can see what the published number was
built from.

THE LATENTS ARE TIME-INDEXED AND THE PANEL GROWS. `sigma` and `s` are
(n_f + n, T) over the estimation panel's months. A weekly panel is longer, so the
weekly job extends them by repeating the last column -- a starting value the
filter refines, and the same treatment the evolution chart already uses. The
estimation panel's first and last dates are saved so that job can check the
alignment rather than assume it.

    cd nowcasting_v3
    caffeinate -i .venv/bin/python -u tools/estimate_au.py [--vintage] [--quick]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from nyfed.au.build import (
    COLLAPSED_GLOBAL_LOADING,
    P_E,
    P_F,
    CollapsedFactorError,
    build_panel,
    estimate_short,
    fetch_vintage,
    load_vintage,
    state_space,
)
from nyfed.au.freshness import StaleSeriesError
from nyfed.au.sources import SPEC_PATH
from nyfed.parameters import map_parameter
from nyfed.spec import load_spec

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "state" / "au_estimate.npz"

PROD = dict(n_gs=10_000, n_burn=8_000, n_thin=2)
QUICK = dict(n_gs=200, n_burn=100, n_thin=1)
SEED = 4
SCHEMA = "v3-estimate-1"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vintage", action="store_true",
                    help="replay the recorded vintage instead of fetching")
    ap.add_argument("--quick", action="store_true",
                    help="short chain, for checking the wiring")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()
    started = time.perf_counter()

    if args.vintage:
        vintage = load_vintage(REPO / "tests/fixtures/au/vintage")
        asof = str(pd.Timestamp(vintage.recorded_at).date())
    else:
        print("fetching live...", flush=True)
        try:
            vintage = fetch_vintage()
        except Exception as exc:                                # noqa: BLE001
            print(f"FETCH FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        asof = str(pd.Timestamp.now(tz="UTC").date())

    # A REFUSAL HERE IS A HARD FAILURE, unlike in the weekly job. The weekly job
    # emits `status: "refused"` and the site renders it, because a stale feed is
    # a fact about this week. An estimation that cannot run leaves the weekly job
    # with nothing at all to load, so it should stop the pipeline loudly.
    try:
        panel = build_panel(asof=asof, vintage=vintage)
    except StaleSeriesError as exc:
        print("REFUSED: " + "; ".join(f"{k} {a}d vs {b}d budget"
                                      for k, a, b in exc.stale), file=sys.stderr)
        return 1

    settings = QUICK if args.quick else PROD
    print(f"panel {panel.Y.shape[0]}x{panel.Y.shape[1]} "
          f"({panel.dates[0].date()}..{panel.dates[-1].date()})", flush=True)
    print(f"sampling {settings['n_gs']}+{settings['n_burn']} at seed {SEED}...",
          flush=True)
    result = estimate_short(panel, seed=SEED, spec_path=SPEC_PATH, **settings)

    # Run it through the guarded funnel before saving. Persisting a collapsed
    # chain would hand every weekly run for the next quarter a model that is not
    # nowcasting, and the weekly job has no way to tell.
    try:
        state_space(panel, result, spec_path=SPEC_PATH)
    except CollapsedFactorError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1

    spec = load_spec(SPEC_PATH)
    n, n_f = spec.blocks.shape
    param_vec = np.median(result.params, axis=1)
    loading = float(map_parameter(param_vec, (n, n_f, P_F, P_E))
                    .Lambda[panel.i_now, 0])

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        out,
        param_vec=param_vec,
        sigma=result.sigmas.mean(axis=2),
        s=result.ss.mean(axis=2),
        meta=json.dumps({
            "schema": SCHEMA,
            "estimated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "asof": asof,
            "seed": SEED,
            "n_gs": settings["n_gs"],
            "n_burn": settings["n_burn"],
            "panel_first": str(panel.dates[0].date()),
            "panel_last": str(panel.dates[-1].date()),
            "panel_rows": int(panel.Y.shape[0]),
            "panel_cols": int(panel.Y.shape[1]),
            "series_id": list(panel.series_id),
            "gdp_global_loading": round(loading, 4),
            "collapse_floor": COLLAPSED_GLOBAL_LOADING,
            "minutes": round((time.perf_counter() - started) / 60, 1),
        }),
    )
    size_kb = out.stat().st_size / 1024
    print(f"\nwrote {out} ({size_kb:.0f} KB) in "
          f"{(time.perf_counter() - started) / 60:.1f} min", flush=True)
    print(f"  GDP's Global loading {loading:.3f} "
          f"(floor {COLLAPSED_GLOBAL_LOADING})", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
