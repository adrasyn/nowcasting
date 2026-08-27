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

``publication_lag_days`` is the ONE fact this registry records about timing,
and everything else about timing is derived from it. It is the number of days
from an observation's PANEL DATE to the day that observation was actually
released. The panel date is where ``fetch_abs._first_of_month_index`` puts it:
the start of the period for a monthly series, and the LAST month of the quarter
for the three quarterly ones (``to_timestamp(how="end")``, which is what
``panel._align``'s ``{3, 6, 9, 12}`` mask requires). Every lag below was
measured against that date, whichever convention applies to the series.

TWO THINGS ARE DERIVED FROM IT, AND BOTH WERE PREVIOUSLY TYPED IN BY HAND
--------------------------------------------------------------------------
**The staleness budget.** ``max_age_days`` is not a field any more; it is

    publication_lag_days + release_interval_days + SLACK_DAYS

A series is at its oldest just before its next release, which is
``publication_lag_days + release_interval_days`` after the observation date;
``SLACK_DAYS`` covers a release moved by a public holiday. Typing the budget in
directly got it wrong twice in this project, both times in the same direction
and both times because the panel date runs weeks ahead of the release -- a
monthly is dated to the first of its reference month and published about two
months later, a quarterly to the last month of its quarter and published about
three: 45-60 days for monthlies (halts healthy data), then 75 (still halts the
four ABS monthlies that publish two months in arrears), then 120 for quarterlies
(refuses ``gdp`` itself for two months out of every three). The formula
reproduces the numbers those guesses were reaching for: ``gdp``'s
94 + 91 = 185 against an observed healthy 178-186,
``building_approvals``' 62 + 31 = 93 against an observed 86.

**WHICH OBSERVATIONS EXISTED at a vintage.** ``build.build_panel`` drops an
observation whose RELEASE date -- ``observation date +
publication_lag_days`` -- falls after ``asof``. Truncating on the observation
date instead, which is what this module's first end-to-end consumer did, admits
data published up to nine weeks after ``asof``: at ``asof="2026-07-01"`` seven
series carried a 2026-07-01 observation that had not been released yet, and this
repo proves it against itself -- ``tests/test_au_fetch_rba.py`` pins the 2026-07
commodity observation to a release date of 4 August 2026. That is the classic
forward-looking evaluation error, and ``build_panel`` is the primitive a
backtest will call, so it would flatter every result Plan C produces.

THAT IS THE SET OF OBSERVATIONS, NOT THEIR PUBLISHED VALUES. The cut reproduces
which observations a person at a desk on ``asof`` could have seen; it does not
reproduce what those observations said on that day. ABS revises seasonally
adjusted series routinely, so a recording made later and replayed at an earlier
``asof`` carries revisions that desk could not have seen. A backtest built on
this primitive is therefore revision-aware in its DATING and revision-blind in
its VALUES, and Plan C inherits both halves.

RELEASE INTERVALS ARE NOT ALWAYS THE FREQUENCY
----------------------------------------------
``RELEASE_INTERVAL_DAYS`` gives 31 days to a monthly and 91 to a quarterly, and
for thirteen of the fifteen series the budget that produces ABSORBS the worst
gap their recorded history contains -- 31 days for the monthlies, 92 for the
quarterlies against a 91-day interval plus 21 days of slack. Two publishers skip
a month on their ordinary calendar and would be refused for behaving exactly as
they always have, so they carry a per-series ``release_interval_override`` with
its own sourced note:

* ``aig_pmi`` -- Ai Group publishes no PMI for one December or January in most
  years. The routine case is a 62-day gap, worst age 96 against the 86-day
  budget the frequency default gives, so the build would have refused **every
  February** once the AiG fetcher is repaired.
* ``nab_conditions`` -- skipped September 2020, a 61-day gap, worst age 104
  against 95.

An override widens the ORDINARY calendar, not the guard's tolerance for
anything: Ai Group missed December 2022 *and* January 2023, a 92-day gap and a
126-day worst age, and that is outside the sourced calendar and still refuses.

An override is also a widened staleness budget, and it is paid for: ``aig_pmi``'s
budget goes 86 -> 117, so a genuinely dead AiG feed is caught 31 days later than
it used to be. That is the right trade. This branch's operating premise is that
a refusal means something is wrong, and a guard that cries wolf every February
trains the operator to do the one thing ``build.py`` forbids -- widen the budget
by hand -- which costs far more than a month of detection latency.

``SLACK_DAYS`` MUST STAY BELOW EVERY RELEASE INTERVAL, the overrides included.
At ``SLACK_DAYS >= release_interval_days`` a series that missed a release
outright still sits inside its budget and the guard stops guarding. 21 days
against a 31-day monthly interval leaves ten days of margin;
``SeriesSource.__post_init__`` refuses an override that breaks the inequality
and ``test_the_slack_cannot_swallow_a_missed_release`` pins it for the registry
as it stands.

``lag_source`` NAMES WHERE THE LAG CAME FROM, and it is not decoration. Every
lag below was read off a release page or a publisher's release-date list, on
2026-08-26, and the string says which. An unsourced lag is the same failure
mode one layer down -- a number that looks measured and is not -- so a lag that
cannot be sourced belongs in a comment saying so, not in the field.


``aig_pmi`` IS STALE IN v2's CSV, NOT DEAD AT SOURCE, AND THERE IS NO SCRAPER
TO REPAIR. Ai Group still publishes it: the July 2026 edition of the Australian
Industry Index reports "The Australian PMI (manufacturing) declined 5.7 points
to -19.6", and recent editions went out 02/06, 30/06 and 04/08 for May, June
and July. What stopped is ``nowcasting_v2/data_raw/aig_pmi.csv``, last
committed 2026-06-11 with its last observation at 2026-05-01.

The reason it stopped is not a broken fetcher. ``nowcasting_v2/seed/panel_info.csv``
gives the series' source as "AiG/investing.com PDF (from_james)" -- a manual
step -- and v2 never consumes the result: v2's live panel spec is ``B3_nab_wmi``,
defined at ``nowcasting_v2/R/sweep_v2.R:116`` as the panel MINUS the AiG block,
which ``R/emit_v2_json.R:45`` states outright. The three aig rows in v2's
``panel_info.csv`` are selection candidates that the panel spec discards before
``build_mai()``'s targeted-predictor test ever sees them. So the file went three
months without an update because nobody had a reason to lift it, and **v3 is now
its only consumer**. Do not "clean up" the aig entry from v2's registry or its
weekly refresh routine on the grounds that v2 does not use it -- that is true and
not the point.

The fix is therefore a step in v2's weekly survey routine
(``docs/cowork-weekly-refresh.md``, step D), not code here, and the CSV was
backfilled to 2026-07 on 2026-08-27 (Jun -16.8, Jul -19.6).

The trap for whoever maintains it is REVISIONS, not a scale break and not a
name collision. Ai Group revises this series every month, and the CSV holds
FIRST VINTAGES -- which is what a real-time nowcast needs. May 2026 was first
published -22.4 (the CSV value) and later revised to -21.3; June was first
published -16.8 and later revised to -13.9. So Ai Group's own prose ("declined
5.7 points to -19.6") is computed against revised figures and will never
reconcile against this history; that is expected, not an error. The source of
record is the investing.com release table
(au.investing.com/economic-calendar/aig-manufacturing-index-203), whose
"Actual" column is the first vintage and which matches this CSV exactly across
2026-02..2026-05. An earlier version of this comment claimed instead that the
source had moved to a net balance while the history carried a 50-centred
diffusion index; that is wrong -- the CSV has been zero-centred throughout
(2014-08 = -5.4).

(The guard refuses from 2026-08-27, not 2026-07-27: the skipped-month override
above widened this series' budget from 86 days to 117, which is the disclosed
price of not refusing every February.)

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


# Days between one release of a series and the next, BY FREQUENCY. A month is
# 31 days and a quarter 91: the LONGEST ordinary gap, because a budget built on
# the average would halt on the long months.
#
# This is the default, not the rule. A publisher whose ordinary calendar skips a
# month overrides it per series -- see `SeriesSource.release_interval_override`.
RELEASE_INTERVAL_DAYS: dict[str, int] = {"m": 31, "q": 91}

# Tolerance on top of "lag + interval", for a release moved by a public holiday
# or an ABS scheduling change. It MUST stay below the shortest release interval:
# at or above it, a series that skipped a release entirely still sits inside its
# budget. See the module docstring.
SLACK_DAYS = 21


@dataclass(frozen=True)
class SeriesSource:
    """Where one panel series comes from, and when it is published.

    ``max_age_days`` and the vintage cut-off are both DERIVED from
    ``publication_lag_days``; neither is stored. See the module docstring for
    why that matters and for what ``lag_source`` is for.
    """

    key: str
    series_id: str
    name: str
    fetcher: str      # "abs" | "rba" | "v2"
    locator: str
    frequency: str    # "m" | "q"
    publication_lag_days: int
    lag_source: str
    # Set only where the publisher's ORDINARY calendar is longer than its
    # frequency implies. Sourced like `publication_lag_days` is, and for the
    # same reason. See RELEASE INTERVALS ARE NOT ALWAYS THE FREQUENCY above.
    release_interval_override: int | None = None
    release_interval_source: str = ""

    def __post_init__(self) -> None:
        if (self.release_interval_override is None) != (
            not self.release_interval_source
        ):
            raise ValueError(
                f"{self.key}: release_interval_override and "
                "release_interval_source go together. A widened interval is a "
                "widened staleness budget, and an unsourced one is a number "
                "that looks measured and is not."
            )
        if (
            self.release_interval_override is not None
            and self.release_interval_override <= SLACK_DAYS
        ):
            raise ValueError(
                f"{self.key}: a release interval of "
                f"{self.release_interval_override} days is at or below "
                f"SLACK_DAYS ({SLACK_DAYS}), so a series that skipped a release "
                "outright would still sit inside its budget and the freshness "
                "guard would stop guarding this series. See the module "
                "docstring and test_the_slack_cannot_swallow_a_missed_release."
            )

    @property
    def release_interval_days(self) -> int:
        if self.release_interval_override is not None:
            return self.release_interval_override
        return RELEASE_INTERVAL_DAYS[self.frequency]

    @property
    def max_age_days(self) -> int:
        """The staleness budget ``freshness.py`` enforces."""
        return self.publication_lag_days + self.release_interval_days + SLACK_DAYS


# Every `publication_lag_days` below is (release date - observation date) for a
# real release, read off the page named in `lag_source` on 2026-08-26. Where two
# consecutive releases were available the LARGER lag is recorded, because the
# vintage cut-off must never admit an unreleased observation.
AU_SERIES: tuple[SeriesSource, ...] = (
    # --- monthly -----------------------------------------------------------
    SeriesSource("employment", "employment", "Employment",
                 "abs", "6202.0:A84423043C", "m", 50,
                 "ABS 6202.0 Labour Force, Australia: July 2026 released "
                 "20/08/2026 (abs.gov.au .../labour-force-australia/latest-release)"),
    SeriesSource("unemployment_rate", "unemployment_rate", "Unemployment rate",
                 "abs", "6202.0:A84423050A", "m", 50,
                 "ABS 6202.0, same release as `employment`: July 2026 released "
                 "20/08/2026"),
    SeriesSource("job_ads", "job_ads", "ANZ-Indeed Job Ads",
                 "v2", "anz_ads", "m", 37,
                 "ANZ 2026 release-date list (anz.com.au/newsroom/media/"
                 "release-dates/): Mar 2026 released 07/04/2026, the longest of "
                 "the seven 2026 releases listed (Jan..Jul span 29-37 days)"),
    SeriesSource("aig_pmi", "aig_pmi", "AiG Manufacturing PMI",
                 "v2", "aig_pmi", "m", 34,
                 "Ai Group Australian Industry Index release list, via the "
                 "mtsinsights economic calendar (mtsinsights.com/events/3815/): "
                 "May 2026 released 02/06, June 30/06, July 04/08 -- 29 to 34 "
                 "days. THIRD-PARTY: Ai Group publishes no release-date list of "
                 "its own, so this is the weakest-sourced lag in the registry",
                 62,
                 "AI GROUP SKIPS THE TURN OF THE YEAR. Measured over the "
                 "recorded vintage's own history, 2015-01 to 2026-05 (v2's "
                 "aig_pmi.csv): the months absent are 2017-06, 2020-12, "
                 "2022-01, 2022-12, 2023-01, 2024-01, 2025-01 and 2025-12 -- "
                 "one December or January missing in seven of the eleven years. "
                 "A single skipped month is a 61- or 62-day gap depending on "
                 "which pair of months it spans, so 62 is the ordinary worst "
                 "case. 2022-12 AND 2023-01 were both missed, a 92-day gap; "
                 "that is outside the ordinary calendar and still refuses"),
    SeriesSource("nab_conditions", "nab_conditions", "NAB Business Conditions",
                 "v2", "nab_cond", "m", 43,
                 "NAB Monthly Business Survey (nab.com.au/news/economy-markets): "
                 "June 2026 released 14/07/2026 (43 days), July 2026 released "
                 "11/08/2026 (41)",
                 62,
                 "NAB SKIPPED SEPTEMBER 2020. Measured over the recorded "
                 "vintage's own history, 2015-01 to 2026-07 (v2's "
                 "nab_cond.csv): 2020-09 is the ONLY month absent, a 61-day gap "
                 "from 2020-08 to 2020-10. Recorded as 62 for the same reason "
                 "as `aig_pmi` -- 62 is what one skipped month costs across the "
                 "longest month pairs, so a 61-day instance needs a 62-day "
                 "interval to have no margin of its own"),
    SeriesSource("building_approvals", "building_approvals", "Building Approvals",
                 "abs", "8731.0:A422070J", "m", 62,
                 "ABS 8731.0 Building Approvals: June 2026 released 30/07/2026 "
                 "(59 days), July 2026 scheduled 01/09/2026 (62)"),
    SeriesSource("household_spending", "household_spending",
                 "Household Spending (real)",
                 "abs", "5682.0:A130200584T", "m", 64,
                 "ABS 5682.0 Monthly Household Spending Indicator: June 2026 "
                 "released 04/08/2026. The next release (July, 27/08/2026) is a "
                 "shorter 57-day lag; the longer observed value is kept"),
    SeriesSource("exports", "exports", "Exports",
                 "abs", "5368.0:A2718577A", "m", 66,
                 "ABS 5368.0 International Trade in Goods: June 2026 released "
                 "06/08/2026 (66 days), July 2026 scheduled 03/09/2026 (64)"),
    SeriesSource("imports", "imports", "Imports",
                 "abs", "5368.0:A2718603V", "m", 66,
                 "ABS 5368.0, same release as `exports`: June 2026 released "
                 "06/08/2026"),
    SeriesSource("commodity_prices", "commodity_prices",
                 "RBA Index of Commodity Prices",
                 "rba", "I2:GRCPAIAD", "m", 34,
                 "RBA Index of Commodity Prices July 2026, release date "
                 "04/08/2026 (rba.gov.au/statistics/frequency/commodity-prices/"
                 "2026/icp-0726.html) -- the release already pinned by "
                 "test_commodity_prices_reproduces_the_published_release"),
    SeriesSource("cpi", "cpi", "Monthly CPI",
                 "abs", "6401.0:A130607789R", "m", 58,
                 "ABS 6401.0 CPI, Australia: June 2026 released 29/07/2026 (58 "
                 "days), July 2026 released 26/08/2026 (56)"),
    SeriesSource("cpi_trimmed", "cpi_trimmed", "Monthly CPI trimmed mean",
                 "abs", "6401.0:A130400381L", "m", 58,
                 "ABS 6401.0, same release as `cpi`: June 2026 released "
                 "29/07/2026"),
    # --- quarterly ---------------------------------------------------------
    SeriesSource("unit_labour_cost", "unit_labour_cost", "Unit labour cost",
                 "abs", "5206.0:A2433074L", "q", 94,
                 "ABS 5206.0 National Accounts, same release as `gdp`: March "
                 "quarter 2026 released 03/06/2026"),
    SeriesSource("gdi", "gdi", "Real gross domestic income",
                 "abs", "5206.0:A2304410X", "q", 94,
                 "ABS 5206.0 National Accounts, same release as `gdp`: March "
                 "quarter 2026 released 03/06/2026"),
    SeriesSource("gdp", "gdp", "Real gross domestic product",
                 "abs", "5206.0:A2304402X", "q", 94,
                 "ABS 5206.0 National Accounts: March quarter 2026 (dated "
                 "2026-03-01) released 03/06/2026; the June quarter is "
                 "scheduled 02/09/2026, a 93-day lag (abs.gov.au .../australian-"
                 "national-accounts-national-income-expenditure-and-product/"
                 "latest-release)"),
)
