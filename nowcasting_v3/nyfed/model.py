"""Model structure: state-space construction and the default prior.

Line-by-line port of ``nyfed_matlab/functions/model/construct_SSM.m`` and
``nyfed_matlab/functions/model/construct_prior.m``.

The model is

    Y_(mt) = y_t(~isquart)
    Y_(qt) = (1 + 2L + 3L^2 + 2L^3 + L^4)/9 * y_t(isquart)
    y_t    = mu + iota*g_t + Lambda*f_t + e_t + o_t
    f_t    = Phi * [f_(t-1); ...; f_(t-p_f)] + sigma_(ft) .* s_(ft) .* eps_(ft)
    e_t    = sum(phi .* [e_(t-1), ..., e_(t-p_e)]) + sigma_(et) .* s_(et) .* eps_(et)

with a random-walk trend ``g_t`` and random-walk log volatilities.

State ordering
--------------
``construct_ssm`` returns a :class:`nyfed.ssm.StateSpace` whose state vector is
stacked in four blocks, in this order.  With ``n_quart > 0`` (the quarterly
case; ``n_quart == 0`` collapses every block to a single lag):

===============  ===============================  ==========================
Block            Size                             Contents
===============  ===============================  ==========================
trend            ``n_g_state = 5``                ``g_t`` and 4 lags
factors          ``n_f_state = max(5, p_f)*n_f``  ``f_t`` and lags, lag-major
monthly errors   ``n_e_state = max(1, p_e)*n_m``  ``e_t`` for monthly series
quarterly errs   ``n_q_state = max(5, p_e)*n_q``  ``e_t`` quarterly + 4 lags
===============  ===============================  ==========================

with ``n_m = n - n_quart`` and ``n_q = n_quart``.  "Lag-major" means the factor
block is ``[f_t; f_(t-1); ...; f_(t-4)]``, each sub-vector holding all ``n_f``
factors, so state index ``n_g_state + j`` is factor ``j`` at time ``t``.  For
the US panel (``n = 31``, ``n_f = 5``, ``p_f = 4``, ``p_e = 1``, three quarterly
series) this is ``5 + 25 + 28 + 15 = 73`` states.

The shock vector has ``1 + n_f + n`` elements: the trend shock, then the
``n_f`` factor shocks, then the measurement-error shocks with the *monthly*
series first and the quarterly ones last -- the same monthly/quarterly split
the state vector uses, not the original series order.

MATLAB stores arrays column-major.  Every ``reshape`` here passes
``order="F"``, and the ``kron`` / block-diagonal assembly follows the same
convention, so the layout matches ``construct_SSM.m`` element for element.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .parameters import Params
from .ssm import StateSpace

__all__ = ["Restrict", "Latent", "Prior", "construct_ssm", "construct_prior"]


# --------------------------------------------------------------------------- #
# Structures
# --------------------------------------------------------------------------- #


@dataclass
class Restrict:
    """MATLAB ``restrict`` struct: model restrictions.

    ``Lambda`` (n, n_f) and ``Phi`` (n_f, n_f, p_f) hold the loading and
    factor-VAR restriction patterns used by the Gibbs updates; ``iota`` (n,) is
    the trend loading; ``f_active`` (n_f, T) is a boolean mask switching factors
    on and off over time (this is how the COVID factor is confined to the
    pandemic window); ``isquart`` (n,) is a boolean flag for quarterly series.

    ``f_active`` and ``isquart`` may be ``None``, matching the ``isfield``
    guards in ``construct_SSM.m``: they then default to all-active and
    all-monthly.
    """

    Lambda: np.ndarray
    Phi: np.ndarray
    iota: np.ndarray
    f_active: np.ndarray | None = None
    isquart: np.ndarray | None = None


@dataclass
class Latent:
    """MATLAB ``latent`` struct.

    ``sigma = [sigma_f; sigma_e]`` and ``s = [s_f; s_e]`` are both
    ``(n_f + n, T)``: the stochastic volatilities and the outlier indicators of
    the factors stacked above those of the measurement errors.  ``state`` is the
    ``(1 + n_f + n, T)`` array of sampled trend/factor/error states, which
    ``construct_SSM.m`` does not read.
    """

    sigma: np.ndarray
    s: np.ndarray
    state: np.ndarray | None = None


@dataclass
class Prior:
    """MATLAB ``prior`` struct, see :func:`construct_prior`."""

    m_mu: np.ndarray
    P_mu: np.ndarray
    nu_g: float
    s2_g: float
    m_Lambda: np.ndarray
    P_Lambda: np.ndarray
    m_Phi: np.ndarray
    P_Phi: np.ndarray
    nu_f: float
    s2_f: float
    a_f: float
    b_f: float
    m_phi: np.ndarray
    P_phi: np.ndarray
    nu_e: float
    s2_e: float
    a_e: float
    b_e: float


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _blkdiag(*blocks: np.ndarray) -> np.ndarray:
    """MATLAB ``blkdiag``: block-diagonal concatenation of 2-D blocks.

    Scalars are treated as 1x1 blocks and zero-size blocks contribute nothing,
    as in MATLAB.
    """
    mats = [np.atleast_2d(np.asarray(b, dtype=float)) for b in blocks]
    rows = sum(m.shape[0] for m in mats)
    cols = sum(m.shape[1] for m in mats)
    out = np.zeros((rows, cols))
    i = j = 0
    for m in mats:
        out[i : i + m.shape[0], j : j + m.shape[1]] = m
        i += m.shape[0]
        j += m.shape[1]
    return out


def _eye_pad(k: int, m: int) -> np.ndarray:
    """``[eye(k), zeros(k, m)]`` -- the companion-form shift block."""
    return np.hstack([np.eye(k), np.zeros((k, m))])


# --------------------------------------------------------------------------- #
# construct_SSM.m
# --------------------------------------------------------------------------- #


def construct_ssm(
    param: Params,
    latent: Latent,
    restrict: Restrict,
    var_init: np.ndarray | None = None,
) -> StateSpace:
    """Construct the state-space form of the nowcast model.

    Port of ``construct_SSM.m``.  Returns a :class:`nyfed.ssm.StateSpace` with
    ``D`` (n,), ``H`` (n, n_state, T), ``Sigma_eps`` (n, n), ``F``
    (n_state, n_state), ``G`` (n_state, n_shock), ``Sigma_eta``
    (n_shock, n_shock, T-1), ``mu_1`` (n_state,) and ``Sigma_1``
    (n_state, n_state).  See the module docstring for the state ordering.

    ``var_init`` defaults to ``2*eye(n_state) + 10*blkdiag(...)`` with a block
    of ones per underlying state -- note this differs from the
    ``(1e-1)*eye + (1e2)*blkd`` quoted in the MATLAB help text; the code is
    taken as the specification.
    """
    # Extract parameters from structure
    mu = np.asarray(param.mu, dtype=float).ravel()
    gamma_g = float(param.gamma_g)
    Lambda = np.asarray(param.Lambda, dtype=float)
    Phi = param.Phi
    phi = param.phi

    # Recover dimensions
    n, n_f = Lambda.shape
    Phi = np.zeros((n_f, n_f)) if Phi is None else np.asarray(Phi, dtype=float)
    if Phi.size == 0:
        Phi = np.zeros((n_f, n_f))
    p_f = Phi.shape[2] if Phi.ndim == 3 else 1
    phi = np.zeros((n, 1)) if phi is None else np.asarray(phi, dtype=float)
    if phi.size == 0:
        phi = np.zeros((n, 1))
    if phi.ndim == 1:
        phi = phi[:, None]
    p_e = phi.shape[1]
    if restrict.isquart is None:
        isquart = np.zeros(n, dtype=bool)
    else:
        isquart = np.asarray(restrict.isquart, dtype=bool).ravel()
    n_quart = int(np.count_nonzero(isquart))
    n_month = n - n_quart

    # Compute number of states
    if n_quart == 0:
        n_g_state = 1
        n_f_state = max(1, p_f) * n_f
        n_e_state = max(1, p_e) * n
        n_q_state = 0
        vec_m = np.ones((1, 1))
        vec_q = np.ones((1, 1))
    else:
        n_g_state = 5
        n_f_state = max(5, p_f) * n_f
        n_e_state = max(1, p_e) * n_month
        n_q_state = max(5, p_e) * n_quart
        vec_m = np.array([[1.0, 0, 0, 0, 0]])
        vec_q = np.array([[1.0, 2, 3, 2, 1]]) / 9
    n_state = n_g_state + n_f_state + n_e_state + n_q_state

    # Extract latent variables
    sigma = np.asarray(latent.sigma, dtype=float)
    s = np.asarray(latent.s, dtype=float)
    T = sigma.shape[1]

    # Extract trend and active-factor indicators
    iota = np.asarray(restrict.iota, dtype=float).ravel()
    if restrict.f_active is None:
        f_active = np.ones((n_f, T))
    else:
        f_active = np.asarray(restrict.f_active, dtype=float)
    if n_quart == 0:
        vec_f_active = f_active.T
    else:
        # A factor that is active at every date pads the leading rows of each
        # lagged copy, so the first four periods do not switch the factor off
        # merely for want of a lag.  This is why a windowed build is not a
        # slice of a full-sample one.
        f_always = np.all(f_active.T != 0, axis=0).astype(float)[None, :]
        blocks = [f_active.T]
        for k in (1, 2, 3, 4):
            blocks.append(
                np.vstack([np.tile(f_always, (k, 1)), f_active[:, : max(T - k, 0)].T])
            )
        vec_f_active = np.hstack(blocks)

    # Extract volatilities and outlier indicators
    sigma_f = sigma[:n_f, :]
    sigma_e = sigma[n_f : n_f + n, :]
    s_f = s[:n_f, :]
    s_e = s[n_f : n_f + n, :]
    sigmaXs_f = sigma_f * s_f
    sigmaXs_e = sigma_e * s_e

    # Form state-space matrices for measurement equation
    # --- D
    D = mu.copy()
    # --- H
    H = np.full((n, n_state, T), np.nan)
    len_vec_m = vec_m.shape[1]
    len_vec_q = vec_q.shape[1]
    iota_m = iota[~isquart][:, None]
    iota_q = iota[isquart][:, None]
    Lambda_m = Lambda[~isquart, :]
    Lambda_q = Lambda[isquart, :]
    for t in range(T):
        H[~isquart, :, t] = np.hstack(
            [
                np.kron(vec_m, iota_m),
                np.kron(vec_m, Lambda_m) * vec_f_active[t, :],
                np.zeros((n_month, n_f_state - len_vec_m * n_f)),
                np.eye(n_month),
                np.zeros((n_month, n_e_state - n_month)),
                np.zeros((n_month, n_q_state)),
            ]
        )
        H[isquart, :, t] = np.hstack(
            [
                np.kron(vec_q, iota_q),
                np.kron(vec_q, Lambda_q) * vec_f_active[t, :],
                # construct_SSM.m uses length(vec_m) here too, not length(vec_q);
                # the two are equal in both branches, so this is faithful.
                np.zeros((n_quart, n_f_state - len_vec_m * n_f)),
                np.zeros((n_quart, n_e_state)),
                np.kron(vec_q, np.eye(n_quart)),
                np.zeros((n_quart, n_q_state - len_vec_q * n_quart)),
            ]
        )
    # --- Sigma_eps
    Sigma_eps = 1e-4 * np.eye(n)

    # Form state-space matrices for transition equation
    # --- F
    F_g = np.hstack([np.ones((1, 1)), np.zeros((1, n_g_state - 1))])
    F_f = np.hstack(
        [
            np.reshape(Phi, (n_f, n_f * p_f), order="F"),
            np.zeros((n_f, n_f_state - p_f * n_f)),
        ]
    )
    phi_diags_m = np.zeros((n_month, n_e_state))
    phi_m = phi[~isquart, :]
    idx_m = np.arange(n_month)
    for lag in range(p_e):
        phi_diags_m[idx_m, lag * n_month + idx_m] = phi_m[:, lag]
    phi_diags_q = np.zeros((n_quart, n_q_state))
    phi_q = phi[isquart, :]
    idx_q = np.arange(n_quart)
    for lag in range(p_e):
        phi_diags_q[idx_q, lag * n_quart + idx_q] = phi_q[:, lag]
    F = _blkdiag(
        np.vstack([F_g, _eye_pad(n_g_state - 1, 1)]),
        np.vstack([F_f, _eye_pad(n_f_state - n_f, n_f)]),
        np.vstack([phi_diags_m, _eye_pad(n_e_state - n_month, n_month)]),
        np.vstack([phi_diags_q, _eye_pad(n_q_state - n_quart, n_quart)]),
    )
    # --- G
    G = _blkdiag(
        np.vstack([np.ones((1, 1)), np.zeros((n_g_state - 1, 1))]),
        np.vstack([np.eye(n_f), np.zeros((n_f_state - n_f, n_f))]),
        np.vstack([np.eye(n_month), np.zeros((n_e_state - n_month, n_month))]),
        np.vstack([np.eye(n_quart), np.zeros((n_q_state - n_quart, n_quart))]),
    )
    # --- Sigma_eta
    # Indexed at t-1: the shocks driving the transition into period t sit in
    # slice t-1, matching the Kalman filter's transition convention.
    n_shock = 1 + n_f + n
    Sigma_eta = np.full((n_shock, n_shock, max(T - 1, 0)), np.nan)
    for t in range(1, T):
        Sigma_eta[:, :, t - 1] = _blkdiag(
            gamma_g**2,
            np.diag(sigmaXs_f[:, t] ** 2),
            np.diag(sigmaXs_e[~isquart, t] ** 2),
            np.diag(sigmaXs_e[isquart, t] ** 2),
        )

    # Form state-space arrays for initial condition
    if var_init is None:
        state_group = [np.ones((n_g_state, n_g_state))]
        for i_f in range(n_f):
            state_group.append(
                f_active[i_f, 0] * np.ones((n_f_state // n_f, n_f_state // n_f))
            )
        for _ in range(n_month):
            k = n_e_state // n_month
            state_group.append(np.ones((k, k)))
        for _ in range(n_quart):
            k = n_q_state // n_quart
            state_group.append(np.ones((k, k)))
        var_init = 2 * np.eye(n_state) + 10 * _blkdiag(*state_group)
    mu_1 = np.zeros(n_state)
    Sigma_1 = np.asarray(var_init, dtype=float)

    return StateSpace(
        H=H,
        F=F,
        G=G,
        mu_1=mu_1,
        Sigma_1=Sigma_1,
        D=D,
        Sigma_eps=Sigma_eps,
        Sigma_eta=Sigma_eta,
    )


# --------------------------------------------------------------------------- #
# construct_prior.m
# --------------------------------------------------------------------------- #


def construct_prior(dims: tuple[int, int, int, int], m_Lambda: np.ndarray) -> Prior:
    """Construct the default prior for the parameters of the nowcast model.

    Port of ``construct_prior.m``.  ``dims = (n, n_f, p_f, p_e)``; ``m_Lambda``
    is the ``(n, n_f)`` prior mean for the loadings.

    Only the live values are ported: the commented-out ``P_Lambda = 5*eye(...)``
    and ``tau_X = 1000`` alternatives, and the inline ``%6 %2`` alternates for
    ``nu_f``/``s2_f``/``nu_e``, are deliberately not reproduced.

    ``example_estimate.m`` divides ``P_Phi`` by 5 *after* calling this function.
    That rescaling belongs to the estimation entry point and is not applied
    here, exactly as in the MATLAB.
    """
    # Recover dimensions
    n, n_f, p_f, p_e = (int(v) for v in dims)
    m_Lambda = np.asarray(m_Lambda, dtype=float)

    # Set prior for unconditional means
    m_mu = np.zeros(n)
    P_mu = 100 * np.eye(n)

    # Set prior for time-varying trend variance
    nu_g = 18.0
    s2_g = 0.0001

    # Set prior for factor loadings
    P_Lambda = 10 * np.eye(n * n_f) - (1e-1 / n) * np.kron(np.eye(n_f), np.ones((n, n)))

    # Factor VAR coefficients
    m_Phi = np.zeros((n_f, n_f, p_f))
    if p_f > 0:
        m_Phi[:, :, 0] = np.eye(n_f)
    Xd_Phi = np.vstack(
        [
            5 * np.diag(np.kron(np.arange(1, p_f + 1, dtype=float), np.ones(n_f))),
            2 * np.tile(np.eye(n_f), (1, p_f)),
            2 * np.tile(np.ones((1, n_f)), (1, p_f)),
        ]
    )
    P_Phi = np.kron(Xd_Phi.T @ Xd_Phi, np.eye(n_f))

    # Set prior for factor time-varying volatility variances
    nu_f = 2.0
    s2_f = 0.001

    # Set prior for factor outlier probabilities
    nper = 12
    pi_mean = 1 - 1 / (2 * nper)
    pi_nobs = 20
    a_f = pi_mean * pi_nobs
    b_f = (1 - pi_mean) * pi_nobs

    # Set prior for measurement error AR coefficients
    m_phi = np.zeros((n, p_e))
    P_phi = _blkdiag(*[25 * (lag**2) * np.eye(n) for lag in range(1, p_e + 1)])

    # Set prior for measurement error time-varying volatility variances
    nu_e = 18.0
    s2_e = 0.0001

    # Set prior for measurement error outlier probabilities
    a_e = pi_mean * pi_nobs
    b_e = (1 - pi_mean) * pi_nobs

    return Prior(
        m_mu=m_mu,
        P_mu=P_mu,
        nu_g=nu_g,
        s2_g=s2_g,
        m_Lambda=m_Lambda,
        P_Lambda=P_Lambda,
        m_Phi=m_Phi,
        P_Phi=P_Phi,
        nu_f=nu_f,
        s2_f=s2_f,
        a_f=a_f,
        b_f=b_f,
        m_phi=m_phi,
        P_phi=P_phi,
        nu_e=nu_e,
        s2_e=s2_e,
        a_e=a_e,
        b_e=b_e,
    )
