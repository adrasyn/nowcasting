"""Readers for the three panel series that v2 fetches and commits.

v3 does not import from v2 and does not run its R code. It reads the CSVs v2's
weekly routine commits to ``nowcasting_v2/data_raw/``. Those three series --
job ads, the AiG PMI and NAB conditions -- originate in media releases and
PDFs, and rebuilding that scraping in Python would duplicate a working thing.

The dependency is real and one-directional: if v2's weekly routine stops, these
files go stale. ``freshness.py`` is what turns that into a halt rather than a
silently old nowcast.

All three CSVs inspected while writing this reader (``anz_ads.csv``,
``aig_pmi.csv``, ``nab_cond.csv``) share the same shape: two columns, header
``date,value``, ISO dates already on the first of the month, one row per
month.

A fourth series, the Internet Vacancy Index (``ivi``, the ``vacancy_index``
registry entry) was originally in scope here and is not any more. v2's
``ivi.csv`` was never written at all -- its own ``seed/panel_info.csv`` and
``seed/panel_info_tier2.csv`` record ``status=MISSING`` / ``BLOCKED``,
``has_csv=FALSE``, "host firewalled": the JSA host has been unreachable from
v2's fetch runner since the series was added, and no fixture has ever been
obtained. ``read_v2_series`` still raises ``FileNotFoundError`` for any
absent stem -- that behaviour is generic and correct -- but ``vacancy_index``
itself has been removed from ``nyfed.au.sources.AU_SERIES``, so nothing calls
``read_v2_series("ivi")`` in this panel any more. See ``sources.py`` for the
removal rationale and the route back in (a direct JSA fetcher, not v2).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

V2_DATA_ROOT = Path(__file__).resolve().parents[3] / "nowcasting_v2" / "data_raw"


def read_v2_series(stem: str, *, root: Path | None = None) -> pd.Series:
    """Read ``<root>/<stem>.csv`` as a first-of-month float series."""
    base = V2_DATA_ROOT if root is None else root
    path = base / f"{stem}.csv"
    if not path.is_file():
        raise FileNotFoundError(
            f"{path} is absent. It is fetched by v2's weekly routine; v3 reads "
            "but never writes it."
        )
    raw = pd.read_csv(path)
    date_candidates = [c for c in raw.columns if c.lower() in ("date", "ref_date", "time")]
    if not date_candidates:
        raise KeyError(
            f"{path} has no date-like column (looked for 'date'/'ref_date'/"
            f"'time', case-insensitive); got {list(raw.columns)}"
        )
    date_col = date_candidates[0]
    value_candidates = [c for c in raw.columns if c != date_col]
    if not value_candidates:
        raise KeyError(
            f"{path} has a date column ({date_col!r}) but nothing else; got "
            f"{list(raw.columns)}"
        )
    value_col = value_candidates[0]
    series = pd.Series(
        pd.to_numeric(raw[value_col], errors="coerce").to_numpy(dtype=float),
        index=pd.DatetimeIndex(raw[date_col]).to_period("M").to_timestamp(),
        name=stem,
    )
    return series[~series.index.duplicated(keep="last")].sort_index()
