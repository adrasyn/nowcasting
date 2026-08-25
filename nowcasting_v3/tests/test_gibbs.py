"""Task 7 is the only module in Plan A whose OUTPUT is a draw, so no fixture can
pin what it returns. It has two safety nets instead.

Tier 1: the conditional posteriors themselves. Every random draw in
``Gibbs_update.m`` can be injected, and with all of them injected the routine is
deterministic; ``tools/octave_shims/gibbs_update_cond.m`` does exactly that and
returns the ``(m_X, Pinv_X)`` pairs the draws would have been taken from. Those
pairs are what a transposed design matrix or a dropped prior-precision term gets
wrong, and they match Octave to ``rtol=1e-10`` below on two panels: the real US
one (per-factor ``Lambda`` loop, quarterly state block, restrictions on both
``Lambda`` and ``Phi``) and a small monthly one (joint ``Lambda`` path,
unrestricted ``Phi``, a ragged edge that truncates ``t_est``).

Tier 2: posterior recovery on data simulated from the model with known
parameters. That catches a mis-specified conditional the moments cannot -
a sampler can have exactly the right conditionals and still be assembled into
the wrong sweep.

The ``synthetic`` fixture is a working scaffold. Note ``truth.Lambda[0, 0]``:
the sampler holds the restricted loading at its *current* value, which starts at
``initval.param.Lambda[0, 0] = 1``, so the simulation has to be normalised the
same way or the whole factor is recovered on a different scale and every
recovery test below fails for a reason that has nothing to do with the sampler.
"""

import numpy as np
import pytest

from nyfed.gibbs import gibbs_sampler, gibbs_update, gibbs_update_moments, s_update
from nyfed.model import InitVal, Latent, Prior, Restrict, construct_prior, construct_ssm
from nyfed.parameters import Params, map_parameter, vec_parameter
from nyfed.settings import GibbsSettings
from nyfed.ssm import simulate_ssm

DIMS = (6, 1, 1, 1)   # n=6 series, 1 factor, VAR(1), AR(1)
T_SIM = 600

# The two Octave oracles. The first takes the per-factor Lambda loop, the second
# the joint one; only one path runs per call, so both are needed.
CASES = ["gibbs_update_cond", "gibbs_update_cond_small"]


def _settings(**kw):
    """GibbsSettings with test-sized run lengths."""
    base = dict(n_gs=2000, n_burn=2000, n_thin=1, n_each=8, n_init=50,
                state_each=1)
    base.update(kw)
    return GibbsSettings(**base)


def _extract(params, name):
    """(n_param, n_gs) -> the named field stacked on a trailing draw axis."""
    draws = [getattr(map_parameter(params[:, i], DIMS), name)
             for i in range(params.shape[1])]
    return np.stack(draws, axis=-1)


# --------------------------------------------------------------------------- #
# Tier 1: the conditional posteriors, against Octave
# --------------------------------------------------------------------------- #


def _dims(d):
    return tuple(int(v) for v in d["dimvec"].ravel())


def _params(d):
    n, n_f, p_f, p_e = _dims(d)
    return Params(
        mu=d["param_gibbs__mu"].ravel(),
        gamma_g=d["param_gibbs__gamma_g"].item(),
        Lambda=d["param_gibbs__Lambda"].reshape(n, n_f, order="F"),
        Phi=d["param_gibbs__Phi"].reshape(n_f, n_f, p_f, order="F"),
        gamma_f=d["param_gibbs__gamma_f"].ravel(),
        pi_f=d["param_gibbs__pi_f"].ravel(),
        phi=d["param_gibbs__phi"].reshape(n, p_e, order="F"),
        gamma_e=d["param_gibbs__gamma_e"].ravel(),
        pi_e=d["param_gibbs__pi_e"].ravel(),
    )


def _latent(d):
    return Latent(sigma=d["latent_gibbs__sigma"], s=d["latent_gibbs__s"])


def _restrict(d):
    n, n_f, p_f, _ = _dims(d)
    return Restrict(
        Lambda=d["restrict__Lambda"].reshape(n, n_f, order="F"),
        Phi=d["restrict__Phi"].reshape(n_f, n_f, p_f, order="F"),
        iota=d["restrict__iota"].ravel(),
        f_active=d["restrict__f_active"].astype(bool),
        isquart=d["restrict__isquart"].astype(bool).ravel(),
    )


def _prior(d):
    n, n_f, p_f, p_e = _dims(d)
    return Prior(
        m_mu=d["prior__m_mu"].ravel(), P_mu=d["prior__P_mu"],
        nu_g=d["prior__nu_g"].item(), s2_g=d["prior__s2_g"].item(),
        m_Lambda=d["prior__m_Lambda"].reshape(n, n_f, order="F"),
        P_Lambda=d["prior__P_Lambda"],
        m_Phi=d["prior__m_Phi"].reshape(n_f, n_f, p_f, order="F"),
        P_Phi=d["prior__P_Phi"],
        nu_f=d["prior__nu_f"].item(), s2_f=d["prior__s2_f"].item(),
        a_f=d["prior__a_f"].item(), b_f=d["prior__b_f"].item(),
        m_phi=d["prior__m_phi"].reshape(n, p_e, order="F"),
        P_phi=d["prior__P_phi"],
        nu_e=d["prior__nu_e"].item(), s2_e=d["prior__s2_e"].item(),
        a_e=d["prior__a_e"].item(), b_e=d["prior__b_e"].item(),
    )


def _draws(d):
    """The injected stand-ins for the six random sites, as the shim took them."""
    from nyfed.gibbs import GibbsDraws
    n, n_f, p_f, p_e = _dims(d)
    return GibbsDraws(
        state=d["state"],
        Phi=d["draw_Phi"].reshape(n_f, n_f, p_f, order="F"),
        phi=d["draw_phi"].reshape(n, p_e, order="F"),
        mu=d["draw_mu"].ravel(),
        Lambda=d["draw_Lambda"].reshape(n, n_f, order="F"),
        sigma=d["sigma_new"],
        s=d["s_new"],
    )


def _moments(d):
    return gibbs_update_moments(_params(d), _latent(d), d["Y"], _prior(d),
                                _restrict(d), draws=_draws(d))


@pytest.mark.fixtures
@pytest.mark.parametrize("name", CASES)
@pytest.mark.parametrize("block", ["mu", "Phi", "phi", "Lambda"])
def test_conditional_posterior_moments_match_octave(fixture, name, block):
    """Tier 1, and the only exact check this module can have. The draw cannot be
    reproduced; the distribution it is drawn FROM can. A sampler with a
    transposed design matrix converges to the wrong posterior while mixing
    perfectly - this is the test that catches it."""
    d = fixture(name)
    got = _moments(d)
    for key in (f"m_{block}", f"Pinv_{block}"):
        want = d[key]
        assert np.allclose(np.reshape(getattr(got, key), want.shape), want,
                           rtol=1e-10), key


@pytest.mark.fixtures
@pytest.mark.parametrize("name", CASES)
@pytest.mark.parametrize("key", ["Rr_Lambda", "RR_Lambda", "y_t", "F_t"])
def test_lambda_design_and_detrended_data_match_octave(fixture, name, key):
    """``m_Lambda`` is ``Pinv_Lambda @ (P m + Rr)``, so two errors in the design
    matrix could in principle cancel there. Pin the pieces separately. ``y_t``
    and ``F_t`` pin the state reconstruction that feeds all of them - the
    quarterly/monthly error split and the f_active mask."""
    d = fixture(name)
    want = d[key]
    got = np.reshape(getattr(_moments(d), key), want.shape)
    assert np.allclose(got, want, rtol=1e-10), key


@pytest.mark.fixtures
def test_lambda_design_matrix_matches_octave(fixture):
    """Stored for the joint path only: concatenated over the five US factors
    R_Lambda is 1550x72 and would dominate the fixture budget."""
    d = fixture("gibbs_update_cond_small")
    assert np.allclose(_moments(d).R_Lambda, d["R_Lambda"], rtol=1e-10)


@pytest.mark.fixtures
@pytest.mark.parametrize("name", CASES)
@pytest.mark.parametrize("key", ["r_f_pad", "r_e_pad"])
def test_volatility_update_arguments_match_octave(fixture, name, key):
    """update_vol and update_scl are Tier 1 from Task 6, but what Gibbs_update
    PASSES them is not: the residual row is padded with t_skip+p leading NaNs
    and T-t_skip-T_est trailing ones, and getting that window wrong silently
    shifts the whole volatility path."""
    d = fixture(name)
    want = d[key]
    got = np.reshape(getattr(_moments(d), key), want.shape)
    assert np.allclose(got, want, rtol=1e-10, equal_nan=True), key


@pytest.mark.fixtures
def test_cleaned_state_is_a_permutation_of_the_drawn_state(fixture):
    """``latent.state`` is the (1 + n_f + n) view of the state draw. Its error
    rows are in SERIES order, but the state vector stores every monthly error
    first and every quarterly one last, so this is a permutation and not a
    slice - and it is the one part of the sweep the posterior moments do not
    already pin."""
    from nyfed.gibbs import _gibbs_update

    d = fixture("gibbs_update_cond")
    n, n_f, _, _ = _dims(d)
    _, latent, _ = _gibbs_update(_params(d), _latent(d), d["Y"], _prior(d),
                                 _restrict(d), None, _draws(d))
    state = d["state"]
    isquart = d["restrict__isquart"].astype(bool).ravel()
    n_quart = int(isquart.sum())
    n_g_state, n_f_state, n_e_state = 5, 25, 28   # the US panel, see model.py

    assert latent.state.shape == (1 + n_f + n, state.shape[1])
    assert np.array_equal(latent.state[0], state[0])
    assert np.array_equal(latent.state[1:1 + n_f], state[n_g_state:n_g_state + n_f])
    errors = latent.state[1 + n_f:]
    m0 = n_g_state + n_f_state
    q0 = m0 + n_e_state
    assert np.array_equal(errors[~isquart], state[m0:m0 + n - n_quart])
    assert np.array_equal(errors[isquart], state[q0:q0 + n_quart])


@pytest.mark.fixtures
def test_us_panel_dimensions_are_what_the_reference_says(fixture):
    """Guard on the US oracle itself: if the fixture ever stops being the real
    31-series panel, every Tier 1 assertion above quietly gets easier."""
    d = fixture("gibbs_update_cond")
    n, n_f, p_f, p_e = _dims(d)
    assert (n, n_f, p_f, p_e) == (31, 5, 4, 1)
    assert d["state"].shape[0] == 73
    assert int(d["restrict__isquart"].sum()) == 3
    assert int(np.count_nonzero(~np.isnan(d["restrict__Phi"]))) == 32
    # Gibbs_update.m branches to the joint Lambda update on this condition. The
    # US panel must fail it, or this fixture is testing the same path twice.
    assert not ((n * n_f < 100) or (n_f == 1))
    # ...and the small panel must satisfy it.
    n_s, n_f_s, _, _ = _dims(fixture("gibbs_update_cond_small"))
    assert (n_s * n_f_s < 100) or (n_f_s == 1)


# --------------------------------------------------------------------------- #
# Tier 2: posterior recovery on simulated data
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def synthetic():
    """Simulate from the model itself with known parameters.

    Deliberately a benign corner of the parameter space: the trend is frozen,
    stochastic volatility is switched off (gamma ~ 0) and no outliers fire
    (pi = 1). Those blocks have their own Tier 1 coverage in Task 6; what is
    unpinned - and therefore what this fixture must isolate - is whether the
    CONDITIONAL POSTERIORS for mu, Lambda, Phi and phi are right.
    """
    n, n_f, p_f, p_e = DIMS
    rng = np.random.default_rng(101)

    Lambda_true = np.linspace(0.6, 1.4, n).reshape(n, n_f)
    # The scale normalisation, imposed on the SIMULATION as well as on the
    # sampler. restrict.Lambda below pins entry (0, 0), and the sampler holds it
    # at its starting value of 1; simulating with anything else would identify
    # the factor on a different scale and rescale every other loading with it.
    Lambda_true[0, 0] = 1.0

    truth = Params(
        mu=np.zeros(n),
        gamma_g=1e-8,
        Lambda=Lambda_true,
        Phi=np.full((n_f, n_f, p_f), 0.6),
        gamma_f=np.full(n_f, 1e-8),
        pi_f=np.ones(n_f),
        phi=np.full((n, p_e), 0.3),
        gamma_e=np.full(n, 1e-8),
        pi_e=np.ones(n),
    )

    restrict = Restrict(
        Lambda=np.full((n, n_f), np.nan),
        Phi=np.full((n_f, n_f, p_f), np.nan),
        iota=np.zeros(n),
        f_active=np.ones((n_f, T_SIM), dtype=bool),
        isquart=np.zeros(n, dtype=bool),
    )
    restrict.Lambda[0, 0] = 1.0        # normalising loading fixes the scale

    latent = Latent(sigma=np.ones((n_f + n, T_SIM)),
                    s=np.ones((n_f + n, T_SIM)))

    y, _, _ = simulate_ssm(construct_ssm(truth, latent, restrict), T_SIM, rng)

    initval = InitVal(
        param=Params(
            mu=np.zeros(n), gamma_g=0.01,
            Lambda=np.ones((n, n_f)),
            Phi=np.zeros((n_f, n_f, p_f)),
            gamma_f=np.full(n_f, 0.1), pi_f=np.full(n_f, 0.95),
            phi=np.zeros((n, p_e)),
            gamma_e=np.full(n, 0.1), pi_e=np.full(n, 0.95),
        ),
        latent=Latent(sigma=np.ones((n_f + n, T_SIM)),
                      s=np.ones((n_f + n, T_SIM))),
    )
    prior = construct_prior(DIMS, initval.param.Lambda)
    return y, truth, restrict, initval, prior


def test_simulated_data_actually_has_the_factor_structure(synthetic):
    """Guard on the fixture itself. If this fails, every recovery test below is
    passing vacuously and proves nothing about the sampler."""
    y, truth, _, _, _ = synthetic
    assert y.shape == (DIMS[0], T_SIM)
    assert np.isfinite(y).all()
    corr = np.corrcoef(y)
    off = corr[~np.eye(DIMS[0], dtype=bool)]
    assert off.min() > 0.1, "series should co-move through the common factor"
    # The normalisation the sampler imposes has to hold in the truth too, or
    # the loadings are recovered up to an arbitrary scale.
    assert truth.Lambda[0, 0] == 1.0


@pytest.mark.slow
def test_posterior_covers_the_true_loadings(synthetic):
    y, truth, restrict, initval, prior = synthetic
    res = gibbs_sampler(y, prior, restrict, initval, _settings(),
                        np.random.default_rng(31))
    lam = _extract(res.params, "Lambda")
    lo, hi = np.percentile(lam, [2.5, 97.5], axis=-1)
    covered = ((truth.Lambda >= lo) & (truth.Lambda <= hi)).mean()
    assert covered >= 0.8, f"only {covered:.0%} of loadings covered"


@pytest.mark.slow
def test_posterior_covers_the_true_factor_var_coefficient(synthetic):
    y, truth, restrict, initval, prior = synthetic
    res = gibbs_sampler(y, prior, restrict, initval, _settings(),
                        np.random.default_rng(32))
    phi = _extract(res.params, "Phi")[0, 0, 0, :]
    lo, hi = np.percentile(phi, [2.5, 97.5])
    assert lo <= truth.Phi[0, 0, 0] <= hi


@pytest.mark.slow
def test_posterior_covers_the_true_idiosyncratic_ar(synthetic):
    y, truth, restrict, initval, prior = synthetic
    res = gibbs_sampler(y, prior, restrict, initval, _settings(),
                        np.random.default_rng(33))
    ar = _extract(res.params, "phi")
    lo, hi = np.percentile(ar, [2.5, 97.5], axis=-1)
    assert ((truth.phi >= lo) & (truth.phi <= hi)).mean() >= 0.8


def test_restricted_loadings_never_move(synthetic):
    """The normalising loading is fixed, not sampled. If it drifts, the model is
    unidentified and every other parameter is only pinned up to scale."""
    y, _, restrict, initval, prior = synthetic
    res = gibbs_sampler(y, prior, restrict, initval,
                        _settings(n_gs=50, n_burn=10),
                        np.random.default_rng(34))
    lam = _extract(res.params, "Lambda")
    fixed = ~np.isnan(restrict.Lambda)
    assert np.allclose(lam[fixed, :].std(axis=-1), 0.0)
    assert np.allclose(lam[fixed, 0], restrict.Lambda[fixed])


def test_two_runs_with_the_same_seed_are_identical(synthetic):
    """Reproducibility WITHIN the port. Not a claim about matching MATLAB."""
    y, _, restrict, initval, prior = synthetic
    cfg = _settings(n_gs=20, n_burn=5)
    a = gibbs_sampler(y, prior, restrict, initval, cfg,
                      np.random.default_rng(99))
    b = gibbs_sampler(y, prior, restrict, initval, cfg,
                      np.random.default_rng(99))
    assert np.array_equal(a.params, b.params)


def test_gibbs_update_preserves_shapes_and_stays_finite(synthetic):
    y, _, restrict, initval, prior = synthetic
    params, latent = gibbs_update(initval.param, initval.latent, y, prior,
                                  restrict, np.random.default_rng(35))
    vec = vec_parameter(params)
    assert vec.shape == (DIMS[0] * (1 + DIMS[1] + DIMS[3] + 2)
                         + DIMS[1] * (DIMS[1] * DIMS[2] + 2) + 1,)
    assert np.isfinite(vec).all()
    assert latent.sigma.shape == initval.latent.sigma.shape


def test_gibbs_update_leaves_its_inputs_alone(synthetic):
    """The sampler calls this thousands of times on the same structures. MATLAB
    passes structs by value; a port that mutates the caller's arrays instead
    would corrupt initval and go unnoticed until a second run."""
    y, _, restrict, initval, prior = synthetic
    sigma_before = initval.latent.sigma.copy()
    s_before = initval.latent.s.copy()
    Lambda_before = initval.param.Lambda.copy()
    gibbs_update(initval.param, initval.latent, y, prior, restrict,
                 np.random.default_rng(37))
    assert np.array_equal(initval.latent.sigma, sigma_before)
    assert np.array_equal(initval.latent.s, s_before)
    assert np.array_equal(initval.param.Lambda, Lambda_before)


def test_s_update_leaves_sigma_untouched(synthetic):
    """S_update.m draws outlier indicators only; sigma is an input there."""
    y, _, restrict, initval, prior = synthetic
    out = s_update(initval.param, initval.latent, y, restrict,
                   np.random.default_rng(36))
    assert np.array_equal(out.sigma, initval.latent.sigma)
    assert out.s.shape == initval.latent.s.shape
