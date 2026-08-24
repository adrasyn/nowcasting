import numpy as np
import pytest

from nyfed.linalg import spd_inv, spd_logdet, spd_solve, symmetrize


def test_symmetrize_averages_with_transpose():
    a = np.array([[1.0, 2.0], [4.0, 3.0]])
    assert np.allclose(symmetrize(a), [[1.0, 3.0], [3.0, 3.0]])


def test_spd_inv_matches_dense_inverse():
    rng = np.random.default_rng(0)
    x = rng.standard_normal((6, 6))
    a = x @ x.T + 6 * np.eye(6)
    assert np.allclose(spd_inv(a), np.linalg.inv(a), rtol=1e-12)


def test_spd_inv_returns_exactly_symmetric():
    rng = np.random.default_rng(1)
    x = rng.standard_normal((5, 5))
    a = x @ x.T + 5 * np.eye(5)
    out = spd_inv(a)
    assert np.array_equal(out, out.T)


def test_spd_solve_matches_dense_solve():
    rng = np.random.default_rng(2)
    x = rng.standard_normal((4, 4))
    a = x @ x.T + 4 * np.eye(4)
    b = rng.standard_normal((4, 3))
    assert np.allclose(spd_solve(a, b), np.linalg.solve(a, b), rtol=1e-12)


def test_spd_logdet_matches_slogdet():
    rng = np.random.default_rng(3)
    x = rng.standard_normal((7, 7))
    a = x @ x.T + 7 * np.eye(7)
    assert spd_logdet(a) == pytest.approx(np.linalg.slogdet(a)[1], rel=1e-12)


def test_spd_logdet_survives_tiny_determinant():
    """log(det(A)) underflows here; the Cholesky form must not."""
    a = 1e-40 * np.eye(30)
    assert np.isfinite(spd_logdet(a))
    assert spd_logdet(a) == pytest.approx(30 * np.log(1e-40), rel=1e-12)


def test_spd_inv_handles_zero_dimension():
    """All-missing periods give a 0x0 system; it must not raise."""
    out = spd_inv(np.zeros((0, 0)))
    assert out.shape == (0, 0)
