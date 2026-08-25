"""Point nowcast, density nowcast and the news decomposition.

Line-by-line port of ``nyfed_matlab/functions/model/point_nowcast.m`` and
``density_nowcast.m``, plus ``news_table``, which reproduces the release-impact
table ``example_nowcast.m`` prints.

The four rows of ``PointNowcast.nowcast`` are a decomposition, not four rival
estimates. Row 1 is old data with the old state space, row 2 old data with the
new one (isolating the parameter revision), row 3 adds the data revisions and
row 4 the new releases. The published nowcast is row 4.

Releases and revisions are kept strictly apart, as ``point_nowcast.m`` keeps
them: a cell counts as a *release* only where the old vintage was missing and
the new one is present. A cell present in both vintages but changed is a
*revision*, and it is accounted for by ``row 3 - row 2``, with ``news`` and
``weights`` left NaN there. Writing news entries for revised cells would leave
the decomposition identity intact and still fill the release-impact table with
rows that never released.

Indices are 0-based Python indices throughout; the MATLAB's 1-based ``i_now``
and ``t_now`` are converted by the caller.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .spec import ModelSpec, check_panel_row_order
from .ssm import (
    StateSpace, _is_tv3, _mat0, fast_smoother, simulation_smoother,
)

__all__ = ["PointNowcast", "point_nowcast", "density_nowcast", "news_table"]


@dataclass
class PointNowcast:
    """MATLAB ``[nowcast, forecasts, news, weights]``.

    ``i_now`` and ``t_now`` are the inputs the outputs were computed at. They
    are not MATLAB outputs; ``news_table`` needs ``i_now`` to rescale the
    weights and would otherwise have to be handed it a second time.
    """

    nowcast: np.ndarray     # (4, len(t_now))
    forecasts: np.ndarray   # (N, T), NaN where not newly released
    news: np.ndarray        # (N, T), NaN where not newly released
    weights: np.ndarray     # (N, T, len(t_now)), NaN where not newly released
    i_now: int
    t_now: np.ndarray       # (len(t_now),)


# --------------------------------------------------------------------------- #
# Helpers for MATLAB's constant-or-time-varying measurement equation
# --------------------------------------------------------------------------- #

def _d_seq(ssm: StateSpace, N: int, T: int) -> np.ndarray:
    """``SSM.D`` as an (N,T) sequence, MATLAB's ``repmat(SSM.D, [1, T])``."""
    if ssm.D is None:
        return np.zeros((N, T))
    D = np.asarray(ssm.D, dtype=float)
    if D.ndim == 1:
        D = D[:, None]
    if D.shape[1] > 1:      # MATLAB: size(SSM.D, 2) > 1, already time varying
        return D
    return np.repeat(D, T, axis=1)


def _fitted(H: np.ndarray, states: np.ndarray, D: np.ndarray) -> np.ndarray:
    """``D_t + H_t x_t`` for every t: point_nowcast.m's inner loop, vectorised."""
    if _is_tv3(H):
        return D + np.einsum("ijt,jt->it", H, states)
    return D + _mat0(H) @ states


def _h_row(H: np.ndarray, i: int, t: int) -> np.ndarray:
    """``SSM.H(i, :, t)``, honouring the constant case."""
    if _is_tv3(H):
        return H[i, :, t]
    return _mat0(H)[i, :]


# --------------------------------------------------------------------------- #
# point_nowcast.m
# --------------------------------------------------------------------------- #

def point_nowcast(
    Y_old: np.ndarray,
    Y_new: np.ndarray,
    ssm_old: StateSpace,
    ssm_new: StateSpace,
    i_now: int,
    t_now: np.ndarray,
) -> PointNowcast:
    """Point nowcast and news decomposition. Port of ``point_nowcast.m``.

    ``Y_old`` and ``Y_new`` are (N,T) with NaN for missing data, ``i_now`` is
    the row of the series being nowcast and ``t_now`` the periods to nowcast or
    forecast. Both indices are 0-based.
    """
    Y_old = np.asarray(Y_old, dtype=float)
    Y_new = np.asarray(Y_new, dtype=float)
    t_now = np.atleast_1d(np.asarray(t_now, dtype=int))

    # Extract dimensions and pre-allocate forecasts, news and weights
    N, T = Y_old.shape
    n_now = t_now.size
    nowcast = np.full((4, n_now), np.nan)
    forecasts = np.full((N, T), np.nan)
    news = np.full((N, T), np.nan)
    weights = np.full((N, T, n_now), np.nan)

    # Determine if measurement equation is time-varying
    D_old = _d_seq(ssm_old, N, T)
    D_new = _d_seq(ssm_new, N, T)
    H_old = np.asarray(ssm_old.H, dtype=float)
    H_new = np.asarray(ssm_new.H, dtype=float)

    # Separate revisions from new releases. MATLAB truncates Y_new to the width
    # of Y_old; the two vintages are aligned on the same calendar.
    Y_new = Y_new[:, :T]
    Y_rev = Y_new.copy()
    Y_rev[np.isnan(Y_old)] = np.nan
    releases = ~np.isnan(Y_new) & np.isnan(Y_old)

    # Compute forecasts using old data and old SSM
    states = fast_smoother(Y_old, ssm_old, need_mses=False).states
    nowcast[0, :] = _fitted(H_old, states, D_old)[i_now, t_now]

    # Compute forecasts using old data and new SSM
    states = fast_smoother(Y_old, ssm_new, need_mses=False).states
    nowcast[1, :] = _fitted(H_new, states, D_new)[i_now, t_now]

    # Compute forecasts using revised data and new SSM
    states = fast_smoother(Y_rev, ssm_new, need_mses=False).states
    fitted = _fitted(H_new, states, D_new)
    nowcast[2, :] = fitted[i_now, t_now]

    # Store forecasts and news. The forecast a release is judged against is the
    # one from revised data, so a revision never shows up as news.
    forecasts[releases] = fitted[releases]
    news[releases] = Y_new[releases] - forecasts[releases]

    # Compute forecasts using new data
    states = fast_smoother(Y_new, ssm_new, need_mses=False).states
    nowcast[3, :] = _fitted(H_new, states, D_new)[i_now, t_now]

    # Compute weights. The smoother is affine in Y - D, and construct_SSM.m
    # leaves the state intercepts at zero, so smoothing a dummy data set that
    # holds D_new everywhere plus a one at (i,t) is exactly the derivative of
    # the nowcast with respect to that one observation.
    for i, t in zip(*np.nonzero(releases)):
        Y_dummy = np.zeros((N, T))
        Y_dummy[i, t] = 1.0
        Y_dummy[np.isnan(Y_new)] = np.nan
        Y_dummy = Y_dummy + D_new

        states = fast_smoother(Y_dummy, ssm_new, need_mses=False).states
        for i_t, t_n in enumerate(t_now):
            weights[i, t, i_t] = _h_row(H_new, i_now, t_n) @ states[:, t_n]

    return PointNowcast(nowcast=nowcast, forecasts=forecasts, news=news,
                        weights=weights, i_now=int(i_now), t_now=t_now)


# --------------------------------------------------------------------------- #
# density_nowcast.m
# --------------------------------------------------------------------------- #

def density_nowcast(
    Y: np.ndarray,
    ssm: StateSpace,
    i_now: int,
    t_now: np.ndarray,
    rng: np.random.Generator,
) -> np.ndarray:
    """One draw from the nowcast distribution. Port of ``density_nowcast.m``.

    Returns a ``(len(t_now),)`` array, one draw per period to be nowcast.
    """
    Y = np.asarray(Y, dtype=float)
    t_now = np.atleast_1d(np.asarray(t_now, dtype=int))

    # Determine if measurement equation is time-varying
    N, T = Y.shape
    D = _d_seq(ssm, N, T)
    H = np.asarray(ssm.H, dtype=float)

    # Draw from nowcast distribution
    states, _ = simulation_smoother(Y, ssm, rng)
    nowcast = np.empty(t_now.size)
    for i_t, t in enumerate(t_now):
        nowcast[i_t] = D[i_now, t] + _h_row(H, i_now, t) @ states[:, t]

    return nowcast


# --------------------------------------------------------------------------- #
# The release-impact table of example_nowcast.m
# --------------------------------------------------------------------------- #

def news_table(
    result: PointNowcast,
    spec: ModelSpec,
    y_location: np.ndarray,
    y_scale: np.ndarray,
) -> pd.DataFrame:
    """Per-release impacts on the nowcast, in the units of the nowcast series.

    Reproduces the table ``example_nowcast.m`` prints: forecasts and actuals are
    de-standardised back to each series' own units, and weights are rescaled to
    the nowcast series' units so that ``impact = (actual - forecast) * weight``
    is in percentage points of the nowcast.

    Only the first period of ``result.t_now`` is tabulated, matching the MATLAB,
    which linear-indexes the (N,T,len(t_now)) weights with an (N,T) mask.

    Rows are sorted by descending absolute impact so the site can take the top
    rows directly; ties keep MATLAB's own enumeration order.

    Raises ``ValueError`` if the spec is not frequency-sorted: this is the one
    place a raw-order panel row meets a ``load_spec``-permuted label, and the
    port relies on the permutation being the identity. See
    :func:`nyfed.spec.check_panel_row_order`.
    """
    check_panel_row_order(spec)
    loc = np.asarray(y_location, dtype=float).reshape(-1, 1)
    scale = np.asarray(y_scale, dtype=float).reshape(-1, 1)
    i_now = result.i_now

    forecast = loc + scale * result.forecasts
    news = scale * result.news
    actual = news + forecast
    weight = scale[i_now, 0] * (result.weights[:, :, 0] / scale)
    impact = (actual - forecast) * weight

    # MATLAB enumerates `releases = ~isnan(actual(:))` in column-major order:
    # every series of one period, then the next period.
    N = actual.shape[0]
    flat = np.flatnonzero(np.ravel(~np.isnan(actual), order="F"))
    rows, cols = flat % N, flat // N

    table = pd.DataFrame({
        "series_id": [spec.series_id[i] for i in rows],
        "series_name": [spec.series_name[i] for i in rows],
        "forecast": forecast[rows, cols],
        "actual": actual[rows, cols],
        "weight": weight[rows, cols],
        "impact": impact[rows, cols],
    })
    order = np.argsort(-np.abs(table["impact"].to_numpy()), kind="stable")
    return table.iloc[order].reset_index(drop=True)
