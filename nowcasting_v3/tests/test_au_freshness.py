"""Staleness guards.

Three Australian monthly indicators were discontinued between March 2025 and
June 2026. A discontinued series does not error -- it stops updating. Without
these guards the model would keep nowcasting from a series that no longer
exists and nothing would say so.
"""

import pandas as pd
import pytest

from nyfed.au.freshness import StaleSeriesError, check_freshness, series_age_days
from nyfed.au.sources import AU_SERIES, SeriesSource

ASOF = pd.Timestamp("2026-08-01")


def _series(last: str, n: int = 24, freq: str = "MS") -> pd.Series:
    idx = pd.date_range(end=pd.Timestamp(last), periods=n, freq=freq)
    return pd.Series(range(n), index=idx, dtype=float)


def _sources(*specs) -> tuple[SeriesSource, ...]:
    return tuple(
        SeriesSource(k, k, k, "abs", "x:y", f, age) for k, f, age in specs
    )


def test_age_is_measured_from_the_last_observation_not_the_file():
    assert series_age_days(_series("2026-07-01"), ASOF) == 31


def test_trailing_nans_do_not_count_as_observations():
    """A series padded with NaN out to the current month is stale, not fresh.
    This is exactly what a discontinued series looks like after assembly."""
    s = _series("2026-08-01")
    s.iloc[-3:] = float("nan")
    assert series_age_days(s, ASOF) == series_age_days(_series("2026-05-01"), ASOF)


def test_a_fresh_panel_passes():
    sources = _sources(("a", "m", 45), ("b", "m", 45))
    check_freshness({"a": _series("2026-07-01"), "b": _series("2026-07-01")},
                    ASOF, sources=sources)


def test_a_stale_series_raises_and_names_itself():
    sources = _sources(("fresh", "m", 45), ("dead", "m", 45))
    with pytest.raises(StaleSeriesError) as excinfo:
        check_freshness({"fresh": _series("2026-07-01"), "dead": _series("2026-01-01")},
                        ASOF, sources=sources)
    assert "dead" in str(excinfo.value)
    assert "fresh" not in str(excinfo.value)
    assert [k for k, _, _ in excinfo.value.stale] == ["dead"]


def test_every_stale_series_is_reported_not_just_the_first():
    """Reporting one at a time turns one broken feed into three debug cycles."""
    sources = _sources(("a", "m", 45), ("b", "m", 45), ("c", "m", 45))
    with pytest.raises(StaleSeriesError) as excinfo:
        check_freshness(
            {"a": _series("2026-01-01"), "b": _series("2026-07-01"),
             "c": _series("2025-11-01")},
            ASOF, sources=sources,
        )
    assert [k for k, _, _ in excinfo.value.stale] == ["a", "c"]


def test_a_missing_series_is_stale_not_absent():
    sources = _sources(("a", "m", 45), ("gone", "m", 45))
    with pytest.raises(StaleSeriesError) as excinfo:
        check_freshness({"a": _series("2026-07-01")}, ASOF, sources=sources)
    assert "gone" in str(excinfo.value)


def test_every_registered_series_declares_a_positive_budget():
    assert all(s.max_age_days > 0 for s in AU_SERIES)


def test_quarterly_budgets_exceed_monthly_ones():
    monthly = max(s.max_age_days for s in AU_SERIES if s.frequency == "m")
    quarterly = min(s.max_age_days for s in AU_SERIES if s.frequency == "q")
    assert quarterly > monthly
