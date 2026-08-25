"""Task 8: point nowcast, density nowcast and the news decomposition.

The ``nowcast_us`` fixture is an exact Octave oracle for every deterministic
output here, so `point_nowcast` and `news_table` are Tier 1 (`rtol=1e-10`) and
only `density_nowcast`, whose output is a draw, is Tier 2.

Index convention: the fixture carries both 1-based MATLAB indices (`i_now`,
`t_now`) and pre-converted 0-based companions (`t_now_py`). `i_now` has no
companion, so every index here is read from the 1-based key and converted with
an explicit `- 1`, rather than mixing the two families.
"""

from pathlib import Path

import numpy as np
import pytest

from nyfed.nowcast import density_nowcast, news_table, point_nowcast
from nyfed.spec import load_spec
from nyfed.ssm import StateSpace

SPEC_PATH = Path(__file__).parents[1] / "nyfed_matlab" / "model_spec_FRED.csv"


def _ssm(d, prefix="SSM"):
    """Rebuild a StateSpace from a fixture's flattened `prefix__field` keys."""
    return StateSpace(
        D=d.get(f"{prefix}__D"), H=d[f"{prefix}__H"],
        Sigma_eps=d.get(f"{prefix}__Sigma_eps"), C=d.get(f"{prefix}__C"),
        F=d[f"{prefix}__F"], G=d[f"{prefix}__G"],
        Sigma_eta=d.get(f"{prefix}__Sigma_eta"), mu_1=d[f"{prefix}__mu_1"].ravel(),
        Sigma_1=d[f"{prefix}__Sigma_1"],
    )


def _spec():
    return load_spec(SPEC_PATH)


def _point(d):
    """point_nowcast on the fixture's inputs, indices converted to 0-based."""
    return point_nowcast(d["Y_old"], d["Y_new"], _ssm(d, "SSM_old"),
                         _ssm(d, "SSM_new"), int(d["i_now"].item()) - 1,
                         d["t_now"].ravel().astype(int) - 1)


@pytest.mark.fixtures
@pytest.mark.parametrize("name", ["nowcast_us", "nowcast_us_1006"])
def test_point_nowcast_matches_octave(fixture, name):
    """Both published vintages. The second has a different release pattern -
    7 cells, non-monotone in series index - so it exercises the column-major
    enumeration the first one cannot.

    `atol=0.0` throughout: np.allclose defaults atol to 1e-8, which would
    dominate rtol on quantities this size and quietly loosen the Tier 1
    tolerance by three orders of magnitude.
    """
    d = fixture(name)
    got = _point(d)
    assert np.allclose(got.nowcast, d["nowcast"], rtol=1e-10, atol=0.0)
    assert np.allclose(got.forecasts, d["forecasts"], rtol=1e-10, atol=0.0,
                       equal_nan=True)
    assert np.allclose(got.news, d["news"], rtol=1e-10, atol=0.0, equal_nan=True)
    assert np.allclose(got.weights, d["weights"], rtol=1e-10, atol=0.0,
                       equal_nan=True)


@pytest.mark.fixtures
def test_impacts_and_revisions_sum_to_the_nowcast_change(fixture):
    """The decomposition identity: last week's nowcast + parameter revision
    + data revision + sum of release impacts = this week's nowcast."""
    d = fixture("nowcast_us")
    got = _point(d)
    released = ~np.isnan(got.news)
    impacts = got.news * got.weights[:, :, 0]
    total = (got.nowcast[1, 0] - got.nowcast[0, 0]) \
        + (got.nowcast[2, 0] - got.nowcast[1, 0]) \
        + np.nansum(impacts[released])
    assert total == pytest.approx(got.nowcast[3, 0] - got.nowcast[0, 0], abs=1e-8)


@pytest.mark.fixtures
def test_series_with_no_release_has_no_impact(fixture):
    d = fixture("nowcast_us")
    got = _point(d)
    unchanged = np.isnan(d["Y_new"]) | (d["Y_new"] == d["Y_old"])
    assert np.isnan(got.news[unchanged]).all()


@pytest.mark.fixtures
def test_revised_cells_are_not_treated_as_news(fixture):
    """A cell present in both vintages is a revision, not a release.

    `point_nowcast.m` routes revisions through the row-3-minus-row-2 term and
    leaves `news` NaN there. A port that wrote news entries for revised cells
    would still satisfy the decomposition identity above - the weights would
    absorb it - but would put phantom rows in the site's release-impact table.
    """
    d = fixture("nowcast_us")
    got = _point(d)
    revised = ~np.isnan(d["Y_old"]) & ~np.isnan(d["Y_new"]) \
        & (d["Y_new"] != d["Y_old"])
    assert revised.sum() > 0, "fixture carries no revisions; test proves nothing"
    assert np.isnan(got.news[revised]).all()
    assert np.isnan(got.weights[revised]).all()
    # Revisions still move the nowcast, through row 3 - row 2.
    assert got.nowcast[2, 0] != got.nowcast[1, 0]


@pytest.mark.fixtures
def test_news_table_columns_and_ordering(fixture):
    d = fixture("nowcast_us")
    got = _point(d)
    table = news_table(got, _spec(), d["Y_location"], d["Y_scale"])
    assert list(table.columns) == ["series_id", "series_name", "forecast",
                                   "actual", "weight", "impact"]
    assert table["impact"].abs().is_monotonic_decreasing


@pytest.mark.fixtures
def test_news_table_rows_are_the_releases_in_original_units(fixture):
    """One row per newly released cell, named from the spec and de-standardised
    the way example_nowcast.m de-standardises it."""
    d = fixture("nowcast_us")
    got = _point(d)
    spec = _spec()
    table = news_table(got, spec, d["Y_location"], d["Y_scale"])

    released = ~np.isnan(d["news"])
    rows, _ = np.nonzero(released)
    assert len(table) == rows.size

    assert sorted(table["series_id"]) == sorted(np.array(spec.series_id)[rows])
    assert sorted(table["series_name"]) == sorted(np.array(spec.series_name)[rows])

    # `actual` is the raw new-vintage datum, de-standardised.
    raw = d["Y_location"] + d["Y_scale"] * d["Y_new"]
    assert np.allclose(np.sort(table["actual"].to_numpy()),
                       np.sort(raw[released]), rtol=1e-10)

    # impact = (actual - forecast) * weight, as example_nowcast.m computes it.
    assert np.allclose(table["impact"].to_numpy(),
                       (table["actual"] - table["forecast"]).to_numpy()
                       * table["weight"].to_numpy(), rtol=1e-10)


@pytest.mark.fixtures
def test_news_table_impacts_sum_to_the_release_contribution(fixture):
    """The table is what the site displays, so its impacts must add up to the
    same release contribution the standardised decomposition gives, in
    percentage points of the nowcast series."""
    d = fixture("nowcast_us")
    got = _point(d)
    table = news_table(got, _spec(), d["Y_location"], d["Y_scale"])
    scale = d["Y_scale"].ravel()[int(d["i_now"].item()) - 1]
    expected = scale * (got.nowcast[3, 0] - got.nowcast[2, 0])
    assert table["impact"].sum() == pytest.approx(expected, abs=1e-8)


@pytest.mark.fixtures
def test_density_nowcast_is_centred_on_the_point_nowcast(fixture):
    """Tier 2: many density draws must average to the point estimate.

    The tolerance is stated as a multiple of the Monte Carlo standard error
    measured from the draws themselves, not as a fixed number that happens to
    hold for one seed.
    """
    d = fixture("nowcast_us")
    rng = np.random.default_rng(41)
    t_now = d["t_now"].ravel().astype(int) - 1
    point = _point(d)
    draws = np.array([density_nowcast(d["Y_new"], _ssm(d, "SSM_new"),
                                      int(d["i_now"].item()) - 1, t_now, rng)
                      for _ in range(500)])
    assert draws.shape == (500, len(t_now))
    for i_t in range(len(t_now)):
        mc_se = draws[:, i_t].std(ddof=1) / np.sqrt(draws.shape[0])
        assert draws[:, i_t].mean() == pytest.approx(point.nowcast[3, i_t],
                                                     abs=4.0 * mc_se)


@pytest.mark.fixtures
def test_density_draws_are_not_degenerate(fixture):
    """A smoother that returned its conditional mean would pass the centring
    test and carry no uncertainty at all."""
    d = fixture("nowcast_us")
    rng = np.random.default_rng(7)
    t_now = d["t_now"].ravel().astype(int) - 1
    draws = np.array([density_nowcast(d["Y_new"], _ssm(d, "SSM_new"),
                                      int(d["i_now"].item()) - 1, t_now, rng)
                      for _ in range(50)])
    assert (draws.std(axis=0) > 0).all()
