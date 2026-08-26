"""ABS time series retrieval.

Split in two so the parsing half is pure and testable without a network:
``fetch_abs_series`` does the retrieval, ``parse_abs_frame`` does everything
else. Every test in this project exercises the second half only.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def _first_of_month_index(index: pd.Index) -> pd.DatetimeIndex:
    """Map an ABS index onto the first day of the month an observation *covers*.

    ``readabs`` hands back a ``PeriodIndex``: monthly series arrive as ``2026-07``
    and quarterly ones as ``2026Q1`` (freq ``Q-DEC``, since ABS quarters end in
    March, June, September and December). ``PeriodIndex.to_timestamp()`` defaults
    to the *start* of the period, which puts 2026Q1 on 1 January. Task 5 aligns
    quarterly series onto the panel by keeping only months ``{3, 6, 9, 12}``, so
    start-of-quarter dating would silently discard every quarterly observation --
    including GDP, the nowcast target -- leaving an all-NaN target row that the
    model would still happily run on. Take ``how="end"`` and re-normalise, so
    2026Q1 lands on 1 March: the last month of the quarter, which is the month a
    quarterly figure is conventionally attributed to.

    A plain ``DatetimeIndex`` is accepted too, for a future source that does not
    come through readabs. ABS dates an observation to a day inside the period it
    covers, so taking the containing month is right for that shape as well.
    """
    if isinstance(index, pd.PeriodIndex):
        stamps = pd.DatetimeIndex(index.to_timestamp(how="end"))
    else:
        stamps = pd.DatetimeIndex(index)
    return pd.DatetimeIndex(stamps.to_period("M").to_timestamp())


def parse_abs_frame(frame: pd.DataFrame, series_id: str) -> pd.Series:
    """Tidy one readabs frame into a first-of-month float series.

    The panel indexes by first-of-month throughout, so normalise here rather
    than at every caller. See ``_first_of_month_index`` for the quarterly rule.
    """
    if series_id in frame.columns:
        column = frame[series_id]
    elif frame.shape[1] == 1:
        column = frame.iloc[:, 0]
    else:
        raise KeyError(
            f"{series_id} is not a column of the fetched frame; got "
            f"{list(frame.columns)[:5]}"
        )

    series = pd.Series(
        pd.to_numeric(column, errors="coerce").to_numpy(dtype=float),
        index=_first_of_month_index(frame.index),
        name=series_id,
    )
    series = series[~series.index.duplicated(keep="last")].sort_index()
    return series


def fetch_abs_series(locator: str, *, cache_dir: Path | None = None) -> pd.Series:
    """Retrieve one ABS series. ``locator`` is ``"<catalogue>:<series id>"``."""
    import readabs as ra  # imported lazily: tests never need it

    cat, series_id = locator.split(":", 1)
    frame, _meta = ra.read_abs_series(cat=cat, series_id=series_id)
    return parse_abs_frame(frame, series_id)
