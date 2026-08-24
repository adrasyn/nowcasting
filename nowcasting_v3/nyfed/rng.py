"""Random draws, in MATLAB's parameterisations.

The Statistics Toolbox functions the reference implementation calls do not map
one-to-one onto ``numpy.random.Generator``, and two of the mismatches are
silent:

* ``gamrnd(a, b)`` takes shape and **scale**, not shape and rate. numpy's
  ``Generator.gamma(shape, scale)`` agrees, but ``scipy.stats.invgamma`` does
  not, so ``update_gam``'s ``1./sqrt(gamrnd(...))`` must stay written that way.
* ``mnrnd(1, P)`` draws one categorical per **row** of ``P`` and returns a
  one-hot matrix. ``Generator.multinomial`` takes a single probability vector,
  so a faithful replacement is a per-row loop - far too slow for a function
  called 36 times per Gibbs iteration over 28,000 iterations. ``mnrnd_rows``
  vectorises it as an inverse-CDF sample and returns the drawn column index
  instead of the one-hot row, which is what every caller actually uses.

Every function takes the ``Generator`` last, so the caller owns the stream.
"""

from __future__ import annotations

import numpy as np

from .linalg import symmetrize

__all__ = ["betarnd", "gamrnd", "mnrnd_rows", "mvnrnd"]


def mvnrnd(
    mean: np.ndarray, cov: np.ndarray, rng: np.random.Generator
) -> np.ndarray:
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


def gamrnd(
    shape: np.ndarray | float, scale: np.ndarray | float, rng: np.random.Generator
) -> np.ndarray:
    """MATLAB ``gamrnd(A, B)``: shape A, **scale** B (not rate)."""
    return rng.gamma(shape, scale)


def betarnd(
    a: np.ndarray | float, b: np.ndarray | float, rng: np.random.Generator
) -> np.ndarray:
    """MATLAB ``betarnd(A, B)``."""
    return rng.beta(a, b)


def mnrnd_rows(probs: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Draw one category per row of ``probs``. MATLAB ``mnrnd(1, probs)``.

    ``probs`` is ``(T, n)`` with rows summing to one. Returns the ``(T,)``
    integer column indices drawn, i.e. ``argmax`` of the one-hot matrix MATLAB
    returns. Vectorised inverse-CDF: one uniform per row, then a search over
    the row's cumulative sum.

    The CDF is divided by its own last column rather than compared as-is, so a
    row that sums to 1 only up to floating-point error cannot fall off the end.
    """
    p = np.asarray(probs, dtype=float)
    if p.ndim != 2:
        raise ValueError(f"probs must be 2-D (T, n), got shape {p.shape}")
    cdf = np.cumsum(p, axis=1)
    cdf /= cdf[:, -1:]
    u = rng.random(p.shape[0])
    return np.argmax(cdf > u[:, None], axis=1)
