"""Reproduce the NY Fed's published US nowcasts end to end.

Line-by-line port of ``nyfed_matlab/example_nowcast.m``: load the spec and two
data vintages, rebuild the parameters from the stored Gibbs output, redraw the
outlier states, build both state spaces, and run the point and density
nowcasts. It is the end-to-end gate for the whole port -- every deterministic
function below is separately pinned to an Octave fixture, and this module is
what shows the assembled whole reaches the numbers the Fed published.

What the MATLAB does that is easy to get wrong
----------------------------------------------

* **Both vintages read the same estimate file.** ``example_nowcast.m`` sets
  ``date_estimate_old == date_estimate_new == 2023-09-20``, and the drop ships
  exactly one ``Estimates_*.mat``. So ``param_old == param_new`` and the two
  latent chains start from the same point; the "parameter revision" row of the
  decomposition is really the *latent* revision, driven only by the different
  data the two ``S_update`` chains see.

* **``S_update`` does not touch ``sigma``.** It redraws the outlier indicators
  ``s`` only and returns its input ``sigma`` unchanged, so averaging ``sigma``
  over the 1,250 draws returns the posterior mean it started from. The
  averaging matters for ``s`` alone. Reproduced here rather than shortcut, so
  the code still says what the MATLAB says.

* **``rng(321)`` is reset between the two latent loops.** Each vintage's chain
  therefore sees the same random stream. Mirrored with a fresh
  ``default_rng(seed)`` per vintage. The density loop is *not* reset, and
  continues from the new-vintage generator, as in the MATLAB.

* **The panel is padded to the forecast horizon.** ``example_nowcast.m`` works
  the pad length out from ``timekey``, a MATLAB ``datetime`` stored as an
  undecodable MCOS object. ``restrict.f_active`` was built on the same extended
  calendar during estimation, so its width is the same ``T``; that is where
  ``T`` comes from here, and :func:`load_vintage` asserts the implied pad is
  the three months from October to December 2023.

* **``t_now`` is 1-based in MATLAB.** ``(find(...,1,'last')+3):3:T`` becomes
  ``arange(last + 3, T, 3)`` on 0-based indices: three months past the last
  observed GDP quarter, then every quarter to the end of the padded panel.

Monte Carlo error
-----------------

The published figures came out of MATLAB's ``rng(321)`` stream, which numpy
cannot reproduce. The port converges to the same limit by a different path,
with Monte Carlo error around it, so the gate tolerance is measured from the
seed-to-seed spread rather than assumed -- see
:func:`nyfed.run_us_reference.main` ``--seeds`` and ``tests/test_end_to_end.py``.

Usage::

    .venv/bin/python -m nyfed.run_us_reference 2023-09-29
    .venv/bin/python -m nyfed.run_us_reference 2023-09-29 --seeds 321 1 2 3 4
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.io import loadmat

from .gibbs import s_update
from .model import Latent, Restrict, construct_ssm
from .nowcast import PointNowcast, density_nowcast, news_table, point_nowcast
from .parameters import Params, map_parameter
from .settings import GibbsSettings
from .spec import ModelSpec, load_spec

__all__ = [
    "MATLAB_DIR",
    "VINTAGE_PAIRS",
    "Estimates",
    "ReferenceWeek",
    "load_estimates",
    "load_vintage",
    "run_reference_week",
]

MATLAB_DIR = Path(__file__).resolve().parents[1] / "nyfed_matlab"

SPEC_FILE = "model_spec_FRED.csv"
NOWCAST_SERIES = "GDPC1"

#: ``date_estimate_new`` / ``date_estimate_old`` in ``example_nowcast.m``. The
#: drop ships one estimate file and both weeks use it.
ESTIMATE_DATE = "2023_09_20"

#: ``(date_nowcast_old, date_nowcast_new)`` per published week. The 2023-09-29
#: week is the one ``example_nowcast.m`` ships configured; the 2023-10-06 week
#: rolls both dates forward one Friday.
VINTAGE_PAIRS: dict[str, tuple[str, str]] = {
    "2023-09-29": ("2023_09_22", "2023_09_29"),
    "2023-10-06": ("2023_09_29", "2023_10_06"),
}

#: ``date_forecast_old`` / ``date_forecast_new``: the panel is NaN-padded to
#: December 2023, three months past the last observed month of every vintage.
FORECAST_PAD = 3


# --------------------------------------------------------------------------- #
# Loading the MATLAB drop
# --------------------------------------------------------------------------- #


@dataclass
class Estimates:
    """The fields of ``Estimates_<date>.mat`` this module reads.

    ``param_gibbs`` is (n_param, n_draw); ``sigmas`` and ``ss`` are
    (n_f + n, T, n_latent_draw). ``T`` is the width of ``restrict.f_active``,
    which is the padded estimation calendar -- see the module docstring.
    """

    dimvec: tuple[int, int, int, int]
    restrict: Restrict
    y_location: np.ndarray      # (n, 1)
    y_scale: np.ndarray         # (n, 1)
    param_gibbs: np.ndarray     # (n_param, n_draw)
    sigmas: np.ndarray          # (n_f + n, T, n_latent_draw)
    ss: np.ndarray              # (n_f + n, T, n_latent_draw)

    @property
    def T(self) -> int:
        return int(self.restrict.f_active.shape[1])

    def median_param(self) -> Params:
        """``map_parameter(median(param_Gibbs, 2), dimvec)``."""
        return map_parameter(np.median(self.param_gibbs, axis=1), self.dimvec)

    def mean_latent(self) -> Latent:
        """``latent.sigma = mean(latents.sigmas, 3)``, likewise ``s``."""
        return Latent(sigma=self.sigmas.mean(axis=2), s=self.ss.mean(axis=2))


def load_estimates(date: str = ESTIMATE_DATE, root: Path = MATLAB_DIR) -> Estimates:
    """Load ``Estimates_<date>.mat``.

    The file is 21 MB and gitignored; it ships with the NY Fed drop and is
    never committed.
    """
    path = root / f"Estimates_{date}.mat"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} is absent. It is the 21 MB estimate file from the NY Fed "
            "drop and is deliberately not committed."
        )
    raw = loadmat(path, struct_as_record=False, squeeze_me=False)
    restrict = raw["restrict"][0, 0]
    return Estimates(
        dimvec=tuple(int(x) for x in raw["dimvec"].ravel()),
        restrict=Restrict(
            Lambda=np.asarray(restrict.Lambda, dtype=float),
            Phi=np.asarray(restrict.Phi, dtype=float),
            iota=np.asarray(restrict.iota, dtype=float).ravel(),
            f_active=np.asarray(restrict.f_active).astype(bool),
            isquart=np.asarray(restrict.isquart).ravel().astype(bool),
        ),
        y_location=np.asarray(raw["Y_location"], dtype=float).reshape(-1, 1),
        y_scale=np.asarray(raw["Y_scale"], dtype=float).reshape(-1, 1),
        param_gibbs=np.asarray(raw["param_Gibbs"], dtype=float),
        sigmas=np.asarray(raw["latents"][0, 0].sigmas, dtype=float),
        ss=np.asarray(raw["latents"][0, 0].ss, dtype=float),
    )


def load_vintage(vintage: str, est: Estimates, root: Path = MATLAB_DIR) -> np.ndarray:
    """Standardise and NaN-pad one data vintage to ``est.T``.

    ``(Data.data' - Y_location) ./ Y_scale`` followed by the NaN columns
    ``example_nowcast.m`` appends out to the forecast horizon.
    """
    path = root / "data" / f"Data_{vintage}.mat"
    data = np.asarray(
        loadmat(path, struct_as_record=False, squeeze_me=False)["data"], dtype=float
    )
    n = est.dimvec[0]
    if data.shape[1] != n:
        raise ValueError(f"{path.name} has {data.shape[1]} series, expected {n}")
    pad = est.T - data.shape[0]
    if pad != FORECAST_PAD:
        raise ValueError(
            f"{path.name} implies a {pad}-month forecast pad; example_nowcast.m "
            f"pads to December 2023, which is {FORECAST_PAD} months"
        )
    Y = (data.T - est.y_location) / est.y_scale
    return np.hstack([Y, np.full((n, pad), np.nan)])


# --------------------------------------------------------------------------- #
# The result
# --------------------------------------------------------------------------- #


@dataclass
class ReferenceWeek:
    """One reproduced publication week.

    ``nowcast`` is the headline: ``pnt_nowcast(1)`` in ``example_nowcast.m``,
    the first entry of ``t_now``, in the nowcast series' own units.

    ``pnt_nowcast_old`` is the same quantity computed from last week's vintage
    and last week's state space -- row 1 of the decomposition, the figure the
    revision and release impacts move away from.

    ``pnt_nowcast`` carries every horizon; ``rev_ssm`` and ``rev_data`` are the
    parameter- and data-revision terms; ``table`` is the release-impact table
    the MATLAB prints; ``density`` is (n_draws, len(t_now)).
    """

    week: str
    seed: int
    point: PointNowcast
    pnt_nowcast: np.ndarray     # (len(t_now),)
    pnt_nowcast_old: np.ndarray  # (len(t_now),) last week's, same units
    rev_ssm: np.ndarray         # (len(t_now),)
    rev_data: np.ndarray        # (len(t_now),)
    table: pd.DataFrame
    impacts: np.ndarray         # (n, T, len(t_now)), NaN off the release cells
    density: np.ndarray         # (n_draws, len(t_now))
    series_id: list[str]        # spec order, so it indexes impacts' first axis
    i_now: int
    t_now: np.ndarray

    @property
    def nowcast(self) -> float:
        """``output.nowcast`` -- the published headline."""
        return float(self.pnt_nowcast[0])

    @property
    def revisions_impact(self) -> float:
        """``rev_SSM(1) + rev_data(1)``."""
        return float(self.rev_ssm[0] + self.rev_data[0])

    @property
    def releases_impact(self) -> float:
        """``sum(news_table.Impact)`` -- first horizon only, as MATLAB prints."""
        return float(self.table["impact"].sum())

    def impact_for(self, series_id: str, horizon: int = 0) -> float:
        """Impact of this week's release of ``series_id``, in pp of the nowcast.

        ``horizon`` indexes ``t_now``; the published tables carry horizon 0
        only (see ``tools/extract_published.py``). Raises rather than returning
        a default for a series that did not release, so a typo in a series id
        cannot pass as a zero impact -- four of the nine published impacts for
        2023-09-29 are smaller in magnitude than 0.01, so a silently-zero
        lookup would sail through any tolerance worth using.
        """
        try:
            row = self.series_id.index(series_id)
        except ValueError:
            raise KeyError(f"{series_id} is not in the panel") from None
        periods = np.flatnonzero(~np.isnan(self.impacts[row, :, horizon]))
        if periods.size == 0:
            raise KeyError(f"{series_id} did not release in {self.week}")
        if periods.size > 1:
            raise KeyError(
                f"{series_id} released in {periods.size} periods in {self.week}; "
                "the published table is keyed by series and cannot be compared"
            )
        return float(self.impacts[row, int(periods[0]), horizon])


# --------------------------------------------------------------------------- #
# example_nowcast.m
# --------------------------------------------------------------------------- #


def _average_latents(
    param: Params,
    latent: Latent,
    Y: np.ndarray,
    restrict: Restrict,
    n_draws: int,
    seed: int,
    progress: bool,
    label: str,
) -> tuple[Latent, np.random.Generator]:
    """``for i_draw = 1:n_GS/n_each; latent = S_update(...); end`` then average.

    MATLAB resets ``rng(321)`` before each of the two loops, so both vintages
    see the same stream; a fresh generator per call mirrors that. The generator
    is returned so the caller can carry it into the density loop, which MATLAB
    does *not* reset.
    """
    rng = np.random.default_rng(seed)
    sigma_sum = np.zeros_like(np.asarray(latent.sigma, dtype=float))
    s_sum = np.zeros_like(np.asarray(latent.s, dtype=float))
    for i_draw in range(n_draws):
        latent = s_update(param, latent, Y, restrict, rng)
        sigma_sum += latent.sigma
        s_sum += latent.s
        if progress and (i_draw + 1) % 250 == 0:
            print(f"  {label}: draw {i_draw + 1}/{n_draws}", flush=True)
    return Latent(sigma=sigma_sum / n_draws, s=s_sum / n_draws), rng


def run_reference_week(
    week: str,
    *,
    seed: int = 321,
    n_draws: int | None = None,
    n_density_draws: int | None = None,
    estimates: Estimates | None = None,
    spec: ModelSpec | None = None,
    root: Path = MATLAB_DIR,
    progress: bool = False,
) -> ReferenceWeek:
    """Reproduce one published week end to end. Port of ``example_nowcast.m``.

    ``seed`` stands in for MATLAB's ``rng(321)``; the two streams differ, so the
    result carries Monte Carlo error (measured in the README). ``n_draws``
    defaults to ``settings.n_GS / settings.n_each = 1250``.

    ``n_density_draws`` defaults to ``n_draws``, as in the MATLAB. It is
    separable only because the density loop runs last and touches nothing the
    point nowcast or the news table depend on, so a Step 0 spread measurement
    can cut it without changing a single number it measures. Leave it alone for
    anything that is meant to be the reference run.
    """
    if week not in VINTAGE_PAIRS:
        raise KeyError(f"{week} is not a published week; have {sorted(VINTAGE_PAIRS)}")
    vintage_old, vintage_new = VINTAGE_PAIRS[week]
    if n_draws is None:
        settings = GibbsSettings()
        n_draws = settings.n_gs // settings.n_each
    if n_density_draws is None:
        n_density_draws = n_draws
    if estimates is None:
        estimates = load_estimates(root=root)
    if spec is None:
        spec = load_spec(root / SPEC_FILE)

    est = estimates
    restrict = est.restrict

    # Fix location and scale of the data, and pad to the forecast horizon
    Y_old = load_vintage(vintage_old, est, root=root)
    Y_new = load_vintage(vintage_new, est, root=root)
    T = Y_new.shape[1]

    # Find index for GDP (variable to nowcast), and the periods to nowcast.
    # MATLAB: t_now = (find(~isnan(Y_new(i_now, :)), 1, 'last') + 3):3:T
    i_now = spec.series_id.index(NOWCAST_SERIES)
    observed = np.flatnonzero(~np.isnan(Y_new[i_now, :]))
    if observed.size == 0:
        raise ValueError(f"{NOWCAST_SERIES} is never observed in {vintage_new}")
    t_now = np.arange(int(observed[-1]) + 3, T, 3)

    # Recover parameters and latent variables. Both vintages read the same
    # estimate file, exactly as example_nowcast.m does.
    param_old = est.median_param()
    param_new = est.median_param()

    # Update latent variables and construct state-space models
    latent_old, _ = _average_latents(param_old, est.mean_latent(), Y_old, restrict,
                                     n_draws, seed, progress, f"{vintage_old} latents")
    latent_new, rng = _average_latents(param_new, est.mean_latent(), Y_new, restrict,
                                       n_draws, seed, progress, f"{vintage_new} latents")
    ssm_old = construct_ssm(param_old, latent_old, restrict)
    ssm_new = construct_ssm(param_new, latent_new, restrict)

    # Compute point nowcast
    point = point_nowcast(Y_old, Y_new, ssm_old, ssm_new, i_now, t_now)
    location = est.y_location
    scale = est.y_scale
    pnt_nowcast = location[i_now, 0] + scale[i_now, 0] * point.nowcast[3, :]
    # Row 1 is last week's data through last week's state space: the figure the
    # revisions and releases below are measured as moving away from.
    pnt_nowcast_old = location[i_now, 0] + scale[i_now, 0] * point.nowcast[0, :]
    rev_ssm = scale[i_now, 0] * (point.nowcast[1, :] - point.nowcast[0, :])
    rev_data = scale[i_now, 0] * (point.nowcast[2, :] - point.nowcast[1, :])

    # forecasts = Y_location + Y_scale.*forecasts_tmp; news = Y_scale.*news_tmp;
    # actual = news + forecasts; weights = Y_scale(i_now)*(weights_tmp./Y_scale);
    # impacts = (actual - forecasts) .* weights, at every horizon.
    forecasts = location + scale * point.forecasts
    actual = scale * point.news + forecasts
    weights = scale[i_now, 0] * (point.weights / scale[:, :, None])
    impacts = (actual - forecasts)[:, :, None] * weights

    # Compute density nowcast, continuing the new vintage's generator
    density = np.array([
        location[i_now, 0] + scale[i_now, 0]
        * density_nowcast(Y_new, ssm_new, i_now, t_now, rng)
        for _ in range(n_density_draws)
    ])

    result = ReferenceWeek(
        week=week, seed=seed, point=point, pnt_nowcast=pnt_nowcast,
        pnt_nowcast_old=pnt_nowcast_old, rev_ssm=rev_ssm, rev_data=rev_data,
        table=news_table(point, spec, est.y_location, est.y_scale),
        impacts=impacts, density=density, series_id=list(spec.series_id),
        i_now=i_now, t_now=t_now,
    )
    return result


# --------------------------------------------------------------------------- #
# Display, as example_nowcast.m displays it
# --------------------------------------------------------------------------- #


def format_week(result: ReferenceWeek) -> str:
    """The block ``example_nowcast.m`` prints, plus the density quantiles."""
    lines = [
        f"Nowcast Update: {result.week}  (seed {result.seed})",
        "",
        f"      Impact from parameter and data revisions:  {result.revisions_impact:8.4f}",
        f"                     Impact from data releases:  {result.releases_impact:8.4f}",
        "                                                +_________",
        f"                                  Total impact:  "
        f"{result.revisions_impact + result.releases_impact:8.4f}",
        "",
        f"                                      nowcast:   {result.nowcast:8.4f}",
        f"                            all horizons:        "
        f"{np.array2string(result.pnt_nowcast, precision=4)}",
        f"      density 16/50/84 pct (first horizon):      "
        f"{np.array2string(np.percentile(result.density[:, 0], [16, 50, 84]), precision=4)}",
        "",
        "  Impact of Data Releases:",
        "",
        result.table.to_string(index=False, float_format=lambda x: f"{x:10.6f}"),
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("week", choices=sorted(VINTAGE_PAIRS))
    parser.add_argument("--seeds", type=int, nargs="+", default=[321],
                        help="one run per seed; report the spread across them")
    parser.add_argument("--draws", type=int, default=None,
                        help="S_update / density draws (default 1250)")
    parser.add_argument("--density-draws", type=int, default=None,
                        help="density draws only; the point nowcast and the "
                             "news table do not depend on this")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    estimates = load_estimates()
    spec = load_spec(MATLAB_DIR / SPEC_FILE)
    results = []
    for seed in args.seeds:
        result = run_reference_week(args.week, seed=seed, n_draws=args.draws,
                                    n_density_draws=args.density_draws,
                                    estimates=estimates, spec=spec,
                                    progress=not args.quiet)
        results.append(result)
        print(format_week(result))
        print()

    if len(results) > 1:
        headline = np.array([r.nowcast for r in results])
        print(f"seeds     : {args.seeds}")
        print(f"nowcasts  : {np.array2string(headline, precision=6)}")
        print(f"mean      : {headline.mean():.6f}")
        print(f"sd        : {headline.std(ddof=1):.6f}")
        print(f"range     : {np.ptp(headline):.6f}")
        ids = sorted(set(results[0].table["series_id"]))
        print("\nper-series impact spread (first horizon):")
        print(f"  {'series':14s} {'mean':>10s} {'sd':>10s} {'range':>10s}")
        for series_id in ids:
            values = np.array([r.impact_for(series_id) for r in results])
            print(f"  {series_id:14s} {values.mean():10.6f} "
                  f"{values.std(ddof=1):10.6f} {np.ptp(values):10.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
