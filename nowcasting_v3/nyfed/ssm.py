"""State-space model: Kalman filter, fast smoother, simulation smoother.

Line-by-line port of ``nyfed_matlab/functions/general/``:
``Kalman_filter.m``, ``fast_smoother.m``, ``simulate_SSM.m``,
``simulation_smoother.m`` and ``compute_LRV.m``.

The model is

    y_t     = D_t + H_t x_t + eps_t,      eps_t ~ N(0_N, Sigma_eps_t)
    x_(t+1) = C_t + F_t x_t + G_t eta_t,  eta_t ~ N(0_K, Sigma_eta_t)
    x_1     ~ N(mu_1, Sigma_1)

with the Durbin and Koopman (2012) conventions the MATLAB uses: ``filter.mu``
holds the one-step-ahead state prediction E[x_t | y_(1:t-1)], the transition
matrices ``C, F, G, Sigma_eta`` are indexed at ``t-1`` and the measurement
matrices ``H, Sigma_eps`` at ``t``.

Time variation is carried by array dimension, exactly as the MATLAB dispatches
on ``size(A, 3) > 1``: a 2-D ``H`` is constant, a 3-D ``H`` is time varying.
Nothing is broadcast to 3-D.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

import numpy as np

from .linalg import spd_inv, spd_logdet, symmetrize

__all__ = [
    "StateSpace",
    "Disturbances",
    "KalmanResult",
    "SmootherMSEs",
    "SmootherResult",
    "kalman_filter",
    "fast_smoother",
    "simulate_ssm",
    "simulation_smoother",
    "compute_lrv",
]


@dataclass
class StateSpace:
    """State-space matrices, constant or time varying.

    MATLAB ``SSM`` struct. ``None`` stands for an absent field, so the same
    defaults apply: ``D = 0``, ``Sigma_eps = zeros(N)``, ``C = zeros(M, 1)``,
    ``Sigma_eta = eye(K)``.

    Shapes: ``D`` (N,) or (N,T); ``H`` (N,M) or (N,M,T); ``Sigma_eps`` (N,N) or
    (N,N,T); ``C`` (M,) or (M,T-1); ``F`` (M,M) or (M,M,T-1); ``G`` (M,K) or
    (M,K,T-1); ``Sigma_eta`` (K,K) or (K,K,T-1); ``mu_1`` (M,); ``Sigma_1``
    (M,M). A column vector stored as (N,1) is accepted for ``D`` and ``C``.
    """

    H: np.ndarray
    F: np.ndarray
    G: np.ndarray
    mu_1: np.ndarray
    Sigma_1: np.ndarray
    D: np.ndarray | None = None
    Sigma_eps: np.ndarray | None = None
    C: np.ndarray | None = None
    Sigma_eta: np.ndarray | None = None


@dataclass
class Disturbances:
    """MATLAB ``disturbances`` struct: ``m_errors`` (N,T), ``shocks`` (K,T-1)."""

    m_errors: np.ndarray
    shocks: np.ndarray


@dataclass
class KalmanResult:
    """MATLAB ``[log_likelihood, prediction, filter]``.

    ``loglik`` is ``None`` unless ``need_loglik=True``; ``filter_mu`` and
    ``filter_sigma`` are ``None`` unless ``need_filter=True``.
    """

    loglik: float | None
    error: np.ndarray
    inv_mse: np.ndarray
    gain: np.ndarray
    filter_mu: np.ndarray | None
    filter_sigma: np.ndarray | None


@dataclass
class SmootherMSEs:
    """MATLAB ``MSEs`` struct."""

    m_errors: np.ndarray
    shocks: np.ndarray
    states: np.ndarray


@dataclass
class SmootherResult:
    """MATLAB ``[disturbances, states, MSEs]``.

    ``mses`` is ``None`` unless ``need_mses=True``.
    """

    m_errors: np.ndarray
    shocks: np.ndarray
    states: np.ndarray
    mses: SmootherMSEs | None


# --------------------------------------------------------------------------- #
# Helpers for MATLAB's constant-or-time-varying conventions
# --------------------------------------------------------------------------- #

def _is_tv3(a: np.ndarray) -> bool:
    """MATLAB ``size(A, 3) > 1`` for a matrix-valued sequence."""
    return a.ndim == 3 and a.shape[2] > 1


def _is_tv2(a: np.ndarray) -> bool:
    """MATLAB ``size(A, 2) > 1`` for a vector-valued sequence."""
    return a.ndim == 2 and a.shape[1] > 1


def _mat0(a: np.ndarray) -> np.ndarray:
    """MATLAB ``A(:, :, 1)``: the first matrix of a sequence."""
    return a[:, :, 0] if a.ndim == 3 else a


def _vec0(a: np.ndarray) -> np.ndarray:
    """MATLAB ``a(:, 1)``: the first column, as a 1-D vector."""
    return a[:, 0] if a.ndim == 2 else a


def _col(a: np.ndarray) -> np.ndarray:
    """A vector-valued sequence as a 2-D (N,1) or (N,T) array, for broadcasting."""
    return a[:, None] if a.ndim == 1 else a


# --------------------------------------------------------------------------- #
# Kalman_filter.m
# --------------------------------------------------------------------------- #

def kalman_filter(
    Y: np.ndarray,
    ssm: StateSpace,
    *,
    need_loglik: bool = False,
    need_filter: bool = True,
) -> KalmanResult:
    """Kalman filter. Port of ``Kalman_filter.m``.

    ``need_loglik`` defaults to ``False``, unlike the MATLAB, which always
    accumulates the log likelihood. The smoothers discard it and it costs a
    log-determinant per period.

    ``need_filter`` is MATLAB's ``nargout > 2``. With it off, ``filter_mu`` and
    ``filter_Sigma`` are never allocated, which saves an (M,M,T) array per call
    on the Gibbs path.

    Note on time variation: this model, as built by ``construct_SSM.m``, only
    ever varies ``H`` and ``Sigma_eta``. ``F`` and ``G`` are ``blkdiag``
    constants, ``Sigma_eps`` is ``1e-4*eye(n)``, ``D`` is ``mu`` and ``C`` is
    never set, so no fixture exercises the time-varying branches of ``C``,
    ``F``, ``G`` or ``Sigma_eps``. Those are pinned by
    ``test_all_six_time_varying_matrices_use_the_matlab_index_split`` alone.
    """
    Y = np.asarray(Y, dtype=float)

    # Unfold state-space struct
    H = np.asarray(ssm.H, dtype=float)
    F = np.asarray(ssm.F, dtype=float)
    G = np.asarray(ssm.G, dtype=float)

    # Recover dimensions
    N, T = Y.shape
    M, K = G.shape[0], G.shape[1]

    # Set state-space matrices to default if needed
    if ssm.D is not None:
        Y = Y - _col(np.asarray(ssm.D, dtype=float))
    Sigma_eps = (
        np.asarray(ssm.Sigma_eps, dtype=float)
        if ssm.Sigma_eps is not None
        else np.zeros((N, N))
    )
    C = np.asarray(ssm.C, dtype=float) if ssm.C is not None else np.zeros(M)
    Sigma_eta = (
        np.asarray(ssm.Sigma_eta, dtype=float)
        if ssm.Sigma_eta is not None
        else np.eye(K)
    )

    # Compute time-varying indicators
    isTV_H = _is_tv3(H)
    isTV_Sigma_eps = _is_tv3(Sigma_eps)
    isTV_C = _is_tv2(C)
    isTV_F = _is_tv3(F)
    isTV_G = _is_tv3(G)
    isTV_Sigma_eta = _is_tv3(Sigma_eta)

    # Create storage
    log_likelihood = -(T * N / 2.0) * np.log(2.0 * np.pi)
    prediction_error = np.full((N, T), np.nan)
    prediction_invMSE = np.full((N, N, T), np.nan)
    prediction_gain = np.full((M, N, T), np.nan)
    if need_filter:
        filter_mu = np.zeros((M, T))
        filter_Sigma = np.zeros((M, M, T))
    else:
        filter_mu = None
        filter_Sigma = None

    # Create auxiliary variables
    Ct = _vec0(C)
    Ft = _mat0(F)
    Gt = _mat0(G)
    Sigma_eta_t = _mat0(Sigma_eta)
    mu = np.asarray(ssm.mu_1, dtype=float).ravel()
    Sigma = symmetrize(np.asarray(ssm.Sigma_1, dtype=float))
    Ht = _mat0(H)
    Sigma_eps_t = _mat0(Sigma_eps)

    # Do first iteration of Kalman filter
    nonmiss = ~np.isnan(Y[:, 0])
    Y_aux = Y[nonmiss, 0]
    Ht_aux = Ht[nonmiss, :]
    Sigma_eps_t_aux = Sigma_eps_t[np.ix_(nonmiss, nonmiss)]
    e = Y_aux - Ht_aux @ mu
    S = symmetrize(Ht_aux @ Sigma @ Ht_aux.T + Sigma_eps_t_aux)
    S_inv = spd_inv(S)
    Kt = Sigma @ Ht_aux.T @ S_inv
    if need_loglik:
        log_likelihood += -0.5 * spd_logdet(S) - 0.5 * (e @ S_inv @ e)

    # Store prediction and filter output
    prediction_error[nonmiss, 0] = e
    prediction_invMSE[:, :, 0][np.ix_(nonmiss, nonmiss)] = S_inv
    prediction_gain[:, :, 0][:, nonmiss] = Kt
    if need_filter:
        filter_mu[:, 0] = mu
        filter_Sigma[:, :, 0] = Sigma

    # Perform Kalman filter recursions
    for t in range(1, T):
        # Update parameters of transition equation if time varying
        if isTV_C:
            Ct = C[:, t - 1]
        if isTV_F:
            Ft = F[:, :, t - 1]
        if isTV_G:
            Gt = G[:, :, t - 1]
        if isTV_Sigma_eta:
            Sigma_eta_t = Sigma_eta[:, :, t - 1]

        # Compute filtered states
        mu = Ct + Ft @ (mu + Kt @ e)
        Sigma = symmetrize(
            Ft @ (Sigma - Kt @ Ht_aux @ Sigma.T) @ Ft.T
            + Gt @ Sigma_eta_t @ Gt.T
        )

        # Update parameters of measurement equation if time varying
        if isTV_H:
            Ht = H[:, :, t]
        if isTV_Sigma_eps:
            Sigma_eps_t = Sigma_eps[:, :, t]

        # Compute predictions and log likelihood
        nonmiss = ~np.isnan(Y[:, t])
        Y_aux = Y[nonmiss, t]
        Ht_aux = Ht[nonmiss, :]
        Sigma_eps_t_aux = Sigma_eps_t[np.ix_(nonmiss, nonmiss)]
        e = Y_aux - Ht_aux @ mu
        S = symmetrize(Ht_aux @ Sigma @ Ht_aux.T + Sigma_eps_t_aux)
        S_inv = spd_inv(S)
        Kt = Sigma @ Ht_aux.T @ S_inv
        if need_loglik:
            log_likelihood += -0.5 * spd_logdet(S) - 0.5 * (e @ S_inv @ e)

        # Store prediction and filter output
        prediction_error[nonmiss, t] = e
        prediction_invMSE[:, :, t][np.ix_(nonmiss, nonmiss)] = S_inv
        prediction_gain[:, :, t][:, nonmiss] = Kt
        if need_filter:
            filter_mu[:, t] = mu
            filter_Sigma[:, :, t] = Sigma

    return KalmanResult(
        loglik=float(log_likelihood) if need_loglik else None,
        error=prediction_error,
        inv_mse=prediction_invMSE,
        gain=prediction_gain,
        filter_mu=filter_mu,
        filter_sigma=filter_Sigma,
    )


# --------------------------------------------------------------------------- #
# fast_smoother.m
# --------------------------------------------------------------------------- #

def fast_smoother(
    Y: np.ndarray, ssm: StateSpace, *, need_mses: bool = True
) -> SmootherResult:
    """Fast disturbance and state smoother. Port of ``fast_smoother.m``.

    ``need_mses`` mirrors the MATLAB's third output. The Gibbs sampler reaches
    this through ``simulation_smoother``, which does not ask for it.
    """
    Y = np.asarray(Y, dtype=float)

    # Unfold state-space struct
    H = np.asarray(ssm.H, dtype=float)
    F = np.asarray(ssm.F, dtype=float)
    G = np.asarray(ssm.G, dtype=float)

    # Recover dimensions
    N, T = Y.shape
    M, K = G.shape[0], G.shape[1]

    # Set state-space matrices to default if needed
    Sigma_eps = (
        np.asarray(ssm.Sigma_eps, dtype=float)
        if ssm.Sigma_eps is not None
        else np.zeros((N, N))
    )
    Sigma_eta = (
        np.asarray(ssm.Sigma_eta, dtype=float)
        if ssm.Sigma_eta is not None
        else np.eye(K)
    )

    # Compute time-varying indicators
    isTV_H = _is_tv3(H)
    isTV_Sigma_eps = _is_tv3(Sigma_eps)
    isTV_F = _is_tv3(F)
    isTV_G = _is_tv3(G)
    isTV_Sigma_eta = _is_tv3(Sigma_eta)

    # Run Kalman filter and recover prediction outputs. MATLAB asks for the
    # filter output only when the MSEs are needed (fast_smoother.m:72-76).
    kf = kalman_filter(Y, ssm, need_filter=need_mses)
    e = kf.error
    S_inv = kf.inv_mse
    Kt = kf.gain

    # -- DISTURBANCE SMOOTHER RECURSIONS ------------------------------------ #

    # Create storage
    m_errors = np.zeros((N, T))
    shocks = np.zeros((K, T - 1))

    # Create auxiliary variables
    Ft = _mat0(F)
    Gt = _mat0(G)
    Sigma_eta_t = _mat0(Sigma_eta)
    Ht = H[:, :, T - 1] if isTV_H else H
    Sigma_eps_t = Sigma_eps[:, :, T - 1] if isTV_Sigma_eps else Sigma_eps

    # Do first iteration of disturbance smoother
    nonmiss = ~np.isnan(e[:, T - 1])
    e_aux = e[nonmiss, T - 1]
    S_inv_aux = S_inv[:, :, T - 1][np.ix_(nonmiss, nonmiss)]
    Ht_aux = Ht[nonmiss, :]
    Sigma_eps_t_aux = Sigma_eps_t[:, nonmiss]  # only ignore missing columns
    u_aux = S_inv_aux @ e_aux
    r_aux = Ht_aux.T @ u_aux + np.zeros(M)
    m_errors[:, T - 1] = Sigma_eps_t_aux @ u_aux

    # Perform disturbance smoother recursions
    for t in range(T - 2, -1, -1):
        # Update parameters of transition equation if time varying
        if isTV_F:
            Ft = F[:, :, t]
        if isTV_G:
            Gt = G[:, :, t]
        if isTV_Sigma_eta:
            Sigma_eta_t = Sigma_eta[:, :, t]

        # Compute smoothed shocks
        shocks[:, t] = Sigma_eta_t @ Gt.T @ r_aux

        # Update parameters of measurement equation if time varying
        if isTV_H:
            Ht = H[:, :, t]
        if isTV_Sigma_eps:
            Sigma_eps_t = Sigma_eps[:, :, t]

        # Compute smoother measurement errors and variances
        nonmiss = ~np.isnan(e[:, t])
        e_aux = e[nonmiss, t]
        S_inv_aux = S_inv[:, :, t][np.ix_(nonmiss, nonmiss)]
        Kt_aux = Kt[:, :, t][:, nonmiss]
        Ht_aux = Ht[nonmiss, :]
        Sigma_eps_t_aux = Sigma_eps_t[:, nonmiss]  # only ignore missing columns
        u_aux = S_inv_aux @ e_aux - (Ft @ Kt_aux).T @ r_aux
        r_aux = Ht_aux.T @ u_aux + Ft.T @ r_aux
        m_errors[:, t] = Sigma_eps_t_aux @ u_aux

    # -- STATE SMOOTHER RECURSIONS ------------------------------------------ #

    # Set state-space matrices to default if needed
    C = np.asarray(ssm.C, dtype=float) if ssm.C is not None else np.zeros(M)

    # Compute time-varying indicators
    isTV_C = _is_tv2(C)

    # Create storage
    states = np.zeros((M, T))

    # Create auxiliary variables
    Ct = _vec0(C)

    # Do first iteration of fast state smoother
    x = np.asarray(ssm.mu_1, dtype=float).ravel() + np.asarray(
        ssm.Sigma_1, dtype=float
    ) @ r_aux
    states[:, 0] = x

    # Perform state smoother recursions
    for t in range(1, T):
        # Update parameters of transition equation if time varying
        if isTV_C:
            Ct = C[:, t - 1]
        if isTV_F:
            Ft = F[:, :, t - 1]
        if isTV_G:
            Gt = G[:, :, t - 1]

        # Compute smoothed states
        x = Ct + Ft @ x + Gt @ shocks[:, t - 1]
        states[:, t] = x

    # -- MEAN-SQUARE ERROR RECURSIONS --------------------------------------- #

    mses = None
    if need_mses:
        # Create storage
        mse_m_errors = np.zeros((N, N, T))
        mse_shocks = np.zeros((K, K, T - 1))
        mse_states = np.zeros((M, M, T))

        # Unwrap struct with MSE of filtered states
        Sigma = kf.filter_sigma

        # Create auxiliary variables
        Ft = _mat0(F)
        Gt = _mat0(G)
        Sigma_eta_t = _mat0(Sigma_eta)
        Ht = H[:, :, T - 1] if isTV_H else H
        Sigma_eps_t = Sigma_eps[:, :, T - 1] if isTV_Sigma_eps else Sigma_eps

        # Do first iteration of disturbance smoother
        nonmiss = ~np.isnan(e[:, T - 1])
        S_inv_aux = S_inv[:, :, T - 1][np.ix_(nonmiss, nonmiss)]
        Ht_aux = Ht[nonmiss, :]
        Sigma_eps_t_aux = Sigma_eps_t[:, nonmiss]  # only ignore missing columns
        D_aux = S_inv_aux
        N_aux = Ht_aux.T @ D_aux @ Ht_aux + np.zeros((M, M))
        mse_m_errors[:, :, T - 1] = symmetrize(
            Sigma_eps_t - Sigma_eps_t_aux @ D_aux @ Sigma_eps_t_aux.T
        )
        Sigma_T = Sigma[:, :, T - 1]
        mse_states[:, :, T - 1] = symmetrize(Sigma_T - Sigma_T @ N_aux @ Sigma_T)

        # Perform disturbance smoother recursions
        for t in range(T - 2, -1, -1):
            # Update parameters of transition equation if time varying
            if isTV_F:
                Ft = F[:, :, t]
            if isTV_G:
                Gt = G[:, :, t]
            if isTV_Sigma_eta:
                Sigma_eta_t = Sigma_eta[:, :, t]

            # Update parameters of measurement equation if time varying
            if isTV_H:
                Ht = H[:, :, t]
            if isTV_Sigma_eps:
                Sigma_eps_t = Sigma_eps[:, :, t]

            # Compute smoother measurement errors and variances
            nonmiss = ~np.isnan(e[:, t])
            S_inv_aux = S_inv[:, :, t][np.ix_(nonmiss, nonmiss)]
            Kt_aux = Kt[:, :, t][:, nonmiss]
            Ht_aux = Ht[nonmiss, :]
            Sigma_eps_t_aux = Sigma_eps_t[:, nonmiss]  # only ignore missing columns
            mse_shocks[:, :, t] = (
                Sigma_eta_t - Sigma_eta_t @ Gt.T @ N_aux @ Gt @ Sigma_eta_t
            )
            FK = Ft @ Kt_aux
            D_aux = S_inv_aux + FK.T @ N_aux @ FK
            KH = Kt_aux @ Ht_aux
            N_aux = (
                Ht_aux.T @ D_aux @ Ht_aux
                + Ft.T @ N_aux @ Ft
                - KH.T @ Ft.T @ N_aux @ Ft
                - Ft.T @ N_aux @ Ft @ KH
            )
            mse_m_errors[:, :, t] = symmetrize(
                Sigma_eps_t - Sigma_eps_t_aux @ D_aux @ Sigma_eps_t_aux.T
            )
            Sigma_t = Sigma[:, :, t]
            mse_states[:, :, t] = symmetrize(Sigma_t - Sigma_t @ N_aux @ Sigma_t)

        mses = SmootherMSEs(
            m_errors=mse_m_errors, shocks=mse_shocks, states=mse_states
        )

    return SmootherResult(
        m_errors=m_errors, shocks=shocks, states=states, mses=mses
    )


# --------------------------------------------------------------------------- #
# simulate_SSM.m
# --------------------------------------------------------------------------- #

def _mvnrnd(mean: np.ndarray, cov: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Draw one N(mean, cov) vector. MATLAB ``mvnrnd``.

    MATLAB factors the covariance with ``cholcov``: a Cholesky factor when the
    matrix is positive definite, otherwise an eigendecomposition, which also
    covers the positive-semidefinite defaults such as ``Sigma_eps = zeros(N)``.
    """
    n = cov.shape[0]
    if n == 0:
        return np.zeros(0)
    cov = symmetrize(cov)
    try:
        chol = np.linalg.cholesky(cov)
    except np.linalg.LinAlgError:
        vals, vecs = np.linalg.eigh(cov)
        chol = vecs * np.sqrt(np.clip(vals, 0.0, None))
    return mean + chol @ rng.standard_normal(n)


def simulate_ssm(
    ssm: StateSpace, T: int, rng: np.random.Generator
) -> tuple[np.ndarray, np.ndarray, Disturbances]:
    """Simulate a state-space model. Port of ``simulate_SSM.m``."""
    # Unfold state-space struct
    H = np.asarray(ssm.H, dtype=float)
    F = np.asarray(ssm.F, dtype=float)
    G = np.asarray(ssm.G, dtype=float)

    # Recover dimensions
    N = H.shape[0]
    M, K = G.shape[0], G.shape[1]

    # Set state-space matrices to default if needed
    D = np.asarray(ssm.D, dtype=float) if ssm.D is not None else np.zeros(N)
    Sigma_eps = (
        np.asarray(ssm.Sigma_eps, dtype=float)
        if ssm.Sigma_eps is not None
        else np.zeros((N, N))
    )
    C = np.asarray(ssm.C, dtype=float) if ssm.C is not None else np.zeros(M)
    Sigma_eta = (
        np.asarray(ssm.Sigma_eta, dtype=float)
        if ssm.Sigma_eta is not None
        else np.eye(K)
    )

    # Compute time-varying indicators
    isTV_D = _is_tv2(D)
    isTV_H = _is_tv3(H)
    isTV_Sigma_eps = _is_tv3(Sigma_eps)
    isTV_C = _is_tv2(C)
    isTV_F = _is_tv3(F)
    isTV_G = _is_tv3(G)
    isTV_Sigma_eta = _is_tv3(Sigma_eta)

    # Create storage
    Y = np.zeros((N, T))
    states = np.zeros((M, T))
    m_errors = np.zeros((N, T))
    shocks = np.zeros((K, T - 1))

    # Create auxiliary variables
    Ct = _vec0(C)
    Ft = _mat0(F)
    Gt = _mat0(G)
    Sigma_eta_t = _mat0(Sigma_eta)
    Dt = _vec0(D)
    Ht = _mat0(H)
    Sigma_eps_t = _mat0(Sigma_eps)

    # Simulate initial condition
    x_t = _mvnrnd(
        np.asarray(ssm.mu_1, dtype=float).ravel(),
        symmetrize(np.asarray(ssm.Sigma_1, dtype=float)),
        rng,
    )
    eps_t = _mvnrnd(np.zeros(N), Sigma_eps_t, rng)
    Y[:, 0] = Dt + Ht @ x_t + eps_t
    states[:, 0] = x_t
    m_errors[:, 0] = eps_t

    # Simulate rest of the sample
    for t in range(1, T):
        # Update parameters of transition equation if time varying
        if isTV_C:
            Ct = C[:, t - 1]
        if isTV_F:
            Ft = F[:, :, t - 1]
        if isTV_G:
            Gt = G[:, :, t - 1]
        if isTV_Sigma_eta:
            Sigma_eta_t = Sigma_eta[:, :, t - 1]

        # Draw shocks and update states
        eta_t = _mvnrnd(np.zeros(K), Sigma_eta_t, rng)
        x_t = Ct + Ft @ x_t + Gt @ eta_t

        # Update parameters of measurement equation if time varying
        if isTV_D:
            Dt = D[:, t]
        if isTV_H:
            Ht = H[:, :, t]
        if isTV_Sigma_eps:
            Sigma_eps_t = Sigma_eps[:, :, t]

        # Draw measurement errors and compute data
        eps_t = _mvnrnd(np.zeros(N), Sigma_eps_t, rng)
        Y[:, t] = Dt + Ht @ x_t + eps_t

        # Store states and disturbances
        states[:, t] = x_t
        shocks[:, t - 1] = eta_t
        m_errors[:, t] = eps_t

    return Y, states, Disturbances(m_errors=m_errors, shocks=shocks)


# --------------------------------------------------------------------------- #
# simulation_smoother.m
# --------------------------------------------------------------------------- #

def simulation_smoother(
    Y: np.ndarray, ssm: StateSpace, rng: np.random.Generator
) -> tuple[np.ndarray, Disturbances]:
    """Durbin-Koopman simulation smoother. Port of ``simulation_smoother.m``."""
    Y = np.asarray(Y, dtype=float)

    # Recover dimensions
    T = Y.shape[1]

    # Create auxiliary state-space model with no constants
    ssm_aux = dataclasses.replace(
        ssm,
        mu_1=0.0 * np.asarray(ssm.mu_1, dtype=float),
        C=None if ssm.C is None else 0.0 * np.asarray(ssm.C, dtype=float),
        D=None if ssm.D is None else 0.0 * np.asarray(ssm.D, dtype=float),
    )

    # Simulate state-space model and run smoother
    Y_sim, states_sim, disturb_sim = simulate_ssm(ssm_aux, T, rng)
    smooth = fast_smoother(Y - Y_sim, ssm, need_mses=False)

    # Compute draw of states
    states = states_sim + smooth.states

    # Compute draw of disturbances
    disturbances = Disturbances(
        m_errors=disturb_sim.m_errors + smooth.m_errors,
        shocks=disturb_sim.shocks + smooth.shocks,
    )

    return states, disturbances


# --------------------------------------------------------------------------- #
# compute_LRV.m
# --------------------------------------------------------------------------- #

def compute_lrv(Y: np.ndarray, n_lag: int | None = None) -> np.ndarray:
    """Long-run variance from a parametric VAR. Port of ``compute_LRV.m``."""
    Y = np.asarray(Y, dtype=float)
    N, T = Y.shape
    if n_lag is None:
        n_lag = int(np.ceil(0.75 * (T ** (1.0 / 3.0))))
    y = Y[:, n_lag:T]
    x = np.empty((1 + N * n_lag, T - n_lag))
    x[0, :] = 1.0
    for i_lag in range(1, n_lag + 1):
        x[1 + N * (i_lag - 1): 1 + N * i_lag, :] = Y[:, n_lag - i_lag: T - i_lag]
    B = np.linalg.lstsq(x.T, y.T, rcond=None)[0].T  # MATLAB: B = y / x
    U = y - B @ x
    S = U @ U.T / ((T - n_lag) - (1 + N * n_lag))
    # MATLAB: sum(reshape(B(:, 2:end), [N, N, n_lag]), 3), column-major, so
    # lag i occupies columns 1 + N*(i-1) ... N*i of B.
    IB = np.linalg.pinv(np.eye(N) - B[:, 1:].reshape(N, n_lag, N).sum(axis=1))
    return IB @ S @ IB.T
