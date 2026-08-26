"""Staleness guards for the Australian panel.

A nowcast built on three-month-old survey data is worse than no nowcast,
because it looks current. Three Australian monthly indicators were
discontinued between March 2025 and June 2026 -- Weekly Payroll Jobs, the
Monthly Business Turnover Indicator and the Monthly Employee Earnings
Indicator -- and none of them raised an error on the way out. They simply
stopped updating.

Age is measured from the last **observed** value, not from the file's mtime and
not from the index's end, because assembly pads every series with NaN out to
the panel's horizon. A discontinued series after assembly looks exactly like a
fresh one until you ignore the padding.
"""

from __future__ import annotations

import pandas as pd

from nyfed.au.sources import AU_SERIES, SeriesSource


class StaleSeriesError(Exception):
    """Raised when any panel input is older than its declared budget."""

    def __init__(self, stale: list[tuple[str, int, int]]):
        self.stale = stale
        lines = "\n".join(
            f"  {key}: {age} days old, budget {budget}" for key, age, budget in stale
        )
        super().__init__(
            f"{len(stale)} panel series are stale; refusing to nowcast:\n{lines}"
        )


def series_age_days(s: pd.Series, asof: pd.Timestamp) -> int:
    """Days from the last non-NaN observation to ``asof``."""
    observed = s.dropna()
    if observed.empty:
        raise ValueError("series has no observations")
    return int((asof - observed.index[-1]).days)


def check_freshness(
    series: dict[str, pd.Series],
    asof: pd.Timestamp,
    *,
    sources: tuple[SeriesSource, ...] = AU_SERIES,
) -> None:
    """Raise if any registered series is missing, empty or past its budget.

    Reports every failure at once. Reporting one at a time turns a single
    broken feed into as many debug cycles as there are stale series.
    """
    stale: list[tuple[str, int, int]] = []
    for source in sources:
        s = series.get(source.key)
        if s is None or s.dropna().empty:
            stale.append((source.key, 10**6, source.max_age_days))
            continue
        age = series_age_days(s, asof)
        if age > source.max_age_days:
            stale.append((source.key, age, source.max_age_days))
    if stale:
        raise StaleSeriesError(stale)
