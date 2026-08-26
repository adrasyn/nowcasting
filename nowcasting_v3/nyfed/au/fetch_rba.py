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


def fetch_rba_series(table: str, *, column: str) -> pd.Series:
    """Retrieve one column of an RBA statistical table."""
    import readabs as ra  # imported lazily: tests never need it

    frame, _meta = ra.read_rba_table(table)
    return parse_rba_frame(frame, column)
