import numpy as np
import pytest

from nyfed.model import Latent, Restrict, construct_prior, construct_ssm
from nyfed.parameters import map_parameter

DIMS = (31, 5, 4, 1)


def _params(d):
    """Rebuild Params from the fixture's stored parameter vector.

    Using `param_vec` rather than the individual `param__*` arrays makes this
    a cross-check of Task 2's map_parameter as well: if the Fortran-order
    unpacking were wrong, every construct_ssm assertion below would fail.
    """
    return map_parameter(d["param_vec"].ravel(), DIMS)


def _latent(d, prefix="latent"):
    return Latent(sigma=d[f"{prefix}__sigma"], s=d[f"{prefix}__s"])


def _restrict(d):
    """f_active and isquart are stored as uint8; the port wants bool."""
    return Restrict(
        Lambda=d["restrict__Lambda"],
        Phi=d["restrict__Phi"],
        iota=d["restrict__iota"].ravel(),
        f_active=d["restrict__f_active"].astype(bool),
        isquart=d["restrict__isquart"].ravel().astype(bool),
    )


@pytest.mark.fixtures
def test_construct_ssm_matches_octave_on_every_matrix(fixture):
    d = fixture("construct_ssm_us")
    got = construct_ssm(_params(d), _latent(d), _restrict(d))
    for name in ("D", "H", "Sigma_eps", "F", "G", "Sigma_eta", "mu_1", "Sigma_1"):
        want = d[f"SSM__{name}"]
        assert np.allclose(np.reshape(getattr(got, name), want.shape), want,
                           rtol=1e-10, atol=0.0), name


@pytest.mark.fixtures
def test_state_dimension_is_seventy_three_for_the_us_panel(fixture):
    """5 trend + max(5,p_f)*n_f=25 factor + (n-n_quart)=28 monthly error
    + max(5,p_e)*n_quart=15 quarterly error."""
    d = fixture("construct_ssm_us")
    got = construct_ssm(_params(d), _latent(d), _restrict(d))
    assert got.F.shape[0] == 73
    assert got.H.shape == (31, 73, 60)


@pytest.mark.fixtures
def test_quarterly_rows_carry_the_mariano_murasawa_weights(fixture):
    """Quarterly series load on 5 trend lags as [1,2,3,2,1]/9; monthly rows load
    on the current period only. These weights encode ANNUALISED quarterly growth
    and must not be changed here - see Plan B, task B3."""
    d = fixture("construct_ssm_us")
    restrict = _restrict(d)
    got = construct_ssm(_params(d), _latent(d), restrict)
    h0 = got.H[:, :, 0]
    isq = restrict.isquart
    expected_q = np.outer(restrict.iota[isq], np.array([1.0, 2, 3, 2, 1]) / 9)
    assert np.allclose(h0[isq, :5], expected_q, rtol=1e-10, atol=0.0)
    assert np.allclose(h0[~isq, 1:5], 0.0)


@pytest.mark.fixtures
def test_covid_factor_is_masked_outside_the_pandemic_window(fixture):
    """f_active zeroes the COVID factor's column of H outside the window. The
    factor block starts at state index 5 (after the 5 trend states)."""
    d = fixture("construct_ssm_us")
    restrict = _restrict(d)
    got = construct_ssm(_params(d), _latent(d), restrict)
    i_cov = 4
    col = 5 + i_cov
    off = np.flatnonzero(~restrict.f_active[i_cov, :])
    on = np.flatnonzero(restrict.f_active[i_cov, :])
    assert off.size and on.size, "fixture window must contain both states"
    assert np.allclose(got.H[:, col, off[0]], 0.0)
    assert not np.allclose(got.H[:, col, on[0]], 0.0)


@pytest.mark.fixtures
def test_construct_prior_matches_octave(fixture):
    d = fixture("construct_prior_us")
    got = construct_prior(DIMS, d["m_Lambda"])
    for name in ("m_mu", "P_mu", "m_Lambda", "P_Lambda", "m_Phi", "P_Phi",
                 "m_phi", "P_phi"):
        want = d[f"prior__{name}"]
        assert np.allclose(np.reshape(getattr(got, name), want.shape), want,
                           rtol=1e-10, atol=0.0), name
    for name in ("nu_g", "s2_g", "nu_f", "s2_f", "nu_e", "s2_e",
                 "a_f", "b_f", "a_e", "b_e"):
        assert float(np.ravel(getattr(got, name))[0]) == pytest.approx(
            float(d[f"prior__{name}"].item()), rel=1e-12), name


def test_prior_outlier_probability_encodes_one_outlier_per_two_years():
    """pi_mean = 1 - 1/(2*12), 20 pseudo-observations. If the Australian panel
    changes this it must be a deliberate, documented choice."""
    prior = construct_prior(DIMS, np.zeros((31, 5)))
    a_f, b_f = float(np.ravel(prior.a_f)[0]), float(np.ravel(prior.b_f)[0])
    assert a_f / (a_f + b_f) == pytest.approx(1 - 1 / 24)
    assert a_f + b_f == pytest.approx(20)
    assert (a_f, b_f) == (float(np.ravel(prior.a_e)[0]),
                          float(np.ravel(prior.b_e)[0]))


def test_prior_phi_shrinks_towards_a_random_walk_in_the_first_lag():
    prior = construct_prior(DIMS, np.zeros((31, 5)))
    assert np.allclose(prior.m_Phi[:, :, 0], np.eye(5))
    assert np.allclose(prior.m_Phi[:, :, 1:], 0.0)
