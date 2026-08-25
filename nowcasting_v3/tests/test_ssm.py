import numpy as np
import pytest

from nyfed.ssm import (
    StateSpace, compute_lrv, fast_smoother, kalman_filter, simulation_smoother,
)


def _ssm(d, prefix="SSM"):
    """Rebuild a StateSpace from a Task 3 fixture.

    Fixtures flatten MATLAB structs to `prefix__field`. `C` and `D` are absent
    from some fixtures because the MATLAB defaults them; pass None so the port
    applies the same default.
    """
    return StateSpace(
        D=d.get(f"{prefix}__D"), H=d[f"{prefix}__H"],
        Sigma_eps=d.get(f"{prefix}__Sigma_eps"), C=d.get(f"{prefix}__C"),
        F=d[f"{prefix}__F"], G=d[f"{prefix}__G"],
        Sigma_eta=d.get(f"{prefix}__Sigma_eta"), mu_1=d[f"{prefix}__mu_1"].ravel(),
        Sigma_1=d[f"{prefix}__Sigma_1"],
    )


def _idx(d, key):
    """Zero-based index array from a fixture's `*_py` companion key."""
    return d[key].ravel().astype(int)


@pytest.mark.fixtures
def test_kalman_matches_octave_on_small_system(fixture):
    """2 series, 3 states, 20 periods, one NaN cell. Small enough to debug by
    hand, and the same system Task 0 used to prove the Octave oracle."""
    d = fixture("kalman_small")
    got = kalman_filter(d["Y"], _ssm(d), need_loglik=True)
    assert got.loglik == pytest.approx(float(d["loglik"].item()), rel=1e-10)
    assert np.allclose(got.error, d["prediction__error"], rtol=1e-10, atol=0.0,
                       equal_nan=True)
    assert np.allclose(got.gain, d["prediction__gain"], rtol=1e-10, atol=0.0,
                       equal_nan=True)
    assert np.allclose(got.filter_mu, d["filter__mu"], rtol=1e-10, atol=0.0)
    assert np.allclose(got.filter_sigma, d["filter__Sigma"], rtol=1e-10, atol=0.0)


@pytest.mark.fixtures
def test_kalman_matches_octave_with_an_entirely_missing_period(fixture):
    """A period where every series is NaN. The filter must propagate the state
    through it without updating, and not produce NaNs downstream."""
    d = fixture("kalman_small")
    got = kalman_filter(d["Y_allmiss"], _ssm(d), need_loglik=True)
    assert got.loglik == pytest.approx(float(d["loglik_allmiss"].item()), rel=1e-10)
    assert np.allclose(got.error, d["prediction_allmiss__error"],
                       rtol=1e-10, atol=0.0, equal_nan=True)
    assert np.allclose(got.filter_mu, d["filter_allmiss__mu"], rtol=1e-10, atol=0.0)
    assert np.isfinite(got.filter_mu).all()


@pytest.mark.fixtures
def test_kalman_matches_octave_on_the_us_panel(fixture):
    """73 states, time-varying H and Sigma_eta, ragged edge, 60-period window."""
    d = fixture("kalman_us")
    got = kalman_filter(d["Y"], _ssm(d))
    assert np.allclose(got.error, d["prediction__error"], rtol=1e-10, atol=0.0,
                       equal_nan=True)
    assert np.allclose(got.inv_mse, d["prediction__invMSE"], rtol=1e-10, atol=0.0,
                       equal_nan=True)
    # Relative tolerance is meaningless on this array's near-zero entries: the
    # worst offending cell has |want| ~ 5e-07 against a gain scale of ~4.2, where
    # a 3.8e-16 absolute difference (about one double-precision ulp) reads as
    # 7.8e-10 relative. Floor atol at 1e-12 of the array's own scale, which still
    # fails on any error at 1e-11 of scale or worse. Measured max abs deviation
    # here: 3.0e-13, about 14x inside this floor.
    gain_scale = np.nanmax(np.abs(d["prediction__gain"]))
    assert np.allclose(got.gain, d["prediction__gain"], rtol=1e-10,
                       atol=1e-12 * gain_scale, equal_nan=True)


@pytest.mark.fixtures
def test_transition_matrices_are_indexed_one_period_back(fixture):
    """Guards the t vs t-1 off-by-one: MATLAB indexes C/F/G/Sigma_eta at t-1 and
    H/Sigma_eps at t. Shifting either produces a plausible filtered path that is
    wrong by one month. filter_sub__mu is stored at full length."""
    d = fixture("kalman_us")
    got = kalman_filter(d["Y"], _ssm(d))
    assert np.allclose(got.filter_mu, d["filter_sub__mu"], rtol=1e-10, atol=0.0)


@pytest.mark.fixtures
def test_filter_covariance_matches_at_the_subsampled_periods(fixture):
    """filter.Sigma is 73x73x60 and was stored at 10 periods to hold the fixture
    size cap. sub_t_py brackets both f_active transitions and the ragged edge."""
    d = fixture("kalman_us")
    got = kalman_filter(d["Y"], _ssm(d))
    assert np.allclose(got.filter_sigma[:, :, _idx(d, "sub_t_py")],
                       d["filter_sub__Sigma"], rtol=1e-10, atol=0.0)


@pytest.mark.fixtures
def test_fast_smoother_matches_octave(fixture):
    d = fixture("fast_smoother_us")
    got = fast_smoother(d["Y"], _ssm(d))
    assert np.allclose(got.states, d["states"], rtol=1e-10, atol=0.0)
    assert np.allclose(got.m_errors, d["disturbances__m_errors"], rtol=1e-10, atol=0.0)
    assert np.allclose(got.shocks, d["disturbances__shocks"], rtol=1e-10, atol=0.0)


@pytest.mark.fixtures
def test_smoother_mses_match_at_the_subsampled_periods(fixture):
    d = fixture("fast_smoother_us")
    got = fast_smoother(d["Y"], _ssm(d))
    t = _idx(d, "sub_t_py")
    ts = _idx(d, "sub_t_shocks_py")
    # Relative tolerance is meaningless on this array's near-zero entries: the
    # worst offending cell has |want| ~ 2.4e-07 against a states scale of ~37.6,
    # where a 2.6e-17 absolute difference reads as 1.1e-10 relative. Floor atol
    # at 1e-12 of the array's own scale, which still fails on any error at 1e-11
    # of scale or worse. Measured max abs deviation here: 7.7e-14.
    states_scale = np.nanmax(np.abs(d["MSEs_sub__states"]))
    assert np.allclose(got.mses.states[:, :, t], d["MSEs_sub__states"], rtol=1e-10,
                       atol=1e-12 * states_scale)
    assert np.allclose(got.mses.m_errors[:, :, t], d["MSEs_sub__m_errors"],
                       rtol=1e-10, atol=0.0)
    # Same near-zero-entry issue as states above: worst cell |want| ~ 8.3e-06
    # against a shocks scale of ~8.6, where a 2.9e-15 absolute difference reads
    # as 3.6e-10 relative. Floor atol at 1e-12 of the array's own scale, which
    # still fails on any error at 1e-11 of scale or worse. Measured max abs
    # deviation here: 1.6e-12.
    shocks_scale = np.nanmax(np.abs(d["MSEs_sub__shocks"]))
    assert np.allclose(got.mses.shocks[:, :, ts], d["MSEs_sub__shocks"], rtol=1e-10,
                       atol=1e-12 * shocks_scale)


def test_simulation_smoother_mean_converges_to_the_smoothed_state():
    """Tier 2. Durbin-Koopman draws are centred on the smoothed state, so the
    average of many draws must converge to fast_smoother's output."""
    rng = np.random.default_rng(11)
    n, m, t = 2, 2, 40
    ssm = StateSpace(
        D=np.zeros(n), H=np.eye(n), Sigma_eps=1e-2 * np.eye(n),
        C=np.zeros(m), F=0.7 * np.eye(m), G=np.eye(m), Sigma_eta=np.eye(m),
        mu_1=np.zeros(m), Sigma_1=np.eye(m),
    )
    y = rng.standard_normal((n, t))
    smoothed = fast_smoother(y, ssm).states
    draws = np.array([simulation_smoother(y, ssm, rng)[0] for _ in range(400)])
    assert np.abs(draws.mean(axis=0) - smoothed).max() < 0.15


def test_compute_lrv_recovers_a_known_long_run_variance():
    """AR(1) with rho=0.5, unit shocks: LRV = 1/(1-0.5)^2 = 4."""
    rng = np.random.default_rng(13)
    t = 20000
    y = np.zeros((1, t))
    eps = rng.standard_normal(t)
    for i in range(1, t):
        y[0, i] = 0.5 * y[0, i - 1] + eps[i]
    assert compute_lrv(y, n_lag=4)[0, 0] == pytest.approx(4.0, rel=0.15)


def test_all_six_time_varying_matrices_use_the_matlab_index_split():
    """Tier 2. The Octave fixtures only vary `H` and `Sigma_eta` -- in this model
    `F` and `G` are blkdiag constants, `Sigma_eps` is 1e-4*eye(n) and `C` is
    never set -- so no fixture can catch an off-by-one in `C`, `F`, `G` or
    `Sigma_eps`. This pins all six against a reference recursion with the
    indexing spelled out: transition matrices at t-1, measurement matrices at t
    (Kalman_filter.m:127-149)."""
    rng = np.random.default_rng(5)
    n, m, k, t = 2, 3, 2, 6

    def spd(dim):
        a = rng.standard_normal((dim, dim))
        return a @ a.T + dim * np.eye(dim)

    D = rng.standard_normal((n, t))
    H = rng.standard_normal((n, m, t))
    Sigma_eps = np.stack([spd(n) for _ in range(t)], axis=2)
    C = rng.standard_normal((m, t - 1))
    F = 0.5 * rng.standard_normal((m, m, t - 1))
    G = rng.standard_normal((m, k, t - 1))
    Sigma_eta = np.stack([spd(k) for _ in range(t - 1)], axis=2)
    mu_1, Sigma_1 = rng.standard_normal(m), spd(m)
    y = rng.standard_normal((n, t))

    ssm = StateSpace(D=D, H=H, Sigma_eps=Sigma_eps, C=C, F=F, G=G,
                     Sigma_eta=Sigma_eta, mu_1=mu_1, Sigma_1=Sigma_1)
    got = kalman_filter(y, ssm)

    # Reference recursion. Every index is written out; nothing is shared with
    # the implementation under test.
    z = y - D
    mu, Sigma = mu_1.copy(), (Sigma_1 + Sigma_1.T) / 2
    want = np.zeros((m, t))
    for i in range(t):
        want[:, i] = mu
        H_i, R_i = H[:, :, i], Sigma_eps[:, :, i]           # measurement at i
        gain = Sigma @ H_i.T @ np.linalg.inv(H_i @ Sigma @ H_i.T + R_i)
        mu_upd = mu + gain @ (z[:, i] - H_i @ mu)
        Sigma_upd = Sigma - gain @ H_i @ Sigma
        if i < t - 1:
            C_i, F_i = C[:, i], F[:, :, i]                  # transition at i,
            G_i, Q_i = G[:, :, i], Sigma_eta[:, :, i]       # i.e. MATLAB's t-1
            mu = C_i + F_i @ mu_upd
            Sigma = F_i @ Sigma_upd @ F_i.T + G_i @ Q_i @ G_i.T

    assert np.allclose(got.filter_mu, want, rtol=1e-10)
