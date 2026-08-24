import numpy as np
import pytest

from nyfed.parameters import Params, map_parameter, vec_parameter

DIMS = (31, 5, 4, 1)  # the US reference panel


def _params(dims=DIMS):
    n, n_f, p_f, p_e = dims
    rng = np.random.default_rng(7)
    return Params(
        mu=rng.standard_normal(n),
        gamma_g=float(rng.standard_normal()),
        Lambda=rng.standard_normal((n, n_f)),
        Phi=rng.standard_normal((n_f, n_f, p_f)),
        gamma_f=rng.standard_normal(n_f),
        pi_f=rng.standard_normal(n_f),
        phi=rng.standard_normal((n, p_e)),
        gamma_e=rng.standard_normal(n),
        pi_e=rng.standard_normal(n),
    )


def test_n_param_matches_formula():
    n, n_f, p_f, p_e = DIMS
    expected = 1 + n * (1 + n_f + p_e + 2) + n_f * (n_f * p_f + 2)
    assert expected == 390
    assert vec_parameter(_params()).shape == (390,)


def test_roundtrip_is_lossless():
    original = _params()
    restored = map_parameter(vec_parameter(original), DIMS)
    for field in ("mu", "Lambda", "Phi", "gamma_f", "pi_f", "phi", "gamma_e", "pi_e"):
        assert np.array_equal(getattr(original, field), getattr(restored, field))
    assert original.gamma_g == restored.gamma_g


def test_phi_uses_fortran_order():
    """MATLAB is column-major. A C-order reshape transposes Phi's lag slices
    and the model still runs, silently wrong."""
    n, n_f, p_f, p_e = DIMS
    vec = np.arange(390, dtype=float)
    phi_block_start = n + 1 + n * n_f
    block = vec[phi_block_start : phi_block_start + n_f * n_f * p_f]
    got = map_parameter(vec, DIMS).Phi
    assert np.array_equal(got, block.reshape((n_f, n_f, p_f), order="F"))
    assert got[0, 1, 0] != got[1, 0, 0]


def test_field_order_is_mu_gamma_lambda_phi():
    n, n_f, p_f, p_e = DIMS
    p = _params()
    vec = vec_parameter(p)
    assert np.array_equal(vec[:n], p.mu)
    assert vec[n] == p.gamma_g
    assert np.array_equal(vec[n + 1 : n + 1 + n * n_f], p.Lambda.reshape(-1, order="F"))
