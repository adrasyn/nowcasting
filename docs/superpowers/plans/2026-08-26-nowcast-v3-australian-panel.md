# Nowcast v3 — Australian Panel Implementation Plan (Plan B)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the NY Fed's 31-series US panel with a 17-series Australian panel, so the ported engine nowcasts Australian GDP.

**Architecture:** A new `nyfed/au/` subpackage owns everything Australian: a series registry, fetchers, freshness guards, panel assembly, PCA seeding, and the annualised→QoQ conversion. The engine in `nyfed/` is not modified — the Australian panel reaches it as a `model_spec_AU.csv` plus a standardised `(n, T)` matrix, exactly as the US panel does. Nothing in `nowcasting_v2/` is touched; four series are read from its committed CSVs.

**Tech Stack:** Python 3.11+, numpy, scipy, pandas, `readabs` (ABS and RBA spreadsheet retrieval), pytest.

**Spec:** `docs/superpowers/specs/2026-08-26-nowcast-v3-australian-panel-design.md` — read it first. It records the four governing decisions and what each was chosen against.

## Global Constraints

- **Python 3.11 or newer.** Use `nowcasting_v3/.venv`. Never the system Python (3.9.6).
- **`nowcasting_v3/nyfed_matlab/` is vendored and READ-ONLY.** Never edit it. A merge gate checks `git log -- nowcasting_v3/nyfed_matlab` shows only the vendoring commit.
- **The engine is not modified.** `nyfed/gibbs.py`, `nyfed/ssm.py`, `nyfed/model.py`, `nyfed/nowcast.py`, `nyfed/parameters.py`, `nyfed/updates.py` and `nyfed/linalg.py` are frozen for this plan. If a task appears to need an engine change, stop and report — it means a mirroring assumption broke.
- **The US fixtures must keep passing.** Every task ends with the full suite green, not just the new tests. This is the strongest guard in the project.
- **Two-tier test rule.** Tier 1 (deterministic): match fixtures at `rtol=1e-10` **with an explicit `atol`**, defaulting to `atol=0.0`; where an array holds near-zero entries alongside entries of order 1, derive a floor as `atol = 1e-12 * np.nanmax(np.abs(want))` from the array in code, never a literal. Tier 2 (stochastic): moments within Monte Carlo error; never assert exact equality on a draw.
- **`filterwarnings = ["error"]`** is set in `pyproject.toml`. No ignore entries may be added.
- **`.item()` for fixture scalars.** Never bare `float()`/`int()`, never `.ravel()[0]`.
- **Fixtures stay under 5 MB** (currently 2.6 MB). Australian source fixtures must be small recorded payloads, not full histories.
- **No network access in tests.** Every fetcher test runs against a recorded fixture. A test that hits the ABS is a broken test.
- **The spec CSV must be frequency-sorted**, all `m` rows before all `q` rows. `load_spec` raises otherwise (`nyfed/spec.py:112`).

---

## File Structure

**Created:**

| Path | Responsibility |
|---|---|
| `nowcasting_v3/nyfed/au/__init__.py` | package marker; re-exports `build_panel`, `AU_SERIES` |
| `nowcasting_v3/nyfed/au/sources.py` | `SeriesSource` dataclass and `AU_SERIES`, the 17-entry registry — the single source of truth for what the panel contains |
| `nowcasting_v3/nyfed/au/fetch_abs.py` | ABS retrieval via `readabs.read_abs_series` |
| `nowcasting_v3/nyfed/au/fetch_rba.py` | RBA retrieval via `readabs.read_rba_table` |
| `nowcasting_v3/nyfed/au/fetch_v2.py` | readers for the four series in `nowcasting_v2/data_raw/` |
| `nowcasting_v3/nyfed/au/freshness.py` | staleness policy and the guard that halts a stale run |
| `nowcasting_v3/nyfed/au/panel.py` | assembles the `(n, T)` standardised matrix from fetched series |
| `nowcasting_v3/nyfed/au/initval.py` | PCA seeding of `param.Lambda` |
| `nowcasting_v3/nyfed/au/emit.py` | annualised → QoQ conversion (spec D4) |
| `nowcasting_v3/model_spec_AU.csv` | the 17-row spec, frequency-sorted |
| `nowcasting_v3/tests/test_au_*.py` | one test module per source file |
| `nowcasting_v3/tests/fixtures/au/` | small recorded source payloads |

**Modified:** none in `nyfed/`. `pyproject.toml` gains one dependency.

---

## Task 1: The series registry and the Australian spec CSV

This task locks in what the panel *is*. Everything downstream reads from it.

**Files:**
- Create: `nowcasting_v3/nyfed/au/__init__.py`, `nowcasting_v3/nyfed/au/sources.py`, `nowcasting_v3/model_spec_AU.csv`
- Test: `nowcasting_v3/tests/test_au_sources.py`

**Interfaces:**
- Consumes: `nyfed.spec.load_spec`, `nyfed.spec.ModelSpec`
- Produces:
  - `SeriesSource` dataclass with fields `key: str`, `series_id: str`, `name: str`, `fetcher: str`, `locator: str`, `frequency: str`, `max_age_days: int`
  - `AU_SERIES: tuple[SeriesSource, ...]` — 17 entries, monthly first then quarterly
  - `SPEC_PATH: Path` pointing at `model_spec_AU.csv`

### Mirroring rule

Every spec value is copied from the series' NY Fed counterpart. Do not invent transformations, trends or priors. The counterpart values, extracted from `nyfed_matlab/model_spec_FRED.csv`:

| Australian series | US counterpart | Freq | Trend | Prior | Transformation | G,S,N,L,C |
|---|---|---|---|---|---|---|
| Employment | PAYEMS | m | 0 | 1 | chg | 1,0,0,**100**,**100** |
| Unemployment rate | UNRATE | m | 0 | −1 | chg | 1,0,0,1,1 |
| ANZ-Indeed Job Ads | JTSJOL | m | 0 | 1 | chg | 1,0,0,1,1 |
| Internet Vacancy Index | ADPMNUSNERSA | m | 0 | 1 | chg | 1,0,0,1,1 |
| AiG Manufacturing PMI | GACDISA066MSFRBNY | m | 0 | 1 | lin | 1,1,0,0,1 |
| NAB Business Conditions | GACDFSA066MSFRBPHI | m | 0 | 1 | lin | 1,1,0,0,1 |
| Building Approvals | PERMIT | m | 0 | 1 | chg | 1,0,0,0,1 |
| Retail Sales | RSAFS | m | 0 | 1 | pch | 1,0,1,0,1 |
| Household Spending (real) | PCEC96 | m | 0 | 1 | pch | 1,0,0,0,1 |
| Exports | BOPTEXP | m | 0 | 1 | pch | 1,0,1,0,1 |
| Imports | BOPTIMP | m | 0 | 1 | pch | 1,0,1,0,1 |
| RBA Commodity Price Index | IQ | m | 0 | 0 | pch | 1,0,1,0,0 |
| Monthly CPI | CPIAUCSL | m | 0 | 0 | pch | 1,0,1,0,0 |
| Monthly CPI trimmed mean | CPILFESL | m | 0 | 0 | pch | 1,0,1,0,0 |
| Unit labour cost | PRS85006112 | q | 0 | 0 | pca | 1,0,0,1,0 |
| Real GDI | A261RX1Q020SBEA | q | 1 | 1 | pca | 1,0,0,0,1 |
| **Real GDP (target)** | GDPC1 | q | 1 | 1 | pca | 1,0,0,0,1 |

### The normalisation decision — read this before writing the CSV

Block values encode three states (`nyfed/spec.py:93-95`): `0` means the series does not load on that factor, `1` means an unrestricted loading to be estimated, and any value `>1` means a **normalising** loading fixed at 1.0, which sets that factor's scale.

The NY Fed panel normalises with three series:

- **Global** ← `INDPRO` (industrial production)
- **Nominal** ← `PCEPI` (PCE chain price index)
- **Labour and COVID** ← `PAYEMS` (total nonfarm payrolls)

**Two of those three have no Australian counterpart.** Industrial production and the PCE price index are both in the fourteen missing series. Only PAYEMS maps, to Employment. So Australia must nominate its own scale-setters for Global and Nominal. This is a modelling decision, not a translation, and the plan document flags it as such under Plan B task B2.

**The choices, with reasoning:**

- **Global ← Household Spending (real).** `INDPRO` is the broadest monthly real-activity series in the US panel. Australia's broadest monthly real-activity series is the Monthly Household Spending Indicator, deflated. Retail sales was considered and rejected: v2's own panel notes record its pre-COVID correlation with GDP growth at +0.06 against household spending's +0.29, and a weak series is a poor thing to fix a factor's scale to.
- **Nominal ← Monthly CPI.** `PCEPI` is the US panel's headline consumption deflator. Australia's monthly headline price index is the ABS Monthly CPI Indicator. Direct analogue.
- **Labour and COVID ← Employment**, mirroring PAYEMS exactly.

Encode the normalisers as `100`, matching the NY Fed's own convention.

- [ ] **Step 1: Write the failing test**

`nowcasting_v3/tests/test_au_sources.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd nowcasting_v3 && .venv/bin/pytest tests/test_au_sources.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'nyfed.au'`

- [ ] **Step 3: Write the registry**

`nowcasting_v3/nyfed/au/__init__.py`:

```python
"""The Australian panel for the v3 nowcast engine.

The engine in ``nyfed/`` is panel-agnostic: it consumes a spec CSV and a
standardised ``(n, T)`` matrix. This subpackage produces the Australian
versions of both and changes nothing in the engine.
"""

from nyfed.au.sources import AU_SERIES, SPEC_PATH, SeriesSource

__all__ = ["AU_SERIES", "SPEC_PATH", "SeriesSource"]
```

`nowcasting_v3/nyfed/au/sources.py`:

```python
"""The 17-series Australian panel registry.

One entry per series, in spec CSV row order: monthly first, then quarterly.
``load_spec`` permutes its fields by frequency and raises if that permutation
is not the identity (``nyfed/spec.py:112``), because the data panel is built in
raw CSV order and is never permuted with it. So this order is load-bearing.

``fetcher`` names the module that retrieves the series and ``locator`` is that
fetcher's argument: an ABS series id, an RBA table code, or a v2 CSV stem.

``max_age_days`` is the staleness budget enforced in ``freshness.py``. It is
set from the publication cycle plus a tolerance, not from convenience: three
Australian monthly indicators were discontinued between March 2025 and June
2026, and a discontinued series does not raise an error, it just stops
updating.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

SPEC_PATH = Path(__file__).resolve().parents[2] / "model_spec_AU.csv"


@dataclass(frozen=True)
class SeriesSource:
    """Where one panel series comes from and how stale it may be."""

    key: str
    series_id: str
    name: str
    fetcher: str      # "abs" | "rba" | "v2"
    locator: str
    frequency: str    # "m" | "q"
    max_age_days: int


AU_SERIES: tuple[SeriesSource, ...] = (
    # --- monthly -----------------------------------------------------------
    SeriesSource("employment", "employment", "Employment",
                 "abs", "6202.0:A84423043C", "m", 45),
    SeriesSource("unemployment_rate", "unemployment_rate", "Unemployment rate",
                 "abs", "6202.0:A84423050A", "m", 45),
    SeriesSource("job_ads", "job_ads", "ANZ-Indeed Job Ads",
                 "v2", "anz_ads", "m", 45),
    SeriesSource("vacancy_index", "vacancy_index", "Internet Vacancy Index",
                 "v2", "ivi", "m", 60),
    SeriesSource("aig_pmi", "aig_pmi", "AiG Manufacturing PMI",
                 "v2", "aig_pmi", "m", 45),
    SeriesSource("nab_conditions", "nab_conditions", "NAB Business Conditions",
                 "v2", "nab_cond", "m", 45),
    SeriesSource("building_approvals", "building_approvals", "Building Approvals",
                 "abs", "8731.0:A422070J", "m", 60),
    SeriesSource("retail_sales", "retail_sales", "Retail Sales",
                 "abs", "8501.0:A3348585R", "m", 60),
    SeriesSource("household_spending", "household_spending",
                 "Household Spending (real)",
                 "abs", "5682.0:A130200584T", "m", 60),
    SeriesSource("exports", "exports", "Exports",
                 "abs", "5368.0:A2718577A", "m", 60),
    SeriesSource("imports", "imports", "Imports",
                 "abs", "5368.0:RESOLVE_IMPORTS", "m", 60),
    SeriesSource("commodity_prices", "commodity_prices",
                 "RBA Index of Commodity Prices",
                 "rba", "I2", "m", 45),
    SeriesSource("cpi", "cpi", "Monthly CPI",
                 "abs", "6484.0:RESOLVE_CPI", "m", 60),
    SeriesSource("cpi_trimmed", "cpi_trimmed", "Monthly CPI trimmed mean",
                 "abs", "6484.0:RESOLVE_CPI_TRIMMED", "m", 60),
    # --- quarterly ---------------------------------------------------------
    SeriesSource("unit_labour_cost", "unit_labour_cost", "Unit labour cost",
                 "abs", "5206.0:RESOLVE_ULC", "q", 120),
    SeriesSource("gdi", "gdi", "Real gross domestic income",
                 "abs", "5206.0:RESOLVE_GDI", "q", 120),
    SeriesSource("gdp", "gdp", "Real gross domestic product",
                 "abs", "5206.0:RESOLVE_GDP", "q", 120),
)
```

Six locators carry a `RESOLVE_` placeholder — `imports`, `cpi`, `cpi_trimmed`, `unit_labour_cost`, `gdi` and `gdp`. **These are resolved in Task 2, not invented here** — Task 2's first step is a discovery step with a test that pins each resolved id. Leaving them visibly unresolved is deliberate: a wrong ABS series id silently returns a different economic series, so it must be a step with its own gate rather than a value copied from memory.

- [ ] **Step 4: Write the spec CSV**

`nowcasting_v3/model_spec_AU.csv` — column order and header names must match what `load_spec` expects (`nyfed/spec.py:68-100`):

```csv
SeriesID,SeriesName,Frequency,Trend,Block0_Global,Block1_Soft,Block2_Nominal,Block3_Labor,Block4_COVID,Prior,Units,Transformation,Category
employment,Employment,m,0,1,0,0,100,100,1,Thousands,chg,Labor
unemployment_rate,Unemployment rate,m,0,1,0,0,1,1,-1,Percent,chg,Labor
job_ads,ANZ-Indeed Job Ads,m,0,1,0,0,1,1,1,Index,chg,Labor
vacancy_index,Internet Vacancy Index,m,0,1,0,0,1,1,1,Index,chg,Labor
aig_pmi,AiG Manufacturing PMI,m,0,1,1,0,0,1,1,Index,lin,Surveys
nab_conditions,NAB Business Conditions,m,0,1,1,0,0,1,1,Index,lin,Surveys
building_approvals,Building Approvals,m,0,1,0,0,0,1,1,Number,chg,Housing and Construction
retail_sales,Retail Sales,m,0,1,0,1,0,1,1,Millions of Dollars,pch,Retail and Consumption
household_spending,Household Spending (real),m,0,100,0,0,0,1,1,Millions of Dollars,pch,Retail and Consumption
exports,Exports,m,0,1,0,1,0,1,1,Millions of Dollars,pch,International Trade
imports,Imports,m,0,1,0,1,0,1,1,Millions of Dollars,pch,International Trade
commodity_prices,RBA Index of Commodity Prices,m,0,1,0,1,0,0,0,Index,pch,International Trade
cpi,Monthly CPI,m,0,1,0,100,0,0,0,Index,pch,Prices
cpi_trimmed,Monthly CPI trimmed mean,m,0,1,0,1,0,0,0,Index,pch,Prices
unit_labour_cost,Unit labour cost,q,0,1,0,0,1,0,0,Index,pca,Labor
gdi,Real gross domestic income,q,1,1,0,0,0,1,1,Millions of Dollars,pca,Income
gdp,Real gross domestic product,q,1,1,0,0,0,1,1,Millions of Dollars,pca,Income
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd nowcasting_v3 && .venv/bin/pytest tests/test_au_sources.py -q`
Expected: 8 passed

- [ ] **Step 6: Run the full suite**

Run: `cd nowcasting_v3 && caffeinate -i .venv/bin/pytest -q`
Expected: 157 US tests still passing plus the new ones. **The machine has slept mid-run before and killed the process; `caffeinate -i` prevents it.**

- [ ] **Step 7: Commit**

```bash
git add nowcasting_v3/nyfed/au/__init__.py nowcasting_v3/nyfed/au/sources.py \
        nowcasting_v3/model_spec_AU.csv nowcasting_v3/tests/test_au_sources.py
git commit -m "feat(v3): Australian series registry and spec CSV"
```

---

## Task 2: Resolve the ABS series ids and build the ABS fetcher

**Files:**
- Create: `nowcasting_v3/nyfed/au/fetch_abs.py`
- Modify: `nowcasting_v3/nyfed/au/sources.py` (replace the five `RESOLVE_` locators)
- Modify: `nowcasting_v3/pyproject.toml` (add `readabs`)
- Test: `nowcasting_v3/tests/test_au_fetch_abs.py`
- Fixtures: `nowcasting_v3/tests/fixtures/au/abs_*.csv`

**Interfaces:**
- Consumes: `nyfed.au.sources.AU_SERIES`, `nyfed.au.sources.SeriesSource`
- Produces:
  - `fetch_abs_series(locator: str, *, cache_dir: Path | None = None) -> pd.Series` — a `DatetimeIndex`-keyed float series, index normalised to first-of-month, sorted ascending, no duplicate dates
  - `parse_abs_frame(frame: pd.DataFrame, series_id: str) -> pd.Series` — the pure parsing half, unit-testable from a fixture with no network

### Resolving the six unknown ids

`readabs` retrieves by catalogue and series id. The six unresolved series are imports (5368.0), monthly CPI and its trimmed mean (6484.0), and unit labour cost, GDI and GDP (5206.0).

Resolve each with `readabs.read_abs_cat` and a description match, then **pin the resolved id in a test** so it cannot drift:

```python
import readabs as ra

frames, meta = ra.read_abs_cat(cat="5368.0")
matches = meta[meta["Data Item Description"].str.contains(
    "Imports of goods and services", case=False, na=False
)]
print(matches[["Series ID", "Data Item Description", "Series Type", "Frequency"]])
```

Pick the seasonally adjusted, chain-volume-measure variant where one exists — that is what the NY Fed counterpart uses. Record the chosen id **and one verified observation** (a date and its published value, read off the ABS release) in the test below. That observation is the gate: a wrong id returns a real series with plausible numbers, and only a known value catches it.

- [ ] **Step 1: Add the dependency**

In `nowcasting_v3/pyproject.toml`, extend the `dependencies` list:

```toml
dependencies = ["numpy>=2.0", "scipy>=1.14", "pandas>=2.2", "readabs>=0.2.6"]
```

Install: `cd nowcasting_v3 && .venv/bin/pip install 'readabs>=0.2.6'`

- [ ] **Step 2: Record fixtures**

Write a throwaway script that fetches each of the eleven ABS series once and saves a **trimmed** copy — the last 36 observations only — to `tests/fixtures/au/abs_<key>.csv` with columns `date,value`. Eleven files of ~36 rows keeps the fixture directory well inside its 5 MB budget.

```python
# tools/record_au_fixtures.py  (throwaway; do not commit)
from pathlib import Path
import readabs as ra
from nyfed.au.sources import AU_SERIES

out = Path("tests/fixtures/au")
out.mkdir(parents=True, exist_ok=True)
for s in AU_SERIES:
    if s.fetcher != "abs":
        continue
    cat, sid = s.locator.split(":")
    frame, _ = ra.read_abs_series(cat=cat, series_id=sid)
    frame.tail(36).to_csv(out / f"abs_{s.key}.csv")
```

- [ ] **Step 3: Write the failing test**

`nowcasting_v3/tests/test_au_fetch_abs.py`:

```python
"""ABS retrieval, tested offline against recorded payloads.

No test here touches the network. The fetcher is split so the parsing half is
pure: `parse_abs_frame` takes the frame readabs would have returned.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from nyfed.au.fetch_abs import parse_abs_frame
from nyfed.au.sources import AU_SERIES

FIXTURES = Path(__file__).parent / "fixtures" / "au"
ABS_SERIES = [s for s in AU_SERIES if s.fetcher == "abs"]


def _fixture_frame(key: str) -> pd.DataFrame:
    return pd.read_csv(FIXTURES / f"abs_{key}.csv", index_col=0, parse_dates=True)


def test_every_abs_series_has_a_recorded_fixture():
    """Same guard as the US fixtures: a missing payload must fail, not skip."""
    missing = [s.key for s in ABS_SERIES if not (FIXTURES / f"abs_{s.key}.csv").is_file()]
    assert not missing, f"no recorded fixture for {missing}"


def test_no_locator_is_left_unresolved():
    unresolved = [s.key for s in AU_SERIES if "RESOLVE_" in s.locator]
    assert not unresolved, f"unresolved ABS ids: {unresolved}"


@pytest.mark.parametrize("source", ABS_SERIES, ids=lambda s: s.key)
def test_parsed_series_is_clean(source):
    parsed = parse_abs_frame(_fixture_frame(source.key), source.locator.split(":")[1])
    assert isinstance(parsed.index, pd.DatetimeIndex)
    assert parsed.index.is_monotonic_increasing
    assert not parsed.index.has_duplicates
    assert (parsed.index.day == 1).all(), "dates must be normalised to first-of-month"
    assert parsed.dtype == np.float64
    assert parsed.notna().any()


@pytest.mark.parametrize("source", ABS_SERIES, ids=lambda s: s.key)
def test_frequency_matches_the_registry(source):
    parsed = parse_abs_frame(_fixture_frame(source.key), source.locator.split(":")[1])
    gaps = parsed.index.to_series().diff().dt.days.dropna()
    step = gaps.median()
    if source.frequency == "m":
        assert 28 <= step <= 31
    else:
        assert 89 <= step <= 92


# Replace each placeholder below with an observation you read off the ABS
# release for that series, then keep it. A wrong series id returns a real
# series with plausible numbers; only a known value catches it.
@pytest.mark.parametrize(
    "key,date,expected",
    [
        ("employment", "2025-06-01", None),
        ("unemployment_rate", "2025-06-01", None),
        ("imports", "2025-06-01", None),
        ("cpi", "2025-06-01", None),
        ("gdp", "2025-04-01", None),
    ],
)
def test_a_verified_observation_pins_the_series_id(key, date, expected):
    if expected is None:
        pytest.fail(
            f"pin {key} at {date} to a value verified against the ABS release "
            "before this task can be marked complete"
        )
    source = next(s for s in AU_SERIES if s.key == key)
    parsed = parse_abs_frame(_fixture_frame(key), source.locator.split(":")[1])
    assert parsed.loc[pd.Timestamp(date)] == pytest.approx(expected, rel=1e-6)
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `cd nowcasting_v3 && .venv/bin/pytest tests/test_au_fetch_abs.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'nyfed.au.fetch_abs'`

- [ ] **Step 5: Write the fetcher**

`nowcasting_v3/nyfed/au/fetch_abs.py`:

```python
"""ABS time series retrieval.

Split in two so the parsing half is pure and testable without a network:
``fetch_abs_series`` does the retrieval, ``parse_abs_frame`` does everything
else. Every test in this project exercises the second half only.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def parse_abs_frame(frame: pd.DataFrame, series_id: str) -> pd.Series:
    """Tidy one readabs frame into a first-of-month float series.

    ABS spreadsheets date monthly observations to the last day of the month
    and quarterly ones to the last day of the quarter. The panel indexes by
    first-of-month throughout, so normalise here rather than at every caller.
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
        index=pd.DatetimeIndex(frame.index).to_period("M").to_timestamp(),
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
```

- [ ] **Step 6: Resolve the five ids and pin the observations**

Run the resolution snippet from this task's preamble for each unresolved series, edit the five locators in `sources.py`, and replace the five `None` values in `test_a_verified_observation_pins_the_series_id` with values read off the ABS release. `test_no_locator_is_left_unresolved` fails until this is done.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `cd nowcasting_v3 && .venv/bin/pytest tests/test_au_fetch_abs.py -q`
Expected: all passed, no skips

- [ ] **Step 8: Run the full suite, then commit**

```bash
cd nowcasting_v3 && caffeinate -i .venv/bin/pytest -q
git add nowcasting_v3/nyfed/au/fetch_abs.py nowcasting_v3/nyfed/au/sources.py \
        nowcasting_v3/pyproject.toml nowcasting_v3/tests/test_au_fetch_abs.py \
        nowcasting_v3/tests/fixtures/au
git commit -m "feat(v3): ABS fetcher, with every series id pinned by a verified observation"
```

---

## Task 3: The RBA and v2 readers

Two small retrieval paths, same shape as Task 2, reviewed together because neither carries its own judgement.

**Files:**
- Create: `nowcasting_v3/nyfed/au/fetch_rba.py`, `nowcasting_v3/nyfed/au/fetch_v2.py`
- Test: `nowcasting_v3/tests/test_au_fetch_rba.py`, `nowcasting_v3/tests/test_au_fetch_v2.py`
- Fixtures: `nowcasting_v3/tests/fixtures/au/rba_I2.csv`

**Interfaces:**
- Consumes: `nyfed.au.sources.AU_SERIES`
- Produces:
  - `fetch_rba_series(table: str, *, column: str) -> pd.Series` — same contract as `fetch_abs_series`
  - `parse_rba_frame(frame: pd.DataFrame, column: str) -> pd.Series`
  - `read_v2_series(stem: str, *, root: Path | None = None) -> pd.Series` — reads `nowcasting_v2/data_raw/<stem>.csv`
  - `V2_DATA_ROOT: Path`

- [ ] **Step 1: Write the failing tests**

`nowcasting_v3/tests/test_au_fetch_v2.py`:

```python
"""Readers for the four series v2 already fetches and commits.

These are the media-release and PDF sources -- job ads, the vacancy index, the
AiG PMI and NAB conditions. v2 fetches them weekly into committed CSVs; v3
reads those rather than rebuilding the scraping.
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
```

`nowcasting_v3/tests/test_au_fetch_rba.py`:

```python
"""RBA table retrieval, tested offline against a recorded payload."""

from pathlib import Path

import numpy as np
import pandas as pd

from nyfed.au.fetch_rba import parse_rba_frame

FIXTURES = Path(__file__).parent / "fixtures" / "au"


def test_the_commodity_price_fixture_is_recorded():
    assert (FIXTURES / "rba_I2.csv").is_file()


def test_the_commodity_index_parses_to_a_monthly_float_series():
    frame = pd.read_csv(FIXTURES / "rba_I2.csv", index_col=0, parse_dates=True)
    parsed = parse_rba_frame(frame, column=frame.columns[0])
    assert isinstance(parsed.index, pd.DatetimeIndex)
    assert parsed.index.is_monotonic_increasing
    assert (parsed.index.day == 1).all()
    assert parsed.dtype == np.float64
    gaps = parsed.index.to_series().diff().dt.days.dropna()
    assert 28 <= gaps.median() <= 31
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd nowcasting_v3 && .venv/bin/pytest tests/test_au_fetch_rba.py tests/test_au_fetch_v2.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Record the RBA fixture**

```python
import readabs as ra
frame, _ = ra.read_rba_table("I2")
frame.tail(36).to_csv("tests/fixtures/au/rba_I2.csv")
```

Inspect the columns and choose the A$ index of commodity prices, all items. Record which column you chose in the docstring of `fetch_rba.py` — the table carries several indices and the wrong column is a different economic series.

- [ ] **Step 4: Write the readers**

`nowcasting_v3/nyfed/au/fetch_rba.py`:

```python
"""RBA statistical table retrieval.

Table I2 is the Index of Commodity Prices. It carries several indices -- A$,
US$, SDR, and sub-indices by commodity group. The panel uses the **A$ all
items** index: Australia's GDP is denominated in A$, and the Q1 2026 miss this
series exists to address was an A$ terms-of-trade shock.
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
    import readabs as ra

    frame, _meta = ra.read_rba_table(table)
    return parse_rba_frame(frame, column)
```

`nowcasting_v3/nyfed/au/fetch_v2.py`:

```python
"""Readers for the four panel series that v2 fetches and commits.

v3 does not import from v2 and does not run its R code. It reads the CSVs v2's
weekly routine commits to ``nowcasting_v2/data_raw/``. Those four series -- job
ads, the vacancy index, the AiG PMI and NAB conditions -- originate in media
releases and PDFs, and rebuilding that scraping in Python would duplicate a
working thing.

The dependency is real and one-directional: if v2's weekly routine stops, these
files go stale. ``freshness.py`` is what turns that into a halt rather than a
silently old nowcast.
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
    date_col = next(c for c in raw.columns if c.lower() in ("date", "ref_date", "time"))
    value_col = next(c for c in raw.columns if c != date_col)
    series = pd.Series(
        pd.to_numeric(raw[value_col], errors="coerce").to_numpy(dtype=float),
        index=pd.DatetimeIndex(raw[date_col]).to_period("M").to_timestamp(),
        name=stem,
    )
    return series[~series.index.duplicated(keep="last")].sort_index()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd nowcasting_v3 && .venv/bin/pytest tests/test_au_fetch_rba.py tests/test_au_fetch_v2.py -q`
Expected: all passed

- [ ] **Step 6: Run the full suite, then commit**

```bash
cd nowcasting_v3 && caffeinate -i .venv/bin/pytest -q
git add nowcasting_v3/nyfed/au/fetch_rba.py nowcasting_v3/nyfed/au/fetch_v2.py \
        nowcasting_v3/tests/test_au_fetch_rba.py nowcasting_v3/tests/test_au_fetch_v2.py \
        nowcasting_v3/tests/fixtures/au/rba_I2.csv
git commit -m "feat(v3): RBA commodity fetcher and v2 CSV readers"
```

---

## Task 4: Freshness guards

The spec calls this the most important operational requirement in the design. A discontinued series does not raise an error — it stops updating.

**Files:**
- Create: `nowcasting_v3/nyfed/au/freshness.py`
- Test: `nowcasting_v3/tests/test_au_freshness.py`

**Interfaces:**
- Consumes: `nyfed.au.sources.AU_SERIES`, `nyfed.au.sources.SeriesSource`
- Produces:
  - `StaleSeriesError(Exception)` with attribute `stale: list[tuple[str, int, int]]` — `(key, age_days, max_age_days)`
  - `check_freshness(series: dict[str, pd.Series], asof: pd.Timestamp, *, sources=AU_SERIES) -> None` — raises `StaleSeriesError` naming every stale series, or returns `None`
  - `series_age_days(s: pd.Series, asof: pd.Timestamp) -> int`

- [ ] **Step 1: Write the failing test**

`nowcasting_v3/tests/test_au_freshness.py`:

```python
"""Staleness guards.

Three Australian monthly indicators were discontinued between March 2025 and
June 2026. A discontinued series does not error -- it stops updating. Without
these guards the model would keep nowcasting from a series that no longer
exists and nothing would say so.
"""

import pandas as pd
import pytest

from nyfed.au.freshness import StaleSeriesError, check_freshness, series_age_days
from nyfed.au.sources import AU_SERIES, SeriesSource

ASOF = pd.Timestamp("2026-08-01")


def _series(last: str, n: int = 24, freq: str = "MS") -> pd.Series:
    idx = pd.date_range(end=pd.Timestamp(last), periods=n, freq=freq)
    return pd.Series(range(n), index=idx, dtype=float)


def _sources(*specs) -> tuple[SeriesSource, ...]:
    return tuple(
        SeriesSource(k, k, k, "abs", "x:y", f, age) for k, f, age in specs
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
    sources = _sources(("a", "m", 45), ("b", "m", 45))
    check_freshness({"a": _series("2026-07-01"), "b": _series("2026-07-01")},
                    ASOF, sources=sources)


def test_a_stale_series_raises_and_names_itself():
    sources = _sources(("fresh", "m", 45), ("dead", "m", 45))
    with pytest.raises(StaleSeriesError) as excinfo:
        check_freshness({"fresh": _series("2026-07-01"), "dead": _series("2026-01-01")},
                        ASOF, sources=sources)
    assert "dead" in str(excinfo.value)
    assert "fresh" not in str(excinfo.value)
    assert [k for k, _, _ in excinfo.value.stale] == ["dead"]


def test_every_stale_series_is_reported_not_just_the_first():
    """Reporting one at a time turns one broken feed into three debug cycles."""
    sources = _sources(("a", "m", 45), ("b", "m", 45), ("c", "m", 45))
    with pytest.raises(StaleSeriesError) as excinfo:
        check_freshness(
            {"a": _series("2026-01-01"), "b": _series("2026-07-01"),
             "c": _series("2025-11-01")},
            ASOF, sources=sources,
        )
    assert [k for k, _, _ in excinfo.value.stale] == ["a", "c"]


def test_a_missing_series_is_stale_not_absent():
    sources = _sources(("a", "m", 45), ("gone", "m", 45))
    with pytest.raises(StaleSeriesError) as excinfo:
        check_freshness({"a": _series("2026-07-01")}, ASOF, sources=sources)
    assert "gone" in str(excinfo.value)


def test_every_registered_series_declares_a_positive_budget():
    assert all(s.max_age_days > 0 for s in AU_SERIES)


def test_quarterly_budgets_exceed_monthly_ones():
    monthly = max(s.max_age_days for s in AU_SERIES if s.frequency == "m")
    quarterly = min(s.max_age_days for s in AU_SERIES if s.frequency == "q")
    assert quarterly > monthly
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd nowcasting_v3 && .venv/bin/pytest tests/test_au_freshness.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'nyfed.au.freshness'`

- [ ] **Step 3: Write the guard**

`nowcasting_v3/nyfed/au/freshness.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd nowcasting_v3 && .venv/bin/pytest tests/test_au_freshness.py -q`
Expected: 9 passed

- [ ] **Step 5: Run the full suite, then commit**

```bash
cd nowcasting_v3 && caffeinate -i .venv/bin/pytest -q
git add nowcasting_v3/nyfed/au/freshness.py nowcasting_v3/tests/test_au_freshness.py
git commit -m "feat(v3): freshness guards that halt on a stale or discontinued series"
```

---

## Task 5: Panel assembly

**Files:**
- Create: `nowcasting_v3/nyfed/au/panel.py`
- Test: `nowcasting_v3/tests/test_au_panel.py`

**Interfaces:**
- Consumes: all three fetchers, `check_freshness`, `nyfed.spec.load_spec`
- Produces:
  - `Panel` dataclass: `Y: np.ndarray` `(n, T)` standardised; `y_location: np.ndarray` `(n, 1)`; `y_scale: np.ndarray` `(n, 1)`; `dates: pd.DatetimeIndex` length `T`; `series_id: list[str]`; `i_now: int`
  - `assemble(series: dict[str, pd.Series], *, start: str, end: str, spec_path=SPEC_PATH) -> Panel`
  - `standardise(raw: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]`

Quarterly series occupy the **last month of their quarter** and are NaN in the other two, which is how `construct_ssm` expects mixed frequency (`nyfed/model.py`, the `isquart` branch).

### Household spending must be deflated to real — added 2026-08-26

The registry fetches `5682.0:A130200584T`, which is the Monthly Household Spending Indicator
**at current prices** — nominal, seasonally adjusted. The spec row calls it "Household
Spending (real)" and mirrors the NY Fed's `PCEC96`, which is *real* personal consumption
expenditures. Its transformation is `pch`, so a nominal series carries inflation straight
into the factor, and this series **normalises the Global factor**, so its scale sets that
factor's scale.

This is not hypothetical. v2 found it empirically and recorded it in its panel notes: nominal
MHSI over-read real GDP through the 2024 inflation — 2024 mean 3-month nominal 0.82% against
real 0.19%, with real GDP around 0.4%.

Queried against the ABS catalogue, the available variants are:

| variant | series | note |
|---|---|---|
| monthly, nominal, seasonally adjusted | `A130200584T` | what the registry fetches |
| monthly, real (chain volume), **Original** | `A130265220L` | not seasonally adjusted |
| quarterly, real, seasonally adjusted | `A130271111R` | 48 obs, 2014Q3–2026Q2 |

**There is no monthly real seasonally-adjusted series**, so a monthly panel row mirroring
`PCEC96` must be derived by deflation.

**Deflate by a spliced monthly CPI, falling back to the quarterly index only where no
monthly one exists.** Amended 2026-08-26 on James's instruction, replacing an earlier ruling
that mirrored v2's quarterly-interpolated method.

v2 deflates with the quarterly All-groups CPI interpolated to monthly. That invents
within-quarter price movement that never happened — its derived `cpi_monthly.csv` runs back to
1948-09, and no monthly Australian CPI reaches 1948. v2 will be fixed separately; v3 should
not ship the same method.

**Australia's monthly CPI history is split across a dead publication and a live one**, verified
by querying the catalogue:

| source | series | coverage |
|---|---|---|
| `6484.0` Monthly CPI Indicator — **ceased Sept 2025**, frozen page still serves data | All-groups monthly | ~2018 → Sept 2025 |
| `6401.0` live | `A130607789R`, All groups CPI, seasonally adjusted | 2024-04 → current (28 obs at 2026-08) |
| `6401.0` quarterly | `A2325846C`, All groups CPI | 1948Q3 → current (312 obs) |

Household spending (`A130200584T`) starts **2012-07**, so a monthly-only deflator would cut six
years off the series that normalises the Global factor. Hence the hybrid.

**Build the deflator in this precedence, most-preferred first:**

1. `6401.0:A130607789R` where present (2024-04 onward)
2. the `6484.0` monthly indicator where present (~2018 → 2025-09) — needs a URL override, the
   same mechanism the ceased Retail Trade catalogue required; it was removed from
   `fetch_abs.py` when CPI moved catalogues and must come back for this
3. `6401.0:A2325846C` interpolated to monthly, for everything earlier

**Splice by ratio, not by concatenation.** The three sources are index numbers on different
bases. Joining them end-to-end puts a step change in the deflator at each seam, which becomes
a spurious spike in deflated household spending — and `pch` turns a spike into a large false
month. At each join, rescale the older series by the ratio of the two series over their
overlap, so the level is continuous.

**Two tests, both of which must be able to fail:**

- The spliced monthly deflator and the quarterly-interpolated one agree within 1% across their
  overlap. A bad rebase shows up here immediately.
- The deflated household spending series **starts at the same month as the nominal one**
  (2012-07). A deflator that silently truncates history would quietly shorten the panel's
  longest consumption record, and the model would run.

### `imports` is negative — carried from Task 2's review

ABS reports imports as a **debit**, so the series enters the panel negative: 2026-06 is
`-45768.0` against `exports` at `+47696.0`. That is correct and is documented in the series'
pin.

It is safe **only if `pch` is implemented as a ratio**. If it is implemented as a log
difference — the common form, and the vendored MATLAB carries no transform code to copy from —
`imports` becomes **all-NaN with no error raised**, and the panel would quietly lose a series.

Assert it: after assembly, `imports` must have at least as many non-NaN observations as
`exports` over the same span. That fails loudly the moment a log transform swallows it.

- [ ] **Step 1: Write the failing test**

`nowcasting_v3/tests/test_au_panel.py`:

```python
"""Panel assembly.

The panel is data, so it is tested like data: ragged edges, histories that
start decades apart, and quarterly series landing in the right month.
"""

import numpy as np
import pandas as pd
import pytest

from nyfed.au.panel import Panel, assemble, standardise
from nyfed.au.sources import AU_SERIES

START, END = "1990-01-01", "2026-06-01"


def _monthly(start: str, end: str, value: float = 1.0) -> pd.Series:
    idx = pd.date_range(start, end, freq="MS")
    return pd.Series(np.arange(len(idx), dtype=float) + value, index=idx)


def _quarterly(start: str, end: str) -> pd.Series:
    idx = pd.date_range(start, end, freq="QE").to_period("M").to_timestamp()
    return pd.Series(np.arange(len(idx), dtype=float), index=idx)


def _panel_inputs() -> dict[str, pd.Series]:
    out = {}
    for s in AU_SERIES:
        out[s.key] = _monthly(START, END) if s.frequency == "m" else _quarterly(START, END)
    return out


def test_standardise_returns_zero_mean_unit_variance_ignoring_nan():
    raw = np.array([[1.0, 2.0, np.nan, 4.0], [10.0, 20.0, 30.0, np.nan]])
    Y, loc, scale = standardise(raw)
    assert loc.shape == (2, 1) and scale.shape == (2, 1)
    assert np.nanmean(Y, axis=1) == pytest.approx([0.0, 0.0], abs=1e-12)
    assert np.nanstd(Y, axis=1, ddof=1) == pytest.approx([1.0, 1.0], abs=1e-12)
    assert np.isnan(Y[0, 2]) and np.isnan(Y[1, 3])


def test_standardise_leaves_a_constant_series_at_zero_rather_than_dividing_by_zero():
    Y, _, scale = standardise(np.array([[3.0, 3.0, 3.0]]))
    assert np.isfinite(Y).all()
    assert scale[0, 0] == 1.0


def test_panel_shape_and_row_order_follow_the_spec():
    panel = assemble(_panel_inputs(), start=START, end=END)
    assert isinstance(panel, Panel)
    assert panel.Y.shape[0] == 17
    assert panel.series_id == [s.series_id for s in AU_SERIES]
    assert panel.Y.shape[1] == len(panel.dates)


def test_gdp_is_i_now():
    panel = assemble(_panel_inputs(), start=START, end=END)
    assert panel.series_id[panel.i_now] == "gdp"


def test_quarterly_series_sit_in_the_last_month_of_their_quarter():
    panel = assemble(_panel_inputs(), start=START, end=END)
    row = panel.series_id.index("gdp")
    observed = panel.dates[~np.isnan(panel.Y[row])]
    assert set(observed.month) == {3, 6, 9, 12}


def test_a_series_that_starts_late_is_nan_before_it_starts_not_zero():
    """Household spending starts in 2012. Filling with zero would be inventing
    data; the Kalman filter handles NaN natively."""
    inputs = _panel_inputs()
    inputs["household_spending"] = _monthly("2012-07-01", END)
    panel = assemble(inputs, start=START, end=END)
    row = panel.series_id.index("household_spending")
    before = panel.dates < pd.Timestamp("2012-07-01")
    assert np.isnan(panel.Y[row, before]).all()
    assert not np.isnan(panel.Y[row, ~before]).all()


def test_a_ragged_edge_is_preserved():
    """Series end on different dates. The most recent months are the whole
    point of a nowcast, so a short series must not truncate the panel."""
    inputs = _panel_inputs()
    inputs["nab_conditions"] = _monthly(START, "2026-04-01")
    panel = assemble(inputs, start=START, end=END)
    row = panel.series_id.index("nab_conditions")
    assert np.isnan(panel.Y[row, -2:]).all()
    assert panel.dates[-1] == pd.Timestamp(END)


def test_assembly_refuses_a_panel_missing_a_registered_series():
    inputs = _panel_inputs()
    del inputs["exports"]
    with pytest.raises(KeyError, match="exports"):
        assemble(inputs, start=START, end=END)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd nowcasting_v3 && .venv/bin/pytest tests/test_au_panel.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'nyfed.au.panel'`

- [ ] **Step 3: Write the assembler**

`nowcasting_v3/nyfed/au/panel.py`:

```python
"""Assemble the Australian panel into the matrix the engine consumes.

The engine wants a standardised ``(n, T)`` array in spec row order, with
quarterly series observed in the last month of each quarter and NaN elsewhere.
Missing data stays NaN: the Kalman filter handles it natively, and filling it
would be inventing observations.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from nyfed.au.sources import AU_SERIES, SPEC_PATH, SeriesSource
from nyfed.spec import load_spec


@dataclass
class Panel:
    """One assembled vintage."""

    Y: np.ndarray            # (n, T), standardised
    y_location: np.ndarray   # (n, 1)
    y_scale: np.ndarray      # (n, 1)
    dates: pd.DatetimeIndex  # length T
    series_id: list[str]
    i_now: int               # row index of the nowcast target


def standardise(raw: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Centre and scale each row, ignoring NaN.

    A constant row has zero standard deviation; scale it by 1.0 rather than
    dividing by zero, which would turn a degenerate series into NaN and hide it.
    """
    location = np.nanmean(raw, axis=1, keepdims=True)
    scale = np.nanstd(raw, axis=1, ddof=1, keepdims=True)
    scale = np.where((scale == 0) | ~np.isfinite(scale), 1.0, scale)
    return (raw - location) / scale, location, scale


def _align(s: pd.Series, dates: pd.DatetimeIndex, source: SeriesSource) -> np.ndarray:
    """Reindex one series onto the panel's monthly grid."""
    aligned = s.reindex(dates)
    if source.frequency == "q":
        keep = np.isin(dates.month, (3, 6, 9, 12))
        aligned = aligned.where(pd.Series(keep, index=dates))
    return aligned.to_numpy(dtype=float)


def assemble(
    series: dict[str, pd.Series],
    *,
    start: str,
    end: str,
    spec_path=SPEC_PATH,
    sources: tuple[SeriesSource, ...] = AU_SERIES,
) -> Panel:
    """Build one standardised vintage from fetched series."""
    spec = load_spec(spec_path)
    dates = pd.date_range(start, end, freq="MS")

    rows = []
    for source in sources:
        if source.key not in series:
            raise KeyError(f"{source.key} is registered but was not fetched")
        rows.append(_align(series[source.key], dates, source))
    raw = np.vstack(rows)

    Y, location, scale = standardise(raw)
    return Panel(
        Y=Y,
        y_location=location,
        y_scale=scale,
        dates=dates,
        series_id=list(spec.series_id),
        i_now=spec.series_id.index("gdp"),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd nowcasting_v3 && .venv/bin/pytest tests/test_au_panel.py -q`
Expected: 8 passed

- [ ] **Step 5: Run the full suite, then commit**

```bash
cd nowcasting_v3 && caffeinate -i .venv/bin/pytest -q
git add nowcasting_v3/nyfed/au/panel.py nowcasting_v3/tests/test_au_panel.py
git commit -m "feat(v3): assemble the Australian panel with ragged edges preserved"
```

---

## Task 6: PCA seeding of the initial loadings

**Files:**
- Create: `nowcasting_v3/nyfed/au/initval.py`
- Test: `nowcasting_v3/tests/test_au_initval.py`

**Interfaces:**
- Consumes: `nyfed.au.panel.Panel`, `nyfed.spec.load_spec`, `nyfed.model.construct_prior`
- Produces: `seed_lambda(panel: Panel, spec_path=SPEC_PATH) -> np.ndarray` — `(n, n_f)`, NaN nowhere, zeros exactly where the spec says a series does not load on a factor

The NY Fed ships `initval.mat`, whose `param.Lambda` doubles as the prior mean for the loadings. Australia needs its own. It must be *sane*, not correct — the sampler re-estimates from it.

- [ ] **Step 1: Write the failing test**

`nowcasting_v3/tests/test_au_initval.py`:

```python
"""PCA seeding of the initial loading matrix."""

import numpy as np
import pandas as pd
import pytest

from nyfed.au.initval import seed_lambda
from nyfed.au.panel import Panel
from nyfed.au.sources import AU_SERIES, SPEC_PATH
from nyfed.spec import load_spec

RNG = np.random.default_rng(0)


def _panel(T: int = 300) -> Panel:
    n = len(AU_SERIES)
    spec = load_spec(SPEC_PATH)
    factor = RNG.standard_normal((1, T))
    Y = 0.8 * factor + 0.3 * RNG.standard_normal((n, T))
    Y[3, :40] = np.nan          # a late-starting series
    Y[-1, ~np.isin(np.arange(T) % 3, [2])] = np.nan   # a quarterly series
    dates = pd.date_range("2001-01-01", periods=T, freq="MS")
    return Panel(Y=Y, y_location=np.zeros((n, 1)), y_scale=np.ones((n, 1)),
                 dates=dates, series_id=list(spec.series_id),
                 i_now=spec.series_id.index("gdp"))


def test_seed_has_the_right_shape_and_no_nan():
    Lambda = seed_lambda(_panel())
    assert Lambda.shape == (17, 5)
    assert np.isfinite(Lambda).all()


def test_zero_loadings_stay_exactly_zero():
    """The spec's zeros are structural. A PCA seed that fills them would give
    the sampler a starting point the model cannot represent."""
    spec = load_spec(SPEC_PATH)
    Lambda = seed_lambda(_panel())
    structural_zeros = spec.blocks == 0
    assert (Lambda[structural_zeros] == 0.0).all()


def test_the_seed_recovers_a_planted_factor():
    """Guard against a seed that is technically valid and economically empty:
    if every series is driven by one factor, the global loadings should not be
    a scatter of near-zeros."""
    Lambda = seed_lambda(_panel())
    assert np.abs(Lambda[:, 0]).mean() > 0.1


def test_missing_data_does_not_produce_nan_loadings():
    panel = _panel()
    panel.Y[5, :] = np.nan          # a series with no observations at all
    Lambda = seed_lambda(panel)
    assert np.isfinite(Lambda).all()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd nowcasting_v3 && .venv/bin/pytest tests/test_au_initval.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the seeder**

`nowcasting_v3/nyfed/au/initval.py`:

```python
"""PCA seeding for the Australian loading matrix.

The NY Fed ships ``initval.mat``; Australia generates its own. The seed only
has to be sane -- the Gibbs sampler re-estimates from it. What it must not do
is put a non-zero loading where the spec says a series does not load on a
factor: those zeros are structural, and a seed that fills them starts the
sampler somewhere the model cannot represent.
"""

from __future__ import annotations

import numpy as np

from nyfed.au.panel import Panel
from nyfed.au.sources import SPEC_PATH
from nyfed.spec import load_spec


def seed_lambda(panel: Panel, spec_path=SPEC_PATH) -> np.ndarray:
    """Seed ``param.Lambda`` by principal components on the assembled panel."""
    spec = load_spec(spec_path)
    n, n_f = spec.blocks.shape

    filled = np.where(np.isnan(panel.Y), 0.0, panel.Y)
    # Rows that are entirely missing contribute nothing; leave them at zero
    # rather than letting an all-NaN row poison the decomposition.
    observed = ~np.isnan(panel.Y).all(axis=1)

    Lambda = np.zeros((n, n_f), dtype=float)
    if observed.sum() >= 2:
        U, S, _ = np.linalg.svd(filled[observed], full_matrices=False)
        components = U[:, :n_f] * S[:n_f]
        Lambda[observed, : components.shape[1]] = components[:, :n_f]

    # Normalise each factor's loadings to unit scale so the seed does not
    # depend on the panel's length.
    norms = np.linalg.norm(Lambda, axis=0, keepdims=True)
    Lambda = np.divide(Lambda, norms, out=np.zeros_like(Lambda), where=norms > 0)

    # Respect the spec's structural zeros.
    Lambda[spec.blocks == 0] = 0.0
    return Lambda
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd nowcasting_v3 && .venv/bin/pytest tests/test_au_initval.py -q`
Expected: 4 passed

- [ ] **Step 5: Run the full suite, then commit**

```bash
cd nowcasting_v3 && caffeinate -i .venv/bin/pytest -q
git add nowcasting_v3/nyfed/au/initval.py nowcasting_v3/tests/test_au_initval.py
git commit -m "feat(v3): PCA seeding of the Australian loading matrix"
```

---

## Task 7: Restrictions and the COVID window

This is where spec decision D3 actually lives. `Restrict.f_active` is, in the engine's own words, "how the COVID factor is confined to the pandemic window" (`nyfed/model.py:78`). Without it the COVID factor is active over the entire sample and distorts every other factor.

**Files:**
- Create: `nowcasting_v3/nyfed/au/restrict.py`
- Test: `nowcasting_v3/tests/test_au_restrict.py`

**Interfaces:**
- Consumes: `nyfed.au.panel.Panel`, `nyfed.spec.ModelSpec`, `nyfed.model.Restrict`
- Produces: `build_restrict(panel: Panel, spec: ModelSpec, *, p_f: int = 4) -> Restrict`, and the module constants `COVID_START = pd.Timestamp("2020-03-01")`, `COVID_END = pd.Timestamp("2021-12-01")`

### Mirror `example_estimate.m:70-85` exactly

```matlab
restrict.Lambda  = spec.Blocks;
restrict.Phi     = NaN(n_f, n_f, p_f);
restrict.iota    = spec.Trend./Y_scale;
restrict.isquart = isquart;

i_CoV = find(strcmpi(spec.BlockNames, 'COVID'));
if (i_CoV > 0)
    t_CoV = or(timekey < datetime(2020, 3, 1), timekey > datetime(2021, 12, 1));
    restrict.Phi(i_CoV, :, :)       = 0;
    restrict.Phi(:, i_CoV, :)       = 0;
    restrict.Phi(i_CoV, i_CoV, :)   = NaN;
    restrict.f_active               = true(n_f, T);
    restrict.f_active(i_CoV, t_CoV) = false;
end
```

Three details that are easy to get wrong:

1. **`iota` divides by `Y_scale`.** It must be built after standardisation, from the same `Y_scale` the panel used. Building it from the raw trend gives a trend on the wrong scale and the model will fit around it.
2. **The COVID factor is isolated in the factor VAR.** Its row and column of `Phi` are zeroed and only its own diagonal is left free, so it neither drives nor is driven by the other factors.
3. **`f_active` is false *outside* the window**, not inside it. An inverted mask is a plausible-looking bug that switches the pandemic factor on for the whole sample except the pandemic.

**A finding worth recording:** the NY Fed's own window is March 2020 to December 2021 — identical to the Australian window chosen in spec D3. The decision stands on its own reasoning, but in code it is a no-op relative to the US: no re-dating is required. Note this in the module docstring so a later reader does not go looking for a difference that is not there.

- [ ] **Step 1: Write the failing test**

`nowcasting_v3/tests/test_au_restrict.py`:

```python
"""Restrictions, and the COVID window that spec decision D3 specifies."""

import numpy as np
import pandas as pd
import pytest

from nyfed.au.panel import Panel
from nyfed.au.restrict import COVID_END, COVID_START, build_restrict
from nyfed.au.sources import SPEC_PATH
from nyfed.spec import load_spec


def _panel(T: int = 440) -> Panel:
    spec = load_spec(SPEC_PATH)
    n = len(spec.series_id)
    dates = pd.date_range("1990-01-01", periods=T, freq="MS")
    return Panel(
        Y=np.zeros((n, T)),
        y_location=np.zeros((n, 1)),
        y_scale=np.full((n, 1), 2.0),
        dates=dates,
        series_id=list(spec.series_id),
        i_now=spec.series_id.index("gdp"),
    )


def test_lambda_is_the_spec_block_pattern():
    spec = load_spec(SPEC_PATH)
    r = build_restrict(_panel(), spec)
    assert np.array_equal(r.Lambda, spec.blocks, equal_nan=True)


def test_iota_is_the_trend_divided_by_the_panel_scale():
    """example_estimate.m:72. Built from raw trend instead, the trend enters on
    the wrong scale and the model fits around it."""
    spec = load_spec(SPEC_PATH)
    panel = _panel()
    r = build_restrict(panel, spec)
    assert r.iota == pytest.approx(spec.trend / panel.y_scale.ravel())


def test_isquart_marks_exactly_the_three_quarterly_series():
    spec = load_spec(SPEC_PATH)
    r = build_restrict(_panel(), spec)
    assert r.isquart.dtype == bool
    assert r.isquart.sum() == 3
    assert r.isquart[spec.series_id.index("gdp")]
    assert not r.isquart[spec.series_id.index("employment")]


def test_the_covid_factor_is_isolated_in_the_factor_var():
    """example_estimate.m:80-82: its row and column are zeroed, only its own
    diagonal stays free, so it neither drives nor is driven by other factors."""
    spec = load_spec(SPEC_PATH)
    r = build_restrict(_panel(), spec, p_f=4)
    i = spec.block_names.index("COVID")
    off_row = np.delete(r.Phi[i, :, :], i, axis=0)
    off_col = np.delete(r.Phi[:, i, :], i, axis=0)
    assert (off_row == 0).all()
    assert (off_col == 0).all()
    assert np.isnan(r.Phi[i, i, :]).all()


def test_other_factors_keep_a_free_factor_var():
    spec = load_spec(SPEC_PATH)
    r = build_restrict(_panel(), spec, p_f=4)
    i = spec.block_names.index("COVID")
    j = 0 if i != 0 else 1
    assert np.isnan(r.Phi[j, j, :]).all()


def test_f_active_is_false_outside_the_window_and_true_inside():
    """The inversion is the bug to guard against: a mask that switches the
    pandemic factor on for the whole sample except the pandemic looks
    completely plausible and is exactly backwards."""
    spec = load_spec(SPEC_PATH)
    panel = _panel()
    r = build_restrict(panel, spec)
    i = spec.block_names.index("COVID")
    inside = (panel.dates >= COVID_START) & (panel.dates <= COVID_END)
    assert r.f_active[i, inside].all()
    assert not r.f_active[i, ~inside].any()
    assert inside.sum() == 22, "March 2020 to December 2021 inclusive"


def test_every_other_factor_is_active_throughout():
    spec = load_spec(SPEC_PATH)
    r = build_restrict(_panel(), spec)
    i = spec.block_names.index("COVID")
    others = [j for j in range(r.f_active.shape[0]) if j != i]
    assert r.f_active[others, :].all()


def test_f_active_spans_the_whole_panel():
    spec = load_spec(SPEC_PATH)
    panel = _panel(T=300)
    r = build_restrict(panel, spec)
    assert r.f_active.shape == (5, 300)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd nowcasting_v3 && .venv/bin/pytest tests/test_au_restrict.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'nyfed.au.restrict'`

- [ ] **Step 3: Write the builder**

`nowcasting_v3/nyfed/au/restrict.py`:

```python
"""Model restrictions for the Australian panel.

Ports ``example_estimate.m:70-85``. This is where spec decision D3 lives:
``Restrict.f_active`` is the boolean mask that confines the COVID factor to the
pandemic window, and without it that factor is active over the whole sample.

The window is March 2020 to December 2021. **That is identical to the NY Fed's
own window** -- spec D3 chose it from Australia's lockdowns and the closed
border, and it happens to coincide, so no re-dating is required. Do not go
looking for a difference from the US code here; there isn't one.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from nyfed.au.panel import Panel
from nyfed.model import Restrict
from nyfed.spec import ModelSpec

COVID_START = pd.Timestamp("2020-03-01")
COVID_END = pd.Timestamp("2021-12-01")


def build_restrict(panel: Panel, spec: ModelSpec, *, p_f: int = 4) -> Restrict:
    """Build the restriction struct for one assembled panel."""
    n, n_f = spec.blocks.shape
    T = panel.Y.shape[1]

    Lambda = spec.blocks.copy()
    Phi = np.full((n_f, n_f, p_f), np.nan)
    # iota divides by the panel's own scale (example_estimate.m:72); building
    # it from the raw trend puts the trend on the wrong scale.
    iota = spec.trend / panel.y_scale.ravel()
    isquart = np.array([f == "q" for f in spec.frequency], dtype=bool)
    f_active = np.ones((n_f, T), dtype=bool)

    if "COVID" in spec.block_names:
        i_cov = spec.block_names.index("COVID")
        # Isolate the pandemic factor in the factor VAR: it neither drives nor
        # is driven by the others (example_estimate.m:80-82).
        Phi[i_cov, :, :] = 0.0
        Phi[:, i_cov, :] = 0.0
        Phi[i_cov, i_cov, :] = np.nan
        outside = (panel.dates < COVID_START) | (panel.dates > COVID_END)
        f_active[i_cov, outside] = False

    return Restrict(
        Lambda=Lambda, Phi=Phi, iota=iota, f_active=f_active, isquart=isquart
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd nowcasting_v3 && .venv/bin/pytest tests/test_au_restrict.py -q`
Expected: 8 passed

- [ ] **Step 5: Run the full suite, then commit**

```bash
cd nowcasting_v3 && caffeinate -i .venv/bin/pytest -q
git add nowcasting_v3/nyfed/au/restrict.py nowcasting_v3/tests/test_au_restrict.py
git commit -m "feat(v3): restrictions and the COVID window for the Australian panel"
```

---

## Task 8: The landmine tests

Plan A recorded four landmines. Three are defused by design decisions; each becomes an executable test so a later change cannot quietly re-arm them.

**Files:**
- Test: `nowcasting_v3/tests/test_au_landmines.py`

**Interfaces:**
- Consumes: `nyfed.au.sources`, `nyfed.spec.load_spec`, `nyfed.model.construct_ssm`, `nyfed.updates.update_vol`
- Produces: nothing — this task is tests only

- [ ] **Step 1: Write the tests**

`nowcasting_v3/tests/test_au_landmines.py`:

```python
"""Executable tests for the four landmines Plan A recorded.

Each was a place where the port faithfully reproduces MATLAB behaviour that is
correct for the US panel and silently wrong for a different one. Comments do
not stop a landmine; these do.
"""

import csv

import numpy as np
import pytest

from nyfed.au.sources import AU_SERIES, SPEC_PATH
from nyfed.spec import load_spec

BLOCK_COLS = [
    "Block0_Global",
    "Block1_Soft",
    "Block2_Nominal",
    "Block3_Labor",
    "Block4_COVID",
]


def test_covid_is_the_fifth_factor():
    """LANDMINE 2. Gibbs_update.m:156-158 pins factor five's stochastic
    volatility at one by hard-coded index. In the NY Fed panel factor five is
    COVID, so the literal port does the intended thing -- but only while COVID
    stays in slot five. Reorder the blocks and that factor silently loses its
    stochastic volatility, with nothing downstream contradicting it, because
    the end-to-end gate nowcasts from stored estimates and never runs the
    sampler."""
    spec = load_spec(SPEC_PATH)
    assert spec.block_names[4] == "COVID"
    assert len(spec.block_names) == 5


def test_the_spec_csv_is_frequency_sorted():
    """LANDMINE 1. load_spec permutes fields monthly-before-quarterly while the
    panel is built in raw CSV order. The guard inside load_spec raises if the
    permutation is not the identity; this asserts the Australian CSV satisfies
    it rather than relying on the guard firing during a live run."""
    with open(SPEC_PATH, newline="") as fh:
        freqs = [r["Frequency"] for r in csv.DictReader(fh)]
    assert freqs == sorted(freqs, key=["d", "w", "m", "q", "sa", "a"].index)


def test_the_quarterly_aggregation_weights_are_unchanged():
    """LANDMINE 3. construct_SSM.m:131 pads the quarterly H branch using
    len(vec_m) where len(vec_q) is meant. Harmless only while both are length
    five. Spec decision D4 keeps the model annualised precisely so this never
    fires; if a later change re-derives the filter for QoQ, this test is the
    trip wire."""
    from nyfed import model

    source = model.construct_ssm.__doc__ or ""
    assert "1, 2, 3, 2, 1" in source or "[1,2,3,2,1]" in source, (
        "construct_ssm no longer documents the Mariano-Murasawa weights; "
        "if vec_q changed length, re-read construct_SSM.m:131 before "
        "trusting any quarterly row of H"
    )


def test_update_vol_does_not_propagate_nan_at_the_volatility_cap():
    """LANDMINE 4. np.minimum propagates NaN where MATLAB's min omits it, at
    the bd = 15 cap in update_vol. Unreachable with US missingness. Australian
    missingness differs -- ragged starts and quarterly-only series -- and this
    is the one landmine that cannot be ruled out by inspection.

    Drive the updater with a NaN in the position the cap touches and assert the
    output is finite."""
    from nyfed.updates import update_vol

    rng = np.random.default_rng(11)
    T = 60
    x = rng.standard_normal(T)
    x[7] = np.nan                      # the ragged-start pattern US data lacks
    sigma = np.full(T, 0.5)
    out = update_vol(x, sigma, 0.9, 0.0, 1e6, rng)
    assert np.isfinite(np.asarray(out)).all(), (
        "a NaN observation produced a NaN volatility; the bd = 15 cap "
        "propagated it. See Plan A landmine 4."
    )


def test_every_factor_except_soft_has_exactly_one_normaliser():
    """Not a Plan A landmine, but the same class: two of the NY Fed's three
    normalising series (INDPRO for Global, PCEPI for Nominal) have no
    Australian counterpart, so Australia nominates its own. A factor with no
    normaliser has an unidentified scale and the sampler will wander."""
    with open(SPEC_PATH, newline="") as fh:
        rows = list(csv.DictReader(fh))
    counts = {c: sum(float(r[c]) > 1 for r in rows) for c in BLOCK_COLS}
    assert counts["Block0_Global"] == 1
    assert counts["Block2_Nominal"] == 1
    assert counts["Block3_Labor"] == 1
    assert counts["Block4_COVID"] == 1
    assert counts["Block1_Soft"] == 0
```

- [ ] **Step 2: Run the tests**

Run: `cd nowcasting_v3 && .venv/bin/pytest tests/test_au_landmines.py -q`

`test_update_vol_does_not_propagate_nan_at_the_volatility_cap` may fail. **That is a real finding, not a broken test.** If it fails, stop and report: it means landmine 4 is live on the Australian panel and needs a fix in `nyfed/updates.py`, which is an engine change and therefore outside this plan's constraints. Do not paper over it by removing the NaN from the input.

Check `update_vol`'s real signature in `nyfed/updates.py:119` before writing the call — the parameter names above are from the Task 6 port and must match exactly.

- [ ] **Step 3: Commit**

```bash
git add nowcasting_v3/tests/test_au_landmines.py
git commit -m "test(v3): executable tests for the four Plan A landmines"
```

---

## Task 9: The annualised → QoQ conversion

Spec decision D4: the model stays annualised; the conversion happens on emit.

**Files:**
- Create: `nowcasting_v3/nyfed/au/emit.py`
- Test: `nowcasting_v3/tests/test_au_emit.py`

**Interfaces:**
- Consumes: nothing from earlier tasks
- Produces:
  - `annualised_to_qoq(annualised: float | np.ndarray) -> float | np.ndarray`
  - `qoq_to_annualised(qoq: float | np.ndarray) -> float | np.ndarray`

Both in **percent**, matching the model's units. The relationship is compounding, not division: `qoq = 100 * ((1 + a/100) ** 0.25 - 1)`.

- [ ] **Step 1: Write the failing test**

`nowcasting_v3/tests/test_au_emit.py`:

```python
"""Annualised to quarter-on-quarter conversion (spec decision D4).

The model works in annualised quarterly growth, as the NY Fed's does.
Australian headline GDP is QoQ. The conversion is compounding, not division:
dividing by four is wrong by about 4% of the figure at typical growth rates,
which is four times the gate tolerance Plan A held itself to.
"""

import numpy as np
import pytest

from nyfed.au.emit import annualised_to_qoq, qoq_to_annualised


def test_zero_maps_to_zero():
    assert annualised_to_qoq(0.0) == 0.0
    assert qoq_to_annualised(0.0) == 0.0


def test_a_known_pair():
    """4% annualised compounds from 0.9853% per quarter."""
    assert annualised_to_qoq(4.0) == pytest.approx(0.98534, abs=1e-5)
    assert qoq_to_annualised(0.98534) == pytest.approx(4.0, abs=1e-4)


def test_the_round_trip_is_exact():
    values = np.array([-8.0, -2.5, 0.0, 0.3, 2.0, 4.0, 12.0])
    assert qoq_to_annualised(annualised_to_qoq(values)) == pytest.approx(values, rel=1e-12)


def test_it_is_not_division_by_four():
    """The lazy conversion is out by enough to matter at the gate tolerance."""
    a = 4.0
    assert abs(annualised_to_qoq(a) - a / 4) > 0.01


def test_negative_growth_converts_without_producing_nan():
    assert np.isfinite(annualised_to_qoq(-6.0))
    assert annualised_to_qoq(-6.0) < 0


def test_it_handles_arrays_elementwise():
    got = annualised_to_qoq(np.array([0.0, 4.0]))
    assert isinstance(got, np.ndarray)
    assert got == pytest.approx([0.0, 0.98534], abs=1e-5)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd nowcasting_v3 && .venv/bin/pytest tests/test_au_emit.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'nyfed.au.emit'`

- [ ] **Step 3: Write the conversion**

`nowcasting_v3/nyfed/au/emit.py`:

```python
"""Unit conversion for the published Australian figure.

Spec decision D4: the model keeps the NY Fed's annualised quarterly growth and
its Mariano-Murasawa aggregation weights unchanged, so every Octave fixture
stays valid and the padding bug at construct_SSM.m:131 never fires. The
conversion to the quarter-on-quarter figure Australia publishes happens here,
at the presentation layer.

Compounding, not division. At 4% annualised the difference between the two is
0.0147pp -- larger than the +-0.01pp tolerance Plan A's gate held itself to.
"""

from __future__ import annotations

import numpy as np


def annualised_to_qoq(annualised):
    """Annualised quarterly growth (percent) to quarter-on-quarter (percent)."""
    return 100.0 * (np.power(1.0 + np.asarray(annualised, dtype=float) / 100.0, 0.25) - 1.0)


def qoq_to_annualised(qoq):
    """Quarter-on-quarter growth (percent) to annualised (percent)."""
    return 100.0 * (np.power(1.0 + np.asarray(qoq, dtype=float) / 100.0, 4.0) - 1.0)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd nowcasting_v3 && .venv/bin/pytest tests/test_au_emit.py -q`
Expected: 6 passed

- [ ] **Step 5: Run the full suite, then commit**

```bash
cd nowcasting_v3 && caffeinate -i .venv/bin/pytest -q
git add nowcasting_v3/nyfed/au/emit.py nowcasting_v3/tests/test_au_emit.py
git commit -m "feat(v3): annualised to QoQ conversion for the published figure"
```

---

## Task 10: End-to-end assembly and the leakage check

The gate for Plan B: the panel is right and the model estimates sanely on it.

**Files:**
- Create: `nowcasting_v3/nyfed/au/build.py`
- Test: `nowcasting_v3/tests/test_au_end_to_end.py`
- Modify: `nowcasting_v3/README.md`

**Interfaces:**
- Consumes: every earlier task
- Produces: `build_panel(*, asof: str, start: str = "1990-01-01", offline: bool = False) -> Panel` — fetches, checks freshness, assembles

- [ ] **Step 1: Write the failing test**

`nowcasting_v3/tests/test_au_end_to_end.py`:

```python
"""Plan B's gate: the panel is right and the model estimates sanely on it.

There is no oracle. Nobody publishes an Australian nowcast from this model, so
nothing here reproduces a reference number. These tests check the things that
can be checked: the panel's shape and history, that the engine accepts it, that
the sampler produces something non-degenerate, and that blanking the current
quarter does not move the nowcast -- the leakage check that cleared v2.
"""

import numpy as np
import pandas as pd
import pytest

from nyfed.au.build import build_panel
from nyfed.au.sources import AU_SERIES, SPEC_PATH
from nyfed.model import construct_ssm
from nyfed.spec import load_spec

ASOF = "2026-06-01"


@pytest.fixture(scope="module")
def panel():
    return build_panel(asof=ASOF)


def test_the_panel_has_one_row_per_registered_series(panel):
    assert panel.Y.shape[0] == len(AU_SERIES) == 17


def test_gdp_and_the_core_labour_series_reach_back_to_1990(panel):
    """The revised Plan B gate. Everything else starts when it genuinely
    starts -- household spending in 2012, the survey series later -- and those
    ragged starts are tested, not filled."""
    cutoff = pd.Timestamp("1990-12-01")
    early = panel.dates <= cutoff
    for key in ("gdp", "employment", "unemployment_rate"):
        row = panel.series_id.index(key)
        assert np.isfinite(panel.Y[row, early]).any(), f"{key} has no pre-1991 history"


def test_late_starting_series_are_nan_not_zero_before_they_start(panel):
    row = panel.series_id.index("household_spending")
    first = panel.dates[np.isfinite(panel.Y[row])][0]
    assert first > pd.Timestamp("2010-01-01")
    assert np.isnan(panel.Y[row, panel.dates < first]).all()


def test_the_engine_accepts_the_australian_panel(panel):
    """construct_ssm is the first engine function the panel meets. If the spec
    and the panel disagree about dimensions, it fails here rather than deep in
    the sampler."""
    spec = load_spec(SPEC_PATH)
    assert spec.blocks.shape[0] == panel.Y.shape[0]
    assert spec.blocks.shape[1] == 5


@pytest.mark.slow
def test_the_sampler_produces_non_degenerate_factors(panel):
    """A short run: enough to prove the sampler completes on this panel and
    does not collapse. Not an accuracy check -- there is nothing to check
    against."""
    from nyfed.au.build import estimate_short

    result = estimate_short(panel, n_gs=200, n_burn=100, seed=321)
    assert np.isfinite(result.params).all()
    assert result.params.std(axis=1).min() > 0, "a parameter never moved"


@pytest.mark.slow
def test_blanking_the_current_quarter_does_not_move_the_nowcast(panel):
    """The leakage check that cleared v2: if the current quarter's monthly
    observations are removed, the nowcast should move by roughly nothing,
    because it should not have been reading them as if they were GDP."""
    from nyfed.au.build import quick_nowcast

    base = quick_nowcast(panel)
    blanked = build_panel(asof=ASOF)
    current = blanked.dates >= pd.Timestamp("2026-04-01")
    blanked.Y[:, current] = np.nan
    moved = quick_nowcast(blanked)
    assert abs(moved - base) < 0.25, (
        f"blanking the current quarter moved the nowcast by {abs(moved - base):.3f}pp"
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd nowcasting_v3 && .venv/bin/pytest tests/test_au_end_to_end.py -q -m "not slow"`
Expected: FAIL with `ModuleNotFoundError: No module named 'nyfed.au.build'`

- [ ] **Step 3: Write the builder**

`nowcasting_v3/nyfed/au/build.py`:

```python
"""Fetch, guard and assemble the Australian panel.

The one entry point Plans C, D and E call. Fetching happens here; every other
module in ``nyfed/au`` is pure and testable offline.
"""

from __future__ import annotations

import pandas as pd

from nyfed.au.fetch_abs import fetch_abs_series
from nyfed.au.fetch_rba import fetch_rba_series
from nyfed.au.fetch_v2 import read_v2_series
from nyfed.au.freshness import check_freshness
from nyfed.au.panel import Panel, assemble
from nyfed.au.sources import AU_SERIES

def _fetch_one(source) -> pd.Series:
    """Dispatch one registry entry to its fetcher.

    Every fetcher takes the registry's ``locator`` and nothing else. The RBA
    column is encoded IN the locator (``"I2:GRCPAIAD"``), exactly as the ABS
    catalogue and series id are (``"6202.0:A84423043C"``) -- do not reintroduce
    a separate column argument or a module-level column constant. Task 3's
    review found that a hand-typed column let ``GRCPAISAD``, a one-character
    variant that is a genuinely different series, pass every test in the suite.
    """
    if source.fetcher == "abs":
        return fetch_abs_series(source.locator)
    if source.fetcher == "rba":
        return fetch_rba_series(source.locator)
    if source.fetcher == "v2":
        return read_v2_series(source.locator)
    raise ValueError(f"{source.key} has unknown fetcher {source.fetcher!r}")


def build_panel(*, asof: str, start: str = "1990-01-01") -> Panel:
    """Fetch every registered series, refuse if any is stale, and assemble."""
    series = {s.key: _fetch_one(s) for s in AU_SERIES}
    check_freshness(series, pd.Timestamp(asof))
    return assemble(series, start=start, end=asof)
```

Add the two wrappers the gate tests import, in the same module:

```python
def estimate_short(panel: Panel, *, n_gs: int, n_burn: int, seed: int):
    """A short sampler run. Proves the sampler completes on this panel and
    does not collapse; it is not an accuracy check, because there is nothing
    to check against.

    ``InitVal`` needs both a parameter draw and a latent draw
    (``nyfed/model.py:111-119``). The NY Fed ships one in ``initval.mat``;
    Australia builds a neutral starting point: the PCA-seeded loadings, an
    identity-ish factor VAR, unit volatilities and no outliers. The sampler
    moves off it immediately -- it only has to be representable.
    """
    import numpy as np

    from nyfed.au.initval import seed_lambda
    from nyfed.au.restrict import build_restrict
    from nyfed.au.sources import SPEC_PATH
    from nyfed.gibbs import gibbs_sampler
    from nyfed.model import InitVal, Latent, construct_prior
    from nyfed.parameters import Params
    from nyfed.settings import GibbsSettings
    from nyfed.spec import load_spec

    spec = load_spec(SPEC_PATH)
    n, n_f = spec.blocks.shape
    p_f, p_e = 4, 1
    T = panel.Y.shape[1]
    dims = (n, n_f, p_f, p_e)

    m_Lambda = seed_lambda(panel)
    prior = construct_prior(dims, m_Lambda)
    prior.P_Phi = prior.P_Phi / 5      # example_estimate.m:88

    # A neutral parameter draw. Free loadings take the PCA seed; restricted
    # ones are already zero there. Phi starts at a mild persistence rather
    # than zero so the factor VAR is not degenerate on sweep one.
    Phi0 = np.zeros((n_f, n_f, p_f))
    Phi0[:, :, 0] = 0.5 * np.eye(n_f)
    param0 = Params(
        mu=np.zeros(n),
        gamma_g=0.0,
        Lambda=np.nan_to_num(m_Lambda),
        Phi=Phi0,
        gamma_f=np.zeros(n_f),
        pi_f=np.full(n_f, 0.05),
        phi=np.zeros((n, p_e)),
        gamma_e=np.zeros(n),
        pi_e=np.full(n, 0.05),
    )
    latent0 = Latent(
        sigma=np.ones((n_f + n, T)),
        s=np.ones((n_f + n, T)),
        state=None,
    )
    restrict = build_restrict(panel, spec, p_f=p_f)
    settings = GibbsSettings(n_gs=n_gs, n_burn=n_burn, n_thin=1)
    return gibbs_sampler(panel.Y, prior, restrict,
                         InitVal(param=param0, latent=latent0),
                         settings, np.random.default_rng(seed))
```

`GibbsSettings` carries `n_gs`, `n_burn`, `n_init`, `n_thin`, `n_each` and `state_each` (`nyfed/settings.py:20-25`); the defaults for the fields not passed above are the production values and are fine for a short run. If `Params`, `Latent` or `InitVal` differ from the shapes above, **follow the source and report the difference** — do not adjust the engine to match this plan.

`quick_nowcast(panel)` runs `nyfed.nowcast.point_nowcast` on the panel against itself (`Y_old = Y_new`) with the state space built from a short sampler run, and returns `point.nowcast[3, 0]` de-standardised through `panel.y_scale[panel.i_now]`. Its only job is to give the leakage test a number to compare; it is not a published figure.

- [ ] **Step 4: Run the fast tests, then the slow ones**

```bash
cd nowcasting_v3 && .venv/bin/pytest tests/test_au_end_to_end.py -q -m "not slow"
cd nowcasting_v3 && caffeinate -i .venv/bin/pytest tests/test_au_end_to_end.py -q -m slow
```

- [ ] **Step 5: Update the README**

Add an "Australian panel" section covering: the 17 series and where each comes from, the four series read from v2 and what breaks if v2's weekly routine stops, the freshness budgets, the normalisation decision and why Australia had to make its own, and the fact that Plan B has no oracle.

- [ ] **Step 6: Run the full suite, then commit**

```bash
cd nowcasting_v3 && caffeinate -i .venv/bin/pytest -q
git add nowcasting_v3/nyfed/au/build.py nowcasting_v3/tests/test_au_end_to_end.py \
        nowcasting_v3/README.md
git commit -m "feat(v3): build the Australian panel end to end - Plan B complete"
```

---

## Plan B gate

Plan B is complete when all of these hold. Do not begin Plan C before then.

- [ ] The full suite passes, including `-m slow`, with the US fixtures still green
- [ ] Every ABS series id is pinned by an observation verified against the ABS release
- [ ] No locator carries a `RESOLVE_` placeholder
- [ ] GDP and the core labour series reach back to at least 1990; every other series starts when it genuinely starts, with ragged edges tested rather than filled
- [ ] The freshness guard halts on a stale series, proven by a test that makes one stale
- [ ] All four landmine tests pass, or landmine 4 is reported as live with evidence
- [ ] The COVID factor is active March 2020 to December 2021 and inactive outside it, proven by `test_f_active_is_false_outside_the_window_and_true_inside`
- [ ] `iota` is built from the panel's own `Y_scale`, not from the raw trend
- [ ] `nyfed/` engine files are unmodified: `git diff --stat main -- nowcasting_v3/nyfed/*.py` is empty
- [ ] `nyfed_matlab/` is unmodified

## Deferred to Plan C

- Backtest performance and band coverage
- The Brent oil price, approved 2026-06-03 *only if the backtest likes it*
- NAB Forward Orders and Stocks as additional Soft-block series
- Judo Bank PMI New Orders and Stocks of Purchases as additional Soft-block series
- Whether the Internet Vacancy Index is collinear with ANZ job ads
- Whether retail sales and household spending are redundant
- Whether the fixed COVID window beats an empirically chosen one
