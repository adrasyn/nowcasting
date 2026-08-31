"""Produce `data/latest_v3.json`: fetch, estimate, nowcast, emit.

THE ONE PATH THAT HAS NEVER RUN. Every test in this project replays
`tests/fixtures/au/vintage`; this is the first thing that fetches four hosts
live (ABS twice, RBA, and v2's committed CSVs) and carries the result all the
way to an artefact a reader sees. Expect it to find things.

A REFUSAL IS A SUCCESSFUL RUN. `check_freshness` refuses a stale feed and
`state_space` refuses a chain that left GDP disconnected from the panel. Both
write a `status: "refused"` payload and exit 0, because a refusal is the
system working -- the site renders it as a refusal rather than showing last
week's number as if it were current. Exit 1 is reserved for a genuine fault:
a host that will not answer, a parse that fails, a bug here.

    cd nowcasting_v3
    caffeinate -i .venv/bin/python -u tools/run_au_nowcast.py            # live
    caffeinate -i .venv/bin/python -u tools/run_au_nowcast.py --vintage  # replay
    ... --quick     # 200/100 instead of the production chain, for wiring checks
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
    COLLAPSED_GLOBAL_LOADING, P_E, P_F, CollapsedFactorError, build_panel,
    estimate_short, fetch_vintage, load_vintage, state_space, target_periods,
)
from nyfed.au.emit import nowcast_payload, refusal_payload
from nyfed.au.freshness import StaleSeriesError
from nyfed.au.sources import AU_SERIES
from nyfed.nowcast import density_nowcast, point_nowcast
from nyfed.parameters import map_parameter
from nyfed.spec import load_spec

REPO = Path(__file__).resolve().parents[1]
SITE_DATA = REPO.parent / "data"
SPEC_PATH = REPO / "model_spec_AU.csv"

# Production settings, from `nyfed/run_us_reference.py` and the README's timing
# table: 10,000 stored draws after 8,000 burn-in. ~1.5 h on this machine.
PROD = dict(n_gs=10_000, n_burn=8_000, n_thin=2)
QUICK = dict(n_gs=200, n_burn=100, n_thin=1)
SEED = 4
N_DENSITY = 1_250          # matches the weekly path the timings were measured on


def _quarter(ts) -> str:
    return f"{ts.year} Q{(ts.month - 1) // 3 + 1}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vintage", action="store_true",
                    help="replay the recorded vintage instead of fetching")
    ap.add_argument("--quick", action="store_true",
                    help="short chain, for checking the wiring")
    ap.add_argument("--out", default=str(SITE_DATA / "latest_v3.json"))
    args = ap.parse_args()

    started = time.perf_counter()
    now = datetime.now(UTC).isoformat(timespec="seconds")
    asof = str(pd.Timestamp.now(tz="UTC").date())
    out = Path(args.out)

    def write(payload: dict) -> None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n")
        print(f"wrote {out}  status={payload['status']}", flush=True)

    # ---- fetch -----------------------------------------------------------
    if args.vintage:
        print("replaying tests/fixtures/au/vintage", flush=True)
        vintage = load_vintage(REPO / "tests/fixtures/au/vintage")
        asof = str(pd.Timestamp(vintage.recorded_at).date())
    else:
        print("fetching live (ABS x2, RBA, v2 CSVs)...", flush=True)
        try:
            vintage = fetch_vintage()
        except Exception as exc:                                # noqa: BLE001
            print(f"FETCH FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        for k, s in sorted(vintage.series.items()):
            obs = s.dropna()
            print(f"  {k:22s} n={len(obs):5d}  through {obs.index[-1].date()}",
                  flush=True)

    # ---- build (may refuse) ---------------------------------------------
    try:
        panel = build_panel(asof=asof, vintage=vintage)
    except StaleSeriesError as exc:
        # `check_freshness` reports a series that has never been observed as
        # 10**6 days old (freshness.py:59). That sentinel is fine inside a
        # traceback and wrong on a web page, so it is named here rather than
        # printed.
        # Registry keys are for code. A refusal is read by a person, so the
        # series gets the name its publisher gives it.
        names = {s.key: s.name for s in AU_SERIES}

        def _age(key: str, age: int, budget: int) -> str:
            label = names.get(key, key)
            if age >= 10 ** 6:
                return f"{label} has no observations at all"
            return f"{label} is {age} days old, against a {budget}-day budget"

        write(refusal_payload(
            reason="stale input",
            detail="; ".join(_age(k, a, b) for k, a, b in exc.stale),
            generated_at=now, asof=asof))
        return 0
    except ValueError as exc:
        write(refusal_payload(reason="panel could not be assembled",
                              detail=str(exc)[:400], generated_at=now, asof=asof))
        return 0

    print(f"panel {panel.Y.shape[0]}x{panel.Y.shape[1]}, "
          f"{panel.dates[0].date()}..{panel.dates[-1].date()}", flush=True)

    # ---- estimate --------------------------------------------------------
    settings = QUICK if args.quick else PROD
    print(f"sampling {settings['n_gs']}+{settings['n_burn']} at seed {SEED}...",
          flush=True)
    result = estimate_short(panel, seed=SEED, spec_path=SPEC_PATH, **settings)
    print(f"  sampled in {(time.perf_counter()-started)/60:.1f} min", flush=True)

    spec = load_spec(SPEC_PATH)
    n, n_f = spec.blocks.shape
    param = map_parameter(np.median(result.params, axis=1), (n, n_f, P_F, P_E))
    loading = float(param.Lambda[panel.i_now, 0])

    try:
        ssm = state_space(panel, result, spec_path=SPEC_PATH)
    except CollapsedFactorError as exc:
        write(refusal_payload(reason="collapsed chain", detail=str(exc)[:400],
                              generated_at=now, asof=asof))
        return 0

    # ---- nowcast ---------------------------------------------------------
    t_now = target_periods(panel)
    loc = float(panel.y_location[panel.i_now, 0])
    scl = float(panel.y_scale[panel.i_now, 0])
    point = point_nowcast(panel.Y, panel.Y, ssm, ssm, panel.i_now, t_now)
    ann = [loc + scl * float(point.nowcast[3, k]) for k in range(len(t_now))]
    horizons = [(_quarter(panel.dates[t]), a) for t, a in zip(t_now, ann)]

    rng = np.random.default_rng(SEED)
    draws = np.vstack([
        loc + scl * density_nowcast(panel.Y, ssm, panel.i_now, t_now, rng)
        for _ in range(N_DENSITY if not args.quick else 200)])

    gdp = vintage.series["gdp"].dropna()
    payload = nowcast_payload(
        panel=panel, horizons=horizons, draws=draws,
        prev_level=float(gdp.iloc[-1]), prev_quarter=_quarter(gdp.index[-1]),
        generated_at=now, asof=asof, gdp_global_loading=loading,
        collapse_floor=COLLAPSED_GLOBAL_LOADING,
        n_gs=settings["n_gs"], n_burn=settings["n_burn"], seed=SEED)
    write(payload)
    for h in payload["horizons"]:
        band = (f"  [{h.get('ci_68_low','?')}, {h.get('ci_68_high','?')}]"
                if "ci_68_low" in h else "")
        print(f"  {h['kind']:8s} {h['quarter']}  {h['qoq_growth_pct']:+.2f}%{band}",
              flush=True)
    print(f"total {(time.perf_counter()-started)/60:.1f} min", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
