"""ABS time series retrieval.

Split in two so the parsing half is pure and testable without a network:
``fetch_abs_series`` does the retrieval, ``parse_abs_frame`` does everything
else. Every test in this project exercises the second half only.
"""

from __future__ import annotations

import pandas as pd

# Catalogues ABS has CEASED, mapped to the frozen landing page that still serves
# their final release.
#
# readabs resolves a catalogue through the ABS Time Series Directory. A ceased
# catalogue is removed from that directory, so `read_abs_series(cat="6484.0",
# ...)` raises outright -- "Catalogue number '6484.0' not found in the ABS Time
# Series Directory" -- even though the release page and its spreadsheets are
# still up. `read_abs_series` takes a `url=` override for exactly this case:
# given the landing page it downloads the zip directly and skips the directory.
#
# 6484.0 is the Monthly CPI Indicator, final release September 2025. Nothing in
# `AU_SERIES` points at it -- `cpi` moved to the live 6401.0 when ABS folded
# monthly CPI into the main collection, and `cpi_trimmed` was dropped from the
# registry entirely (2026-08-28) because 6484.0 has no trimmed mean INDEX to
# splice it onto. It is here for the deflator, which splices 6484.0's ~8 years
# of monthly history under the live series' 28 months -- and `build_panel` now
# reuses that same splice for the panel's own `cpi` row. See
# `nyfed/au/deflator.py`.
#
# This is a dict rather than a `url=` parameter on `fetch_abs_series` on
# purpose: `sources.py` keeps locators self-contained so that no caller has to
# supply a second argument to get the right series, and the same rule should
# hold for a dead catalogue. `fetch_abs_series("6484.0:A128481587A")` works.
CEASED_CATALOGUE_URLS: dict[str, str] = {
    "6484.0": (
        "https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation"
        "/monthly-consumer-price-index-indicator/sep-2025"
    ),
}


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
        # Every ABS payload is single-column, so this branch is the normal path
        # for an unlabelled frame -- but it must not launder a labelled one. A
        # frame carrying some *other* series id would otherwise be accepted and
        # then renamed to the requested id, which is exactly how a fixture
        # recorded under a superseded id parses clean and pins the stale
        # series' values. This session sat in that state: the registry moved to
        # 6401.0 while the recorded CPI payloads still said 6484.0.
        only = frame.columns[0]
        if isinstance(only, str) and only.strip() and only != series_id:
            raise KeyError(
                f"frame is labelled {only!r} but {series_id!r} was requested; "
                "refusing to rename it -- re-record the payload, or fix the locator"
            )
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


# Catalogues fetched as ONE TABLE rather than the whole release.
#
# `read_abs_series` defaults to downloading every spreadsheet in the catalogue
# as a single zip. For 6202.0 (Labour Force) that zip is about 30 MB, and
# readabs fetches it under a fixed 60-second request timeout. From this Mac it
# arrives in three seconds; from a GitHub runner it sat near the limit and
# crossed it on 10 and 11 September 2026, three attempts each time, which is
# what took the quarterly estimate down twice (issues #41, #42). Both series
# the registry needs from 6202.0 live in table 1, which is about 1 MB and
# arrives in under a second. readabs' own docstring for `read_abs_series`
# shows exactly this call, `single_excel_only="62020001"`.
#
# Keyed by catalogue, applied to every series from it. Adding a series that
# lives in another table means adding its catalogue's table here or dropping
# the entry -- `parse_abs_frame` refuses a frame that lacks the series id, so
# a wrong table fails loudly rather than returning the wrong column.
SINGLE_TABLE: dict[str, str] = {
    "6202.0": "62020001",
}


def fetch_abs_series(locator: str) -> pd.Series:
    """Retrieve one ABS series. ``locator`` is ``"<catalogue>:<series id>"``.

    There is deliberately no ``cache_dir``: readabs 0.2.6 takes no such
    argument, so a parameter here could not be forwarded and would silently
    leave every caller writing to the ``.readabs_cache/`` directory readabs
    creates in the working tree.
    """
    import readabs as ra  # imported lazily: tests never need it

    cat, series_id = locator.split(":", 1)
    kwargs = {}
    if cat in SINGLE_TABLE:
        kwargs["single_excel_only"] = SINGLE_TABLE[cat]
    frame, _meta = ra.read_abs_series(
        cat=cat, series_id=series_id, url=CEASED_CATALOGUE_URLS.get(cat, ""), **kwargs
    )
    return parse_abs_frame(frame, series_id)
