"""The Gibbs sampler.

Line-by-line port of ``nyfed_matlab/functions/model/``:

* ``Gibbs_update.m`` - one sweep of the sampler: a state draw, then the
  conditional posteriors of ``Phi``, the factor volatilities and outliers,
  ``phi``, the idiosyncratic volatilities and outliers, ``mu``, ``gamma_g`` and
  ``Lambda``, in that order.
* ``S_update.m`` - the outlier indicators alone, for the nowcast path.
* ``Gibbs_sampler.m`` - the burn-in/thin/store loop around it.

The sweep is **sequential**, and that shapes this module's API. ``m_mu`` is
computed from the ``phi`` drawn earlier in the same sweep and from the
volatilities updated earlier in the same sweep; ``m_Lambda`` additionally uses
the ``mu`` drawn two blocks above it. So "the conditional posteriors" are not a
function of the inputs alone - they are a function of the inputs and of the
draws taken so far.

That is why :class:`GibbsDraws` exists. Every random site in ``Gibbs_update.m``
can be injected, and with all of them injected the routine is deterministic, so
the posterior moments can be pinned exactly against Octave even though no draw
can be. :func:`gibbs_update_moments` is that path;
``tools/octave_shims/gibbs_update_cond.m`` is its oracle. It is not decoration:
Task 9 nowcasts from MATLAB's stored estimates, so nothing downstream of this
file would ever contradict a wrong sampler.

The estimation window
---------------------
``Gibbs_update.m`` does not estimate over the whole panel. It drops
``t_skip = p_e + 5*(n_quart > 0)`` leading periods - enough lags for the AR(p_e)
errors and for the five-month quarterly aggregator - and it stops at the last
period carrying any observation at all, so the NaN forecast pad that
``example_estimate.m`` appends is excluded. Everything between those two points
is ``T_est`` periods long and every design matrix below is built on it.

MATLAB stores arrays column-major. Every ``reshape`` and every linear-index
assignment here passes ``order="F"``, which matters most for
``Phi(unr_Phi) = vec_Phi``: the unrestricted entries of a ``(n_f, n_f, p_f)``
array are enumerated down columns, then across, then by lag.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from .linalg import spd_inv
from .model import (
    InitVal, Latent, Prior, Restrict, _blkdiag, construct_ssm, state_layout,
)
from .parameters import Params, vec_parameter
from .rng import mvnrnd
from .settings import GibbsSettings
from .ssm import simulation_smoother
from .updates import update_gam, update_ps, update_scl, update_vol

__all__ = [
    "GibbsDraws",
    "GibbsMoments",
    "GibbsResult",
    "gibbs_sampler",
    "gibbs_update",
    "gibbs_update_moments",
    "s_update",
]

# Gibbs_update.m / S_update.m: the discrete support of the outlier scale.
_N_S_VALS = 100


@dataclass
class GibbsDraws:
    """Stand-ins for the six random sites of ``Gibbs_update.m``.

    Any field left ``None`` is drawn from the generator instead, so the
    production path is ``GibbsDraws()`` and the deterministic oracle path is a
    fully populated one. ``sigma`` and ``s`` replace the ``update_vol`` /
    ``update_scl`` results wholesale - both are Tier 1 pinned in their own right
    by Task 6, and what this module has to get right is the residual rows it
    passes them, which are returned as ``GibbsMoments.r_f_pad`` / ``r_e_pad``
    whichever path is taken.

    Shapes: ``state`` (n_state, T); ``Phi`` (n_f, n_f, p_f); ``phi`` (n, p_e);
    ``mu`` (n,); ``Lambda`` (n, n_f); ``sigma`` and ``s`` (n_f + n, T). ``Phi``
    and ``Lambda`` are read only at their *unrestricted* entries, exactly where
    the MATLAB writes the draw.
    """

    state: np.ndarray | None = None
    Phi: np.ndarray | None = None
    phi: np.ndarray | None = None
    mu: np.ndarray | None = None
    Lambda: np.ndarray | None = None
    sigma: np.ndarray | None = None
    s: np.ndarray | None = None


@dataclass
class GibbsMoments:
    """The conditional posteriors of one sweep, before any draw is taken.

    ``m_X`` is the posterior mean and ``Pinv_X`` the posterior *covariance* -
    ``Gibbs_update.m``'s name for it, being the inverse of the posterior
    precision, and the second argument of ``mvnrnd``.

    ``Lambda`` has two code paths and only one runs per call. The joint path
    fills these fields directly. The per-factor path stacks: ``m_Lambda`` and
    ``Rr_Lambda`` are the per-factor vectors concatenated in factor order,
    ``Pinv_Lambda`` and ``RR_Lambda`` are block diagonal over factors, and
    ``R_Lambda`` is the per-factor design matrices concatenated left to right.

    ``r_f_pad`` (n_f, T) and ``r_e_pad`` (n, T) are the residual rows handed to
    ``update_vol`` and ``update_scl``, NaN outside the estimation window.
    ``y_t`` (n, T_est) and ``F_t`` (n_f, T_est) are the detrended
    monthly-equivalent data and the masked factors that every block is built on.
    """

    m_mu: np.ndarray
    Pinv_mu: np.ndarray
    m_Phi: np.ndarray
    Pinv_Phi: np.ndarray
    m_phi: np.ndarray
    Pinv_phi: np.ndarray
    m_Lambda: np.ndarray
    Pinv_Lambda: np.ndarray
    R_Lambda: np.ndarray
    Rr_Lambda: np.ndarray
    RR_Lambda: np.ndarray
    r_f_pad: np.ndarray
    r_e_pad: np.ndarray
    y_t: np.ndarray
    F_t: np.ndarray


@dataclass
class GibbsResult:
    """MATLAB ``[params, latents]``.

    ``params`` is ``(n_param, n_gs)``. ``states`` ``(1 + n_f + n, T, n_gs //
    n_each)``, ``sigmas`` and ``ss`` ``(n_f + n, T, n_gs // n_each)`` are
    ``None`` unless ``need_latents``, matching ``Gibbs_sampler.m``'s
    ``nargout > 1`` guard.
    """

    params: np.ndarray
    states: np.ndarray | None = None
    sigmas: np.ndarray | None = None
    ss: np.ndarray | None = None


# --------------------------------------------------------------------------- #
# Shared bookkeeping
# --------------------------------------------------------------------------- #


@dataclass
class _Window:
    """Dimensions and the estimation window, as both MATLAB files compute them."""

    n: int
    n_f: int
    p_f: int
    p_e: int
    T: int
    isquart: np.ndarray
    n_quart: int
    t_skip: int
    T_est: int
    n_g_state: int
    n_f_state: int
    n_e_state: int

    @property
    def est(self) -> slice:
        """``t_skip + (1:T_est)`` in MATLAB, 0-based."""
        return slice(self.t_skip, self.t_skip + self.T_est)


def _as_phi_array(Phi: np.ndarray | None, n_f: int) -> tuple[np.ndarray, int]:
    """Normalise ``param.Phi`` to ``(n_f, n_f, p_f)``, returning it and ``p_f``.

    ``Gibbs_update.m`` reads ``p_f = size(Phi, 3)``, which is 1 for a 2-D array
    and 0 for an empty one; MATLAB drops trailing singleton dimensions, so a
    ``p_f = 1`` model arrives here as ``(n_f, n_f)``.
    """
    if Phi is None:
        return np.zeros((n_f, n_f, 0)), 0
    Phi = np.asarray(Phi, dtype=float)
    if Phi.size == 0:
        return np.zeros((n_f, n_f, 0)), 0
    if Phi.ndim == 2:
        Phi = Phi[:, :, None]
    return Phi, Phi.shape[2]


def _as_lag_array(x: np.ndarray | None, n: int) -> tuple[np.ndarray, int]:
    """Normalise ``param.phi`` / ``restrict``-shaped ``(n, p_e)`` arrays."""
    if x is None:
        return np.zeros((n, 0)), 0
    x = np.asarray(x, dtype=float)
    if x.size == 0:
        return np.zeros((n, 0)), 0
    if x.ndim == 1:
        x = x[:, None]
    return x, x.shape[1]


def _window(param: Params, Y: np.ndarray, restrict: Restrict) -> _Window:
    n, n_f = np.asarray(param.Lambda, dtype=float).shape
    _, p_f = _as_phi_array(param.Phi, n_f)
    _, p_e = _as_lag_array(param.phi, n)

    T = Y.shape[1]
    if restrict.isquart is None:
        isquart = np.zeros(n, dtype=bool)
    else:
        isquart = np.asarray(restrict.isquart, dtype=bool).ravel()
    n_quart = int(np.count_nonzero(isquart))
    t_skip = p_e + 5 * (n_quart > 0)

    # t_est = ~all(isnan(Y), 1); t_est(1:find(t_est, 1, 'last')) = true
    observed = ~np.all(np.isnan(Y), axis=0)
    if not observed.any():
        raise ValueError("Y has no observed period")
    T_est = int(np.flatnonzero(observed)[-1]) + 1 - t_skip

    # Same block sizes construct_ssm builds the state vector with; see
    # model.state_layout for why this is not recomputed here.
    layout = state_layout(n, n_f, p_f, p_e, n_quart)

    return _Window(n=n, n_f=n_f, p_f=p_f, p_e=p_e, T=T, isquart=isquart,
                   n_quart=n_quart, t_skip=t_skip, T_est=T_est,
                   n_g_state=layout.n_g_state, n_f_state=layout.n_f_state,
                   n_e_state=layout.n_e_state)


def _s_support(pi_f: np.ndarray, pi_e: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """``s_vals`` (n_s,) and ``s_probs`` (n_f + n, n_s): the outlier prior.

    Mass ``pi`` on no outlier, the rest spread evenly over scales 2 to 5.
    """
    vals = np.concatenate([[1.0], np.linspace(2.0, 5.0, _N_S_VALS - 1)])
    pis = np.concatenate([np.ravel(pi_f), np.ravel(pi_e)])[:, None]
    rest = np.full((pis.shape[0], _N_S_VALS - 1), 1.0 / (_N_S_VALS - 1))
    return vals, np.hstack([pis, (1.0 - pis) * rest])


def _reconstruct(state: np.ndarray, w: _Window) -> tuple[np.ndarray, ...]:
    """Split the state draw into ``g_t``, ``f_t`` and ``e_t`` over the window."""
    est = w.est
    g_t = state[0:1, est]
    f_t = state[w.n_g_state:w.n_g_state + w.n_f, est]
    e_t = np.full((w.n, w.T_est), np.nan)
    m0 = w.n_g_state + w.n_f_state
    q0 = m0 + w.n_e_state
    e_t[~w.isquart, :] = state[m0:m0 + (w.n - w.n_quart), est]
    e_t[w.isquart, :] = state[q0:q0 + w.n_quart, est]
    return g_t, f_t, e_t


def _mask_factors(f_t: np.ndarray, restrict: Restrict, w: _Window) -> np.ndarray:
    """``F_t = double(f_active) .* f_t`` over the window, or ``f_t`` if absent."""
    if restrict.f_active is None:
        return f_t
    return np.asarray(restrict.f_active, dtype=float)[:, w.est] * f_t


def _lag_stack(x: np.ndarray, p: int, T_est: int) -> np.ndarray:
    """``[x_(t-1); ...; x_(t-p)]`` for ``t = p+1 ... T_est``, lag-major.

    MATLAB::

        for lag = 1:p
            lags((lag-1)*k+(1:k), :) = x(:, (p+1-lag):(T_est-lag));
        end
    """
    k = x.shape[0]
    lags = np.full((k * p, T_est - p), np.nan)
    for lag in range(1, p + 1):
        lags[(lag - 1) * k:lag * k, :] = x[:, p - lag:T_est - lag]
    return lags


def _pad_residual(row: np.ndarray, lead: int, w: _Window) -> np.ndarray:
    """``[NaN(1, t_skip+p), row, NaN(1, T-t_skip-T_est)]``."""
    out = np.full(w.T, np.nan)
    out[w.t_skip + lead:w.t_skip + w.T_est] = row
    return out


def _diag_lags(phi: np.ndarray, n: int, p_e: int) -> np.ndarray:
    """``phi_diags``: ``zeros(n, n*p_e)`` with ``phi(:, lag)`` on each diagonal.

    MATLAB writes this as a logical-mask assignment,
    ``phi_diags(logical(repmat(eye(n), 1, p_e))) = phi``, which fills column
    ``lag*n + i`` at row ``i`` with ``phi(i, lag)`` - column-major order makes
    the flattened ``phi`` line up lag block by lag block.
    """
    out = np.zeros((n, n * p_e))
    idx = np.arange(n)
    for lag in range(p_e):
        out[idx, lag * n + idx] = phi[:, lag]
    return out


# --------------------------------------------------------------------------- #
# Gibbs_update.m
# --------------------------------------------------------------------------- #


def _gibbs_update(
    param: Params,
    latent: Latent,
    Y: np.ndarray,
    prior: Prior,
    restrict: Restrict,
    rng: np.random.Generator | None,
    draws: GibbsDraws,
) -> tuple[Params, Latent, GibbsMoments]:
    """One sweep of ``Gibbs_update.m``, returning the moments as well.

    Every random site consults ``draws`` first and falls back to ``rng``. With
    ``rng`` left ``None`` the four terminal blocks - ``gamma_f``, ``pi_f``,
    ``gamma_e``, ``pi_e`` and ``gamma_g`` - are not drawn at all and the
    returned :class:`Params` carries the input values there. Nothing later in
    the sweep reads them, so the moments are unaffected; the shim leaves those
    five draws in place for the same reason.
    """
    Y = np.asarray(Y, dtype=float)
    w = _window(param, Y, restrict)
    n, n_f, p_f, p_e, T, T_est = w.n, w.n_f, w.p_f, w.p_e, w.T, w.T_est

    # Extract parameters from structure. Copied, not aliased: MATLAB passes the
    # struct by value and this routine assigns into Lambda, Phi and phi.
    mu = np.asarray(param.mu, dtype=float).ravel()
    Lambda = np.asarray(param.Lambda, dtype=float).copy()
    Phi, _ = _as_phi_array(param.Phi, n_f)
    Phi = Phi.copy()
    gamma_f = np.asarray(param.gamma_f, dtype=float).ravel()
    phi, _ = _as_lag_array(param.phi, n)
    phi = phi.copy()
    gamma_e = np.asarray(param.gamma_e, dtype=float).ravel()

    # Set support for scale_eps and ps prior
    s_vals, s_probs = _s_support(param.pi_f, param.pi_e)

    # LATENT VARIABLES -------------------------------------------------------
    if draws.state is None:
        if rng is None:
            raise ValueError("gibbs_update needs rng when draws.state is absent")
        ssm = construct_ssm(param, latent, restrict)
        state, _ = simulation_smoother(Y, ssm, rng)
    else:
        state = np.asarray(draws.state, dtype=float)

    g_t, f_t, e_t = _reconstruct(state, w)
    F_t = _mask_factors(f_t, restrict, w)

    # Extract volatilities and outlier indicators
    sigma = np.asarray(latent.sigma, dtype=float).copy()
    s = np.asarray(latent.s, dtype=float).copy()
    sigmaXs_f = sigma[:n_f, w.est] * s[:n_f, w.est]
    sigmaXs_e = sigma[n_f:n_f + n, w.est] * s[n_f:n_f + n, w.est]

    # Construct detrended monthly-equivalent data
    y_t = mu[:, None] + Lambda @ F_t + e_t

    # FACTORS ----------------------------------------------------------------
    f_lags = _lag_stack(f_t, p_f, T_est)
    f = f_t[:, p_f:T_est]

    m_Phi = np.zeros(0)
    Pinv_Phi = np.zeros((0, 0))
    if p_f > 0:
        s_Phi = (1.0 / sigmaXs_f[:, p_f:T_est]).reshape(-1, order="F")
        r_Phi = s_Phi * f.reshape(-1, order="F")
        R_Phi = s_Phi[:, None] * np.kron(f_lags.T, np.eye(n_f))
        vec_Phi = Phi.reshape(-1, order="F")
        unr_Phi = np.isnan(np.asarray(restrict.Phi, dtype=float)).reshape(-1, order="F")
        if not unr_Phi.all():  # impose restrictions
            r_Phi = r_Phi - R_Phi[:, ~unr_Phi] @ vec_Phi[~unr_Phi]
            R_Phi = R_Phi[:, unr_Phi]
        Rr_Phi = R_Phi.T @ r_Phi
        RR_Phi = R_Phi.T @ R_Phi
        P_Phi_unr = np.asarray(prior.P_Phi, dtype=float)[np.ix_(unr_Phi, unr_Phi)]
        Pinv_Phi = spd_inv(P_Phi_unr + RR_Phi)
        vec_m_Phi = np.asarray(prior.m_Phi, dtype=float).reshape(-1, order="F")
        m_Phi = Pinv_Phi @ (P_Phi_unr @ vec_m_Phi[unr_Phi] + Rr_Phi)
        if draws.Phi is None:
            draw = mvnrnd(m_Phi, Pinv_Phi, _require_rng(rng, "Phi"))
        else:
            draw = np.asarray(draws.Phi, dtype=float).reshape(-1, order="F")[unr_Phi]
        vec_Phi = vec_Phi.copy()
        vec_Phi[unr_Phi] = draw
        Phi = vec_Phi.reshape((n_f, n_f, p_f), order="F")

    # Update sigma_f and s_f
    r_f_pad = np.full((n_f, T), np.nan)
    r_f = f - Phi.reshape(n_f, n_f * p_f, order="F") @ f_lags
    for i_f in range(n_f):
        r_f_tmp = _pad_residual(r_f[i_f, :], p_f, w)
        r_f_pad[i_f, :] = r_f_tmp
        if draws.sigma is None:
            sigma[i_f, :] = update_vol(r_f_tmp / s[i_f, :], sigma[i_f, :],
                                       gamma_f[i_f], rng=_require_rng(rng, "sigma_f"))
            s[i_f, :] = update_scl(r_f_tmp / sigma[i_f, :], s_vals, s_probs[i_f, :],
                                   _require_rng(rng, "s_f"))
        else:
            sigma[i_f, :] = np.asarray(draws.sigma, dtype=float)[i_f, :]
            s[i_f, :] = np.asarray(draws.s, dtype=float)[i_f, :]
        if i_f == 4:
            # Gibbs_update.m:156-158, "%% TEMP for matfiles_sig1". Factor 5 is
            # the pandemic factor of the US specification (example_estimate.m
            # puts COVID in block 5) and its volatility is held at one; the
            # estimates this project reproduces were produced with this line in
            # place. It is a hard-coded index, not a property of the model, so
            # it fires for the fifth factor of ANY panel. Ported as written.
            sigma[i_f, :] = 1.0
    sigma_f = sigma[:n_f, w.est]
    s_f = s[:n_f, w.est]

    # Update gamma_f
    r_gam_f = 2.0 * (np.log(sigma_f[:, p_f + 1:T_est])
                     - np.log(sigma_f[:, p_f:T_est - 1])).T
    gamma_f_new = update_gam(r_gam_f, prior.nu_f, prior.s2_f,
                             _require_rng(rng, "gamma_f")) if rng is not None \
        else np.asarray(param.gamma_f, dtype=float).ravel()

    # Update pi_f
    pi_f_new = update_ps(s_f.T, prior.a_f, prior.b_f,
                         _require_rng(rng, "pi_f")) if rng is not None \
        else np.asarray(param.pi_f, dtype=float).ravel()

    # ERRORS -----------------------------------------------------------------
    e_lags = _lag_stack(e_t, p_e, T_est)
    e = e_t[:, p_e:T_est]

    m_phi = np.zeros(0)
    Pinv_phi = np.zeros((0, 0))
    if p_e > 0:
        Tp = T_est - p_e
        s_phi = (1.0 / sigmaXs_e[:, p_e:T_est]).reshape(-1, order="F")
        r_phi = s_phi * e.reshape(-1, order="F")
        # R_phi(logical(repmat(eye(n), T_est-p_e, p_e))) = e_lags': column-major
        # order puts e_lags(lag*n+i, b) at row b*n+i, column lag*n+i.
        R_phi = np.zeros((n * Tp, n * p_e))
        rows = np.arange(Tp)[:, None] * n + np.arange(n)[None, :]
        for lag in range(p_e):
            R_phi[rows, (lag * n + np.arange(n))[None, :]] = \
                e_lags[lag * n:(lag + 1) * n, :].T
        R_phi = s_phi[:, None] * R_phi
        Rr_phi = R_phi.T @ r_phi
        RR_phi = R_phi.T @ R_phi
        P_phi = np.asarray(prior.P_phi, dtype=float)
        Pinv_phi = spd_inv(P_phi + RR_phi)
        m_phi = Pinv_phi @ (
            P_phi @ np.asarray(prior.m_phi, dtype=float).reshape(-1, order="F")
            + Rr_phi
        )
        if draws.phi is None:
            vec_phi = mvnrnd(m_phi, Pinv_phi, _require_rng(rng, "phi"))
        else:
            vec_phi = np.asarray(draws.phi, dtype=float).reshape(-1, order="F")
        phi = vec_phi.reshape((n, p_e), order="F")

    # Update sigma_e and s_e
    r_e_pad = np.full((n, T), np.nan)
    r_e = e - _diag_lags(phi, n, p_e) @ e_lags
    for i in range(n):
        r_e_tmp = _pad_residual(r_e[i, :], p_e, w)
        r_e_pad[i, :] = r_e_tmp
        if draws.sigma is None:
            sigma[n_f + i, :] = update_vol(
                r_e_tmp / s[n_f + i, :], sigma[n_f + i, :], gamma_e[i],
                rng=_require_rng(rng, "sigma_e"))
            s[n_f + i, :] = update_scl(
                r_e_tmp / sigma[n_f + i, :], s_vals, s_probs[n_f + i, :],
                _require_rng(rng, "s_e"))
        else:
            sigma[n_f + i, :] = np.asarray(draws.sigma, dtype=float)[n_f + i, :]
            s[n_f + i, :] = np.asarray(draws.s, dtype=float)[n_f + i, :]
    sigma_e = sigma[n_f:n_f + n, w.est]
    s_e = s[n_f:n_f + n, w.est]
    sigmaXs_e = sigma_e * s_e

    # Update gamma_e
    r_gam_e = 2.0 * (np.log(sigma_e[:, p_e + 1:T_est])
                     - np.log(sigma_e[:, p_e:T_est - 1])).T
    gamma_e_new = update_gam(r_gam_e, prior.nu_e, prior.s2_e,
                             _require_rng(rng, "gamma_e")) if rng is not None \
        else np.asarray(param.gamma_e, dtype=float).ravel()

    # Update pi_e
    pi_e_new = update_ps(s_e.T, prior.a_e, prior.b_e,
                         _require_rng(rng, "pi_e")) if rng is not None \
        else np.asarray(param.pi_e, dtype=float).ravel()

    # MEASUREMENTS -----------------------------------------------------------
    y_mu = y_t[:, p_e:T_est] - Lambda @ F_t[:, p_e:T_est]
    for lag in range(1, p_e + 1):
        y_mu = y_mu - phi[:, lag - 1:lag] * (
            y_t[:, p_e - lag:T_est - lag] - Lambda @ F_t[:, p_e - lag:T_est - lag]
        )

    # Update mu
    prec_e = 1.0 / sigmaXs_e[:, p_e:T_est] ** 2
    one_minus = 1.0 - phi.sum(axis=1)
    Rr_mu = one_minus * np.sum(prec_e * y_mu, axis=1)
    RR_mu = np.diag(np.sum(prec_e, axis=1) * one_minus**2)
    P_mu = np.asarray(prior.P_mu, dtype=float)
    # linsolve(symmetrize(P_mu + RR_mu), eye(n), option). MATLAB does not
    # symmetrize the RESULT here as it does for the other three blocks;
    # spd_inv does, and both arguments are diagonal-plus-symmetric, so the two
    # differ only at rounding.
    Pinv_mu = spd_inv(P_mu + RR_mu)
    m_mu = Pinv_mu @ (P_mu @ np.asarray(prior.m_mu, dtype=float).ravel() + Rr_mu)
    if draws.mu is None:
        mu = mvnrnd(m_mu, Pinv_mu, _require_rng(rng, "mu"))
    else:
        mu = np.asarray(draws.mu, dtype=float).ravel()

    # Update gamma_g
    r_g = (g_t[:, 1:T_est] - g_t[:, 0:T_est - 1]).T
    gamma_g_new = update_gam(r_g, prior.nu_g, prior.s2_g,
                             _require_rng(rng, "gamma_g")).item() \
        if rng is not None else np.asarray(param.gamma_g, dtype=float).item()

    # Update Lambda
    P_Lambda = np.asarray(prior.P_Lambda, dtype=float)
    m_Lambda_prior = np.asarray(prior.m_Lambda, dtype=float)
    restrict_Lambda = np.asarray(restrict.Lambda, dtype=float)
    s_Lambda = (1.0 / sigmaXs_e[:, p_e:T_est]).reshape(-1, order="F")
    draw_Lambda = None if draws.Lambda is None \
        else np.asarray(draws.Lambda, dtype=float)

    if (n * n_f < 100) or (n_f == 1):
        # Joint update over every unrestricted loading at once.
        y_Lambda = y_t[:, p_e:T_est] - mu[:, None]
        f_Lambda = np.zeros((n * (T_est - p_e), n * n_f))
        for lag in range(1, p_e + 1):
            y_Lambda = y_Lambda - phi[:, lag - 1:lag] * (
                y_t[:, p_e - lag:T_est - lag] - mu[:, None]
            )
            f_Lambda = f_Lambda + np.kron(F_t[:, p_e - lag:T_est - lag].T,
                                          np.diag(phi[:, lag - 1]))

        r_Lambda = s_Lambda * y_Lambda.reshape(-1, order="F")
        R_Lambda = s_Lambda[:, None] * (
            np.kron(F_t[:, p_e:T_est].T, np.eye(n)) - f_Lambda
        )
        vec_Lambda = Lambda.reshape(-1, order="F")
        unr = np.isnan(restrict_Lambda).reshape(-1, order="F")
        if not unr.all():  # impose restrictions
            r_Lambda = r_Lambda - R_Lambda[:, ~unr] @ vec_Lambda[~unr]
            R_Lambda = R_Lambda[:, unr]
        Rr_Lambda = R_Lambda.T @ r_Lambda
        RR_Lambda = R_Lambda.T @ R_Lambda
        P_unr = P_Lambda[np.ix_(unr, unr)]
        Pinv_Lambda = spd_inv(P_unr + RR_Lambda)
        m_Lambda = Pinv_Lambda @ (
            P_unr @ m_Lambda_prior.reshape(-1, order="F")[unr] + Rr_Lambda
        )
        if draw_Lambda is None:
            draw = mvnrnd(m_Lambda, Pinv_Lambda, _require_rng(rng, "Lambda"))
        else:
            draw = draw_Lambda.reshape(-1, order="F")[unr]
        vec_Lambda = vec_Lambda.copy()
        vec_Lambda[unr] = draw
        Lambda = vec_Lambda.reshape((n, n_f), order="F")
    else:
        # Factor by factor, conditioning on the loadings of the other factors -
        # including those updated earlier in this same loop.
        m_parts, Pinv_parts, R_parts, Rr_parts, RR_parts = [], [], [], [], []
        for i_f in range(n_f):
            other = np.arange(n_f) != i_f
            y_Lambda = (y_t[:, p_e:T_est] - mu[:, None]
                        - Lambda[:, other] @ F_t[other, :][:, p_e:T_est])
            f_Lambda = np.zeros((n * (T_est - p_e), n))
            for lag in range(1, p_e + 1):
                y_Lambda = y_Lambda - phi[:, lag - 1:lag] * (
                    y_t[:, p_e - lag:T_est - lag] - mu[:, None]
                    - Lambda[:, other] @ F_t[other, :][:, p_e - lag:T_est - lag]
                )
                f_Lambda = f_Lambda + np.kron(
                    F_t[i_f:i_f + 1, p_e - lag:T_est - lag].T,
                    np.diag(phi[:, lag - 1]),
                )

            r_Lambda = s_Lambda * y_Lambda.reshape(-1, order="F")
            R_Lambda_i = s_Lambda[:, None] * (
                np.kron(F_t[i_f:i_f + 1, p_e:T_est].T, np.eye(n)) - f_Lambda
            )
            vec_Lambda = Lambda[:, i_f]
            unr = np.isnan(restrict_Lambda[:, i_f])
            if not unr.all():  # impose restrictions
                r_Lambda = r_Lambda - R_Lambda_i[:, ~unr] @ vec_Lambda[~unr]
                R_Lambda_i = R_Lambda_i[:, unr]
            Rr_i = R_Lambda_i.T @ r_Lambda
            RR_i = R_Lambda_i.T @ R_Lambda_i
            P_i = P_Lambda[i_f * n:(i_f + 1) * n, i_f * n:(i_f + 1) * n]
            P_unr = P_i[np.ix_(unr, unr)]
            Pinv_i = spd_inv(P_unr + RR_i)
            m_i = Pinv_i @ (P_unr @ m_Lambda_prior[:, i_f][unr] + Rr_i)
            if draw_Lambda is None:
                draw = mvnrnd(m_i, Pinv_i, _require_rng(rng, "Lambda"))
            else:
                draw = draw_Lambda[:, i_f][unr]
            Lambda[unr, i_f] = draw

            m_parts.append(m_i)
            Pinv_parts.append(Pinv_i)
            R_parts.append(R_Lambda_i)
            Rr_parts.append(Rr_i)
            RR_parts.append(RR_i)

        m_Lambda = np.concatenate(m_parts)
        Pinv_Lambda = _blkdiag(*Pinv_parts)
        R_Lambda = np.hstack(R_parts)
        Rr_Lambda = np.concatenate(Rr_parts)
        RR_Lambda = _blkdiag(*RR_parts)

    # STORE LATENT VARIABLES -------------------------------------------------
    state_clean = np.full((1 + n_f + n, T), np.nan)
    state_clean[0, :] = state[0, :]
    state_clean[1:1 + n_f, :] = state[w.n_g_state:w.n_g_state + n_f, :]
    m0 = w.n_g_state + w.n_f_state
    q0 = m0 + w.n_e_state
    head = np.zeros(1 + n_f, dtype=bool)
    state_clean[np.concatenate([head, ~w.isquart]), :] = \
        state[m0:m0 + (n - w.n_quart), :]
    state_clean[np.concatenate([head, w.isquart]), :] = \
        state[q0:q0 + w.n_quart, :]

    param_out = Params(
        mu=mu,
        gamma_g=gamma_g_new,
        Lambda=Lambda,
        Phi=Phi,
        gamma_f=gamma_f_new,
        pi_f=pi_f_new,
        phi=phi,
        gamma_e=gamma_e_new,
        pi_e=pi_e_new,
    )
    latent_out = Latent(sigma=sigma, s=s, state=state_clean)
    moments = GibbsMoments(
        m_mu=m_mu, Pinv_mu=Pinv_mu,
        m_Phi=m_Phi, Pinv_Phi=Pinv_Phi,
        m_phi=m_phi, Pinv_phi=Pinv_phi,
        m_Lambda=m_Lambda, Pinv_Lambda=Pinv_Lambda,
        R_Lambda=R_Lambda, Rr_Lambda=Rr_Lambda, RR_Lambda=RR_Lambda,
        r_f_pad=r_f_pad, r_e_pad=r_e_pad, y_t=y_t, F_t=F_t,
    )
    return param_out, latent_out, moments


def _require_rng(rng: np.random.Generator | None, site: str) -> np.random.Generator:
    if rng is None:
        raise ValueError(f"gibbs_update needs rng or an injected draw for {site}")
    return rng


def gibbs_update(
    param: Params,
    latent: Latent,
    Y: np.ndarray,
    prior: Prior,
    restrict: Restrict,
    rng: np.random.Generator,
) -> tuple[Params, Latent]:
    """One Gibbs sweep. Port of ``Gibbs_update.m``.

    Returns the updated parameters and the updated latents - the cleaned
    ``(1 + n_f + n, T)`` state draw, the volatilities and the outlier
    indicators. The inputs are never modified.
    """
    param_out, latent_out, _ = _gibbs_update(param, latent, Y, prior, restrict,
                                             rng, GibbsDraws())
    return param_out, latent_out


def gibbs_update_moments(
    param: Params,
    latent: Latent,
    Y: np.ndarray,
    prior: Prior,
    restrict: Restrict,
    *,
    state: np.ndarray | None = None,
    draws: GibbsDraws | None = None,
    rng: np.random.Generator | None = None,
) -> GibbsMoments:
    """The conditional posteriors of one sweep, without taking the draws.

    With ``draws`` fully populated this is deterministic and reproduces
    ``tools/octave_shims/gibbs_update_cond.m`` exactly. ``state`` is accepted
    separately as a convenience; it overrides ``draws.state``.
    """
    draws = GibbsDraws() if draws is None else draws
    if state is not None:
        # `replace`, not a field-by-field rebuild: a seventh injectable site
        # added to GibbsDraws later must not be silently dropped here.
        draws = replace(draws, state=state)
    return _gibbs_update(param, latent, Y, prior, restrict, rng, draws)[2]


# --------------------------------------------------------------------------- #
# S_update.m
# --------------------------------------------------------------------------- #


def s_update(
    param: Params,
    latent: Latent,
    Y: np.ndarray,
    restrict: Restrict,
    rng: np.random.Generator,
) -> Latent:
    """Redraw the outlier indicators only. Port of ``S_update.m``.

    ``sigma`` is an input here, not an output: the nowcast path holds the
    volatilities at their estimated values and only lets the outlier states
    respond to the new vintage. The returned ``Latent`` carries the input
    ``sigma`` and ``state`` unchanged.
    """
    Y = np.asarray(Y, dtype=float)
    w = _window(param, Y, restrict)
    n, n_f, p_f, p_e, T_est = w.n, w.n_f, w.p_f, w.p_e, w.T_est

    Phi, _ = _as_phi_array(param.Phi, n_f)
    phi, _ = _as_lag_array(param.phi, n)
    s_vals, s_probs = _s_support(param.pi_f, param.pi_e)

    # Form state-space representation and draw states and errors
    ssm = construct_ssm(param, latent, restrict)
    state, _ = simulation_smoother(Y, ssm, rng)
    _, f_t, e_t = _reconstruct(state, w)

    # `.copy()` on both, as _gibbs_update does: the returned Latent must not
    # alias the caller's buffer. run_us_reference._average_latents accumulates
    # `sigma_sum += latent.sigma` over 1,250 S_update calls on this array, so an
    # alias would let any later in-place write reach back into that running sum.
    sigma = np.asarray(latent.sigma, dtype=float).copy()
    s = np.asarray(latent.s, dtype=float).copy()

    # Update s_f
    f_lags = _lag_stack(f_t, p_f, T_est)
    r_f = f_t[:, p_f:T_est] - Phi.reshape(n_f, n_f * p_f, order="F") @ f_lags
    for i_f in range(n_f):
        r_f_tmp = _pad_residual(r_f[i_f, :], p_f, w)
        s[i_f, :] = update_scl(r_f_tmp / sigma[i_f, :], s_vals,
                               s_probs[i_f, :], rng)

    # Update s_e
    e_lags = _lag_stack(e_t, p_e, T_est)
    r_e = e_t[:, p_e:T_est] - _diag_lags(phi, n, p_e) @ e_lags
    for i in range(n):
        r_e_tmp = _pad_residual(r_e[i, :], p_e, w)
        s[n_f + i, :] = update_scl(r_e_tmp / sigma[n_f + i, :], s_vals,
                                   s_probs[n_f + i, :], rng)

    return Latent(sigma=sigma, s=s, state=latent.state)


# --------------------------------------------------------------------------- #
# Gibbs_sampler.m
# --------------------------------------------------------------------------- #


def gibbs_sampler(
    Y: np.ndarray,
    prior: Prior,
    restrict: Restrict,
    initval: InitVal,
    settings: GibbsSettings,
    rng: np.random.Generator,
    *,
    need_latents: bool = False,
) -> GibbsResult:
    """Run the Gibbs sampler. Port of ``Gibbs_sampler.m``.

    ``n_burn`` sweeps are discarded, then ``n_gs`` draws are stored, ``n_thin``
    sweeps apart. Latents, when asked for, are stored every ``n_each``th stored
    draw. The MATLAB's progress ``fprintf`` and its MCMC trace plot are
    display-only and are not reproduced, as with ``load_settings.m``'s
    ``plot_MCMC``.
    """
    Y = np.asarray(Y, dtype=float)
    param = initval.param
    n, n_f = np.asarray(param.Lambda, dtype=float).shape
    _, p_f = _as_phi_array(param.Phi, n_f)
    _, p_e = _as_lag_array(param.phi, n)
    T = Y.shape[1]
    n_state = 1 + n_f + n
    n_param = 1 + n * (1 + n_f + p_e + 2) + n_f * (n_f * p_f + 2)

    n_gs = int(settings.n_gs)
    n_burn = int(settings.n_burn)
    n_thin = int(settings.n_thin)
    n_each = int(settings.n_each)

    params = np.zeros((n_param, n_gs))
    states = sigmas = ss = None
    if need_latents:
        n_store = n_gs // n_each
        states = np.zeros((n_state, T, n_store))
        sigmas = np.zeros((n_f + n, T, n_store))
        ss = np.zeros((n_f + n, T, n_store))

    # Extract initial values. Copied so that a second run from the same initval
    # starts from the same place.
    latent = Latent(sigma=np.asarray(initval.latent.sigma, dtype=float).copy(),
                    s=np.asarray(initval.latent.s, dtype=float).copy())

    # Set missing restriction matrices to default values
    if restrict.f_active is None:
        f_active = np.ones((n_f, T))
    else:
        f_active = np.asarray(restrict.f_active, dtype=float)

    for i_gs in range(-n_burn, n_gs + 1):
        for _ in range(n_thin):
            param, latent = gibbs_update(param, latent, Y, prior, restrict, rng)
            # Gibbs_sampler.m:140 masks the pandemic factor's stored state where
            # that factor is switched off:
            #     latent.state(6,:) = latent.state(6,:).*restrict.f_active(5,:);
            # State row 6 is factor 5 and f_active row 5 is the pandemic factor,
            # so the line is "zero a factor's state where the factor is
            # inactive". Applied here to every factor: the other four rows of
            # f_active are all-true in the US specification, so this is
            # numerically identical there, and unlike the hard-coded form it is
            # defined for a panel with fewer than five factors.
            latent.state[1:1 + n_f, :] *= f_active

        # Store draws
        if i_gs > 0:
            params[:, i_gs - 1] = vec_parameter(param)
            if need_latents and (i_gs % n_each == 0):
                k = i_gs // n_each - 1
                states[:, :, k] = latent.state
                sigmas[:, :, k] = latent.sigma
                ss[:, :, k] = latent.s

    return GibbsResult(params=params, states=states, sigmas=sigmas, ss=ss)
