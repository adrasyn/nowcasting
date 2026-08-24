"""Guard the Octave-generated fixture set.

Every Tier 1 exactness test in this port compares a Python result against one of
these fixtures. If a fixture is missing an input or an output, the test that
uses it silently narrows instead of failing, so this module asserts that each
fixture exists and still carries the keys later tasks depend on.

Regenerate with:
    cd nowcasting_v3/tools && octave gen_fixtures.m && ../.venv/bin/python matload.py
"""

from pathlib import Path

import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"

# Fixtures must stay small enough to commit: CI has no Octave and cannot
# regenerate them, so they are test inputs rather than build output.
MAX_TOTAL_MIB = 5.0

# Keys each fixture must carry. Not exhaustive - these are the inputs and
# outputs a later task cannot do its job without.
REQUIRED = {
    "kalman_small": [
        "Y", "SSM__D", "SSM__H", "SSM__Sigma_eps", "SSM__C", "SSM__F", "SSM__G",
        "SSM__Sigma_eta", "SSM__mu_1", "SSM__Sigma_1",
        "loglik", "prediction__error", "prediction__invMSE", "prediction__gain",
        "filter__mu", "filter__Sigma",
        "disturbances__m_errors", "disturbances__shocks", "states",
        "MSEs__m_errors", "MSEs__shocks", "MSEs__states",
        # same system with one entirely missing period
        "Y_allmiss", "loglik_allmiss", "prediction_allmiss__error",
        "filter_allmiss__mu", "states_allmiss",
    ],
    "kalman_us": [
        "Y", "SSM__D", "SSM__H", "SSM__Sigma_eps", "SSM__F", "SSM__G",
        "SSM__Sigma_eta", "SSM__mu_1", "SSM__Sigma_1",
        "loglik", "prediction__error", "prediction__invMSE", "prediction__gain",
        "filter_sub__mu", "filter_sub__Sigma", "sub_t", "sub_t_py",
        "window_start", "window_start_py", "window_len", "T_full",
    ],
    "fast_smoother_us": [
        "Y", "SSM__D", "SSM__H", "SSM__Sigma_eps", "SSM__F", "SSM__G",
        "SSM__Sigma_eta", "SSM__mu_1", "SSM__Sigma_1",
        "disturbances__m_errors", "disturbances__shocks", "states",
        "MSEs_sub__m_errors", "MSEs_sub__shocks", "MSEs_sub__states",
        "sub_t", "sub_t_py", "sub_t_shocks", "sub_t_shocks_py",
        "window_start", "window_start_py", "window_len", "T_full",
    ],
    "construct_ssm_us": [
        "dimvec", "param_vec",
        "param__mu", "param__gamma_g", "param__Lambda", "param__Phi",
        "param__gamma_f", "param__pi_f", "param__phi", "param__gamma_e",
        "param__pi_e",
        "latent__sigma", "latent__s",
        "restrict__Lambda", "restrict__Phi", "restrict__iota",
        "restrict__isquart", "restrict__f_active",
        "SSM__D", "SSM__H", "SSM__Sigma_eps", "SSM__F", "SSM__G",
        "SSM__Sigma_eta", "SSM__mu_1", "SSM__Sigma_1",
        "window_start", "window_start_py", "window_len", "T_full", "i_now",
    ],
    "construct_prior_us": [
        "dimvec", "m_Lambda",
        "prior__m_mu", "prior__P_mu", "prior__nu_g", "prior__s2_g",
        "prior__m_Lambda", "prior__P_Lambda", "prior__m_Phi", "prior__P_Phi",
        "prior__nu_f", "prior__s2_f", "prior__a_f", "prior__b_f",
        "prior__m_phi", "prior__P_phi", "prior__nu_e", "prior__s2_e",
        "prior__a_e", "prior__b_e",
    ],
    "update_scl": ["x", "x_miss", "vals", "probs", "posteriors", "posteriors_miss"],
    "update_vol_cond": [
        "x", "x_miss", "sigma_in", "gamma", "utmp", "mean_prior", "var_prior",
        "weights", "posteriors", "mean_t", "vars_t", "y_t",
        "x1_KF", "p1_KF", "x2_KF", "p2_KF", "ln_sigmasq", "sigma_out",
        "weights_miss", "posteriors_miss", "y_t_miss", "x1_KF_miss",
        "p1_KF_miss", "ln_sigmasq_miss", "sigma_out_miss",
    ],
    "published_nowcasts": [
        "published__2023_09_29", "published__2023_10_06",
        "news_2023_09_29__forecast", "news_2023_09_29__actual",
        "news_2023_09_29__weight", "news_2023_09_29__impact",
        "news_2023_09_29__series_name", "news_2023_09_29__series_index",
        "news_2023_10_06__forecast", "news_2023_10_06__actual",
        "news_2023_10_06__weight", "news_2023_10_06__impact",
        "news_2023_10_06__series_name", "news_2023_10_06__series_index",
    ],
    "nowcast_us": [
        "Y_old", "Y_new", "i_now", "t_now", "t_now_py",
        "SSM_old__D", "SSM_old__H", "SSM_old__Sigma_eps", "SSM_old__F",
        "SSM_old__G", "SSM_old__Sigma_eta", "SSM_old__mu_1", "SSM_old__Sigma_1",
        "SSM_new__D", "SSM_new__H", "SSM_new__Sigma_eps", "SSM_new__F",
        "SSM_new__G", "SSM_new__Sigma_eta", "SSM_new__mu_1", "SSM_new__Sigma_1",
        "nowcast", "forecasts", "news", "weights",
        # enough to rebuild both SSMs from scratch
        "dimvec", "param_vec_old", "param_vec_new",
        "latent_old__sigma", "latent_old__s", "latent_new__sigma", "latent_new__s",
        "restrict__Lambda", "restrict__Phi", "restrict__iota",
        "restrict__isquart", "restrict__f_active",
        "Y_location", "Y_scale",
        "window_start", "window_start_py", "window_len", "T_full",
    ],
    "nowcast_us_1006": [
        "Y_old", "Y_new", "i_now", "t_now", "t_now_py",
        "SSM_old__D", "SSM_old__H", "SSM_old__Sigma_eps", "SSM_old__F",
        "SSM_old__G", "SSM_old__Sigma_eta", "SSM_old__mu_1", "SSM_old__Sigma_1",
        "SSM_new__D", "SSM_new__H", "SSM_new__Sigma_eps", "SSM_new__F",
        "SSM_new__G", "SSM_new__Sigma_eta", "SSM_new__mu_1", "SSM_new__Sigma_1",
        "nowcast", "forecasts", "news", "weights",
        # enough to rebuild both SSMs from scratch
        "dimvec", "param_vec_old", "param_vec_new",
        "latent_old__sigma", "latent_old__s", "latent_new__sigma", "latent_new__s",
        "restrict__Lambda", "restrict__Phi", "restrict__iota",
        "restrict__isquart", "restrict__f_active",
        "Y_location", "Y_scale",
        "window_start", "window_start_py", "window_len", "T_full",
    ],
}

EXPECTED = list(REQUIRED)


@pytest.mark.parametrize("name", EXPECTED)
def test_fixture_loads_and_is_non_empty(fixture, name):
    data = fixture(name)
    assert data, f"fixture {name} is empty"


@pytest.mark.parametrize("name", EXPECTED)
def test_fixture_has_required_keys(fixture, name):
    data = fixture(name)
    missing = [key for key in REQUIRED[name] if key not in data]
    assert not missing, f"fixture {name} is missing {missing}"


@pytest.mark.parametrize("name", EXPECTED)
def test_fixture_arrays_are_finite_where_expected(fixture, name):
    """No fixture array may be all-NaN; that is the signature of a bad capture."""
    import numpy as np

    data = fixture(name)
    for key, array in data.items():
        if array.size and np.issubdtype(array.dtype, np.floating):
            assert not np.isnan(array).all(), f"{name}.{key} is entirely NaN"


def test_fixture_directory_is_small_enough_to_commit():
    if not FIXTURE_DIR.exists():
        pytest.skip("fixtures absent - run tools/gen_fixtures.m")
    total = sum(p.stat().st_size for p in FIXTURE_DIR.glob("*.npz"))
    mib = total / 1024 / 1024
    assert mib < MAX_TOTAL_MIB, f"fixtures are {mib:.2f} MiB, budget is {MAX_TOTAL_MIB} MiB"


# The NY Fed's published 2023 Q4 nowcasts, annualised QoQ. These are the Task 9
# gate targets and are read out of nyfed_matlab/output/Update_*.mat by
# tools/extract_published.py; see its header for why that takes byte-level work.
PUBLISHED = {
    "published__2023_09_29": 2.0241866715115893,
    "published__2023_10_06": 2.3834662755905036,
}


@pytest.mark.parametrize("key,value", sorted(PUBLISHED.items()))
def test_published_nowcast_scalars(fixture, key, value):
    data = fixture("published_nowcasts")
    assert data[key].item() == value


@pytest.mark.parametrize("vintage,n", [("2023_09_29", 9), ("2023_10_06", 7)])
def test_published_news_table_is_internally_consistent(fixture, vintage, n):
    """example_nowcast.m computes impacts = (actual - forecasts) .* weights.

    The identity must hold to the bit. It is what proves the news table was read
    out of the MCOS subsystem correctly rather than plausibly.
    """
    import numpy as np

    data = fixture("published_nowcasts")
    forecast = data[f"news_{vintage}__forecast"]
    actual = data[f"news_{vintage}__actual"]
    weight = data[f"news_{vintage}__weight"]
    impact = data[f"news_{vintage}__impact"]
    names = data[f"news_{vintage}__series_name"]
    index = data[f"news_{vintage}__series_index"]

    assert forecast.shape == (n,)
    assert {actual.shape, weight.shape, impact.shape, names.shape, index.shape} == {(n,)}
    assert np.array_equal(impact, (actual - forecast) * weight)
    assert len(set(names.tolist())) == n, "row names must be unique, as MATLAB tables require"
    assert set(index.tolist()) <= set(range(1, 32))
