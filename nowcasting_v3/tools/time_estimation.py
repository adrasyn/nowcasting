"""Time the two production paths, so Plan E can be decided on a measurement.

Two numbers, both recorded in ``README.md``:

``estimate``
    One full ``gibbs_sampler`` run at ``load_settings.m``'s production settings
    (``n_GS = 10000``, ``n_burn = 8000``, ``n_thin = 2``) on the US panel --
    ``example_estimate.m``, minus the display. This is the quarterly
    re-estimation job, and its wall clock decides whether that job fits a
    GitHub Actions runner.

``weekly``
    The weekly nowcast path: 1,250 ``S_update`` draws per vintage, one
    ``point_nowcast``, 1,250 ``density_nowcast`` draws. This is what a cron job
    runs every Friday, and it has to fit ``timeout-minutes: 60``.

``example_estimate.m`` computes ``Y_location`` / ``Y_scale`` as the pre-2020
mean and standard deviation, which needs ``timekey`` -- a MATLAB ``datetime``
stored as an MCOS object that neither scipy nor Octave decodes. The values it
computed are stored in ``Estimates_2023_09_20.mat`` and are read from there
instead; they are the same numbers, not an approximation of them.

Usage::

    ../.venv/bin/python time_estimation.py weekly
    ../.venv/bin/python time_estimation.py estimate
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
from scipy.io import loadmat

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nyfed.gibbs import gibbs_sampler                       # noqa: E402
from nyfed.model import InitVal, Latent, construct_prior    # noqa: E402
from nyfed.parameters import Params                         # noqa: E402
from nyfed.run_us_reference import (                        # noqa: E402
    MATLAB_DIR,
    SPEC_FILE,
    load_estimates,
    load_vintage,
    run_reference_week,
)
from nyfed.settings import GibbsSettings                     # noqa: E402
from nyfed.spec import load_spec                             # noqa: E402


def load_initval() -> InitVal:
    """``load('initval.mat')`` -- the starting point of ``example_estimate.m``."""
    raw = loadmat(MATLAB_DIR / "initval.mat", struct_as_record=False,
                  squeeze_me=False)["initval"][0, 0]
    p = raw.param[0, 0]
    param = Params(
        mu=np.asarray(p.mu, dtype=float).ravel(),
        gamma_g=np.asarray(p.gamma_g, dtype=float).item(),
        Lambda=np.asarray(p.Lambda, dtype=float),
        Phi=np.asarray(p.Phi, dtype=float),
        gamma_f=np.asarray(p.gamma_f, dtype=float).ravel(),
        pi_f=np.asarray(p.pi_f, dtype=float).ravel(),
        phi=np.asarray(p.phi, dtype=float),
        gamma_e=np.asarray(p.gamma_e, dtype=float).ravel(),
        pi_e=np.asarray(p.pi_e, dtype=float).ravel(),
    )
    latent = Latent(sigma=np.asarray(raw.sigma, dtype=float),
                    s=np.asarray(raw.s, dtype=float))
    return InitVal(param=param, latent=latent)


def time_estimate(n_gs: int, n_burn: int, seed: int) -> float:
    est = load_estimates()
    Y = load_vintage("2023_09_20", est)
    initval = load_initval()
    if initval.latent.sigma.shape[1] != Y.shape[1]:
        raise ValueError(
            f"initval covers {initval.latent.sigma.shape[1]} periods, "
            f"the panel {Y.shape[1]}"
        )
    # example_estimate.m: prior = construct_prior(dimvec, initval.param.Lambda)
    # followed by prior.P_Phi = prior.P_Phi/5.
    prior = construct_prior(est.dimvec, initval.param.Lambda)
    prior.P_Phi = prior.P_Phi / 5
    settings = GibbsSettings(n_gs=n_gs, n_burn=n_burn)
    sweeps = (n_burn + n_gs + 1) * settings.n_thin

    print(f"gibbs_sampler: n_gs={n_gs}, n_burn={n_burn}, n_thin={settings.n_thin}"
          f" -> {sweeps} gibbs_update sweeps on a {Y.shape} panel", flush=True)
    started = time.perf_counter()
    result = gibbs_sampler(Y, prior, est.restrict, initval, settings,
                           np.random.default_rng(seed), need_latents=False)
    elapsed = time.perf_counter() - started

    # A run that silently degenerated would still take the same wall clock.
    if not np.isfinite(result.params).all():
        raise RuntimeError("the sampler produced non-finite parameters")
    first, last = result.params[:, :100], result.params[:, -100:]
    print(f"params {result.params.shape}, "
          f"first-100 mean |param| = {np.abs(first).mean():.6f}, "
          f"last-100 mean |param| = {np.abs(last).mean():.6f}")
    print(f"elapsed: {elapsed:.1f} s = {elapsed / 60:.1f} min "
          f"= {elapsed / 3600:.2f} h  ({elapsed / sweeps:.4f} s/sweep)")
    return elapsed


def time_weekly(week: str, seed: int) -> float:
    est = load_estimates()
    spec = load_spec(MATLAB_DIR / SPEC_FILE)
    print(f"weekly path for {week}: 2 x 1250 S_update, 1 point_nowcast, "
          "1250 density_nowcast", flush=True)
    started = time.perf_counter()
    result = run_reference_week(week, seed=seed, estimates=est, spec=spec)
    elapsed = time.perf_counter() - started
    print(f"nowcast = {result.nowcast:.6f}")
    print(f"elapsed: {elapsed:.1f} s = {elapsed / 60:.1f} min")
    return elapsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("path", choices=["estimate", "weekly"])
    parser.add_argument("--n-gs", type=int, default=10000)
    parser.add_argument("--n-burn", type=int, default=8000)
    parser.add_argument("--week", default="2023-09-29")
    parser.add_argument("--seed", type=int, default=321)
    args = parser.parse_args(argv)
    if args.path == "estimate":
        time_estimate(args.n_gs, args.n_burn, args.seed)
    else:
        time_weekly(args.week, args.seed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
