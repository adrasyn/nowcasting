"""The Australian panel's registry and spec CSV.

These tests are the contract every later task builds on: seventeen series,
frequency-sorted, mirroring the NY Fed spec values series by series, with
exactly one normalising series per factor.
"""

import csv
from pathlib import Path

import numpy as np
import pytest

from nyfed.au.sources import AU_SERIES, SPEC_PATH, SeriesSource
from nyfed.spec import load_spec

BLOCK_COLS = [
    "Block0_Global",
    "Block1_Soft",
    "Block2_Nominal",
    "Block3_Labor",
    "Block4_COVID",
]


def test_the_registry_has_seventeen_series():
    assert len(AU_SERIES) == 17
    assert all(isinstance(s, SeriesSource) for s in AU_SERIES)


def test_series_keys_are_unique():
    keys = [s.key for s in AU_SERIES]
    assert len(set(keys)) == len(keys)


def test_the_registry_is_frequency_sorted_monthly_before_quarterly():
    """load_spec raises on an unsorted spec; the registry must match the CSV."""
    freqs = [s.frequency for s in AU_SERIES]
    assert set(freqs) <= {"m", "q"}
    assert freqs == sorted(freqs, key=["m", "q"].index)
    assert freqs.count("q") == 3


def test_the_spec_csv_row_order_matches_the_registry():
    with open(SPEC_PATH, newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert [r["SeriesID"] for r in rows] == [s.series_id for s in AU_SERIES]


def test_the_spec_csv_loads_without_tripping_the_panel_order_guard():
    spec = load_spec(SPEC_PATH)
    assert len(spec.series_id) == 17
    assert spec.blocks.shape == (17, 5)


def test_gdp_is_the_last_row_and_is_quarterly():
    """i_now indexes the nowcast series; the runner resolves it by id."""
    assert AU_SERIES[-1].key == "gdp"
    assert AU_SERIES[-1].frequency == "q"


def test_exactly_one_series_normalises_each_factor():
    """A factor with no normaliser has an unidentified scale; a factor with two
    is over-restricted. The NY Fed panel has one per factor except Soft, which
    it leaves unnormalised -- mirror that exactly."""
    with open(SPEC_PATH, newline="") as fh:
        rows = list(csv.DictReader(fh))
    normalisers = {
        col: [r["SeriesID"] for r in rows if float(r[col]) > 1] for col in BLOCK_COLS
    }
    assert normalisers["Block0_Global"] == ["household_spending"]
    assert normalisers["Block2_Nominal"] == ["cpi"]
    assert normalisers["Block3_Labor"] == ["employment"]
    assert normalisers["Block4_COVID"] == ["employment"]
    assert normalisers["Block1_Soft"] == []


def test_loaded_blocks_encode_normalisers_as_one_and_free_loadings_as_nan():
    spec = load_spec(SPEC_PATH)
    ids = spec.series_id
    g = spec.blocks[:, 0]
    assert g[ids.index("household_spending")] == 1.0
    assert np.isnan(g[ids.index("employment")])
    assert spec.blocks[ids.index("cpi"), 4] == 0.0  # prices do not load on COVID


@pytest.mark.parametrize(
    "series_id,transformation,prior",
    [
        ("employment", "chg", 1.0),
        ("unemployment_rate", "chg", -1.0),
        ("cpi", "pch", 0.0),
        ("gdp", "pca", 1.0),
    ],
)
def test_spec_values_mirror_the_us_counterpart(series_id, transformation, prior):
    spec = load_spec(SPEC_PATH)
    i = spec.series_id.index(series_id)
    assert spec.transformation[i] == transformation
    assert spec.prior[i] == prior
