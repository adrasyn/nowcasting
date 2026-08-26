"""Readers for the three series v2 already fetches and commits.

These are the media-release and PDF sources -- job ads, the AiG PMI and NAB
conditions. v2 fetches them weekly into committed CSVs; v3 reads those rather
than rebuilding the scraping. A fourth source, the Internet Vacancy Index,
was originally in scope here but was dropped from the registry: v2 has never
successfully fetched it (see ``nyfed.au.sources`` and ``nyfed.au.fetch_v2``
for the detail), so there is nothing left for this reader to be tested
against for that series.
"""

from pathlib import Path

import pandas as pd
import pytest

from nyfed.au.fetch_v2 import V2_DATA_ROOT, read_v2_series
from nyfed.au.sources import AU_SERIES

V2_SERIES = [s for s in AU_SERIES if s.fetcher == "v2"]


def test_the_v2_data_root_exists():
    """v3 depends on v2's committed CSVs. If this fails the dependency is
    broken and no amount of downstream defaulting should hide it."""
    assert V2_DATA_ROOT.is_dir(), f"{V2_DATA_ROOT} is absent"


@pytest.mark.parametrize("source", V2_SERIES, ids=lambda s: s.key)
def test_every_v2_series_is_present_and_parses(source):
    parsed = read_v2_series(source.locator)
    assert isinstance(parsed.index, pd.DatetimeIndex)
    assert parsed.index.is_monotonic_increasing
    assert not parsed.index.has_duplicates
    assert (parsed.index.day == 1).all()
    assert parsed.notna().sum() >= 24, "fewer than two years of observations"


def test_a_missing_v2_csv_raises_rather_than_returning_empty(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_v2_series("does_not_exist", root=tmp_path)
