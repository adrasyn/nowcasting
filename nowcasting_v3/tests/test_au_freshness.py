"""Staleness guards.

Three Australian monthly indicators were discontinued between March 2025 and
June 2026. A discontinued series does not error -- it stops updating. Without
these guards the model would keep nowcasting from a series that no longer
exists and nothing would say so.
"""

from pathlib import Path

import pandas as pd
import pytest

from nyfed.au.freshness import StaleSeriesError, check_freshness, series_age_days
from nyfed.au.sources import (
    RELEASE_INTERVAL_DAYS, SLACK_DAYS, AU_SERIES, SeriesSource,
)

ASOF = pd.Timestamp("2026-08-01")


def _series(last: str, n: int = 24, freq: str = "MS") -> pd.Series:
    idx = pd.date_range(end=pd.Timestamp(last), periods=n, freq=freq)
    return pd.Series(range(n), index=idx, dtype=float)


def _sources(*specs) -> tuple[SeriesSource, ...]:
    """Synthetic registry rows. ``specs`` are ``(key, frequency, lag)``.

    The third element is the PUBLICATION LAG, not the budget: ``max_age_days``
    is derived (``lag + release interval + slack``) and is not a field any more.
    A test that wants a particular budget has to choose a lag, which is the
    point -- the budget is not a number anybody types.
    """
    return tuple(
        SeriesSource(k, k, k, "abs", "x:y", f, lag, "synthetic, for this test")
        for k, f, lag in specs
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
    sources = _sources(("a", "m", 14), ("b", "m", 14))
    check_freshness({"a": _series("2026-07-01"), "b": _series("2026-07-01")},
                    ASOF, sources=sources)


def test_a_stale_series_raises_and_names_itself():
    sources = _sources(("fresh", "m", 14), ("dead", "m", 14))
    with pytest.raises(StaleSeriesError) as excinfo:
        check_freshness({"fresh": _series("2026-07-01"), "dead": _series("2026-01-01")},
                        ASOF, sources=sources)
    assert "dead" in str(excinfo.value)
    assert "fresh" not in str(excinfo.value)
    assert [k for k, _, _ in excinfo.value.stale] == ["dead"]


def test_every_stale_series_is_reported_not_just_the_first():
    """Reporting one at a time turns one broken feed into three debug cycles."""
    sources = _sources(("a", "m", 14), ("b", "m", 14), ("c", "m", 14))
    with pytest.raises(StaleSeriesError) as excinfo:
        check_freshness(
            {"a": _series("2026-01-01"), "b": _series("2026-07-01"),
             "c": _series("2025-11-01")},
            ASOF, sources=sources,
        )
    assert [k for k, _, _ in excinfo.value.stale] == ["a", "c"]


def test_a_missing_series_is_stale_not_absent():
    sources = _sources(("a", "m", 14), ("gone", "m", 14))
    with pytest.raises(StaleSeriesError) as excinfo:
        check_freshness({"a": _series("2026-07-01")}, ASOF, sources=sources)
    assert "gone" in str(excinfo.value)


def test_every_registered_series_declares_a_positive_budget():
    assert all(s.max_age_days > 0 for s in AU_SERIES)


def test_quarterly_budgets_exceed_monthly_ones():
    monthly = max(s.max_age_days for s in AU_SERIES if s.frequency == "m")
    quarterly = min(s.max_age_days for s in AU_SERIES if s.frequency == "q")
    assert quarterly > monthly


def test_the_quarterly_budget_passes_a_healthy_series_and_still_catches_a_dead_one():
    """The budget the first end-to-end build had to correct, pinned so it stays.

    A quarterly ABS observation is dated to the LAST MONTH of its quarter, and
    the national accounts are published about two months after the quarter ends
    -- so an entirely current ``gdp`` reaches roughly 186 days old just before
    the next release, and a run that day is a run on the freshest data that
    exists. The budget was 120, which refused three healthy series -- including
    the nowcast target -- on every build between late June and early September.
    Measured on 2026-08-26 with the March quarter the latest published: 178
    days.

    The two ages below are the two cases the budget has to separate: the oldest
    a current series gets, and a series that has missed a release entirely.
    """
    quarterly = [s for s in AU_SERIES if s.frequency == "q"]
    assert quarterly, "no quarterly series to test against"

    asof = pd.Timestamp("2026-08-26")
    healthy = {s.key: _series("2026-03-01", freq="QS-DEC") for s in quarterly}
    assert series_age_days(healthy[quarterly[0].key], asof) == 178
    check_freshness(healthy, asof, sources=tuple(quarterly))

    # Just before the next release: the oldest a healthy series ever gets.
    oldest_healthy = {s.key: _series("2026-03-01", freq="QS-DEC") for s in quarterly}
    check_freshness(oldest_healthy, pd.Timestamp("2026-09-02"),
                    sources=tuple(quarterly))

    # One release missed outright: 2025-12 still the latest in September 2026.
    missed = {s.key: _series("2025-12-01", freq="QS-DEC") for s in quarterly}
    with pytest.raises(StaleSeriesError) as excinfo:
        check_freshness(missed, pd.Timestamp("2026-09-02"), sources=tuple(quarterly))
    assert {k for k, _, _ in excinfo.value.stale} == {s.key for s in quarterly}


def test_the_budget_is_derived_from_the_publication_lag_not_typed_in():
    """``max_age_days`` was a hand-typed field and was wrong three times running.

    It is now a property, so there is no number to mistype -- but a property can
    be reimplemented wrongly too, so check the arithmetic against the registry's
    own two primitives, and check that the lags themselves carry a source.
    """
    for source in AU_SERIES:
        assert source.max_age_days == (
            source.publication_lag_days + source.release_interval_days + SLACK_DAYS
        ), source.key
        assert source.publication_lag_days > 0, source.key
        assert len(source.lag_source) > 40, (
            f"{source.key}'s lag has no usable provenance; an unsourced lag is "
            "a number that looks measured and is not"
        )

        # The interval is the frequency default unless the series overrides it,
        # and an override is a widened staleness budget -- so it carries its own
        # provenance, on the same terms as the lag.
        if source.release_interval_override is None:
            assert (
                source.release_interval_days
                == RELEASE_INTERVAL_DAYS[source.frequency]
            ), source.key
        else:
            assert source.release_interval_days == source.release_interval_override
            assert (
                source.release_interval_override
                > RELEASE_INTERVAL_DAYS[source.frequency]
            ), (
                f"{source.key} overrides its release interval DOWNWARD, which "
                "tightens a budget rather than accommodating a known calendar "
                "skip; that is what the frequency default is for"
            )
            assert len(source.release_interval_source) > 40, (
                f"{source.key}'s widened release interval has no usable "
                "provenance; it widens the staleness budget by "
                f"{source.release_interval_override - RELEASE_INTERVAL_DAYS[source.frequency]}"
                " days"
            )


def test_a_widened_release_interval_must_be_sourced_and_must_not_disarm_the_guard():
    """The two ways a per-series interval could be typed in wrongly, made real.

    An override widens the staleness budget for one series, so it has the same
    hazard the hand-typed ``max_age_days`` field had: a number that nobody can
    trace, or one large enough that the guard stops guarding. Both are refused
    at construction rather than only asserted about the registry as it stands,
    because the registry is what changes.
    """
    ok = dict(key="x", series_id="x", name="x", fetcher="v2", locator="x",
              frequency="m", publication_lag_days=34,
              lag_source="synthetic, for this test")

    with pytest.raises(ValueError, match="looks measured and is not"):
        SeriesSource(**ok, release_interval_override=62)
    with pytest.raises(ValueError, match="go together"):
        SeriesSource(**ok, release_interval_source="a note with no number")

    # At or below SLACK_DAYS the budget can no longer separate a healthy series
    # from one that missed a release outright -- the inequality below.
    with pytest.raises(ValueError, match="stop guarding"):
        SeriesSource(**ok, release_interval_override=SLACK_DAYS,
                     release_interval_source="synthetic, for this test")

    fine = SeriesSource(**ok, release_interval_override=SLACK_DAYS + 1,
                        release_interval_source="synthetic, for this test")
    assert fine.max_age_days == 34 + SLACK_DAYS + 1 + SLACK_DAYS


def _recorded(key: str) -> pd.Series:
    """One registered series' real history, out of the committed vintage."""
    frame = pd.read_csv(
        Path(__file__).parent / "fixtures" / "au" / "vintage" / "series.csv",
        parse_dates=["date"],
    )
    part = frame[frame["key"] == key]
    assert not part.empty, f"the recorded vintage has no {key}"
    return pd.Series(
        part["value"].to_numpy(dtype=float),
        index=pd.DatetimeIndex(part["date"]),
    ).sort_index()


# Every gap over 31 days in the recorded `aig_pmi` history since 2015, as
# (last observation before the gap, first observation after it). Ai Group skips
# the turn of the year: the months absent are 2017-06, 2020-12, 2022-01,
# 2022-12, 2023-01, 2024-01, 2025-01 and 2025-12, so six of the seven gaps are
# a missing December or January.
AIG_REAL_GAPS = [
    ("2017-05-01", "2017-07-01"),
    ("2020-11-01", "2021-01-01"),
    ("2021-12-01", "2022-02-01"),
    ("2022-11-01", "2023-02-01"),   # December 2022 AND January 2023: 92 days
    ("2023-12-01", "2024-02-01"),
    ("2024-12-01", "2025-02-01"),
    ("2025-11-01", "2026-01-01"),
]


@pytest.mark.parametrize(
    "before,after", [g for g in AIG_REAL_GAPS if g != ("2022-11-01", "2023-02-01")]
)
def test_a_skipped_month_does_not_refuse_a_healthy_aig_pmi(before, after):
    """The false refusal I2 found, demonstrated on the real gaps rather than
    asserted about the arithmetic.

    Ai Group publishes no PMI for one December or January in most years. The gap
    is 61 or 62 days, and the series is at its oldest on the day the next
    edition lands: 34 days of publication lag on top, so 95 or 96 days old on a
    series that has behaved exactly as it always has. Under the 31-day monthly
    default the budget was 86 and the build refused EVERY FEBRUARY -- currently
    masked only because `aig_pmi` is stale for an unrelated reason.

    Both halves are exercised: the registry's own entry passes, and the SAME
    real history under the frequency default still fails. Without the second
    half this test would pass on a budget of ten thousand days.
    """
    history = _recorded("aig_pmi")
    last_before = pd.Timestamp(before)
    assert last_before in history.index
    assert pd.Timestamp(after) in history.index
    assert history.loc[last_before:pd.Timestamp(after)].shape[0] == 2, (
        f"{before}..{after} is not a gap in the recorded aig_pmi history"
    )

    source = next(s for s in AU_SERIES if s.key == "aig_pmi")
    # The oldest the series gets: the day its next edition is published.
    worst = pd.Timestamp(after) + pd.Timedelta(days=source.publication_lag_days)
    stale_view = {"aig_pmi": history.loc[:last_before]}
    age = series_age_days(stale_view["aig_pmi"], worst)
    assert age >= 95, f"expected a ~96-day worst age across the skip, got {age}"

    check_freshness(stale_view, worst, sources=(source,))

    # The bug, made and watched to fail: the same series, the same day, with
    # the release interval its FREQUENCY implies instead of its calendar.
    by_frequency = SeriesSource(
        source.key, source.series_id, source.name, source.fetcher, source.locator,
        source.frequency, source.publication_lag_days, source.lag_source,
    )
    assert by_frequency.max_age_days == 86
    with pytest.raises(StaleSeriesError, match="aig_pmi"):
        check_freshness(stale_view, worst, sources=(by_frequency,))


def test_a_double_skip_is_still_refused_even_with_the_widened_interval():
    """The widened budget accommodates ONE skipped month, not any gap at all.

    December 2022 and January 2023 are both absent from the AiG history -- a
    92-day gap, 30 days longer than the routine one. That is outside the
    calendar the override is sourced from, and it still refuses. An override
    that swallowed it would have stopped separating "Ai Group's January" from
    "the feed has stopped", which is the whole job.
    """
    history = _recorded("aig_pmi")
    source = next(s for s in AU_SERIES if s.key == "aig_pmi")
    worst = pd.Timestamp("2023-02-01") + pd.Timedelta(
        days=source.publication_lag_days
    )
    stale_view = {"aig_pmi": history.loc[:pd.Timestamp("2022-11-01")]}
    assert series_age_days(stale_view["aig_pmi"], worst) == 126
    with pytest.raises(StaleSeriesError, match="aig_pmi"):
        check_freshness(stale_view, worst, sources=(source,))


def test_the_september_2020_gap_does_not_refuse_a_healthy_nab_conditions():
    """The same finding on the other overridden series, on its one real gap.

    NAB published no September 2020 survey: the recorded history runs 2020-08 to
    2020-10 with nothing between. 61 days plus a 43-day lag is 104, against the
    95-day budget the monthly default gives -- so this build would have refused
    in October 2020 on a series that was working.
    """
    history = _recorded("nab_conditions")
    assert pd.Timestamp("2020-09-01") not in history.index
    source = next(s for s in AU_SERIES if s.key == "nab_conditions")
    worst = pd.Timestamp("2020-10-01") + pd.Timedelta(
        days=source.publication_lag_days
    )
    stale_view = {"nab_conditions": history.loc[:pd.Timestamp("2020-08-01")]}
    assert series_age_days(stale_view["nab_conditions"], worst) == 104

    check_freshness(stale_view, worst, sources=(source,))

    by_frequency = SeriesSource(
        source.key, source.series_id, source.name, source.fetcher, source.locator,
        source.frequency, source.publication_lag_days, source.lag_source,
    )
    assert by_frequency.max_age_days == 95
    with pytest.raises(StaleSeriesError, match="nab_conditions"):
        check_freshness(stale_view, worst, sources=(by_frequency,))


def test_the_slack_cannot_swallow_a_missed_release():
    """The one inequality the budget formula has to satisfy.

    ``max_age_days = lag + interval + slack``. A series that missed a release
    outright reaches ``lag + 2 * interval``. So the guard only guards while
    ``slack < interval``; at or above it a skipped release sits inside the
    budget for ever and the whole mechanism is decorative.
    """
    assert SLACK_DAYS < min(RELEASE_INTERVAL_DAYS.values())

    for source in AU_SERIES:
        missed = source.publication_lag_days + 2 * source.release_interval_days
        assert missed > source.max_age_days, (
            f"{source.key}: a series that skipped a release would be {missed} "
            f"days old against a {source.max_age_days}-day budget, and would "
            "never be caught"
        )
