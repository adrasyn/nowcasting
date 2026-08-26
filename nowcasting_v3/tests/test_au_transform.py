"""The spec's Transformation column, applied.

The NY Fed ships pre-transformed data; we build the pipeline they did not. Without
this the panel reaches the engine as levels where the spec declares growth rates,
and the model runs anyway.
"""

import numpy as np
import pandas as pd
import pytest

from nyfed.au.sources import SPEC_PATH
from nyfed.au.transform import transform_panel
from nyfed.spec import load_spec

DATES = pd.date_range("2020-01-01", periods=24, freq="MS")


def _spec():
    return load_spec(SPEC_PATH)


def test_lin_is_left_untouched():
    spec = _spec()
    i = spec.transformation.index("lin")
    raw = np.full((len(spec.series_id), 24), np.nan)
    raw[i] = np.arange(24, dtype=float)
    out = transform_panel(raw, spec, DATES)
    assert np.array_equal(out[i], raw[i], equal_nan=True)


def test_pch_is_a_ratio_not_a_log_difference():
    """imports enters the panel NEGATIVE by ABS's debit convention. A log
    difference would make it all-NaN with no error raised.

    Finiteness alone is too weak to pin this: ``100 * (|x_t| / |x_{t-k}| - 1)``
    is finite everywhere here and would report a rising debit as a rising
    number, so the first two cells are checked by VALUE. Under the debit
    convention a debit growing from -100 to -110 is imports up 10 per cent, and
    -110 to -99 is imports down 10 per cent; the signs are the assertion.
    """
    spec = _spec()
    i = spec.series_id.index("imports")
    assert spec.transformation[i] == "pch"
    raw = np.full((len(spec.series_id), 24), np.nan)
    raw[i] = -np.linspace(100.0, 200.0, 24)
    raw[i, :3] = [-100.0, -110.0, -99.0]     # a debit that grows, then shrinks
    out = transform_panel(raw, spec, DATES)
    assert np.isfinite(out[i, 1:]).all(), "negative series became NaN -- log transform?"
    assert out[i, 1] == pytest.approx(10.0, abs=1e-12)
    assert out[i, 2] == pytest.approx(-10.0, abs=1e-12)


def test_monthly_pch_steps_back_one_month():
    spec = _spec()
    i = spec.series_id.index("cpi")
    raw = np.full((len(spec.series_id), 24), np.nan)
    raw[i] = 100.0 * (1.01 ** np.arange(24))
    out = transform_panel(raw, spec, DATES)
    assert out[i, 1:] == pytest.approx(1.0, abs=1e-9)
    assert np.isnan(out[i, 0]), "the first observation has no predecessor"


def test_quarterly_pca_steps_back_three_months_and_annualises_by_four():
    """GDP is observed in months 3, 6, 9, 12 only. Stepping back one month
    would compare it to an empty cell; annualising by 12 would report a
    quarterly rate as a monthly one. Both produce plausible numbers."""
    spec = _spec()
    i = spec.series_id.index("gdp")
    assert spec.transformation[i] == "pca"
    raw = np.full((len(spec.series_id), 24), np.nan)
    quarter_ends = [m for m, d in enumerate(DATES) if d.month in (3, 6, 9, 12)]
    for step, m in enumerate(quarter_ends):
        raw[i, m] = 1000.0 * (1.01 ** step)      # 1% per quarter
    out = transform_panel(raw, spec, DATES)
    expected = 100.0 * (1.01 ** 4 - 1)           # ~4.06% annualised
    got = out[i, quarter_ends[1:]]
    assert got == pytest.approx(expected, abs=1e-9)
    assert np.isnan(out[i, quarter_ends[0]]), "the first quarter has no predecessor"


def test_transformed_values_land_where_the_observations_are():
    """A quarterly transform must not write into the two empty months."""
    spec = _spec()
    i = spec.series_id.index("gdp")
    raw = np.full((len(spec.series_id), 24), np.nan)
    quarter_ends = [m for m, d in enumerate(DATES) if d.month in (3, 6, 9, 12)]
    for step, m in enumerate(quarter_ends):
        raw[i, m] = 1000.0 + step
    out = transform_panel(raw, spec, DATES)
    non_quarter = [m for m in range(24) if m not in quarter_ends]
    assert np.isnan(out[i, non_quarter]).all()


def test_chg_is_a_first_difference():
    spec = _spec()
    i = spec.series_id.index("employment")
    assert spec.transformation[i] == "chg"
    raw = np.full((len(spec.series_id), 24), np.nan)
    raw[i] = np.arange(24, dtype=float) * 5.0
    out = transform_panel(raw, spec, DATES)
    assert out[i, 1:] == pytest.approx(5.0, abs=1e-12)


def test_every_spec_transformation_code_is_handled():
    """An unrecognised code must raise, not pass the series through untouched.
    Silently returning levels for a code nobody implemented is the failure this
    whole task exists to fix."""
    spec = _spec()
    assert set(spec.transformation) <= {"lin", "chg", "pch", "pca"}


def test_an_unrecognised_transformation_raises_rather_than_returning_levels():
    """The subset assertion above pins today's spec; this pins the behaviour
    when someone adds a code tomorrow. An untransformed level standardises
    cleanly and the model runs on it without complaint, so falling through is
    the one outcome that must be impossible."""
    spec = _spec()
    spec.transformation[0] = "cca"
    raw = np.zeros((len(spec.series_id), 24))
    with pytest.raises(ValueError, match="not implemented"):
        transform_panel(raw, spec, DATES)


def test_an_unrecognised_frequency_raises_rather_than_assuming_monthly():
    """The lag to the previous observation and the annualisation exponent both
    come from the frequency. Defaulting an unknown one to monthly would
    annualise it by 12 and produce a plausible number."""
    spec = _spec()
    spec.frequency[-1] = "sa"
    raw = np.zeros((len(spec.series_id), 24))
    with pytest.raises(ValueError, match="no lag is known"):
        transform_panel(raw, spec, DATES)


def test_a_grid_that_is_not_consecutive_months_is_refused():
    """A quarterly step of 3 columns means 'one quarter' only on a monthly
    grid."""
    spec = _spec()
    raw = np.zeros((len(spec.series_id), 24))
    with pytest.raises(ValueError, match="consecutive month starts"):
        transform_panel(raw, spec, pd.date_range("2020-01-01", periods=24, freq="QS"))
