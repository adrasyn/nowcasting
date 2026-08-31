"""Plan C, Phase 0: measure the warm start before Phase 1 commits to a window.

Four questions, from the spec
(`docs/superpowers/specs/2026-08-27-nowcast-v3-plan-c-backtest-design.md`):

  1. cold vs warm wall-clock per fit;
  2. whether the warm start lands in the identified basin EVERY time;
  3. the chain length a warm start actually needs, against the cold default;
  4. warm vs cold nowcast agreement on the same vintage.

Question 2 is the go/no-go. If warm starts do not reliably hold the basin, Plan
C stops here and the decision returns to the spec change rather than routing
around it.

WHAT A WARM START IS HERE, precisely: the PRIOR stays cold and the INITVAL goes
warm. The prior is a modelling choice -- rebuilding it from the previous fit
would let the same data inform the prior and the likelihood, and the posterior
being sampled would drift vintage by vintage. Only the chain's starting POINT
carries over, so warm and cold target the SAME posterior at every vintage and
the comparison in question 4 means something.

Carrying it over needs one adjustment: the panel gains a column each vintage, so
the previous chain's latent draw is one month short. The last column is repeated
to fill it. That is a starting value the sampler moves off on sweep one, not an
imputation.

THREE BLOCKS, not one. The spec asks for ~6 consecutive vintages; this runs
three separate runs of six across the reachable window (2022, 2024, 2026),
because a warm start that holds in 2026 -- every series long, every scale
settled -- says little about 2022, where `job_ads` is a few months old. If warm
starts fail anywhere it is likelier to be early.

Run:
    cd nowcasting_v3
    caffeinate -i .venv/bin/python -u tools/plan_c_phase0.py OUT.csv [HOURS]

Writes one CSV row per fit as it goes, so a kill at any point leaves a usable
partial measurement. Stops cleanly at the hour budget (default 4).
"""

from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from nyfed.au.build import (
    COLLAPSED_GLOBAL_LOADING,
    P_E,
    P_F,
    Panel,
    build_panel,
    load_vintage,
)
from nyfed.au.build import _initial_point  # noqa: PLC2701 -- the cold prior/initval pair
from nyfed.au.build import target_periods
from nyfed.au.restrict import build_restrict
from nyfed.gibbs import gibbs_sampler
from nyfed.model import InitVal, Latent, construct_ssm
from nyfed.nowcast import point_nowcast
from nyfed.parameters import map_parameter
from nyfed.settings import GibbsSettings
from nyfed.spec import load_spec
from nyfed.ssm import StateSpace

REPO = Path(__file__).resolve().parents[1]
SPEC_PATH = REPO / "model_spec_AU.csv"
VINTAGE_DIR = REPO / "tests" / "fixtures" / "au" / "vintage"

I_GLOBAL = 0

# Six consecutive monthly vintages per block. The first is the cold ANCHOR; the
# five after it are walked warm, which is the shape Plan C's backtest has.
BLOCKS = {
    "early": "2022-01-01",
    "middle": "2024-01-01",
    "recent": "2025-12-01",
}
N_VINTAGES = 6

# Chain lengths a warm start is tried at, shortest first. `n_burn` is half of
# `n_gs` throughout, matching the gate's 200/100 ratio.
WARM_LENGTHS = (50, 100, 200, 500)

# The cold default the gate ships, and the seeds the cold arm is tried at. Five
# seeds rather than one, because 18 of 30 collapse cold: a single cold seed
# would measure the lottery, not the cost.
COLD_N_GS, COLD_SEEDS = 200, (4, 13, 19, 22, 27)

# The anchor has to start identified or the whole block measures nothing. These
# are the identified seeds measured on this panel (see the sorted distribution
# in tests/test_au_end_to_end.py); tried in order until one clears the floor.
ANCHOR_SEEDS = (4, 13, 22, 19, 27, 16, 18, 23, 24, 20, 26)
ANCHOR_N_GS = 2000

FIELDS = [
    "block", "asof", "arm", "n_gs", "n_burn", "seed",
    "seconds", "sweeps", "global_loading", "collapsed", "nowcast",
    "panel_rows", "panel_cols", "deflator_skipped",
]


def _fit(panel: Panel, *, n_gs: int, n_burn: int, seed: int, initval=None):
    """One chain. ``initval=None`` is the cold start; anything else is warm."""
    spec = load_spec(SPEC_PATH)
    restrict = build_restrict(panel, spec, p_f=P_F)
    prior, cold_initval = _initial_point(panel, spec, restrict)
    settings = GibbsSettings(n_gs=n_gs, n_burn=n_burn, n_thin=1)
    started = time.perf_counter()
    result = gibbs_sampler(
        panel.Y, prior, restrict, initval if initval is not None else cold_initval,
        settings, np.random.default_rng(seed), need_latents=True,
    )
    return result, time.perf_counter() - started, spec, restrict


def _summarise(panel: Panel, result, spec, restrict):
    """Global loading, collapse verdict, and the nowcast if it is meaningful."""
    n, n_f = spec.blocks.shape
    param = map_parameter(np.median(result.params, axis=1), (n, n_f, P_F, P_E))
    loading = float(param.Lambda[panel.i_now, I_GLOBAL])
    collapsed = loading <= COLLAPSED_GLOBAL_LOADING
    nowcast = ""
    if not collapsed:
        latent = Latent(sigma=result.sigmas.mean(axis=2), s=result.ss.mean(axis=2))
        ssm: StateSpace = construct_ssm(param, latent, restrict)
        t_now = target_periods(panel)
        # Same call `quick_nowcast` makes: row 3 of `nowcast`, then out of
        # standardised units and into GDP's own annualised percent.
        point = point_nowcast(panel.Y, panel.Y, ssm, ssm, panel.i_now, t_now)
        location = float(panel.y_location[panel.i_now, 0])
        scale = float(panel.y_scale[panel.i_now, 0])
        nowcast = location + scale * float(point.nowcast[3, 0])
    return loading, collapsed, nowcast


def _warm_initval(result, T_new: int) -> InitVal:
    """The previous chain's LAST draw, stretched to the new panel's length.

    The panel gains a column per vintage. `Latent` is (n_f + n, T), so the last
    column is repeated to cover the new month -- a starting value, not an
    imputation: sweep one draws over it.
    """
    n_state = result.sigmas.shape[0]
    dims_n = result.sigmas.shape[0]  # n_f + n
    sigma = result.sigmas[:, :, -1]
    s = result.ss[:, :, -1]
    pad = T_new - sigma.shape[1]
    if pad > 0:
        sigma = np.concatenate([sigma, np.repeat(sigma[:, -1:], pad, axis=1)], axis=1)
        s = np.concatenate([s, np.repeat(s[:, -1:], pad, axis=1)], axis=1)
    elif pad < 0:
        sigma, s = sigma[:, :T_new], s[:, :T_new]
    assert sigma.shape == (dims_n, T_new) == s.shape, (sigma.shape, n_state, T_new)
    return sigma, s


def main() -> int:
    out_path = Path(sys.argv[1])
    budget_s = float(sys.argv[2] if len(sys.argv) > 2 else 4.0) * 3600.0
    started = time.perf_counter()

    vintage = load_vintage(VINTAGE_DIR)
    spec_dims = load_spec(SPEC_PATH).blocks.shape

    fresh = not out_path.exists()
    fh = out_path.open("a", newline="")
    writer = csv.DictWriter(fh, fieldnames=FIELDS)
    if fresh:
        writer.writeheader()
        fh.flush()

    def emit(**row):
        writer.writerow({k: row.get(k, "") for k in FIELDS})
        fh.flush()

    def out_of_time() -> bool:
        return time.perf_counter() - started > budget_s

    for block, first in BLOCKS.items():
        asofs = [str(d.date()) for d in
                 pd.date_range(first, periods=N_VINTAGES, freq="MS")]
        print(f"\n=== block {block}: {asofs[0]} .. {asofs[-1]} ===", flush=True)

        panels = {}
        for asof in asofs:
            try:
                panels[asof] = build_panel(asof=asof, vintage=vintage)
            except Exception as exc:                       # noqa: BLE001
                print(f"  {asof}  UNBUILDABLE: {type(exc).__name__}: "
                      f"{str(exc)[:90]}", flush=True)
        if len(panels) < 2:
            print(f"  block {block} skipped: fewer than two buildable vintages",
                  flush=True)
            continue
        built = [a for a in asofs if a in panels]

        # --- the cold anchor -------------------------------------------------
        anchor_asof = built[0]
        panel = panels[anchor_asof]
        carried = None
        for seed in ANCHOR_SEEDS:
            if out_of_time():
                break
            result, secs, spec, restrict = _fit(
                panel, n_gs=ANCHOR_N_GS, n_burn=ANCHOR_N_GS // 2, seed=seed)
            loading, collapsed, nowcast = _summarise(panel, result, spec, restrict)
            emit(block=block, asof=anchor_asof, arm="anchor_cold",
                 n_gs=ANCHOR_N_GS, n_burn=ANCHOR_N_GS // 2, seed=seed,
                 seconds=round(secs, 2), sweeps=ANCHOR_N_GS + ANCHOR_N_GS // 2,
                 global_loading=round(loading, 4), collapsed=int(collapsed),
                 nowcast=nowcast, panel_rows=panel.Y.shape[0],
                 panel_cols=panel.Y.shape[1],
                 deflator_skipped=";".join(sorted(panel.deflator_skipped)))
            print(f"  anchor {anchor_asof} seed {seed:2d}  {secs:6.1f}s  "
                  f"loading {loading:7.4f}  {'COLLAPSED' if collapsed else 'ok'}",
                  flush=True)
            if not collapsed:
                carried = result
                break
        if carried is None:
            print(f"  block {block}: NO ANCHOR FOUND -- warm walk skipped",
                  flush=True)
            continue
        last_walked = None

        # --- walk the rest ---------------------------------------------------
        for asof in built[1:]:
            if out_of_time():
                print("  budget reached; stopping", flush=True)
                break
            panel = panels[asof]
            T = panel.Y.shape[1]
            sigma, s = _warm_initval(carried, T)
            n, n_f = spec_dims
            prev_param = map_parameter(carried.params[:, -1], (n, n_f, P_F, P_E))
            warm = InitVal(param=prev_param, latent=Latent(sigma=sigma, s=s))

            next_carried = None
            for n_gs in WARM_LENGTHS:
                if out_of_time():
                    break
                result, secs, spec, restrict = _fit(
                    panel, n_gs=n_gs, n_burn=n_gs // 2, seed=4, initval=warm)
                loading, collapsed, nowcast = _summarise(panel, result, spec, restrict)
                emit(block=block, asof=asof, arm="warm", n_gs=n_gs,
                     n_burn=n_gs // 2, seed=4, seconds=round(secs, 2),
                     sweeps=n_gs + n_gs // 2, global_loading=round(loading, 4),
                     collapsed=int(collapsed), nowcast=nowcast,
                     panel_rows=panel.Y.shape[0], panel_cols=T,
                     deflator_skipped=";".join(sorted(panel.deflator_skipped)))
                print(f"  {asof} warm n_gs={n_gs:4d}  {secs:6.1f}s  "
                      f"loading {loading:7.4f}  "
                      f"{'COLLAPSED' if collapsed else 'ok':9s} "
                      f"nowcast {nowcast if nowcast == '' else round(nowcast, 4)}",
                      flush=True)
                if n_gs == WARM_LENGTHS[-1]:
                    next_carried = result

            for seed in COLD_SEEDS:
                if out_of_time():
                    break
                result, secs, spec, restrict = _fit(
                    panel, n_gs=COLD_N_GS, n_burn=COLD_N_GS // 2, seed=seed)
                loading, collapsed, nowcast = _summarise(panel, result, spec, restrict)
                emit(block=block, asof=asof, arm="cold", n_gs=COLD_N_GS,
                     n_burn=COLD_N_GS // 2, seed=seed, seconds=round(secs, 2),
                     sweeps=COLD_N_GS + COLD_N_GS // 2,
                     global_loading=round(loading, 4), collapsed=int(collapsed),
                     nowcast=nowcast, panel_rows=panel.Y.shape[0], panel_cols=T,
                     deflator_skipped=";".join(sorted(panel.deflator_skipped)))
                print(f"  {asof} cold seed {seed:2d}   {secs:6.1f}s  "
                     f"loading {loading:7.4f}  "
                     f"{'COLLAPSED' if collapsed else 'ok':9s} "
                     f"nowcast {nowcast if nowcast == '' else round(nowcast, 4)}",
                     flush=True)

            if next_carried is None:
                print(f"  {asof}: warm chain not carried (budget); block ends",
                      flush=True)
                break
            carried = next_carried
            last_walked = asof

        # --- the closing drift check ----------------------------------------
        # "Warm start hides a decaying chain" is the first risk in the spec's
        # table, and logging the loading every vintage does not close it: a
        # chain can hold the basin and still be sampling a posterior that has
        # drifted away from the one a fresh fit would find. This is the
        # anchor comparison the spec calls the pass/fail -- one COLD long fit at
        # the last vintage walked, so the warm nowcast there has a reference
        # that shares its chain length instead of only the 200-sweep cold arm.
        if not out_of_time() and last_walked is not None:
            panel = panels[last_walked]
            for seed in ANCHOR_SEEDS:
                if out_of_time():
                    break
                result, secs, spec, restrict = _fit(
                    panel, n_gs=ANCHOR_N_GS, n_burn=ANCHOR_N_GS // 2, seed=seed)
                loading, collapsed, nowcast = _summarise(
                    panel, result, spec, restrict)
                emit(block=block, asof=last_walked, arm="anchor_cold_close",
                     n_gs=ANCHOR_N_GS, n_burn=ANCHOR_N_GS // 2, seed=seed,
                     seconds=round(secs, 2),
                     sweeps=ANCHOR_N_GS + ANCHOR_N_GS // 2,
                     global_loading=round(loading, 4), collapsed=int(collapsed),
                     nowcast=nowcast, panel_rows=panel.Y.shape[0],
                     panel_cols=panel.Y.shape[1],
                     deflator_skipped=";".join(sorted(panel.deflator_skipped)))
                print(f"  close  {last_walked} seed {seed:2d}  {secs:6.1f}s  "
                      f"loading {loading:7.4f}  "
                      f"{'COLLAPSED' if collapsed else 'ok':9s} "
                      f"nowcast {nowcast if nowcast == '' else round(nowcast, 4)}",
                      flush=True)
                if not collapsed:
                    break

        if out_of_time():
            break

    fh.close()
    print(f"\nwrote {out_path} in {(time.perf_counter() - started) / 60:.1f} min",
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
