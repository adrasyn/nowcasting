"""RBA table retrieval, tested offline against a recorded payload."""

from pathlib import Path

import numpy as np
import pandas as pd

from nyfed.au.fetch_rba import parse_rba_frame

FIXTURES = Path(__file__).parent / "fixtures" / "au"


def test_the_commodity_price_fixture_is_recorded():
    assert (FIXTURES / "rba_I2.csv").is_file()


def test_the_commodity_index_parses_to_a_monthly_float_series():
    frame = pd.read_csv(FIXTURES / "rba_I2.csv", index_col=0, parse_dates=True)
    parsed = parse_rba_frame(frame, column=frame.columns[0])
    assert isinstance(parsed.index, pd.DatetimeIndex)
    assert parsed.index.is_monotonic_increasing
    assert (parsed.index.day == 1).all()
    assert parsed.dtype == np.float64
    gaps = parsed.index.to_series().diff().dt.days.dropna()
    assert 28 <= gaps.median() <= 31


def test_the_fixture_first_column_is_the_a_dollar_all_items_index():
    """Table I2 carries 21 columns -- three currencies each for the all-items
    index and five sub-indices (rural, non-rural, base metals, bulk, and a
    bulk-spot variant). Every one of them parses to a plausible-looking float
    series, so shape alone cannot catch a fixture recorded against the wrong
    column. Pin the RBA series id directly, the same discipline Task 2 applied
    to a mislabelled ABS payload: this asserts the fixture's own header, not
    just that *some* column parses.
    """
    frame = pd.read_csv(FIXTURES / "rba_I2.csv", index_col=0, parse_dates=True)
    assert frame.columns[0] == "GRCPAIAD", (
        "rba_I2.csv's first column is not GRCPAIAD (Commodity prices -- A$, "
        "all items); re-record the fixture or fix the column choice in "
        "fetch_rba.py -- every other column in this table is a different "
        "index or a different currency"
    )
