import numpy as np
import pytest

from nyfed.rng import mnrnd_rows
from nyfed.updates import (
    KSC_MEANS, KSC_PROBS, KSC_STDVS, update_gam, update_ps, update_scl, update_vol,
)

STAGES = ("posteriors", "mean_t", "vars_t", "y_t",
          "x1_KF", "p1_KF", "x2_KF", "p2_KF", "ln_sigmasq")


def test_ksc_mixture_probabilities_sum_to_one():
    """Omori, Chib, Shephard & Nakajima (2007), 10-component approximation to
    log chi-square with 1 df. Transcribe from update_vol.m, not the paper."""
    assert len(KSC_PROBS) == len(KSC_MEANS) == len(KSC_STDVS) == 10
    assert KSC_PROBS.sum() == pytest.approx(1.0, abs=1e-12)


@pytest.mark.fixtures
@pytest.mark.parametrize("suffix", ["", "_miss"])
def test_update_vol_reproduces_octave_stage_by_stage(fixture, suffix):
    """Tier 1. With the mixture draw and the innovations injected, update_vol is
    fully deterministic, so every intermediate must match - not just the final
    path. A stage-level assert says WHICH line diverged."""
    d = fixture("update_vol_cond")
    got = update_vol(
        d[f"x{suffix}"].ravel(), d["sigma_in"].ravel(),
        float(d["gamma"].item()),
        mean_prior=float(d["mean_prior"].item()),
        var_prior=float(d["var_prior"].item()),
        weights=d[f"weights{suffix}"], innovations=d["utmp"].ravel(),
        return_stages=True,
    )
    for name in STAGES:
        want = d[f"{name}{suffix}"] if f"{name}{suffix}" in d else d[name]
        # equal_nan: y_t is NaN wherever x is, so the _miss case compares NaN
        # against NaN. np.allclose defaults to equal_nan=False, which would
        # fail on agreeing values. It still fails if the NaN patterns differ.
        assert np.allclose(np.reshape(getattr(got, name), want.shape), want,
                           rtol=1e-10, atol=0.0, equal_nan=True), f"{name}{suffix}"
    assert np.allclose(got.sigma, d[f"sigma_out{suffix}"].ravel(), rtol=1e-10,
                       atol=0.0)


@pytest.mark.fixtures
@pytest.mark.parametrize("suffix", ["", "_miss"])
def test_update_scl_posterior_weights_match_octave(fixture, suffix):
    d = fixture("update_scl")
    got = update_scl(d[f"x{suffix}"].ravel(), d["vals"].ravel(), d["probs"].ravel(),
                     return_posteriors=True)
    assert np.allclose(got, d[f"posteriors{suffix}"], rtol=1e-10, atol=0.0)


def test_update_scl_falls_back_to_the_prior_where_data_is_missing():
    """Missing months are normal on the ragged edge. update_scl.m sets the
    posterior to the prior there; without that branch every missing month draws
    from a garbage posterior."""
    rng = np.random.default_rng(21)
    vals = np.concatenate([[1.0], np.linspace(2, 5, 99)])
    probs = np.concatenate([[0.9], np.full(99, 0.1 / 99)])
    drawn = update_scl(np.full(5000, np.nan), vals, probs, rng)
    assert np.mean(drawn == 1.0) == pytest.approx(0.9, abs=0.02)


def test_update_scl_detects_a_large_outlier():
    rng = np.random.default_rng(22)
    vals = np.concatenate([[1.0], np.linspace(2, 5, 99)])
    probs = np.concatenate([[0.95], np.full(99, 0.05 / 99)])
    x = np.concatenate([np.zeros(99), [8.0]])
    drawn = np.array([update_scl(x, vals, probs, rng)[-1] for _ in range(200)])
    assert drawn.mean() > 2.0
    assert update_scl(x, vals, probs, rng)[0] == 1.0


def test_update_vol_survives_an_exact_zero_residual():
    """The 1e-4 floor inside log(x^2 + barr) is load-bearing: without it an exact
    zero residual sends the log to -inf."""
    rng = np.random.default_rng(24)
    out = update_vol(np.zeros(50), np.ones(50), 0.2, rng=rng)
    assert np.isfinite(out).all()


def test_update_vol_tracks_a_known_volatility_break():
    """Tier 2, production path. sigma is flat then 5x; the smoothed path must
    rise across the break."""
    rng = np.random.default_rng(23)
    t = 400
    truth = np.concatenate([np.full(t // 2, 1.0), np.full(t // 2, 5.0)])
    x = truth * rng.standard_normal(t)
    sigma = np.ones(t)
    for _ in range(40):
        sigma = update_vol(x, sigma, 0.2, rng=rng)
    assert sigma[:t // 2].mean() < 2.0
    assert sigma[t // 2:].mean() > 3.0


def test_update_gam_recovers_a_known_scale():
    """x_t = gamma * eps_t with gamma = 0.3, diffuse prior. Note update_gam
    returns 1/sqrt(gamrnd(...)) - an inverse-gamma expressed through a gamma.
    Do not substitute scipy.stats.invgamma; the parameterisations differ."""
    rng = np.random.default_rng(25)
    x = 0.3 * rng.standard_normal((20000, 1))
    draws = [update_gam(x, np.array([2.0]), np.array([0.001]), rng)[0]
             for _ in range(50)]
    assert np.mean(draws) == pytest.approx(0.3, rel=0.05)


def test_update_ps_recovers_a_known_probability():
    rng = np.random.default_rng(26)
    x = (rng.random((10000, 1)) < 0.8).astype(float)
    draws = [update_ps(x, np.array([1.0]), np.array([1.0]), rng)[0]
             for _ in range(50)]
    assert np.mean(draws) == pytest.approx(0.8, abs=0.02)


def test_mnrnd_rows_respects_the_row_probabilities():
    rng = np.random.default_rng(27)
    idx = mnrnd_rows(np.tile([0.1, 0.3, 0.6], (30000, 1)), rng)
    counts = np.bincount(idx, minlength=3) / len(idx)
    assert np.allclose(counts, [0.1, 0.3, 0.6], atol=0.01)


def test_mnrnd_rows_handles_differing_rows():
    rng = np.random.default_rng(28)
    probs = np.vstack([np.tile([1.0, 0.0], (500, 1)), np.tile([0.0, 1.0], (500, 1))])
    idx = mnrnd_rows(probs, rng)
    assert (idx[:500] == 0).all()
    assert (idx[500:] == 1).all()
