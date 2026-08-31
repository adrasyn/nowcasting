"""The Australian panel's registry and spec CSV.

These tests are the contract every later task builds on: fourteen series,
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

FRED_SPEC_PATH = Path(__file__).resolve().parents[1] / "nyfed_matlab" / "model_spec_FRED.csv"

# Every AU series and the NY Fed series its spec row is copied from. Keep
# this in sync with the mirroring table in the task brief.
#
# NOT MIRRORED, DELIBERATELY: the NY Fed runs four price series (headline
# and core, for both CPI and PCE). Australia publishes no monthly PCE
# deflator, so this panel could only ever mirror the CPI pair -- and the
# core half (`cpi_trimmed` <- CPILFESL) was dropped on 2026-08-28 because
# it had no back history to splice and alone held the earliest buildable
# vintage at 2024-07. See the `cpi_trimmed` note in `nyfed/au/sources.py`.
NY_FED_COUNTERPART = {
    "employment": "PAYEMS",
    "unemployment_rate": "UNRATE",
    "job_ads": "JTSJOL",
    "aig_pmi": "GACDISA066MSFRBNY",
    "nab_conditions": "GACDFSA066MSFRBPHI",
    "building_approvals": "PERMIT",
    "household_spending": "PCEC96",
    "exports": "BOPTEXP",
    "imports": "BOPTIMP",
    "commodity_prices": "IQ",
    "cpi": "CPIAUCSL",
    "unit_labour_cost": "PRS85006112",
    "gdi": "A261RX1Q020SBEA",
    "gdp": "GDPC1",
}

MIRRORED_FIELDS = [
    "Frequency",
    "Trend",
    "Block0_Global",
    "Block1_Soft",
    "Block2_Nominal",
    "Block3_Labor",
    "Block4_COVID",
    "Prior",
    "Transformation",
]

# Two cells deliberately differ from their NY Fed counterpart. The NY Fed
# normalises Global with INDPRO (industrial production) and Nominal with
# PCEPI (the PCE price index); Australia publishes neither, so those two
# factors would otherwise have no scale-setter and an unidentified scale.
# Australia nominates its own normalisers instead: Household Spending for
# Global, Monthly CPI for Nominal. Each entry maps (series, field) to the
# (AU value, US counterpart value) that is expected -- not equal.
KNOWN_DEVIATIONS = {
    ("household_spending", "Block0_Global"): ("100", "1"),
    ("cpi", "Block2_Nominal"): ("100", "1"),
}


def test_the_registry_has_fourteen_series():
    assert len(AU_SERIES) == 14
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
    assert len(spec.series_id) == 14
    assert spec.blocks.shape == (14, 5)


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


def test_every_row_mirrors_its_ny_fed_counterpart_exactly():
    """The mirroring rule, checked cell-by-cell for all fourteen rows.

    Every AU spec value is supposed to be copied from its NY Fed counterpart
    in ``model_spec_FRED.csv``: Frequency, Trend, all five block columns,
    Prior and Transformation. A narrower test -- one that samples a few
    series or a few fields -- would pass unchanged if, say, unit_labour_cost's
    Trend or exports' Prior were silently altered, because nothing else in
    this suite reads those cells against their source of truth.

    KNOWN_DEVIATIONS carries the two cells that are supposed to differ. Any
    other mismatch is a real defect: a wrong value copied from the brief, or
    a value that drifted after this test was written.
    """
    with open(SPEC_PATH, newline="") as fh:
        au_rows = {r["SeriesID"]: r for r in csv.DictReader(fh)}
    with open(FRED_SPEC_PATH, newline="") as fh:
        us_rows = {r["SeriesID"]: r for r in csv.DictReader(fh)}

    assert set(NY_FED_COUNTERPART) == {s.series_id for s in AU_SERIES}

    mismatches = []
    for au_id, us_id in NY_FED_COUNTERPART.items():
        au_row, us_row = au_rows[au_id], us_rows[us_id]
        for field in MIRRORED_FIELDS:
            au_val, us_val = au_row[field], us_row[field]
            deviation = KNOWN_DEVIATIONS.get((au_id, field))
            if deviation is not None:
                assert (au_val, us_val) == deviation, (
                    f"{au_id}.{field}: expected the recorded deviation "
                    f"{deviation}, got ({au_val!r}, {us_val!r})"
                )
                continue
            if au_val != us_val:
                mismatches.append(
                    f"{au_id}.{field}: AU={au_val!r} US({us_id})={us_val!r}"
                )
    assert not mismatches, "\n".join(mismatches)
