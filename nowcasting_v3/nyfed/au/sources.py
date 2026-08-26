"""The 15-series Australian panel registry.

One entry per series, in spec CSV row order: monthly first, then quarterly.
``load_spec`` permutes its fields by frequency and raises if that permutation
is not the identity (``nyfed/spec.py:112``), because the data panel is built in
raw CSV order and is never permuted with it. So this order is load-bearing.

``fetcher`` names the module that retrieves the series and ``locator`` is that
fetcher's argument: ``"<catalogue>:<series id>"`` for ABS, ``"<table>:<column>"``
for RBA, or a bare v2 CSV stem. Both the ABS and RBA locators are self-contained
on purpose -- ``sources.py`` is the single place that names which column of a
multi-column source the panel means, so a fixture or a fetch dispatcher can be
checked against the registry directly rather than trusting a caller to type
the right column by hand. See the ``commodity_prices`` entry below for why
this matters concretely.

``max_age_days`` is the staleness budget enforced in ``freshness.py``. It is
set from the publication cycle plus a tolerance, not from convenience: four
Australian monthly indicators were discontinued between March 2025 and June
2026, and a discontinued series does not raise an error, it just stops
updating.

No ``retail_sales`` entry: ABS ceased "Retail Trade, Australia" (cat. 8501.0)
after the June 2025 release, published 31 July 2025 as its final edition --
the fourth Australian monthly indicator this project has lost, after Weekly
Payroll Jobs (Mar 2025), the Monthly Business Turnover Indicator (Nov 2025)
and the Monthly Employee Earnings Indicator (Jun 2026). A permanently frozen
series would fail ``check_freshness`` on every run rather than the runs
where staleness is a real signal, so the series is dropped rather than kept
and exempted. ``household_spending`` (the Monthly Household Spending
Indicator, ABS's own replacement) already covers this ground and covers it
better: ~68% of household consumption against Retail Trade's ~33%, and a
stronger pre-COVID GDP correlation in v2's panel notes (+0.29 vs +0.06). Do
not add retail sales back without first checking whether ABS has resumed it.

``cpi`` and ``cpi_trimmed`` locators point at catalogue 6401.0, not 6484.0.
ABS retired the standalone "Monthly CPI Indicator" (6484.0) in favour of
folding monthly data into the main "Consumer Price Index, Australia"
(6401.0) collection from the October 2025 (pre-basis-change) release
onward; 6484.0's series stop dead at 2025-09-01 and will never update. The
replacement monthly, seasonally-adjusted analytical series (table 640106)
only goes back to 2024-04-01 -- about 28 months of history as of this task,
against 6484.0's ~8 years. That is a real short-history constraint on the
Nominal block's normaliser and on the price factor generally; it is not a
substitution of something close, it is what currently exists. Re-check ABS
for a longer back series before this becomes a problem for estimation.

``commodity_prices`` locates ``"I2:GRCPAIAD"``: RBA statistical table I2
carries 21 columns -- an all-items index and five sub-indices (rural,
non-rural, base metals, bulk commodities, and a "with bulk commodities spot
prices" variant), each in three currency terms (A$, US$, SDR). ``GRCPAIAD``
is the all-items index in A$ terms. Australia's GDP is A$-denominated, and
the Q1 2026 miss this series was added to address was an A$ terms-of-trade
shock, so the US$/SDR variants would not serve that purpose even though
they parse to equally plausible numbers -- and ``GRCPAISAD``, the
bulk-commodities-spot variant, is one character away and a genuinely
different series. The column lives here, not as a bare table code plus a
caller-supplied argument, precisely so a fetch dispatcher cannot silently
choose the wrong one: ``fetch_rba.fetch_rba_series`` takes this locator
whole and splits it, the same as ABS.

No ``vacancy_index`` entry: this panel was designed around a row v2 lists
but does not have. v2's own ``seed/panel_info.csv`` marks the Jobs and
Skills Australia Internet Vacancy Index (``ivi``) ``status=MISSING``,
``has_csv=FALSE``, "host firewalled" -- the JSA host has been unreachable
from v2's fetch runner since the series was added, and no ``ivi.csv`` has
ever been written to ``nowcasting_v2/data_raw/``. There is no working
route to this series, so it is dropped rather than kept as a permanently
failing registry row (the same reasoning as the ``retail_sales`` drop
above). It was also already flagged, independently of the outage, as the
panel's weakest mapping: IVI is a vacancy count against ANZ-Indeed Job
Ads' ad count, and the two are expected to be collinear -- job_ads (still
in the panel) already covers this economic concept. JSA does publish the
IVI publicly, so it is not lost for good: a fetcher against JSA directly
(not through v2) is the route back in, if a future evidence gate (e.g.
Plan C) wants it.
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
    SeriesSource("aig_pmi", "aig_pmi", "AiG Manufacturing PMI",
                 "v2", "aig_pmi", "m", 45),
    SeriesSource("nab_conditions", "nab_conditions", "NAB Business Conditions",
                 "v2", "nab_cond", "m", 45),
    SeriesSource("building_approvals", "building_approvals", "Building Approvals",
                 "abs", "8731.0:A422070J", "m", 60),
    SeriesSource("household_spending", "household_spending",
                 "Household Spending (real)",
                 "abs", "5682.0:A130200584T", "m", 60),
    SeriesSource("exports", "exports", "Exports",
                 "abs", "5368.0:A2718577A", "m", 60),
    SeriesSource("imports", "imports", "Imports",
                 "abs", "5368.0:A2718603V", "m", 60),
    SeriesSource("commodity_prices", "commodity_prices",
                 "RBA Index of Commodity Prices",
                 "rba", "I2:GRCPAIAD", "m", 45),
    SeriesSource("cpi", "cpi", "Monthly CPI",
                 "abs", "6401.0:A130607789R", "m", 60),
    SeriesSource("cpi_trimmed", "cpi_trimmed", "Monthly CPI trimmed mean",
                 "abs", "6401.0:A130400381L", "m", 60),
    # --- quarterly ---------------------------------------------------------
    SeriesSource("unit_labour_cost", "unit_labour_cost", "Unit labour cost",
                 "abs", "5206.0:A2433074L", "q", 120),
    SeriesSource("gdi", "gdi", "Real gross domestic income",
                 "abs", "5206.0:A2304410X", "q", 120),
    SeriesSource("gdp", "gdp", "Real gross domestic product",
                 "abs", "5206.0:A2304402X", "q", 120),
)
