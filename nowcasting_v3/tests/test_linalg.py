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
    want = np.linalg.inv(a)
    # Explicit atol=0.0, the two-tier rule's default: entries run 7.3e-4 to
    # 0.147, so there is no near-zero row needing a derived floor. Without the
    # explicit atol, np.allclose's default 1e-8 would dominate rtol=1e-12 by
    # five orders and the stated tolerance would be fiction. Measured max
    # deviation 5.55e-17 against a bound of 1e-12*7.3e-4 = 7.3e-16, margin 13x.
    assert np.allclose(spd_inv(a), want, rtol=1e-12, atol=0.0)


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
    want = np.linalg.solve(a, b)
    # Explicit atol=0.0, as above; entries run 0.026 to 0.473, no near-zero
    # row. Measured max deviation 1.11e-16 against a bound of 1e-12*0.026 =
    # 2.6e-14, margin 232x.
    assert np.allclose(spd_solve(a, b), want, rtol=1e-12, atol=0.0)


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
