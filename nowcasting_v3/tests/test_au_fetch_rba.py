"""RBA table retrieval, tested offline against a recorded payload."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from nyfed.au.fetch_rba import parse_rba_frame
from nyfed.au.sources import AU_SERIES

FIXTURES = Path(__file__).parent / "fixtures" / "au"
RBA_SERIES = [s for s in AU_SERIES if s.fetcher == "rba"]


def _fixture_path(source):
    table = source.locator.split(":")[0]
    return FIXTURES / f"rba_{table}.csv"


def _fixture_frame(source):
    return pd.read_csv(_fixture_path(source), index_col=0, parse_dates=True)


def _parse(source):
    column = source.locator.split(":")[1]
    return parse_rba_frame(_fixture_frame(source), column)


def test_every_rba_series_has_a_recorded_fixture():
    """Same guard as the ABS fixtures: a missing payload must fail, not skip."""
    missing = [s.key for s in RBA_SERIES if not _fixture_path(s).is_file()]
    assert not missing, f"no recorded fixture for {missing}"


@pytest.mark.parametrize("source", RBA_SERIES, ids=lambda s: s.key)
def test_the_fixture_header_carries_the_registry_column(source):
    """The registry names a column; the fixture must actually carry it.

    Table I2 has 21 columns -- three currencies each for the all-items index and
    five sub-indices (rural, non-rural, base metals, bulk, and a bulk-spot
    variant) -- and the committed fixture holds all 21, whole. So be precise
    about which failure this catches and which it does not.

    IT CATCHES a fixture that no longer has the registry's column at all: a
    re-record trimmed to a few columns, a payload taken from the wrong RBA
    table, or a registry locator naming a column that does not exist. Those
    would otherwise surface as a KeyError deep in ``_parse``.

    IT DOES NOT CATCH the registry drifting from ``GRCPAIAD`` to a sibling --
    ``GRCPAISAD``, the bulk-commodities-spot variant, is one character away and
    is in the fixture, so this assertion would pass on it. What catches that is
    ``test_commodity_prices_reproduces_the_published_release``, which pins the
    all-items index against the values RBA published on 4 August 2026; a
    different column parses to an equally plausible float series and misses
    those numbers. The two tests are complementary and neither substitutes for
    the other.
    """
    expected = source.locator.split(":")[1]
    assert expected in _fixture_frame(source).columns, (
        f"{_fixture_path(source).name} has no column {expected!r} (registry "
        f"locator {source.locator!r} for {source.key!r}); re-record the "
        "fixture or fix sources.py"
    )


@pytest.mark.parametrize("source", RBA_SERIES, ids=lambda s: s.key)
def test_the_commodity_index_parses_to_a_monthly_float_series(source):
    parsed = _parse(source)
    assert isinstance(parsed.index, pd.DatetimeIndex)
    assert parsed.index.is_monotonic_increasing
    assert (parsed.index.day == 1).all()
    assert parsed.dtype == np.float64
    gaps = parsed.index.to_series().diff().dt.days.dropna()
    assert 28 <= gaps.median() <= 31


def test_commodity_prices_reproduces_the_published_release():
    """RBA Index of Commodity Prices, July 2026 -- release date 4 August 2026,
    https://www.rba.gov.au/statistics/frequency/commodity-prices/2026/icp-0726.html:
    "In Australian dollar terms, the index increased by 1.2 per cent in
    July... The index has increased by 7.5 per cent in Australian dollar
    terms" (over the year to July 2026).

    Shape, dtype and column-name checks all pass on a fixture that was
    corrupted or silently rescaled under the correct header -- the same
    defect class as Task 2's Important 1 for the ABS fixtures. A published
    movement cannot reproduce from the wrong numbers, so reproduce both the
    monthly and annual change from the fixture's GRCPAIAD column directly.
    Tolerance is 0.05, the precision the RBA release rounds to.
    """
    source = next(s for s in AU_SERIES if s.key == "commodity_prices")
    parsed = _parse(source)
    now = parsed.loc[pd.Timestamp("2026-07-01")]
    prev = parsed.loc[pd.Timestamp("2026-06-01")]
    year_ago = parsed.loc[pd.Timestamp("2025-07-01")]
    mom = (now / prev - 1) * 100
    yoy = (now / year_ago - 1) * 100
    assert mom == pytest.approx(1.2, abs=0.05), "month-on-month change"
    assert yoy == pytest.approx(7.5, abs=0.05), "year-on-year change"


def test_the_parser_accepts_the_period_index_readabs_actually_returns():
    """``read_rba_table`` hands back a ``PeriodIndex``, not a ``DatetimeIndex``.

    The recorded fixture is a CSV, so ``pd.read_csv(parse_dates=True)`` rebuilds
    it as a ``DatetimeIndex`` and every other test in this file exercises a
    shape the live fetcher never sees. Measured against RBA table I2 on
    2026-08-26, ``read_rba_table("I2").index`` is
    ``PeriodIndex(dtype='period[M]')``, and ``pd.DatetimeIndex`` of a
    ``PeriodIndex`` raises ``TypeError: Passing PeriodDtype data is invalid``
    under pandas 2.x -- so ``commodity_prices`` was the one registry entry that
    could not be fetched at all, with the whole offline suite green.

    This is the ABS half's ``_first_of_month_index`` rule applied to the RBA
    half: it is the same normalisation, and Task 2 wrote it for exactly this
    shape.
    """
    frame = _fixture_frame(RBA_SERIES[0])
    live_shape = frame.copy()
    live_shape.index = pd.DatetimeIndex(frame.index).to_period("M")
    assert isinstance(live_shape.index, pd.PeriodIndex)

    parsed = parse_rba_frame(live_shape, RBA_SERIES[0].locator.split(":")[1])
    pd.testing.assert_series_equal(parsed, _parse(RBA_SERIES[0]))
