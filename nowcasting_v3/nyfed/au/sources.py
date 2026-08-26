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
