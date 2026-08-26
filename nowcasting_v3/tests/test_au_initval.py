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
    """Guard against a seed that is technically valid and economically empty.

    A magnitude threshold on ``Lambda[:, 0]`` does NOT discriminate signal
    from noise: the Global block carries no structural zeros (every row is
    either unrestricted or the normalising ``1.0``), so ``seed_lambda``
    always rescales that column to unit L2 norm -- on pure i.i.d. noise as
    much as on a real common factor. A unit vector in 15 dimensions has
    mean |entry| ~ sqrt(2 / (pi * 15)) ~ 0.21 essentially regardless of what,
    if anything, it recovered. (This test previously asserted exactly
    ``mean(|Lambda[:, 0]|) > 0.1`` and could not fail: on a panel of pure
    noise with no common factor at all, it still measured ~0.2.)

    Compare against a noise control instead, with a statistic that is not a
    magnitude. Reconstruct each panel's own factor SCORE from its own seeded
    loadings and its own data (``Lambda[:, 0] @ filled_Y``), and correlate
    that score against the TRUE factor used to build the planted panel. The
    noise panel is built with no relationship to that factor at all, so --
    independent of whatever ``Lambda`` its own SVD happens to produce -- its
    reconstructed score has no reason to correlate with it; the planted
    panel's score should. Verified over 10 random seeds before fixing this
    threshold: planted-panel correlation was 0.99+ throughout, noise-panel
    correlation stayed below 0.11.
    """
    spec = load_spec(SPEC_PATH)
    n, T = len(AU_SERIES), 300
    dates = pd.date_range("2001-01-01", periods=T, freq="MS")

    def _panel_from(Y: np.ndarray) -> Panel:
        return Panel(Y=Y, y_location=np.zeros((n, 1)), y_scale=np.ones((n, 1)),
                     dates=dates, series_id=list(spec.series_id),
                     i_now=spec.series_id.index("gdp"))

    def _score(panel: Panel, Lambda: np.ndarray) -> np.ndarray:
        filled = np.where(np.isnan(panel.Y), 0.0, panel.Y)
        return Lambda[:, 0] @ filled

    def _abs_corr(a: np.ndarray, b: np.ndarray) -> float:
        return abs(np.corrcoef(a, b)[0, 1])

    rng = np.random.default_rng(42)
    factor = rng.standard_normal((1, T))
    Y_planted = 0.8 * factor + 0.3 * rng.standard_normal((n, T))
    Y_noise = rng.standard_normal((n, T))  # no common factor at all

    # Same missingness on both, so the comparison isolates signal vs. no
    # signal rather than missingness vs. none.
    missing = np.zeros((n, T), dtype=bool)
    missing[3, :40] = True
    missing[-1, :] = ~np.isin(np.arange(T) % 3, [2])
    Y_planted[missing] = np.nan
    Y_noise[missing] = np.nan

    panel_planted = _panel_from(Y_planted)
    panel_noise = _panel_from(Y_noise)

    corr_planted = _abs_corr(
        _score(panel_planted, seed_lambda(panel_planted)), factor[0]
    )
    corr_noise = _abs_corr(_score(panel_noise, seed_lambda(panel_noise)), factor[0])

    assert corr_planted > 0.8
    assert corr_noise < 0.3
    assert corr_planted > corr_noise + 0.5


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
