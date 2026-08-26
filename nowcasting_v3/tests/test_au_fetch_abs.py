"""ABS retrieval, tested offline against recorded payloads.

No test here touches the network. The fetcher is split so the parsing half is
pure: `parse_abs_frame` takes the frame readabs would have returned.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from nyfed.au.fetch_abs import parse_abs_frame
from nyfed.au.sources import AU_SERIES, SeriesSource

FIXTURES = Path(__file__).parent / "fixtures" / "au"
ABS_SERIES = [s for s in AU_SERIES if s.fetcher == "abs"]
QUARTERLY = [s for s in ABS_SERIES if s.frequency == "q"]

# readabs returns a PeriodIndex, and `tools/record_au_fixtures.py` writes it out
# verbatim: "2026-07" for a monthly series, "2026Q1" for a quarterly one. Rebuild
# that index here rather than pre-converting it at recording time, so the fixture
# exercises `parse_abs_frame` on the exact shape the real fetch produces. Reading
# "2026Q1" back with `parse_dates=True` sends pandas down its dateutil fallback,
# which emits a UserWarning -- fatal under `filterwarnings = ["error"]`.
_PERIOD_FREQ = {"m": "M", "q": "Q-DEC"}


def _fixture_frame(source: SeriesSource) -> pd.DataFrame:
    frame = pd.read_csv(FIXTURES / f"abs_{source.key}.csv", index_col=0)
    frame.index = pd.PeriodIndex(
        frame.index.astype(str), freq=_PERIOD_FREQ[source.frequency]
    )
    return frame


def _parse(source: SeriesSource) -> pd.Series:
    return parse_abs_frame(_fixture_frame(source), source.locator.split(":")[1])


def test_every_abs_series_has_a_recorded_fixture():
    """Same guard as the US fixtures: a missing payload must fail, not skip."""
    missing = [s.key for s in ABS_SERIES if not (FIXTURES / f"abs_{s.key}.csv").is_file()]
    assert not missing, f"no recorded fixture for {missing}"


def test_no_locator_is_left_unresolved():
    unresolved = [s.key for s in AU_SERIES if "RESOLVE_" in s.locator]
    assert not unresolved, f"unresolved ABS ids: {unresolved}"


@pytest.mark.parametrize("source", ABS_SERIES, ids=lambda s: s.key)
def test_parsed_series_is_clean(source):
    parsed = _parse(source)
    assert isinstance(parsed.index, pd.DatetimeIndex)
    assert parsed.index.is_monotonic_increasing
    assert not parsed.index.has_duplicates
    assert (parsed.index.day == 1).all(), "dates must be normalised to first-of-month"
    assert parsed.dtype == np.float64
    assert parsed.notna().any()


@pytest.mark.parametrize("source", ABS_SERIES, ids=lambda s: s.key)
def test_frequency_matches_the_registry(source):
    parsed = _parse(source)
    gaps = parsed.index.to_series().diff().dt.days.dropna()
    step = gaps.median()
    if source.frequency == "m":
        assert 28 <= step <= 31
    else:
        assert 89 <= step <= 92


@pytest.mark.parametrize("source", QUARTERLY, ids=lambda s: s.key)
def test_quarterly_observations_land_on_the_last_month_of_their_quarter(source):
    """The month set must be exactly {3, 6, 9, 12}, not merely "it parsed".

    Task 5 aligns quarterly series onto the monthly panel by keeping only those
    four months. `PeriodIndex.to_timestamp()` dates a quarter to its *first*
    month -- {1, 4, 7, 10} -- so the obvious repair for the PeriodIndex would
    drop every quarterly observation, GDP included, with no error anywhere.
    """
    months = set(_parse(source).index.month)
    assert months == {3, 6, 9, 12}, (
        f"{source.key} landed on months {sorted(months)}; Task 5 keeps only "
        "{3, 6, 9, 12} and would silently drop everything else"
    )


def test_parse_abs_frame_handles_every_index_shape_a_source_can_hand_it():
    """Monthly PeriodIndex, quarterly PeriodIndex, and a plain DatetimeIndex."""
    monthly = parse_abs_frame(
        pd.DataFrame({"X": [1.0, 2.0]}, index=pd.PeriodIndex(["2026-06", "2026-07"], freq="M")),
        "X",
    )
    assert list(monthly.index) == [pd.Timestamp("2026-06-01"), pd.Timestamp("2026-07-01")]

    quarterly = parse_abs_frame(
        pd.DataFrame({"X": [1.0, 2.0]}, index=pd.PeriodIndex(["2025Q4", "2026Q1"], freq="Q-DEC")),
        "X",
    )
    assert list(quarterly.index) == [pd.Timestamp("2025-12-01"), pd.Timestamp("2026-03-01")]

    # ABS dates an observation to a day inside the period it covers, so an
    # end-of-quarter DatetimeIndex must land on the same months as above.
    from_datetimes = parse_abs_frame(
        pd.DataFrame({"X": [1.0, 2.0]}, index=pd.DatetimeIndex(["2025-12-31", "2026-03-31"])),
        "X",
    )
    assert list(from_datetimes.index) == [pd.Timestamp("2025-12-01"), pd.Timestamp("2026-03-01")]


# Each row below is an observation read off the ABS release named in `source`,
# with `tol` set to the precision that release publishes it at. A wrong series
# id returns a real series with plausible numbers; only a known value catches
# it. Re-verify against ABS -- do not relax -- if a row starts failing: these
# are seasonally adjusted series and ABS revises them.
@pytest.mark.parametrize(
    "key,date,expected,tol,source",
    [
        (
            "employment", "2026-07-01", 14807.2, 0.05,
            "ABS 6202.0 Labour Force, Australia, July 2026: employment "
            "14,807,200 persons seasonally adjusted (series unit is '000)",
        ),
        (
            "unemployment_rate", "2026-07-01", 4.5, 0.05,
            "ABS 6202.0 Labour Force, Australia, July 2026: unemployment rate "
            "4.5% seasonally adjusted",
        ),
        (
            "imports", "2026-06-01", -45768.0, 0.5,
            "ABS 5368.0 International Trade in Goods, June 2026: goods debits "
            "-$45,768m seasonally adjusted (ABS signs debits negative)",
        ),
        (
            "cpi", "2026-07-01", 107.13, 0.005,
            "ABS 6401.0 CPI, Australia, July 2026: All groups CPI seasonally "
            "adjusted rose 0.6% in the month and 3.5% over the year; 107.13 "
            "against 106.45 (Jun 2026) is +0.639% and against 103.55 "
            "(Jul 2025) is +3.457%. ABS prints the movements, not this "
            "analytical index level",
        ),
        (
            "gdp", "2026-03-01", 695945.0, 0.5,
            "ABS 5206.0 National Accounts, March quarter 2026: GDP chain "
            "volume measures $695,945m seasonally adjusted. Dated to March, "
            "the last month of 2026Q1",
        ),
    ],
)
def test_a_verified_observation_pins_the_series_id(key, date, expected, tol, source):
    series_source = next(s for s in AU_SERIES if s.key == key)
    parsed = _parse(series_source)
    stamp = pd.Timestamp(date)
    assert stamp in parsed.index, f"{key} has no observation at {date}"
    assert parsed.loc[stamp] == pytest.approx(expected, abs=tol), source
