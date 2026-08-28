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
    # The panel is 14 series (`retail_sales`, `vacancy_index` and `cpi_trimmed`
    # were dropped from the registry), over 5 factors -- derive both from the
    # spec rather than hard-coding numbers that would go stale the next time a
    # series is added or dropped.
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


def _normalisers(spec) -> list[tuple[int, int]]:
    """``(row, column)`` of every block's normalising loading.

    ``load_spec`` turns the spec's ``100`` entries into ``1.0`` and its ``1``
    entries into ``NaN``, so a finite non-zero entry is exactly a normaliser.
    The Soft block has none -- no series carries ``100`` in ``Block1_Soft`` --
    and a block without one has no sign to be consistent with.
    """
    rows, cols = np.nonzero(np.nan_to_num(spec.blocks) == 1.0)
    return list(zip(rows.tolist(), cols.tolist(), strict=True))


def test_the_seed_agrees_in_sign_with_each_block_s_normalising_series():
    """A principal component's sign is arbitrary; the spec's normalisation is not.

    ``model_spec_AU.csv`` fixes household spending's Global loading, employment's
    Labor and COVID loadings and CPI's Nominal loading at ``+1``, which DEFINES
    each of those factors to move with that series. ``np.linalg.svd`` returns
    either sign of a component with equal right, so a seed that does not orient
    itself contradicts that definition roughly half the time -- and the
    contradiction is not cosmetic. The seed is the prior MEAN for every free
    loading in the column (``construct_prior`` centres ``m_Lambda`` there with
    precision 10, i.e. a prior standard deviation near 0.32), so a flipped
    column pulls every other series in the block toward the wrong sign while the
    normaliser stays pinned at +1.

    Measured on the real panel before this was fixed (the 15-series panel of the
    time, which still carried `cpi_trimmed`): the Global column's seed was
    negative for 12 of 15 series INCLUDING its normaliser, and GDP's Global
    loading was still -0.76 after 3,000 sweeps -- i.e. real GDP growth loading
    the broadest factor with the opposite sign to real consumption growth, on a
    panel where the two correlate +0.12.

    Twenty independent panels, because one panel only samples the coin once.
    """
    spec = load_spec(SPEC_PATH)
    pairs = _normalisers(spec)
    assert pairs, "no block carries a normalising loading; the test is vacuous"

    wrong = []
    for seed in range(20):
        rng = np.random.default_rng(1000 + seed)
        n, T = len(AU_SERIES), 240
        factor = rng.standard_normal((1, T))
        Y = 0.8 * factor + 0.3 * rng.standard_normal((n, T))
        dates = pd.date_range("2001-01-01", periods=T, freq="MS")
        panel = Panel(Y=Y, y_location=np.zeros((n, 1)), y_scale=np.ones((n, 1)),
                      dates=dates, series_id=list(spec.series_id),
                      i_now=spec.series_id.index("gdp"))
        Lambda = seed_lambda(panel)
        for row, col in pairs:
            if Lambda[row, col] < 0.0:
                wrong.append((seed, spec.series_id[row], spec.block_names[col],
                              float(Lambda[row, col])))
    assert not wrong, (
        f"{len(wrong)} of {20 * len(pairs)} normalising loadings were seeded "
        f"against their own normalisation, e.g. {wrong[:3]}"
    )
