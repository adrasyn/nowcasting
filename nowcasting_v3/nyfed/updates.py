"""The four conditional updaters of the Gibbs sampler.

Ports, in order, ``nyfed_matlab/functions/model/``:

* ``update_vol.m`` - stochastic volatility, via the 10-component mixture
  approximation to a log chi-square with 1 df, followed by a local-level
  Kalman filter and a backward simulation smoother.
* ``update_scl.m`` - the discrete outlier scale ``s_t``.
* ``update_gam.m`` - the volatility-of-volatility, an inverse-gamma draw.
* ``update_ps.m`` - the outlier probability, a beta draw.

``update_vol`` runs once per factor and per idiosyncratic component on every
Gibbs iteration, so this module is the sampler's inner loop.

Random draws are taken through :mod:`nyfed.rng`, which keeps MATLAB's
parameterisations. ``update_vol`` and ``update_scl`` also expose the
*conditional* part of themselves - the mixture posteriors, and for
``update_vol`` every filter and smoother intermediate - because everything
they return is a draw, and the posterior is the only thing a fixture can pin
exactly. ``tools/octave_shims/update_vol_cond.m`` is ``update_vol.m`` with its
two random statements (``mnrnd(1, posteriors)`` and ``randn(T+1, 1)``) replaced
by arguments; ``weights`` and ``innovations`` below are those two arguments, in
that role and that orientation.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .rng import betarnd, gamrnd, mnrnd_rows

__all__ = [
    "KSC_MEANS", "KSC_PROBS", "KSC_STDVS", "VolStages",
    "update_gam", "update_ps", "update_scl", "update_vol",
]

# 10-component mixture approximation to log chi-square with 1 df.
# Transcribed verbatim from update_vol.m lines 29-31 - NOT retyped from Omori,
# Chib, Shephard & Nakajima (2007), whose table is ordered differently in some
# printings. update_vol.m stores the variances and takes the square root.
KSC_PROBS = np.array(
    [0.00609, 0.04775, 0.13057, 0.20674, 0.22715,
     0.18842, 0.12047, 0.05591, 0.01575, 0.00115]
)
KSC_MEANS = np.array(
    [1.92677, 1.34744, 0.73504, 0.02266, -0.85173,
     -1.97278, -3.46788, -5.55246, -8.68384, -14.65000]
)
KSC_STDVS = np.sqrt(
    np.array([0.11265, 0.17788, 0.26768, 0.40611, 0.62699,
              0.98583, 1.57469, 2.54498, 4.16591, 7.33342])
)

# update_vol.m: barr floors log(x^2), small guards the smoother's 1/p2, and bd
# caps the volatility the routine is willing to return.
_BARR = 1e-4
_SMALL = 1e-10
_BOUND = 15.0


@dataclass
class VolStages:
    """Every intermediate ``update_vol_cond.m`` returns, in its order.

    Stage-by-stage comparison against the Octave fixture localises a mismatch
    to one line of ``update_vol.m`` instead of to the function as a whole.
    """

    posteriors: np.ndarray  # (T, 10) mixture posterior, before the draw
    mean_t: np.ndarray      # (T,)    mixture mean selected by `weights`
    vars_t: np.ndarray      # (T,)    mixture variance selected by `weights`
    y_t: np.ndarray         # (T,)    log(x^2 + barr) - mean_t
    x1_KF: np.ndarray       # (T+1,)  filtered state mean
    p1_KF: np.ndarray       # (T+1,)  filtered state variance
    x2_KF: np.ndarray       # (T+1,)  one-step forecast mean
    p2_KF: np.ndarray       # (T+1,)  one-step forecast variance
    ln_sigmasq: np.ndarray  # (T+1,)  smoothed draw of log sigma^2
    sigma: np.ndarray       # (T,)    exp(ln_sigmasq[1:]/2), capped at bd


def _normalise_rows(pxlikelihood: np.ndarray, prior: np.ndarray) -> np.ndarray:
    """Divide each row by its total, then fall back to ``prior`` where that
    total is not usable. MATLAB::

        xmlikelihood = sum(pxlikelihood, 2);
        posteriors   = pxlikelihood./repmat(xmlikelihood, 1, n);
        posteriors(isnan(posteriors)) = probs_rep(isnan(posteriors));

    The row total is taken as the last column of a ``cumsum`` rather than with
    ``sum``. MATLAB accumulates ``sum(X, 2)`` sequentially while numpy's
    ``sum`` is pairwise, and the two disagree in the last bit; going through
    ``cumsum``, which is sequential by construction, reproduces Octave exactly
    while staying a single vectorised call. It is measurably dearer than
    ``sum`` once the support is wide (roughly 7 us -> 54 us per call at
    ``update_scl``'s 100 points), so it is the first thing to revisit if
    Task 7's profile lands on this line.

    The NaN fallback covers two cases with one branch, exactly as MATLAB does:
    a missing observation, and a row whose likelihoods all underflow to zero
    so that the division is 0/0.
    """
    with np.errstate(divide="ignore", invalid="ignore"):
        posteriors = pxlikelihood / np.cumsum(pxlikelihood, axis=1)[:, -1:]
    return np.where(np.isnan(posteriors), prior, posteriors)


def _mixture_posteriors(ln_eps: np.ndarray) -> np.ndarray:
    """Bayes rule over the 10 mixture components. update_vol.m lines 44-52."""
    with np.errstate(divide="ignore", invalid="ignore"):
        likelihood = (
            np.exp(-0.5 * ((ln_eps[:, None] - KSC_MEANS) / KSC_STDVS) ** 2)
            / KSC_STDVS
        )
    return _normalise_rows(likelihood * KSC_PROBS, KSC_PROBS)


def update_vol(
    x: np.ndarray,
    sigma: np.ndarray,
    gamma: float,
    mean_prior: float = 0.0,
    var_prior: float = 1e6,
    rng: np.random.Generator | None = None,
    *,
    weights: np.ndarray | None = None,
    innovations: np.ndarray | None = None,
    return_stages: bool = False,
) -> np.ndarray | VolStages:
    """Update the volatility path. Port of ``update_vol.m``.

    Model::

        x_t           = sigma_t * eps_t
        ln(sigma_t^2) = ln(sigma_(t-1)^2) + gamma * ups_t

    ``x`` and ``sigma`` are ``(T,)``; ``gamma`` is scalar. Returns the ``(T,)``
    updated volatilities, or a :class:`VolStages` when ``return_stages``.

    ``weights`` ``(T, 10)`` and ``innovations`` ``(T+1,)`` are the injection
    seam matching ``tools/octave_shims/update_vol_cond.m``: they stand in for
    ``mnrnd(1, posteriors)`` and ``randn(T+1, 1)``. Either left ``None`` is
    drawn from ``rng`` - the production path. With both supplied the routine is
    deterministic and reproduces Octave.
    """
    x = np.asarray(x, dtype=float).ravel()
    sigma = np.asarray(sigma, dtype=float).ravel()
    T = x.shape[0]

    # Construct log(eps_t^2) and apply Bayes rule over the mixture.
    ln_eps = np.log(x**2 + _BARR) - np.log(sigma**2)
    posteriors = _mixture_posteriors(ln_eps)

    # Draw weights from posterior. mnrnd_rows returns the drawn column index;
    # for a one-hot row `weights` the products below reduce to that lookup.
    if weights is None:
        if rng is None:
            raise ValueError("update_vol needs rng when weights is not supplied")
        drawn = mnrnd_rows(posteriors, rng)
        mean_t = KSC_MEANS[drawn]
        vars_t = KSC_STDVS[drawn] ** 2
    else:
        w = np.asarray(weights, dtype=float)
        if w.shape != (T, KSC_PROBS.size):
            raise ValueError(f"weights must be ({T}, {KSC_PROBS.size}), got {w.shape}")
        mean_t = w @ KSC_MEANS
        vars_t = (w @ KSC_STDVS) ** 2

    gamsq = float(gamma) ** 2
    ln_x = np.log(x**2 + _BARR)
    y_t = ln_x - mean_t

    # Initialize univariate filter.
    x1_KF = np.zeros(T + 1)
    p1_KF = np.zeros(T + 1)
    x2_KF = np.zeros(T + 1)
    p2_KF = np.zeros(T + 1)
    ln_sigmasq = np.zeros(T + 1)

    x1 = float(mean_prior)
    p1 = float(var_prior)
    x1_KF[0] = x1
    p1_KF[0] = p1

    # update_vol.m splits this loop in two on `any(isnan(y_t))`; the two bodies
    # are numerically identical wherever y_t is observed, the split being an
    # optimisation, so one loop with the missing-value test is the same filter.
    for t in range(1, T + 1):
        # Forecast state mean and variance.
        x2 = x1
        p2 = p1 + gamsq
        yt = y_t[t - 1]

        # Update state mean and variance.
        if yt != yt:  # NaN: no observation, so the forecast stands.
            x1 = x2
            p1 = p2
        else:
            h = p2 + vars_t[t - 1]
            k = p2 / h
            x1 = x2 + k * (yt - x2)
            p1 = p2 - k * p2

        # Store state means and variances.
        x1_KF[t] = x1
        p1_KF[t] = p1
        x2_KF[t] = x2
        p2_KF[t] = p2

    # Apply smoothing.
    if innovations is None:
        if rng is None:
            raise ValueError("update_vol needs rng when innovations is not supplied")
        utmp = rng.standard_normal(T + 1)
    else:
        utmp = np.asarray(innovations, dtype=float).ravel()
        if utmp.shape != (T + 1,):
            raise ValueError(f"innovations must be ({T + 1},), got {utmp.shape}")

    x3mean = x1
    p3 = p1
    x3 = x3mean + np.sqrt(p3) * utmp[T]
    ln_sigmasq[T] = x3

    for t in range(T, 0, -1):
        x1 = x1_KF[t - 1]
        p1 = p1_KF[t - 1]
        x2 = x2_KF[t]
        p2 = p2_KF[t]
        if p2 > _SMALL:
            # update_vol.m forms the reciprocal first; p1*(1/p2) and p1/p2
            # differ in the last bit, and this is the only place the port can
            # drift from Octave without a reason.
            p2i = 1.0 / p2
            k = p1 * p2i
            x3mean = x1 + k * (x3 - x2)
            p3 = p1 - k * p1
        else:
            x3mean = x1
            p3 = p1
        x3 = x3mean + np.sqrt(p3) * utmp[t - 1]
        ln_sigmasq[t - 1] = x3

    # Compute updated volatilities, then impose the upper bound.
    out = np.minimum(np.exp(ln_sigmasq[1:T + 1] / 2.0), _BOUND)

    if return_stages:
        return VolStages(
            posteriors=posteriors, mean_t=mean_t, vars_t=vars_t, y_t=y_t,
            x1_KF=x1_KF, p1_KF=p1_KF, x2_KF=x2_KF, p2_KF=p2_KF,
            ln_sigmasq=ln_sigmasq, sigma=out,
        )
    return out


def update_scl(
    x: np.ndarray,
    vals: np.ndarray,
    probs: np.ndarray,
    rng: np.random.Generator | None = None,
    *,
    return_posteriors: bool = False,
) -> np.ndarray:
    """Update the discrete outlier scales. Port of ``update_scl.m``.

    Model: ``x_t = s_t * eps_t`` with ``s_t ~ Discrete(vals, probs)``. ``x`` is
    ``(T,)``; ``vals`` and ``probs`` are ``(n_s,)``. Returns the ``(T,)`` drawn
    scales, or the ``(T, n_s)`` posterior when ``return_posteriors``.
    """
    x = np.asarray(x, dtype=float).ravel()
    vals = np.asarray(vals, dtype=float).ravel()
    probs = np.asarray(probs, dtype=float).ravel()

    # Apply Bayes rule over the discrete support. The posterior falls back to
    # the prior wherever x is missing - NaN months are normal on the ragged
    # edge, and without that branch each one would draw from 0/0.
    with np.errstate(divide="ignore", invalid="ignore"):
        likelihood = np.exp(-0.5 * (x[:, None] / vals) ** 2) / vals
    posteriors = _normalise_rows(likelihood * probs, probs)

    if return_posteriors:
        return posteriors

    # Draw scales from posterior.
    if rng is None:
        raise ValueError("update_scl needs rng unless return_posteriors is set")
    return vals[mnrnd_rows(posteriors, rng)]


def update_gam(
    x: np.ndarray,
    nu_prior: np.ndarray,
    s2_prior: np.ndarray,
    rng: np.random.Generator,
) -> np.ndarray:
    """Update the scale of ``x_t = gamma * eps_t``. Port of ``update_gam.m``.

    ``x`` is ``(T, N)``; ``nu_prior`` and ``s2_prior`` are ``(N,)``. Returns
    ``(N,)`` standard deviations.

    The draw is inverse-gamma, written as MATLAB writes it - the reciprocal
    square root of a gamma with shape ``nu/2`` and **scale** ``2/(nu*s2)``.
    ``scipy.stats.invgamma`` parameterises differently and would be wrong here
    without any error being raised.
    """
    x = np.asarray(x, dtype=float)
    nu_prior = np.asarray(nu_prior, dtype=float).ravel()
    s2_prior = np.asarray(s2_prior, dtype=float).ravel()

    T = x.shape[0]
    nu_post = nu_prior + T
    s2_post = (nu_prior / nu_post) * s2_prior + (1.0 / nu_post) * np.sum(x**2, axis=0)
    return 1.0 / np.sqrt(gamrnd(nu_post / 2.0, 2.0 / (nu_post * s2_post), rng))


def update_ps(
    x: np.ndarray,
    a_prior: np.ndarray,
    b_prior: np.ndarray,
    rng: np.random.Generator,
) -> np.ndarray:
    """Update the Bernoulli probability. Port of ``update_ps.m``.

    ``x`` is ``(T, N)``; ``a_prior`` and ``b_prior`` are ``(N,)``. Returns
    ``(N,)`` probabilities drawn from the conjugate beta posterior.

    MATLAB counts successes as ``x == 1`` exactly and failures as everything
    else, so a NaN counts as a failure rather than being excluded. Ported as
    written - the caller passes an indicator, never missing data.
    """
    x = np.asarray(x, dtype=float)
    a_prior = np.asarray(a_prior, dtype=float).ravel()
    b_prior = np.asarray(b_prior, dtype=float).ravel()

    alpha_post = a_prior + np.sum(x == 1, axis=0)
    beta_post = b_prior + np.sum(~(x == 1), axis=0)
    return betarnd(alpha_post, beta_post, rng)
