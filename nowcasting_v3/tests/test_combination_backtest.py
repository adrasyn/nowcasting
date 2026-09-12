"""The combination backtest's arithmetic, on frames small enough to check by eye.

`tools/combination_backtest.py` reads four CSVs and writes a measurement CSV and
the band parameters the emitter publishes. Everything that decides a NUMBER in
those outputs lives in three pure functions -- `pair`, `score`, `bands` -- and
they are what is tested here. The file reading is not: a test that reads the
real 189-Monday backtest would be measuring the measurement.

The rows below are invented. They are chosen so every expected figure can be
worked out on paper, because the point of the exercise is to catch a merge that
silently drops half its rows or a quantile that is computed on the signed error
instead of the absolute one.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from combination_backtest import bands, pair, score  # noqa: E402

# --------------------------------------------------------------------------- #
# Pairing
# --------------------------------------------------------------------------- #


def _v2(rows):
    return pd.DataFrame(rows, columns=["as_of", "target", "v2",
                                       "months_with_data_v2"])


def _v3(rows):
    return pd.DataFrame(rows, columns=["as_of", "target", "v3_raw", "v3",
                                       "months_with_data_v3"])


def test_pair_averages_the_two_models_on_the_shared_mondays():
    """Two Mondays, one quarter: the combination is the mean of the PUBLISHED
    figures, so v3's corrected column and not its raw one."""
    got = pair(_v2([("2026-08-10", "2026Q2", 0.30, 3),
                    ("2026-08-17", "2026Q2", 0.50, 3)]),
               _v3([("2026-08-10", "2026Q2", 0.60, 0.50, 2),
                    ("2026-08-17", "2026Q2", 0.80, 0.70, 2)]))
    assert list(got["as_of"]) == ["2026-08-10", "2026-08-17"]
    assert list(got["combo"]) == pytest.approx([0.40, 0.60])
    assert list(got["v3_raw"]) == pytest.approx([0.60, 0.80])


def test_pair_drops_a_monday_only_one_model_has():
    """Half a combination is one model published under another name."""
    got = pair(_v2([("2026-08-10", "2026Q2", 0.30, 3),
                    ("2026-08-17", "2026Q2", 0.50, 3)]),
               _v3([("2026-08-17", "2026Q2", 0.80, 0.70, 2)]))
    assert list(got["as_of"]) == ["2026-08-17"]


def test_pair_drops_a_monday_where_the_two_models_name_different_quarters():
    """v2 replays a 60-day GDP lag and v3 the ABS's actual release dates, so
    around a print they can disagree about which quarter is current. A pair
    across two different quarters is not a combination of anything."""
    got = pair(_v2([("2026-08-31", "2026Q3", 0.58, 2)]),
               _v3([("2026-08-31", "2026Q2", 0.41, 0.30, 3)]))
    assert got.empty


def test_pair_keeps_both_models_month_counts():
    got = pair(_v2([("2026-08-10", "2026Q3", 0.62, 1)]),
               _v3([("2026-08-10", "2026Q3", 0.48, 0.37, 1)]))
    assert int(got["months_with_data_v2"].iloc[0]) == 1
    assert int(got["months_with_data_v3"].iloc[0]) == 1


def test_pair_min_months_drops_the_data_less_forecasts():
    """The live rule at the next-quarter horizon: v3 declines to record a
    forecast built on no month of data and v2 refuses to make one, so a row
    where either model has none was never published and is not scored."""
    v2 = _v2([("2026-07-27", "2026Q3", 0.62, 0),
              ("2026-08-03", "2026Q3", 0.62, 1),
              ("2026-08-10", "2026Q3", 0.62, 1)])
    v3 = _v3([("2026-07-27", "2026Q3", 0.54, 0.43, 0),
              ("2026-08-03", "2026Q3", 0.39, 0.28, 0),
              ("2026-08-10", "2026Q3", 0.48, 0.37, 1)])
    assert list(pair(v2, v3, min_months=1)["as_of"]) == ["2026-08-10"]
    assert len(pair(v2, v3)) == 3


def test_pair_refuses_a_frame_with_a_missing_column():
    with pytest.raises(ValueError, match="months_with_data_v2"):
        pair(pd.DataFrame({"as_of": ["2026-08-10"], "target": ["2026Q2"],
                           "v2": [0.3]}),
             _v3([("2026-08-10", "2026Q2", 0.6, 0.5, 2)]))


def test_pair_sorts_by_monday_then_quarter():
    got = pair(_v2([("2026-08-17", "2026Q2", 0.5, 3),
                    ("2026-08-10", "2026Q2", 0.3, 3)]),
               _v3([("2026-08-17", "2026Q2", 0.8, 0.7, 2),
                    ("2026-08-10", "2026Q2", 0.6, 0.5, 2)]))
    assert list(got["as_of"]) == ["2026-08-10", "2026-08-17"]


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #


ERRORS = [-0.1, 0.2, -0.3, 0.4]  # mean +0.05, abs mean 0.25, ms 0.075


def test_score_is_bias_mae_rmse_and_n():
    got = score(ERRORS)
    assert got["bias"] == pytest.approx(0.05)
    assert got["mae"] == pytest.approx(0.25)
    assert got["rmse"] == pytest.approx(np.sqrt(0.075), abs=1e-4)
    assert got["n"] == 4


def test_score_ignores_the_rows_with_no_actual():
    """A quarter the ABS has not printed has no error, and a nan would make
    every figure in the table nan rather than making the gap visible."""
    got = score(ERRORS + [np.nan])
    assert got["n"] == 4
    assert got["bias"] == pytest.approx(0.05)


def test_score_of_nothing_is_n_zero_not_a_crash():
    got = score([])
    assert got["n"] == 0 and got["mae"] is None


# --------------------------------------------------------------------------- #
# Bands
# --------------------------------------------------------------------------- #


def test_bands_are_quantiles_of_the_absolute_error():
    """|e| = 0.1, 0.2, 0.3, 0.4. The 68th percentile sits 2.04 steps along the
    sorted four, i.e. 0.3 + 0.04 x 0.1 = 0.304; the 95th at 2.85 steps, 0.385."""
    got = bands(ERRORS)
    assert got["p68"] == pytest.approx(0.304)
    assert got["p95"] == pytest.approx(0.385)
    assert got["n"] == 4
    assert got["mae"] == pytest.approx(0.25)
    assert got["bias"] == pytest.approx(0.05)


def test_bands_are_symmetric_about_the_point_not_about_zero_error():
    """A one-sided error set still gets a band centred on the point: the sign
    of the miss is the bias, which is reported beside the band and not folded
    into it."""
    got = bands([0.2, 0.2, 0.2, 0.2])
    assert got["p68"] == pytest.approx(0.2)
    assert got["bias"] == pytest.approx(0.2)


def test_bands_of_nothing_refuses():
    with pytest.raises(ValueError, match="no errors"):
        bands([])
