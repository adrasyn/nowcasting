"""RBA statistical table retrieval.

Table I2 is the Index of Commodity Prices. It carries several indices --
all-items and sub-indices by commodity group (rural, non-rural, base
metals, bulk commodities, and a bulk-commodities-spot variant), each in
three currency terms (A$, US$, SDR) -- 21 columns in total. The panel uses
column **GRCPAIAD**, "Commodity prices -- A$": the all-items index,
Australian dollar terms. Australia's GDP is denominated in A$, and the Q1
2026 miss this series exists to address was an A$ terms-of-trade shock, so
the US$ or SDR variant would not serve that purpose even though the level
is plausible-looking either way. Do not swap in a sub-index (rural,
non-rural, base metals, bulk) or the "with bulk commodities spot prices"
variant (GRCPAISAD) without a documented reason -- both parse cleanly and
both are a different series.

The column choice is not a parameter a caller supplies -- it lives in
``nyfed.au.sources.AU_SERIES`` as part of the locator, ``"I2:GRCPAIAD"``,
the same self-contained shape ABS locators use (``"<catalogue>:<series
id>"``). ``fetch_rba_series`` takes that one string and splits it, rather
than taking ``table`` and ``column`` as two separate arguments: a
two-argument signature invites a future caller to type the column by hand,
and ``GRCPAISAD`` -- one character away from the correct column -- would
type-check, fetch, and parse without complaint. Keeping the column in the
registry makes ``sources.py`` the single place a fixture or a caller can be
checked against, for both source families.
"""

from __future__ import annotations

import pandas as pd


def parse_rba_frame(frame: pd.DataFrame, column: str) -> pd.Series:
    """Tidy one RBA table column into a first-of-month float series."""
    if column not in frame.columns:
        raise KeyError(f"{column} is not a column of table; got {list(frame.columns)[:5]}")
    series = pd.Series(
        pd.to_numeric(frame[column], errors="coerce").to_numpy(dtype=float),
        index=pd.DatetimeIndex(frame.index).to_period("M").to_timestamp(),
        name=column,
    )
    return series[~series.index.duplicated(keep="last")].sort_index()


def fetch_rba_series(locator: str) -> pd.Series:
    """Retrieve one column of an RBA statistical table.

    ``locator`` is ``"<table>:<column>"``, e.g. ``"I2:GRCPAIAD"`` -- the same
    self-contained shape as ``fetch_abs.fetch_abs_series``'s ABS locator, and
    for the same reason: the column is part of what a registry entry names,
    not something a caller chooses at the call site.
    """
    import readabs as ra  # imported lazily: tests never need it

    table, column = locator.split(":", 1)
    frame, _meta = ra.read_rba_table(table)
    return parse_rba_frame(frame, column)
