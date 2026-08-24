"""Symmetric positive-definite linear algebra.

Ports MATLAB's ``linsolve(A, B, struct('SYM',true,'POSDEF',true))`` and
replaces ``log(det(A))`` with a Cholesky log-determinant, which does not
underflow for the ill-conditioned prediction MSEs this model produces.
"""

from __future__ import annotations

import numpy as np
from scipy.linalg import cho_factor, cho_solve


def symmetrize(a: np.ndarray) -> np.ndarray:
    """Return (A + A') / 2. MATLAB: the ``symmetrize`` inline handle."""
    return (a + a.T) / 2.0


def spd_solve(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Solve A X = B for symmetric positive-definite A."""
    if a.shape[0] == 0:
        return np.zeros((0, b.shape[1] if b.ndim > 1 else 0))
    return cho_solve(cho_factor(symmetrize(a), lower=True), b)


def spd_inv(a: np.ndarray) -> np.ndarray:
    """Invert a symmetric positive-definite matrix, returning an exactly
    symmetric result. MATLAB: ``linsolve(A, eye(k), option)``."""
    k = a.shape[0]
    if k == 0:
        return np.zeros((0, 0))
    out = cho_solve(cho_factor(symmetrize(a), lower=True), np.eye(k))
    return symmetrize(out)


def spd_logdet(a: np.ndarray) -> float:
    """log|A| for symmetric positive-definite A, via Cholesky."""
    if a.shape[0] == 0:
        return 0.0
    chol = np.linalg.cholesky(symmetrize(a))
    return float(2.0 * np.sum(np.log(np.diag(chol))))
