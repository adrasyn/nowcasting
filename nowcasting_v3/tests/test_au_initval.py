"""PCA seeding of the initial loading matrix."""

import numpy as np
import pandas as pd
import pytest

from nyfed.au.initval import seed_lambda
from nyfed.au.panel import Panel
from nyfed.au.sources import AU_SERIES, SPEC_PATH
from nyfed.spec import load_spec

RNG = np.random.default_rng(0)


def _panel(T: int = 300) -> Panel:
    n = len(AU_SERIES)
    spec = load_spec(SPEC_PATH)
    factor = RNG.standard_normal((1, T))
    Y = 0.8 * factor + 0.3 * RNG.standard_normal((n, T))
    Y[3, :40] = np.nan          # a late-starting series
    Y[-1, ~np.isin(np.arange(T) % 3, [2])] = np.nan   # a quarterly series
    dates = pd.date_range("2001-01-01", periods=T, freq="MS")
    return Panel(Y=Y, y_location=np.zeros((n, 1)), y_scale=np.ones((n, 1)),
                 dates=dates, series_id=list(spec.series_id),
                 i_now=spec.series_id.index("gdp"))


def test_seed_has_the_right_shape_and_no_nan():
    spec = load_spec(SPEC_PATH)
    Lambda = seed_lambda(_panel())
    # The panel is 15 series (`retail_sales` and `vacancy_index` were dropped
    # from the registry), over 5 factors -- derive both from the spec rather
    # than hard-coding numbers that would go stale the next time a series is
    # added or dropped.
    assert Lambda.shape == spec.blocks.shape
    assert Lambda.shape == (len(AU_SERIES), 5)
    assert np.isfinite(Lambda).all()


def test_zero_loadings_stay_exactly_zero():
    """The spec's zeros are structural. A PCA seed that fills them would give
    the sampler a starting point the model cannot represent."""
    spec = load_spec(SPEC_PATH)
    Lambda = seed_lambda(_panel())
    structural_zeros = spec.blocks == 0
    assert structural_zeros.any()  # the guard below is vacuous if this fails
    assert (Lambda[structural_zeros] == 0.0).all()


def test_the_seed_recovers_a_planted_factor():
    """Guard against a seed that is technically valid and economically empty:
    if every series is driven by one factor, the global loadings should not be
    a scatter of near-zeros."""
    Lambda = seed_lambda(_panel())
    assert np.abs(Lambda[:, 0]).mean() > 0.1


def test_missing_data_does_not_produce_nan_loadings():
    panel = _panel()
    panel.Y[5, :] = np.nan          # a series with no observations at all
    Lambda = seed_lambda(panel)
    assert np.isfinite(Lambda).all()


def test_all_nan_row_is_seeded_at_zero_not_dropped_from_the_shape():
    """A row with no observations gets a zero loading, not an omitted one --
    the output must stay (n, n_f) so downstream code never has to special-case
    a missing series."""
    panel = _panel()
    panel.Y[5, :] = np.nan
    spec = load_spec(SPEC_PATH)
    Lambda = seed_lambda(panel)
    assert Lambda.shape == spec.blocks.shape
    assert (Lambda[5, :] == 0.0).all()
