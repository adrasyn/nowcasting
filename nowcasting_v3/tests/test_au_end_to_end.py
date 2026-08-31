"""Plan B's gate: the panel is right and the model estimates sanely on it.

There is no oracle. Nobody publishes an Australian nowcast from this model, so
nothing here reproduces a reference number, and nothing here is tuned toward a
number that looks right. These tests check the things that can be checked: the
panel's shape and history, that the row that enters the panel is the DEFLATED
household spending series, that the engine accepts the panel, that the sampler
moves every free parameter, and that data from after the target quarter does
not move the nowcast while the same shock inside it does.

WHAT THE LEAKAGE CHECK MEASURES, AND WHAT IT DOES NOT
-----------------------------------------------------
"Blanking the current quarter does not move the nowcast" cannot be the test.
Two problems, and the second one is fatal:

1. At this vintage the nowcast target IS the current quarter -- GDP is observed
   through 2025-12, so Q1 2026 is what the model is nowcasting, and Q1's
   monthly observations are exactly what it is supposed to read. A nowcast that
   ignored them would be a broken nowcast, not a leak-free one. The leak worth
   testing for is the one that cleared v2: data from AFTER the target quarter
   being read as though it belonged to the target quarter.

2. A blanking test passes whenever the nowcast does not move, INCLUDING when
   the pipeline is dead. Blanking is also a weak instrument in its own right:
   measured at this gate's own seed, removing all three of Q1's months moves the
   nowcast by 0.051pp, against 2.169pp for a one-sigma shock to the same cells
   -- not because the model ignores them but because they came in close to what
   it expected. Removal measures how surprising the data was, not whether the
   data is read.

So the instrument is a one-sigma SHOCK, applied to the same rows, through the
same state space, in two places:

* the target quarter's own months (January-March 2026) -> the nowcast moves
  2.169pp;
* the months after it (April 2026, the only post-target month this vintage
  contains) -> it moves 0.013pp, some 160 times less.

WHERE THE NO-LEAK GUARANTEE ACTUALLY COMES FROM. Not from the number above.
Structurally, a post-target observation can only reach the target quarter's
fitted value -- Q1 2026 at this vintage -- through the smoothed state, because
the Mariano-Murasawa aggregation in
``construct_ssm`` -- weights ``[1 2 3 2 1]/9`` over the quarter's own months --
is what maps months onto a quarterly observation, and that is engine code
pinned against Octave in Task 1. What is left to check on the Australian side
is that the panel puts each observation in the right column, which
``test_quarterly_rows_sit_in_the_last_month_of_their_quarter`` and the fetch
tests' date pinning do deterministically.

THE NUMERICAL CHECK IS A CONSISTENCY CHECK, NOT A LEAK DETECTOR, and saying
otherwise would be a false claim about a real guard. Measured: a genuine
one-month misalignment -- April's observation written into March's column,
which is what an off-by-one in ``panel._align`` would produce -- is caught at
NONE of the six seeds tried. The healthy ratios are 17.6, 162.5, 52.6, 365.2,
395.4 and 17.5; under the leak they become 49.5, 37.8, 16.9, 22.9, 109.8 and
320.4, every one still above the asserted floor of 10, and two of them higher
than the healthy value. (Those six seeds were measured on the 15-series panel,
before `cpi_trimmed` was dropped, and the conclusion -- the probe catches
nothing -- did not warrant re-measuring for one fewer price series.) At this
vintage only ONE post-target month exists and only seven of the fourteen series
have published it, so there is too little post-target data for the ratio to
separate the two cases at all. A vintage-pair
leakage test (build at two dates, compare) is the instrument that would, and it
belongs to Plan C, where more than one post-target month is available.

The state space is estimated ONCE, on the unmodified panel, and reused for
every arm. Re-estimating per arm would mix the effect of changing observations
with the sampler's own noise and make the difference uninterpretable in either
direction. Thresholds are set from the spread across six sampler seeds, not
from the one seed the tests run at -- see each test's docstring.

THE BUILD REPLAYS A RECORDED VINTAGE
------------------------------------
``build_panel`` fetches live when given no vintage; that is what production
does and it is not what a test should do. See ``nyfed/au/build.py`` for why the
gate replays ``tests/fixtures/au/vintage`` instead, and
``test_the_recorded_vintage_agrees_with_the_payloads_verified_against_ABS``
for the check that the recording is the same data as the payloads that were
verified against the published releases.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from nyfed.au.build import (
    COLLAPSED_GLOBAL_LOADING,
    CollapsedFactorError,
    P_E,
    P_F,
    build_panel,
    estimate_short,
    free_parameter_mask,
    load_vintage,
    quick_nowcast,
    state_space,
    target_periods,
)
from nyfed.au.deflator import (
    DEFLATOR_SOURCES,
    MIN_SPLICE_OVERLAP,
    build_deflator,
    real_household_spending,
)
from nyfed.au.emit import annualised_to_qoq
from nyfed.au.fetch_abs import parse_abs_frame
from nyfed.au.fetch_rba import parse_rba_frame
from nyfed.au.freshness import StaleSeriesError
from nyfed.au.panel import Panel
from nyfed.au.restrict import COVID_END, COVID_START, build_restrict
from nyfed.au.sources import AU_SERIES, SPEC_PATH
from nyfed.model import construct_ssm
from nyfed.parameters import map_parameter
from nyfed.spec import load_spec

FIXTURES = Path(__file__).parent / "fixtures" / "au"
VINTAGE = FIXTURES / "vintage"

# The vintage the model path is built at. Chosen by measurement, and it moved
# once already: 2026-07-01 was picked while `build_panel` cut vintages by
# reference date, and under an honest release-date cut that vintage contains no
# data at all from after its target quarter -- the fastest series in the panel
# has a 34-day lag, so nothing published inside Q2 2026 has arrived by
# 2026-07-01 that is not itself a Q2 month.
#
# 2026-06-01 is the vintage that works, and there is exactly one window like it:
#   * Q1 2026 GDP is released 2026-06-03, so at 2026-06-01 the last observed
#     GDP is Q4 2025 and the target quarter is Q1 2026;
#   * April 2026 is then a post-target month, and eight series had published it
#     by 2026-06-01;
#   * every series passes its budget -- `aig_pmi`, the binding one, is 61 days
#     old against 117.
# What makes the window unique is the post-target data, not the budgets. Later
# vintages build too -- `COMPOSED_BUILDS` exercises 2026-07-01 -- but the panel's
# fastest series has a 34-day lag, so a vintage inside a quarter carries no
# month from after the quarter it is nowcasting. `aig_pmi` stopped updating on
# 2026-05-01, so from 2026-08-27 every vintage is refused on that series alone.
ASOF = "2026-06-01"

# GDP is observed through 2025-12, so the target quarter is Q1 2026.
TARGET_QUARTER = (pd.Timestamp("2026-01-01"), pd.Timestamp("2026-03-01"))

# A short run: enough to show the sampler completes and does not collapse. Not
# an accuracy check -- there is nothing to check against.
#
# THE SEED IS PART OF THE MEASUREMENT, NOT A TUNING KNOB, and it is disclosed
# rather than quietly chosen. GDP's posterior on this panel is BIMODAL: a chain
# settles into one basin within its first sweeps and stays there, and
# lengthening the chain does not resolve it (measured to 2,000 sweeps). In the
# low basin the nowcast is driven by GDP's own idiosyncratic dynamics and barely
# reads the monthly panel at all.
#
# ALL THREE SEEDS BELOW WERE RE-MEASURED ON 2026-08-28, when `cpi_trimmed` left
# the registry. Dropping a series changes the panel and so changes which seed
# lands where; the previous values (3, 6 and 5) were measurements of the
# 15-series panel and two of the three had swapped basins. Thirty seeds, sorted:
#
#   0.065 0.074 0.075 0.118 0.149 0.330 0.369 0.369 0.436 0.439 0.493 0.535
#   0.550 0.627 0.736 0.745 0.796 0.856 | 1.096 1.215 1.230 1.397 1.430 1.465
#   1.497 1.524 1.558 1.596 1.601 1.712
#
# 18 of 30 below the floor, 12 above, and the widest gap in the distribution
# (0.856 -> 1.096) still straddles `COLLAPSED_GLOBAL_LOADING`, so the floor set
# at 1.0 on the old panel survives the change on its own evidence.
#
# `test_the_gdp_loading_is_bimodal_across_seeds` pins the finding directly, so
# it is a measured property of this panel rather than a footnote, and the gate
# runs at a seed in the identified basin so that the discriminator below is
# testing the pipeline rather than the coin flip. If the seed changes,
# `test_the_gate_runs_in_the_basin_where_gdp_loads_the_global_factor` fails and
# names the reason.
N_GS, N_BURN, SEED = 200, 100, 4      # 1.413 on the shipping panel

# THE SHIPPING PANEL IS NO LONGER BIMODAL. Re-measured on 2026-08-30, when
# `DEFAULT_START` moved from 1990 to 1980 (see `nyfed/au/build.py` for the
# evidence): THIRTY of thirty seeds land in the identified basin, sorted
#
#   1.393 1.413 1.417 1.452 1.472 1.489 1.504 1.524 1.548 1.557 1.565 1.568
#   1.569 1.583 1.596 1.645 1.651 1.652 1.661 1.679 1.703 1.737 1.768 1.780
#   1.817 1.839 1.849 1.858 1.952 2.049
#
# against the 1990 panel's 18-collapsed/12-identified split. There is no second
# basin and no middle band left to sample: the lowest chain sits 0.39 above the
# floor. The COVID window's share of GDP's standardised variation falls from
# 64.5% to 48.2% with the extra forty quarters, and that is enough.
#
# THE GUARD IS KEPT AND STILL TESTED, on `legacy_panel` below. A guard that
# cannot fire on today's panel is not a dead guard -- it is one whose failure
# mode this panel happens to avoid, and the failure mode is one vintage or one
# spec change away from returning. `COLLAPSED_SEED` and `MIDDLE_BAND_SEED` are
# measurements of THAT panel, not this one.
COLLAPSED_SEED = 14                   # 0.075 on `legacy_panel` -- collapsed
LEGACY_START = "1990-01-01"           # where the panel opened until 2026-08-30

# The Global block, column 0 of `spec.blocks`.
I_GLOBAL = 0


@pytest.fixture(scope="module")
def panel() -> Panel:
    return build_panel(asof=ASOF, vintage=VINTAGE)


@pytest.fixture(scope="module")
def spec():
    return load_spec(SPEC_PATH)


@pytest.fixture(scope="module")
def fitted(panel):
    """One short sampler run, and the state space and horizons it implies."""
    result = estimate_short(panel, n_gs=N_GS, n_burn=N_BURN, seed=SEED)
    return result, state_space(panel, result), target_periods(panel)


@pytest.fixture(scope="module")
def legacy_panel() -> Panel:
    """The panel as it opened until 2026-08-30: 1990, not 1980.

    A REGRESSION FIXTURE, not a second production path. The collapse guard
    protects against a chain that leaves the target disconnected from the panel,
    and on the shipping panel that no longer happens at any of thirty seeds --
    so the guard has nowhere to demonstrate itself. Deleting its tests because
    the current panel is healthy would leave the guard unexercised until the day
    it matters. This panel is where it fires.
    """
    return build_panel(asof=ASOF, start=LEGACY_START, vintage=VINTAGE)


@pytest.fixture(scope="module")
def legacy_identified_result(legacy_panel):
    """Seed 4 on the legacy panel: 1.430, the identified basin."""
    return estimate_short(legacy_panel, n_gs=N_GS, n_burn=N_BURN, seed=SEED)


@pytest.fixture(scope="module")
def collapsed_result(legacy_panel):
    """Seed 14 on the legacy panel: 0.075, unambiguously collapsed.

    Shared by the bimodality measurement and the collapse-guard test so that the
    two cost a single sampler run between them.
    """
    return estimate_short(legacy_panel, n_gs=N_GS, n_burn=N_BURN,
                          seed=COLLAPSED_SEED)


def _with_data(panel: Panel, Y: np.ndarray) -> Panel:
    """The same vintage with a different data matrix. Never mutates ``panel``."""
    return Panel(Y=Y, y_location=panel.y_location, y_scale=panel.y_scale,
                 dates=panel.dates, series_id=panel.series_id, i_now=panel.i_now)


# --------------------------------------------------------------------------- #
# The panel
# --------------------------------------------------------------------------- #


def test_the_panel_has_one_row_per_registered_series(panel):
    """14, not the 17 an earlier draft of this plan assumed: ABS ceased Retail
    Trade in July 2025, the Internet Vacancy Index turned out never to have been
    fetched by v2 at all, and ``cpi_trimmed`` was dropped on 2026-08-28. See
    ``nyfed/au/sources.py``."""
    assert panel.Y.shape[0] == len(AU_SERIES) == 14
    assert panel.series_id == [s.series_id for s in AU_SERIES]
    assert panel.series_id[panel.i_now] == "gdp"


def test_gdp_and_the_core_labour_series_reach_back_to_1990(panel):
    """The revised Plan B gate. Everything else starts when it genuinely
    starts -- household spending in 2012, monthly CPI in 2024 -- and those
    ragged starts are tested, not filled."""
    cutoff = pd.Timestamp("1990-12-01")
    early = panel.dates <= cutoff
    for key in ("gdp", "employment", "unemployment_rate"):
        row = panel.series_id.index(key)
        assert np.isfinite(panel.Y[row, early]).any(), f"{key} has no pre-1991 history"


def test_late_starting_series_are_nan_not_zero_before_they_start(panel):
    for key, not_before in (("household_spending", "2010-01-01"),
                            # 2017-09: `cpi` is spliced onto the ceased
                            # 6484.0 indicator, so it starts there, not 2024.
                            ("cpi", "2015-01-01"),
                            ("job_ads", "2015-01-01")):
        row = panel.series_id.index(key)
        first = panel.dates[np.isfinite(panel.Y[row])][0]
        assert first > pd.Timestamp(not_before), key
        assert np.isnan(panel.Y[row, panel.dates < first]).all(), key


def test_quarterly_rows_sit_in_the_last_month_of_their_quarter(panel):
    for key in ("gdp", "gdi", "unit_labour_cost"):
        row = panel.series_id.index(key)
        observed = panel.dates[np.isfinite(panel.Y[row])]
        assert set(observed.month) == {3, 6, 9, 12}, key


def test_the_engine_accepts_the_australian_panel(panel, spec):
    """``construct_ssm`` is the first engine function the panel meets. If the
    spec and the panel disagree about dimensions it fails here rather than deep
    in the sampler, so build a real state space rather than only comparing
    shapes -- a shape check would pass on a spec whose restrictions the engine
    cannot represent."""
    assert spec.blocks.shape[0] == panel.Y.shape[0]
    assert spec.blocks.shape[1] == 5

    n, n_f = spec.blocks.shape
    T = panel.Y.shape[1]
    restrict = build_restrict(panel, spec, p_f=P_F)
    from nyfed.model import Latent
    from nyfed.parameters import Params

    latent = Latent(sigma=np.ones((n_f + n, T)), s=np.ones((n_f + n, T)))
    param = Params(
        mu=np.zeros(n), gamma_g=0.01,
        Lambda=np.nan_to_num(restrict.Lambda), Phi=np.nan_to_num(restrict.Phi),
        gamma_f=np.full(n_f, 0.03), pi_f=np.full(n_f, 0.95),
        phi=np.zeros((n, P_E)), gamma_e=np.full(n, 0.01), pi_e=np.full(n, 0.95),
    )
    ssm = construct_ssm(param, latent, restrict)
    assert ssm.H.shape[0] == n
    assert np.isfinite(np.asarray(ssm.F)).all()


def test_the_nowcast_target_is_the_quarter_after_the_last_observed_gdp(panel):
    t_now = target_periods(panel)
    last_gdp = panel.dates[np.isfinite(panel.Y[panel.i_now])][-1]
    # Q1 2026 is released 2026-06-03, two days after this vintage, so Q4 2025
    # is still the latest observed quarter and Q1 2026 is what is nowcast.
    assert last_gdp == pd.Timestamp("2025-12-01")
    assert panel.dates[t_now[0]] == TARGET_QUARTER[1]
    assert list(panel.dates[t_now]) == [pd.Timestamp("2026-03-01"),
                                        pd.Timestamp("2026-06-01")]


# One composed build per row, from the SAME committed recording. Each entry is
# (asof, last observed GDP month, the quarters `target_periods` returns).
#
# WHY MORE THAN ONE. Until this table existed the whole composed pipeline --
# cut, deflate, guard, assemble -- had exactly one passing end-to-end instance,
# at ASOF, plus one asserting a refusal. That is what let `build_deflator`
# refuse every vintage before 2024-11 without anything noticing: the one asof
# that was exercised happened to be one where all three deflator tiers were
# available. It costs about a second of runtime and no new fixture.
#
# The expectations are not free parameters. `last_gdp` follows from the national
# accounts' 94-day lag and the number of horizons from how far the panel runs
# past it, so the rows alternate 1, 1, 2 with the quarterly calendar -- a
# property of the vintage, not a constant, which is exactly what a single
# instance could not show.
COMPOSED_BUILDS = [
    # Early enough that the live 6401.0 CPI tier has only three released months
    # and cannot be rebased, so `build_deflator` must SKIP it. Under the tier
    # guard this task replaced, every asof before 2024-11-01 died here.
    ("2024-08-01", "2024-03-01", ["2024-06-01"]),
    ("2024-11-01", "2024-06-01", ["2024-09-01"]),
    ("2025-09-01", "2025-03-01", ["2025-06-01", "2025-09-01"]),
    # February: `aig_pmi` is 92 days old across Ai Group's missing January,
    # which the frequency-default budget of 86 refused. See
    # test_au_freshness.py.
    ("2026-02-01", "2025-09-01", ["2025-12-01"]),
    ("2026-03-01", "2025-09-01", ["2025-12-01", "2026-03-01"]),
    ("2026-05-01", "2025-12-01", ["2026-03-01"]),
    ("2026-07-01", "2026-03-01", ["2026-06-01"]),
]


@pytest.mark.parametrize("asof,last_gdp,horizons", COMPOSED_BUILDS)
def test_the_composed_build_works_across_vintages(asof, last_gdp, horizons):
    """The whole pipeline at seven vintages, not one. See COMPOSED_BUILDS."""
    built = build_panel(asof=asof, vintage=VINTAGE)

    assert built.series_id == [s.series_id for s in AU_SERIES]
    assert built.dates[-1] == pd.Timestamp(asof)
    assert built.series_id[built.i_now] == "gdp"

    observed_gdp = built.dates[np.isfinite(built.Y[built.i_now])]
    assert observed_gdp[-1] == pd.Timestamp(last_gdp)
    assert [str(d.date()) for d in built.dates[target_periods(built)]] == horizons

    # The deflated household spending row survived whatever the deflator had to
    # skip at this vintage: a tier dropped silently would show up as a short or
    # empty row here, not as an error.
    spending = built.series_id.index("household_spending")
    finite = built.dates[np.isfinite(built.Y[spending])]
    assert finite[0] <= pd.Timestamp("2012-09-01"), (
        f"household spending starts {finite[0].date()} at {asof}; the deflator "
        "truncated the row that normalises the Global factor"
    )
    assert len(finite) > 130

    # Nothing in the panel had a release date after the vintage -- the same
    # invariant test_the_vintage_cut_is_by_release_date_not_by_reference_date
    # pins at ASOF, checked at every asof in the table.
    lags = {s.key: s.publication_lag_days for s in AU_SERIES}
    for row, key in enumerate(built.series_id):
        last = built.dates[np.isfinite(built.Y[row])][-1]
        assert last + pd.Timedelta(days=lags[key]) <= pd.Timestamp(asof), key


def test_the_composed_builds_cover_more_than_one_horizon_count():
    """The table has to contain the variation it claims to, or it is one case
    written seven times."""
    counts = {len(h) for _, _, h in COMPOSED_BUILDS}
    assert counts == {1, 2}
    assert len({a for a, _, _ in COMPOSED_BUILDS}) == len(COMPOSED_BUILDS)


# --------------------------------------------------------------------------- #
# The deflated row
# --------------------------------------------------------------------------- #


def test_the_household_spending_row_is_the_deflated_series_not_the_nominal_one(panel):
    """Carried forward from Task 5, and the single easiest thing in this plan to
    get silently wrong.

    The registry fetches ``5682.0:A130200584T`` at CURRENT prices.
    ``panel.assemble`` deflates nothing -- it takes whatever it is handed and
    the model runs on it either way -- so ``build_panel`` is the only thing
    standing between the nominal series and the Global factor, which this row
    normalises.

    Checked by reconstruction rather than by assertion: undo the row's
    standardisation and compare it against the ``pch`` of both candidate
    series. It matches the real one to floating point and misses the nominal one
    by up to 1.47pp in a single month, which is roughly five times the panel's
    median absolute monthly move.
    """
    vintage = load_vintage(VINTAGE).as_of(ASOF)
    nominal = vintage.series["household_spending"]
    real, _ = real_household_spending(nominal, vintage.deflator_sources)
    assert real.iloc[-1] < 0.8 * nominal.iloc[-1], (
        "the deflated series is not materially below the nominal one; the "
        "deflator did nothing"
    )

    row = panel.series_id.index("household_spending")
    observed = panel.Y[row] * panel.y_scale[row, 0] + panel.y_location[row, 0]

    def monthly_pch(series: pd.Series) -> np.ndarray:
        aligned = series.reindex(panel.dates)
        return (100.0 * (aligned / aligned.shift(1) - 1.0)).to_numpy(dtype=float)

    finite = np.isfinite(observed)
    assert finite.sum() > 150
    np.testing.assert_allclose(observed[finite], monthly_pch(real)[finite], atol=1e-9)

    gap = np.abs(observed[finite] - monthly_pch(nominal)[finite])
    assert gap.max() > 1.0, (
        "the panel row is indistinguishable from the NOMINAL series' growth; "
        "the deflation step is not reaching the panel"
    )


# --------------------------------------------------------------------------- #
# The freshness guard, live
# --------------------------------------------------------------------------- #


def test_a_build_at_the_vintages_own_date_is_refused_because_the_pmi_is_dead():
    """Not a bug: the guard doing its job, pinned so it cannot be quietly lost.

    ``nowcasting_v2/data_raw/aig_pmi.csv`` was last committed on 2026-06-11 with
    its last observation at 2026-05-01, so the row v3 reads stopped months ago.
    Ai Group itself has NOT stopped -- sourcing the publication lag turned up
    releases for May, June and July 2026, the last of which still reports a
    separate manufacturing headline -- so what is dead is v2's scraper, and the
    fix is a working fetcher rather than a replacement series. Either way the
    build must refuse, and the way to nowcast again is not to widen the budget.

    IT REFUSES ON THAT SERIES AND NOTHING ELSE. Under the old hand-typed 75-day
    monthly budget this build also named building approvals, household spending,
    exports and imports -- all four entirely current, all four dated to the
    start of their reference month and published about two months later.
    Deriving the budget from a sourced publication lag passes them and still
    catches the dead row, so the negative assertion is the load-bearing half.

    DATED TO THE VINTAGE, NOT TO ``today()``. The recording is frozen, so a
    ``today()``-based version of this test had a shelf life rather than a
    meaning: re-scanned day by day on 2026-08-28, the stale set stays
    ``{aig_pmi}`` through 2026-09-23, becomes five series on 2026-09-24, ten by
    2026-09-29, thirteen by 2026-10-20 and all fourteen on 2026-11-05 -- at
    which point the gate would fail looking like a freshness regression instead
    of "the vintage needs re-recording". (An earlier draft of this docstring
    said "all fifteen by 2026-10-20"; the scan says the last series to go is
    ``nab_conditions``, sixteen days later.) Measuring against the vintage's own
    ``recorded_at`` asks the question the frozen data can actually answer.

    A WEEK AFTER THE RECORDING, NOT ON ITS OWN DATE, AND THE WEEK IS THE POINT.
    ``aig_pmi``'s budget widened from 86 days to 117 when the registry took on
    Ai Group's skipped December or January (``sources.py``), so the last
    observation at 2026-05-01 first breaches it on 2026-08-27 -- one day after
    this recording was made. That is the disclosed cost of not refusing every February: the
    dead feed is still caught, 31 days later than before. The offset is small
    and deliberate; if it ever has to grow, the budget is what changed.
    """
    vintage = load_vintage(VINTAGE)
    assert vintage.recorded_at is not None, "the recording has no date to test at"
    recorded_on = pd.Timestamp(vintage.recorded_at).tz_convert(None).normalize()
    asof = recorded_on + pd.Timedelta(days=7)

    pmi = next(s for s in AU_SERIES if s.key == "aig_pmi")
    assert pmi.max_age_days == 117, (
        "the skipped-month override moved; re-check the offset above"
    )

    with pytest.raises(StaleSeriesError) as excinfo:
        build_panel(asof=str(asof.date()), vintage=vintage)

    stale = {key: age for key, age, _ in excinfo.value.stale}
    assert set(stale) == {"aig_pmi"}, f"expected only aig_pmi, got {sorted(stale)}"
    assert stale["aig_pmi"] > pmi.max_age_days
    assert "aig_pmi" in str(excinfo.value)


def test_a_2018_vintage_deflates_household_spending_over_its_whole_span():
    """The deflator at a vintage six years before its most preferred tier exists.

    At ``asof="2018-06-01"`` the live 6401.0 monthly CPI has not been published
    -- it begins in 2024-04 -- so tier 1 is legitimately empty, tier 2 (the
    ceased 6484.0 indicator, 2017-09 onward) leads, and the interpolated
    quarterly tier covers everything before it. That is the precedence design
    working, and until this task it raised ``deflator source cpi_monthly_live is
    empty`` instead.

    69 months, 2012-07 to 2018-03: household spending's entire released span at
    that vintage, deflated, with nothing truncated at the leading edge.
    """
    vintage = load_vintage(VINTAGE)
    cut = vintage.as_of("2018-06-01")

    deflator = build_deflator(cut.deflator_sources, recorded=vintage.deflator_sources)
    assert list(deflator.skipped) == ["cpi_monthly_live"]
    assert set(deflator.coverage()) == {"cpi_monthly_ceased", "cpi_quarterly"}

    real, _ = real_household_spending(
        cut.series["household_spending"],
        cut.deflator_sources,
        recorded=vintage.deflator_sources,
    )
    real = real.dropna()
    assert (real.index[0], real.index[-1]) == (
        pd.Timestamp("2012-07-01"), pd.Timestamp("2018-03-01")
    )
    assert len(real) == 69
    assert (real > 0).all()


def test_the_deflator_builds_at_every_monthly_vintage_and_never_hits_the_splice_floor():
    """``_admit``'s load-bearing claim, checked rather than argued.

    The admission pass compares each tier against the single adjacent older tier,
    while ``splice`` measures the overlap against the UNION of everything newer.
    The union contains the adjacent tier, so the admitted overlap is a lower
    bound and ``splice``'s ``min_overlap`` should never be what refuses -- it is
    a backstop, not the working guard. That is an argument; this is the
    measurement, over 164 consecutive monthly vintages of the real recording.

    It also pins the other half of I1: at every one of those vintages the
    deflator BUILDS. The failures that remain before 2024-08 are the panel's
    (``cpi`` has no history before 2024-04), not the deflator's.
    """
    vintage = load_vintage(VINTAGE)
    thin = []
    for asof in pd.date_range("2013-01-01", "2026-08-01", freq="MS"):
        cut = vintage.as_of(asof)
        deflator = build_deflator(
            cut.deflator_sources, recorded=vintage.deflator_sources
        )
        index = deflator.index
        assert not index.isna().any() and (index > 0).all(), asof
        assert (index.index == pd.date_range(
            index.index[0], index.index[-1], freq="MS"
        )).all(), f"the deflator has a hole at {asof.date()}"
        thin += [
            (str(asof.date()), seam.older, seam.n_overlap)
            for seam in deflator.seams
            if seam.n_overlap < MIN_SPLICE_OVERLAP
        ]
    assert not thin, f"splice's floor was reached after admission: {thin}"


def test_a_2018_vintage_refuses_naming_the_one_series_that_is_short():
    """The build still cannot go back to 2018, and only one series says why.

    ``job_ads`` (ANZ-Indeed) begins 2021-01, so before then it has no
    observations at all and the freshness guard names it. TWO SERIES USED TO BE
    IN THIS SET.

    ``cpi`` left it when `build_panel` began splicing the live 6401.0 series
    onto the ceased 6484.0 Monthly CPI Indicator, which starts 2017-09.

    ``cpi_trimmed`` left it by being dropped from the registry on 2026-08-28.
    It could not be spliced the way `cpi` was -- 6484.0 published EXCLUSION-based
    measures ("All groups CPI excluding volatile items") and a year-ended trimmed
    RATE, never a trimmed mean INDEX, and joining either onto a trimmed mean
    would join two different constructions. Pinned at 2024-04 it was, alone, the
    binding constraint on how far back Plan C could backtest. See the
    ``cpi_trimmed`` note in ``nyfed/au/sources.py`` for why a fifth series in a
    five-series Nominal block did not earn that cost.

    ``job_ads`` is now the whole boundary, and it is a much cheaper one --
    ``test_the_earliest_buildable_vintage_is_set_by_job_ads`` measures where.
    """
    with pytest.raises(StaleSeriesError) as excinfo:
        build_panel(asof="2018-06-01", vintage=VINTAGE)
    assert {key for key, _, _ in excinfo.value.stale} == {"job_ads"}


def test_the_earliest_buildable_vintage_is_set_by_job_ads():
    """Plan C's backtest window, measured rather than assumed.

    This is the number dropping ``cpi_trimmed`` bought, and the reason to drop
    it. Measured on this recorded vintage, against the registry at 2b49a15:

        with    `cpi_trimmed`:  earliest asof 2024-07-01  (~7 target quarters)
        without `cpi_trimmed`:  earliest asof 2021-05-01  (~20 target quarters)

    THE THREE MONTHS BEFORE IT EACH FAIL FOR THEIR OWN REASON, and all three
    are asserted because between them they are the whole boundary:

      2021-02  `job_ads` has no observation released yet -- StaleSeriesError
      2021-03  it has one, but `chg` consumes the first, leaving an all-NaN row
      2021-04  it has one finite observation, whose ddof=1 sd is undefined
      2021-05  two observations: the first vintage that honestly builds

    2021-04 is the case worth pinning. It BUILT before `standardise` grew its
    thin-row guard, silently, with `job_ads` standardised against an invented
    scale of 1.0 -- the panel one would actually have backtested on. See
    ``nyfed/au/panel.py``.

    Two observations is the arithmetic floor, not an informativeness one.
    `job_ads`' scale reads 0.50 at n=2 against ~6.3 from about n=7 (2021-10),
    so Plan C should choose its own start inside this range with that in view;
    what this test fixes is where the primitive stops lying.

    Pinned so that a later change moving the boundary in either direction has
    to say so here. If a longer `job_ads` back series appears, the earliest
    date moves and this test is where that shows up.
    """
    with pytest.raises(StaleSeriesError) as excinfo:
        build_panel(asof="2021-02-01", vintage=VINTAGE)
    assert {key for key, _, _ in excinfo.value.stale} == {"job_ads"}

    with pytest.raises(ValueError, match="no finite observation at all"):
        build_panel(asof="2021-03-01", vintage=VINTAGE)

    with pytest.raises(ValueError, match="fewer than 2 finite observations"):
        build_panel(asof="2021-04-01", vintage=VINTAGE)

    panel = build_panel(asof="2021-05-01", vintage=VINTAGE)
    assert panel.Y.shape[0] == len(AU_SERIES) == 14
    assert panel.dates[-1] == pd.Timestamp("2021-05-01")
    i_ads = panel.series_id.index("job_ads")
    assert np.isfinite(panel.Y[i_ads]).sum() == 2


def test_the_vintage_cut_is_by_release_date_not_by_reference_date(panel):
    """The look-ahead this task shipped in round 1, now a standing check.

    An Australian series' panel date runs weeks ahead of its release -- a
    monthly is dated to the first of its reference month, a quarterly to the
    LAST month of its quarter -- so cutting a vintage at ``asof`` on the
    observation's own date admits data nobody had yet, up to nine weeks of it
    on ``gdp``.
    The invariant is the one a person at a desk would recognise: nothing in the
    panel can have a release date after the vintage.

    The instance is pinned as well as the rule, against a release date this repo
    verified independently: ``test_commodity_prices_reproduces_the_published
    _release`` records the 2026-07 commodity index as released 4 August 2026,
    a 34-day lag, which puts the 2026-05 observation at 2026-06-04 -- three days
    after this vintage. So April is the last commodity month a 2026-06-01
    vintage may contain, and the reference-date rule would have given it May.
    """
    asof = pd.Timestamp(ASOF)
    lags = {s.key: s.publication_lag_days for s in AU_SERIES}

    unreleased = []
    for row, key in enumerate(panel.series_id):
        observed = panel.dates[np.isfinite(panel.Y[row])]
        released = observed[-1] + pd.Timedelta(days=lags[key])
        if released > asof:
            unreleased.append((key, str(observed[-1].date()), str(released.date())))
    assert not unreleased, (
        f"observations in the panel that had not been released at {ASOF}: "
        f"{unreleased}"
    )

    commodity = panel.series_id.index("commodity_prices")
    observed = panel.dates[np.isfinite(panel.Y[commodity])]
    assert observed[-1] == pd.Timestamp("2026-04-01")


# --------------------------------------------------------------------------- #
# The recorded vintage
# --------------------------------------------------------------------------- #


def test_the_recorded_vintage_covers_every_registered_series_and_deflator_tier():
    vintage = load_vintage(VINTAGE)
    assert set(vintage.series) == {s.key for s in AU_SERIES}
    assert set(vintage.deflator_sources) == {d.key for d in DEFLATOR_SOURCES}
    assert all(not s.dropna().empty for s in vintage.series.values())


def test_the_recorded_vintage_agrees_with_the_payloads_verified_against_ABS(spec):
    """The recording is checked, not trusted.

    ``tests/fixtures/au/abs_*.csv`` and ``rba_I2.csv`` are the trimmed payloads
    Tasks 2 and 3 pinned against published ABS and RBA releases. The vintage is
    a separate, full-history recording of the same series, so where the two
    overlap they must agree exactly. Without this, a vintage recorded from the
    wrong series -- or corrupted in the CSV round trip -- would build a panel,
    standardise cleanly and estimate happily.

    THIS COVERS 12 OF THE 15 ROWS -- 11 ABS and 1 RBA. ``job_ads``, ``aig_pmi``
    and ``nab_conditions`` are recorded in the vintage like everything else, but
    they come from v2's committed CSVs and have no release-pinned payload in
    this repo to be checked against -- so for those three the recording is
    trusted, not checked, and that is the honest description of it.
    """
    period_freq = {"m": "M", "q": "Q-DEC"}
    vintage = load_vintage(VINTAGE)
    compared = 0
    for source in AU_SERIES:
        if source.fetcher == "abs":
            frame = pd.read_csv(FIXTURES / f"abs_{source.key}.csv", index_col=0)
            frame.index = pd.PeriodIndex(
                frame.index.astype(str), freq=period_freq[source.frequency]
            )
            recorded = parse_abs_frame(frame, source.locator.split(":")[1])
        elif source.fetcher == "rba":
            table = source.locator.split(":")[0]
            frame = pd.read_csv(FIXTURES / f"rba_{table}.csv", index_col=0,
                                parse_dates=True)
            recorded = parse_rba_frame(frame, source.locator.split(":")[1])
        else:
            # The v2 rows ARE in the recording; what they lack is a
            # release-pinned payload to check against, so "checked, not
            # trusted" holds for 12 of the 15 rows and is stated as such.
            continue
        overlap = recorded.index.intersection(vintage.series[source.key].index)
        assert len(overlap) >= 24, f"{source.key}: only {len(overlap)} months overlap"
        np.testing.assert_allclose(
            vintage.series[source.key].reindex(overlap).to_numpy(dtype=float),
            recorded.reindex(overlap).to_numpy(dtype=float),
            rtol=0, atol=0, err_msg=source.key,
        )
        compared += 1
    assert compared == len([s for s in AU_SERIES if s.fetcher in ("abs", "rba")])


def test_a_vintage_recorded_under_a_different_locator_is_refused(tmp_path):
    """A recording is only as good as the locators it was fetched from.

    ``sources.py`` has already moved once mid-project -- monthly CPI from the
    ceased 6484.0 to the live 6401.0 -- and a recording made before that move
    would replay the dead catalogue's numbers under the new id without a word.
    """
    for name in ("series.csv", "deflator_sources.csv"):
        (tmp_path / name).write_bytes((VINTAGE / name).read_bytes())
    manifest = json.loads((VINTAGE / "manifest.json").read_text())
    manifest["locators"]["gdp"] = "5206.0:SOMETHING_ELSE"
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))

    with pytest.raises(ValueError, match="gdp"):
        load_vintage(tmp_path)


# --------------------------------------------------------------------------- #
# The model path
# --------------------------------------------------------------------------- #


@pytest.mark.slow
def test_the_sampler_moves_every_free_parameter_and_no_restricted_one(panel, spec, fitted):
    """A short run: enough to prove the sampler completes on this panel and does
    not collapse. Not an accuracy check -- there is nothing to check against.

    "Every parameter moved" would be the wrong assertion and would fail on a
    correct run: ``GibbsResult.params`` stores the whole vector, and 74 of the
    Australian panel's 246 entries are restricted -- structural zeros and
    normalising ones -- which the sampler holds fixed by design. The two-sided
    version is the one with a right answer, and the restricted half is a real
    check: a restricted entry that moved would mean a normalising loading had
    drifted off 1 and the factor it normalises had silently rescaled.
    """
    result, _, _ = fitted
    n, n_f = spec.blocks.shape
    free = free_parameter_mask(build_restrict(panel, spec, p_f=P_F), (n, n_f, P_F, P_E))

    assert np.isfinite(result.params).all()
    assert result.params.shape[1] == N_GS
    assert 0 < free.sum() < free.size

    spread = result.params.std(axis=1)
    assert (spread[free] > 0).all(), (
        f"{int((spread[free] == 0).sum())} free parameters never moved"
    )
    assert (spread[~free] == 0).all(), (
        f"{int((spread[~free] > 0).sum())} restricted parameters moved"
    )


@pytest.mark.slow
def test_the_nowcast_reaches_publication_units_without_tripping_the_domain_guard(
    panel, fitted
):
    """``emit.annualised_to_qoq`` raises at or below -100% annualised, by design.

    Nothing in a sane nowcast reaches it, so this is not a test of the guard --
    Task 9 pins that -- but of the WIRING: it says that what comes out of
    ``quick_nowcast`` is in the domain the publication step accepts, and that
    the two agree about units. GDP's spec transformation is ``pca``, so the
    number is annualised; if it were ever handed over as a quarter-on-quarter
    figure, or with the standardisation left on, this is where that would show.
    """
    _, ssm, t_now = fitted
    annualised = quick_nowcast(panel, ssm=ssm, t_now=t_now)
    assert np.isfinite(annualised)
    assert -100.0 < annualised < 100.0
    qoq = float(annualised_to_qoq(annualised))
    assert np.isfinite(qoq)
    assert abs(qoq) < abs(annualised)      # compounding, not division


def _shock_move(panel, ssm, t_now, rows, columns, base):
    """How far a one-sigma shock to ``rows`` x ``columns`` moves the nowcast.

    Every row of the panel is standardised, so +1.0 is one standard deviation of
    that series' own transformed history, and the answer comes back in GDP's own
    units (annualised percentage points).
    """
    shocked = panel.Y.copy()
    shocked[np.ix_(rows, columns)] += 1.0
    return abs(quick_nowcast(_with_data(panel, shocked), ssm=ssm, t_now=t_now) - base)


@pytest.mark.slow
def test_the_target_quarters_own_months_drive_the_nowcast(panel, spec, fitted):
    """The pipeline reads its data. Everything below depends on this.

    A nowcast that had stopped reading its monthly indicators -- a broken
    transform, an alignment that dropped the current quarter, a measurement
    equation that ignored the monthly rows -- would sail through any "the
    nowcast did not move" test. This is the arm that fails in that case, and it
    is why the sensitivity comparison below means anything at all.

    Threshold from measurement, and the measurement has TWO populations, which
    is the point of ``test_the_gdp_loading_is_bimodal_across_seeds``. In the
    basin this gate runs in -- GDP loading the Global factor -- a one-sigma
    shock across January-March 2026 moved the nowcast by 2.169, 2.345 and
    1.833pp at seeds 1, 3 and 7. In the other basin it moved 0.015, 0.316 and
    0.185pp at seeds 321, 2 and 99, because there GDP barely loads the factor
    the monthly series feed. The floor is set well below the first population
    and well above the second, so this test asserts that the gate is in the
    basin it says it is in as much as it asserts that the pipeline reads data.

    CONFIRMED BY BREAKING IT, in the shape the bug would really take: with the
    target quarter's months dropped from the panel -- the alignment failure Task
    2 actually hit, where a mask silently emptied the columns that matter -- the
    shock lands on nothing and the move is exactly 0.0.
    """
    _, ssm, t_now = fitted
    monthly = np.array([f == "m" for f in spec.frequency])
    inside = (panel.dates >= TARGET_QUARTER[0]) & (panel.dates <= TARGET_QUARTER[1])
    assert inside.sum() == 3
    base = quick_nowcast(panel, ssm=ssm, t_now=t_now)

    # 0.5 PERCENTAGE POINTS OF NOWCAST RESPONSE -- not the 0.75 loading floor in
    # `COLLAPSED_GLOBAL_LOADING`, which shares two digits and nothing else. This
    # one is measured from the identified basin's responses (1.833, 2.169,
    # 2.345pp); do not "unify" the two.
    move = _shock_move(panel, ssm, t_now, monthly, inside, base)
    assert move > 0.5, (
        f"a one-sigma shock to the target quarter's own months moved the "
        f"nowcast by only {move:.4f}pp; either the model is not reading them or "
        "the chain is in the basin where GDP does not load the Global factor"
    )

    # The break, run here rather than described: with those months emptied the
    # same shock has nothing to act on.
    emptied = panel.Y.copy()
    emptied[np.ix_(monthly, inside)] = np.nan
    dropped = _with_data(panel, emptied)
    dropped_base = quick_nowcast(dropped, ssm=ssm, t_now=t_now)
    assert _shock_move(dropped, ssm, t_now, monthly, inside, dropped_base) == 0.0


@pytest.mark.slow
def test_later_months_move_the_nowcast_far_less_than_the_target_quarters_own(
    panel, spec, fitted
):
    """The leakage-shaped check, with its limits stated rather than implied.

    The target quarter is Q1 2026; April 2026 is in the panel because seven of
    the fourteen series had published it by this vintage. A one-sigma shock to
    those April observations moves the Q1 nowcast by a small fraction of what
    the same shock inside Q1 does. Not zero, and it should not be: the smoother
    is two-sided, so a later month legitimately carries a little information
    about the factor path in March.

    WHAT THIS DOES NOT ESTABLISH. It does not detect a one-month misalignment.
    Measured across six sampler seeds, the probe is caught at NONE of them: the
    healthy ratios are 17.6, 162.5, 52.6, 365.2, 395.4 and 17.5, and with
    April's observation written into March's column they become 49.5, 37.8,
    16.9, 22.9, 109.8 and 320.4 -- every one still above the asserted 10, and
    two of them higher than the healthy value. (Round 1 of this task reported
    "2 of 4 seeds" on a different vintage; the correct count there was 1 of 4,
    and on an honest vintage it is 0 of 6.) Those six seeds were measured on the
    15-SERIES PANEL, before `cpi_trimmed` was dropped, and were not re-measured
    for it: the finding is that the probe catches nothing, and one fewer price
    series is not a reason to expect it to start. One post-target month,
    published by seven of the fourteen series, is not enough signal for this
    statistic to separate the cases. The structural
    guarantee is elsewhere (the Octave-pinned quarterly aggregation, plus the
    panel's deterministic alignment tests); this is a consistency check on top
    of it, and Plan C should add a vintage-pair test when more than one
    post-target month exists.

    Thresholds from the same six seeds: the post-target move was 0.0008, 0.0046,
    0.0060, 0.0064, 0.0106 and 0.0134pp, and the ratio never fell below 17.5 --
    in EITHER basin, which is why the ratio rather than the level is what this
    test asserts. The asserted floor of 10 is a long way below the smallest of
    those, which is why it survives a panel change unmeasured; if it ever fires,
    re-measure the six-seed spread before moving it.
    """
    _, ssm, t_now = fitted
    monthly = np.array([f == "m" for f in spec.frequency])
    inside = (panel.dates >= TARGET_QUARTER[0]) & (panel.dates <= TARGET_QUARTER[1])
    after = panel.dates > TARGET_QUARTER[1]
    # Three columns after the target quarter, but only April carries data: the
    # fastest series in the panel has a 34-day lag, so May and June had not been
    # published at this vintage. Seven of the eleven monthly series had April.
    assert after.sum() == 3
    assert np.isfinite(panel.Y[np.ix_(monthly, after)]).sum() == 7, (
        "no post-target observations to shock; the comparison would be vacuous"
    )

    base = quick_nowcast(panel, ssm=ssm, t_now=t_now)
    after_move = _shock_move(panel, ssm, t_now, monthly, after, base)
    inside_move = _shock_move(panel, ssm, t_now, monthly, inside, base)

    assert after_move < 0.15, (
        f"a one-sigma shock to data from AFTER the target quarter moved the "
        f"nowcast by {after_move:.4f}pp"
    )
    assert inside_move > 10 * after_move, (
        f"target-quarter shock {inside_move:.4f}pp against post-target "
        f"{after_move:.4f}pp: the two are too close to tell apart"
    )


@pytest.mark.slow
def test_the_gate_runs_in_the_basin_where_gdp_loads_the_global_factor(panel, spec, fitted):
    """Pin the OUTCOME of the seed-orientation fix, not only its rule.

    ``test_the_seed_agrees_in_sign_with_each_block_s_normalising_series`` enforces
    the rule that produced this -- orient each PCA column to its block's
    normalising series -- but a rule test cannot see the symptom the defect
    produced, which was real GDP growth loading the broadest factor against real
    consumption growth. This is that symptom, measured on the estimated model.

    It is also the gate's declaration of which posterior mode it is in. See
    ``test_the_gdp_loading_is_bimodal_across_seeds``: at ``SEED`` the chain
    settles with GDP's Global loading near 1.43, and every sensitivity number in
    this module is a number from that basin.

    The normalising loadings are checked in the same breath. They are restricted,
    so they must come back at EXACTLY 1.0; anything else means a normaliser
    drifted and the factor it defines has silently rescaled.
    """
    result, _, _ = fitted
    n, n_f = spec.blocks.shape
    param = map_parameter(np.median(result.params, axis=1), (n, n_f, P_F, P_E))

    i_gdp = panel.series_id.index("gdp")
    # The guard's own constant, not a literal: this test predates the guard, and
    # a copy of the number here could drift away from the threshold that
    # actually refuses without either side failing.
    assert param.Lambda[i_gdp, I_GLOBAL] > COLLAPSED_GLOBAL_LOADING, (
        f"GDP's Global loading is {param.Lambda[i_gdp, I_GLOBAL]:.3f}, at or "
        f"below the {COLLAPSED_GLOBAL_LOADING} floor `state_space` refuses at; "
        "before the seed-orientation fix it was -0.76 after 3,000 sweeps, "
        "against a normaliser pinned at +1"
    )
    i_hh = panel.series_id.index("household_spending")
    assert param.Lambda[i_hh, I_GLOBAL] == 1.0

    normalising = np.nan_to_num(spec.blocks) == 1.0
    assert normalising.sum() == 4
    np.testing.assert_array_equal(param.Lambda[normalising], np.ones(4))


@pytest.mark.slow
def test_the_gdp_loading_is_bimodal_across_seeds(
    legacy_panel, spec, legacy_identified_result, collapsed_result
):
    """The finding that moved `DEFAULT_START`, kept as the record of why.

    THIS TEST RUNS ON ``legacy_panel`` (1990), NOT ON WHAT SHIPS. Every number
    below was true of the panel this project ran on until 2026-08-30, and none
    of it is true of the 1980 panel -- see
    ``test_the_shipping_panel_is_not_bimodal``. It is kept because the mechanism
    is still latent: the COVID window did not go away, its share of GDP's
    variation merely fell from 64.5% to 48.2%, and a future spec or vintage that
    pushes it back up brings all of this with it.

    THE PREMISE, measured on the panel rather than asserted: GDP loads only the
    Global factor and the COVID factor; the COVID factor is active for 22 months
    (March 2020 to December 2021); and those 22 months hold **8 of GDP's 143
    observations but 64.5% of its standardised sum of squares**, including all
    five of its largest absolute values. A factor confined to that window can fit
    the biggest moves in the target series almost perfectly.

    THE MECHANISM IS A TWO-SIDED HANDOVER, and the two sides are not equally
    reliable. Re-measured on 2026-08-28 over seven collapsed and six identified
    seeds on this panel:

                    Global    COVID   sigma_e outside the window
      collapsed      0.169    0.798        1.239
      identified     1.429    0.751        0.884

    THE IDIOSYNCRATIC HALF IS THE ROBUST ONE. The COVID factor is zero outside
    its 22 months, so it cannot absorb what the Global loading drops -- 135
    observations still need explaining, and what takes them is GDP's own
    stochastic volatility, up 40% between the basin means. That is why the
    result is a series explained by itself, and it is the half this test
    asserts, at a 1.15x margin rather than a bare inequality: the groups do not
    separate cleanly seed by seed. Every collapsed seed measured sits above the
    identified MEAN of 0.884, but the highest identified value (1.143) exceeds
    the two lowest collapsed ones (1.017, 1.020), so this is a basin-mean
    difference and not a classifier.

    THE COVID HALF IS WEAKER THAN IT LOOKED. 0.798 against 0.751 is barely a
    difference, and two of the seven collapsed seeds (7 and 9) load the COVID
    factor NEGATIVELY, at -0.53 and -0.13. It holds at ``COLLAPSED_SEED``
    (1.210 against 0.921) and at five of seven, so it is asserted -- but as a
    tendency with named exceptions, not as the mechanism. Inside the identified
    basin the COVID loading FALLS as the Global loading rises (1.229 at Global
    1.096, down to 0.235 at Global 1.712), which is the competition the premise
    above describes; across the collapse it mostly does not.

    A LIKELY ENABLER, worth Plan C's attention: the Global factor is normalised
    by household spending, which starts in 2012, so only 164 of the panel's 438
    months pin that factor's scale at all.

    These are separate basins, not tails of one distribution. A chain picks one
    in its first sweeps and stays. Over the 200 stored draws at each of the two
    seeds this test runs, GDP's Global loading has a 5-95% range of
    -0.150..0.293 at ``COLLAPSED_SEED``, with the first and last fifty draws
    averaging 0.051 and 0.075, against 1.106..1.631 at ``SEED`` averaging 1.383
    and 1.311. The ranges do not overlap and neither chain drifts toward the
    other. Lengthening to 2,000 sweeps does not resolve it, and 18 of 30 seeds
    land below the floor on this panel.

    THIS IS WHY THE GATE DECLARES ITS SEED and why ``state_space`` refuses a
    collapsed chain outright. The NY Fed does not face the coin flip because
    ``initval.mat`` ships a fitted starting point that puts the chain in the
    right basin; Australia starts from a bland one. Plan C needs a starting
    point with that job, or a spec that does not make a 22-month factor compete
    with the Global factor for the target series.
    """
    panel = legacy_panel
    n, n_f = spec.blocks.shape
    i_gdp, i_covid = panel.series_id.index("gdp"), spec.block_names.index("COVID")
    window = (panel.dates >= COVID_START) & (panel.dates <= COVID_END)

    # The premise.
    row = panel.Y[i_gdp]
    observed = np.isfinite(row)
    assert observed.sum() == 143
    assert (observed & window).sum() == 8
    share = np.nansum(row[observed & window] ** 2) / np.nansum(row[observed] ** 2)
    assert share > 0.6, f"the COVID window carries {share:.1%} of GDP's variation"
    largest = np.argsort(-np.abs(np.where(observed, row, 0.0)))[:5]
    assert window[largest].all()

    identified_result = legacy_identified_result
    summaries = {}
    for name, result in (("identified", identified_result),
                         ("collapsed", collapsed_result)):
        param = map_parameter(np.median(result.params, axis=1), (n, n_f, P_F, P_E))
        sigma_e = result.sigmas[n_f + i_gdp].mean(axis=1)
        summaries[name] = (float(param.Lambda[i_gdp, I_GLOBAL]),
                           float(param.Lambda[i_gdp, i_covid]),
                           float(sigma_e[~window].mean()))

    identified, collapsed = summaries["identified"], summaries["collapsed"]
    assert identified[0] > COLLAPSED_GLOBAL_LOADING, (
        f"seed {SEED} is no longer in the identified basin"
    )
    assert collapsed[0] <= COLLAPSED_GLOBAL_LOADING, (
        f"seed {COLLAPSED_SEED} no longer lands in the collapsed basin -- if "
        "that is a real improvement, re-measure the spread before relaxing "
        "anything that depends on it"
    )
    # Both halves of the handover, because naming only the COVID factor would be
    # an incomplete account: it cannot explain the 135 out-of-window quarters.
    # A tendency, not the mechanism: seeds 7 and 9 collapse with a NEGATIVE
    # COVID loading. Asserted at these two seeds because it holds at these two
    # seeds; the docstring says how far it generalises and the assertion below
    # carries the half that does.
    assert collapsed[1] > identified[1], (
        f"GDP's COVID loading is {collapsed[1]:.3f} in the collapsed basin "
        f"against {identified[1]:.3f} in the identified one"
    )
    assert collapsed[2] > 1.15 * identified[2], (
        f"GDP's idiosyncratic volatility OUTSIDE the COVID window is "
        f"{collapsed[2]:.3f} collapsed against {identified[2]:.3f} identified; "
        "the out-of-window variance has to go somewhere and the COVID factor "
        "cannot take it"
    )

    i_hh = panel.series_id.index("household_spending")
    assert np.isfinite(panel.Y[i_hh]).sum() == 164


@pytest.mark.slow
def test_the_shipping_panel_is_not_bimodal(panel, spec, fitted):
    """The other half of the finding above, and the reason the panel moved.

    Thirty seeds on the 1980 panel, sorted, ALL identified:

      1.393 1.413 1.417 1.452 1.472 1.489 1.504 1.524 1.548 1.557 1.565 1.568
      1.569 1.583 1.596 1.645 1.651 1.652 1.661 1.679 1.703 1.737 1.768 1.780
      1.817 1.839 1.849 1.858 1.952 2.049

    against the legacy panel's 18 collapsed and 12 identified. No second basin,
    no middle band, and the lowest chain sits 0.39 above the floor.

    THIS TEST DOES NOT RE-RUN THIRTY SEEDS -- that is fifteen minutes for a
    number already recorded above and in `nyfed/au/build.py`. It runs the two
    seeds that were CHOSEN because they fail on the legacy panel:
    ``COLLAPSED_SEED`` (0.075 there) and ``MIDDLE_BAND_SEED`` (0.856 there). If
    the shipping panel's health were an artefact of seed selection, these two
    are exactly where it would show. Both clear the floor here, and by a
    distance.
    """
    result, _, _ = fitted
    n, n_f = spec.blocks.shape
    i_gdp = panel.series_id.index("gdp")

    def loading(res):
        par = map_parameter(np.median(res.params, axis=1), (n, n_f, P_F, P_E))
        return float(par.Lambda[i_gdp, I_GLOBAL])

    at_gate = loading(result)
    assert at_gate > COLLAPSED_GLOBAL_LOADING, f"SEED {SEED} gives {at_gate:.3f}"

    for seed, on_legacy in ((COLLAPSED_SEED, 0.075), (MIDDLE_BAND_SEED, 0.856)):
        got = loading(estimate_short(panel, n_gs=N_GS, n_burn=N_BURN, seed=seed))
        assert got > COLLAPSED_GLOBAL_LOADING, (
            f"seed {seed} gives {got:.3f} on the shipping panel, at or below the "
            f"{COLLAPSED_GLOBAL_LOADING} floor. It gives {on_legacy} on the "
            "legacy panel, and the point of this test is that the 1980 start "
            "rescues it. If that has stopped being true, re-measure the thirty "
            "seeds before trusting anything else in this module."
        )

    # The premise behind all of it, measured rather than asserted: the extra
    # forty quarters are what shrink the COVID window's grip on the target.
    window = (panel.dates >= COVID_START) & (panel.dates <= COVID_END)
    row = panel.Y[i_gdp]
    observed = np.isfinite(row)
    assert observed.sum() == 183, "GDP's observation count has moved"
    share = np.nansum(row[observed & window] ** 2) / np.nansum(row[observed] ** 2)
    assert 0.45 < share < 0.52, (
        f"the COVID window carries {share:.1%} of GDP's variation on the "
        "shipping panel; it was 64.5% at the 1990 start and 48.2% when the "
        "start moved to 1980"
    )


@pytest.mark.slow
def test_a_collapsed_chain_is_refused_rather_than_turned_into_a_number(
    panel, legacy_panel, collapsed_result
):
    """The guard the re-review asked for, and the reason it is not just a default.

    ``estimate_short`` and ``quick_nowcast`` used to default to seed 321 -- a
    seed that lands in the collapsed basin. A caller taking the defaults got a
    plausible 2.83% number from a model whose response to its entire monthly
    panel was 0.015pp. Switching the default is not the fix, because on that
    panel 18 of 30 seeds collapsed and the next caller passes their own; the fix
    is that the model detects its own collapse from a quantity it already
    computes and refuses.

    RUN ON ``legacy_panel``, BECAUSE THE SHIPPING PANEL CANNOT COLLAPSE. Since
    ``DEFAULT_START`` moved to 1980 no seed of thirty leaves the identified
    basin, so there is no collapsed chain to hand the guard. That is a property
    of today's panel, not a repeal of the failure mode -- one spec change or one
    thin vintage brings it back, and an unexercised guard is one nobody notices
    has broken. The legacy panel keeps it honest.

    Both arms are exercised: the funnel (``state_space``) and the entry point
    (``quick_nowcast``), because it is the entry point the README advertises.
    """
    with pytest.raises(CollapsedFactorError, match=r"gdp's loading"):
        state_space(legacy_panel, collapsed_result)

    with pytest.raises(CollapsedFactorError):
        quick_nowcast(legacy_panel, n_gs=N_GS, n_burn=N_BURN, seed=COLLAPSED_SEED)

    # ...and the identified basin is not refused, or the guard would just be a
    # blanket refusal that happens to look right. Checked on BOTH panels: the
    # legacy one because that is where the refusal above happened, and the
    # shipping one because that is what production calls.
    assert np.isfinite(
        quick_nowcast(legacy_panel, n_gs=N_GS, n_burn=N_BURN, seed=SEED))
    assert np.isfinite(quick_nowcast(panel, n_gs=N_GS, n_burn=N_BURN, seed=SEED))


def test_the_library_defaults_do_not_land_in_the_collapsed_basin():
    """The defaults are checked, not trusted -- cheaply, without a sampler run.

    A default that is only correct because someone remembered to change it is
    the failure this round was reported for. This reads the signature.
    """
    import inspect

    for function in (estimate_short, quick_nowcast):
        default = inspect.signature(function).parameters["seed"].default
        assert default == SEED, (
            f"{function.__name__} defaults to seed {default}; the gate measures "
            f"seed {SEED} into the identified basin and seed {COLLAPSED_SEED} "
            "into the collapsed one"
        )


# --- residual 2: a skipped deflator tier must be visible from build_panel ---


def test_build_panel_reports_no_deflator_skips_on_the_ordinary_path(panel):
    """Three tiers in, three tiers used, nothing to report."""
    assert panel.deflator_skipped == {}


def test_build_panel_surfaces_a_skipped_deflator_tier(monkeypatch):
    """A skip was a recorded fact for a direct caller and silent in production.

    ``real_household_spending`` returned only the deflated series, discarding
    the ``Deflator`` -- so the one thing that says the deflator fell back to
    interpolated quarterly prices for the recent months never reached the
    caller, and an operator had to call the deflator directly to find out.
    Residual 1 makes the REFUSE branch reachable again; this makes the SKIP
    branch legible, which is the other half of the same two lines.
    """
    from dataclasses import replace

    from nyfed.au import build as build_mod

    skipped = {"cpi_monthly_live": "supplies no observation at this vintage"}

    real = build_mod.real_household_spending

    def fake(nominal, sources, **kwargs):
        deflated, actual = real(nominal, sources, **kwargs)
        return deflated, replace(actual, skipped=skipped)

    monkeypatch.setattr(build_mod, "real_household_spending", fake)
    assert build_panel(asof=ASOF, vintage=VINTAGE).deflator_skipped == skipped


def test_the_panel_cpi_row_carries_the_whole_monthly_history(panel):
    """The Nominal block's normaliser must not be 24 observations long.

    The registry fetches the LIVE 6401.0 monthly CPI, whose every All-groups
    index number restarts at 2024-04 because the ABS ceased the 6484.0 Monthly
    CPI Indicator. Used raw it left `cpi` -- which normalises the Nominal block
    -- absent for the first two years of the 2022+ window Plan C evaluates on.
    `build_panel` now splices the ceased tier on, monthly only.
    """
    i = panel.series_id.index("cpi")
    observed = panel.dates[np.flatnonzero(np.isfinite(panel.Y[i]))]
    assert len(observed) > 100
    # 2017-10, not 2017-09: `pch` consumes the first level to make a change.
    assert observed[0] == pd.Timestamp("2017-10-01")


def test_the_panel_cpi_row_has_no_interpolated_quarterly_months(panel):
    """Nothing before the ceased monthly indicator starts.

    The deflator interpolates the quarterly index back to 1948 and is right to
    -- there it is a level ratio. Here the transformation is `pch`, so an
    interpolated level becomes three fabricated monthly changes per real
    quarterly one, and the DFM cannot tell that from information.
    """
    i = panel.series_id.index("cpi")
    observed = panel.dates[np.flatnonzero(np.isfinite(panel.Y[i]))]
    assert observed.min() >= pd.Timestamp("2017-09-01")


# --- the middle band the old 0.75 floor admitted ---------------------------

MIDDLE_BAND_SEED = 3      # 0.856 on `legacy_panel`: above 0.75, below 1.0


def test_a_chain_between_the_basins_is_refused(legacy_panel):
    """The defect that raising the floor to 1.0 fixes, pinned so it stays fixed.

    Thirty seeds on each of two panels showed THREE groups, not two. Chains sit
    between the basins on every panel measured -- 0.783/0.901/0.924 on a control
    with the short `cpi` row, 0.785/0.823/0.843 on the 15-series panel, and
    0.796/0.856 on this one. The old 0.75 floor ADMITTED all of them: they
    cleared the guard while sitting nowhere near the identified basin, and Plan
    C's warm start would have carried one forward silently, never tripping the
    floor again.

    The earlier ten-seed measurement did not sample the middle band at all,
    which is how a floor got set inside it.

    ``MIDDLE_BAND_SEED`` is 3, and its history is the argument for re-measuring
    these constants rather than carrying them forward. It was the gate's own
    DEFAULT seed until 2026-08-28, sitting at 1.562 on the 15-series panel.
    Dropping `cpi_trimmed` moved it to 0.856 -- into the band the old floor
    admitted. Moving the panel start to 1980 moved it again, to 2.049, the
    highest of all thirty seeds. Nothing about the seed ever changed; the panel
    did, three times.

    RUN ON ``legacy_panel``: the shipping panel has no middle band left to
    sample, and this test exists to keep the floor's placement honest, not to
    describe today's panel.
    """
    result = estimate_short(legacy_panel, n_gs=N_GS, n_burn=N_BURN,
                            seed=MIDDLE_BAND_SEED)
    with pytest.raises(CollapsedFactorError, match=r"gdp's loading"):
        state_space(legacy_panel, result)


def test_the_floor_sits_in_the_gap_measured_on_both_panels():
    """1.0 is not a round number picked for tidiness.

    It is the only value that sits inside the widest gap on BOTH panels
    measured: 0.924 -> 1.124 on the control, 0.843 -> 1.089 on the shipping
    panel. 0.75 sat inside neither gap -- it sat below the middle band.
    """
    control_gap = (0.924, 1.124)
    shipping_gap = (0.843, 1.089)
    for lo, hi in (control_gap, shipping_gap):
        assert lo < COLLAPSED_GLOBAL_LOADING < hi
    assert not (control_gap[0] < 0.75 < control_gap[1])
    assert not (shipping_gap[0] < 0.75 < shipping_gap[1])
