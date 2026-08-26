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
than the healthy value. At this vintage only ONE post-target month exists and
only eight of the fifteen series have published it, so there is too little
post-target data for the ratio to separate the two cases at all. A vintage-pair
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
from nyfed.au.deflator import DEFLATOR_SOURCES, real_household_spending
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
#     old against 86.
# `aig_pmi` stopped updating on 2026-05-01, so no vintage after 2026-07-26
# passes at all; that is what makes the window unique.
ASOF = "2026-06-01"

# GDP is observed through 2025-12, so the target quarter is Q1 2026.
TARGET_QUARTER = (pd.Timestamp("2026-01-01"), pd.Timestamp("2026-03-01"))

# A short run: enough to show the sampler completes and does not collapse. Not
# an accuracy check -- there is nothing to check against.
#
# THE SEED IS PART OF THE MEASUREMENT, NOT A TUNING KNOB, and it is disclosed
# rather than quietly chosen. GDP's posterior on this panel is BIMODAL: the
# Global factor and the COVID factor compete to explain the target series, a
# chain settles into one basin within its first sweeps and stays there, and
# lengthening the chain does not resolve it (measured to 2,000 sweeps). Three of
# six seeds land in the basin where GDP loads Global at ~1.3, three in the one
# where it loads ~0.1 and the COVID factor takes ~1.4 instead. In the second
# basin the nowcast is driven by GDP's own idiosyncratic dynamics and barely
# reads the monthly panel at all.
#
# `test_the_gdp_loading_is_bimodal_across_seeds` pins that finding directly, so
# it is a measured property of this panel rather than a footnote, and the gate
# runs at a seed in the identified basin so that the discriminator below is
# testing the pipeline rather than the coin flip. If the seed changes,
# `test_the_gate_runs_in_the_basin_where_gdp_loads_the_global_factor` fails and
# names the reason.
N_GS, N_BURN, SEED = 200, 100, 1

# A seed that lands in the OTHER basin, used to exercise the collapse guard.
COLLAPSED_SEED = 321

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
def collapsed_result(panel):
    """One chain at seed 321, which lands in the collapsed basin.

    Shared by the bimodality measurement and the collapse-guard test so that the
    two cost a single sampler run between them.
    """
    return estimate_short(panel, n_gs=N_GS, n_burn=N_BURN, seed=COLLAPSED_SEED)


def _with_data(panel: Panel, Y: np.ndarray) -> Panel:
    """The same vintage with a different data matrix. Never mutates ``panel``."""
    return Panel(Y=Y, y_location=panel.y_location, y_scale=panel.y_scale,
                 dates=panel.dates, series_id=panel.series_id, i_now=panel.i_now)


# --------------------------------------------------------------------------- #
# The panel
# --------------------------------------------------------------------------- #


def test_the_panel_has_one_row_per_registered_series(panel):
    """15, not the 17 an earlier draft of this plan assumed: ABS ceased Retail
    Trade in July 2025, and the Internet Vacancy Index turned out never to have
    been fetched by v2 at all. See ``nyfed/au/sources.py``."""
    assert panel.Y.shape[0] == len(AU_SERIES) == 15
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
                            ("cpi", "2020-01-01"),
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
    real = real_household_spending(nominal, vintage.deflator_sources)
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
    meaning: scanned day by day, the stale set stays ``{aig_pmi}`` through
    2026-09-23, becomes five series on 2026-09-24 and all fifteen by 2026-10-20
    -- at which point the gate would fail looking like a freshness regression
    instead of "the vintage needs re-recording". Measuring at the vintage's own
    ``recorded_at`` asks the question the frozen data can actually answer: on
    the day this was fetched, what did the guard say?
    """
    vintage = load_vintage(VINTAGE)
    assert vintage.recorded_at is not None, "the recording has no date to test at"
    recorded_on = pd.Timestamp(vintage.recorded_at).tz_convert(None).normalize()

    with pytest.raises(StaleSeriesError) as excinfo:
        build_panel(asof=str(recorded_on.date()), vintage=vintage)

    stale = {key: age for key, age, _ in excinfo.value.stale}
    assert set(stale) == {"aig_pmi"}, f"expected only aig_pmi, got {sorted(stale)}"
    assert stale["aig_pmi"] > 100
    assert "aig_pmi" in str(excinfo.value)


def test_the_vintage_cut_is_by_release_date_not_by_reference_date(panel):
    """The look-ahead this task shipped in round 1, now a standing check.

    Australian series are dated to the START of the period they cover and are
    published weeks later, so cutting a vintage at ``asof`` on the observation's
    own date admits data nobody had yet -- up to nine weeks of it on ``gdp``.
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

    THIS COVERS 13 OF THE 15 ROWS. ``job_ads``, ``aig_pmi`` and
    ``nab_conditions`` are recorded in the vintage like everything else, but
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
            # trusted" holds for 13 of the 15 rows and is stated as such.
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

    The target quarter is Q1 2026; April 2026 is in the panel because eight of
    the fifteen series had published it by this vintage. A one-sigma shock to
    those April observations moves the Q1 nowcast by 0.013pp against 2.169pp for
    the same shock inside Q1. Not zero, and it should not be: the smoother is
    two-sided, so a later month legitimately carries a little information about
    the factor path in March.

    WHAT THIS DOES NOT ESTABLISH. It does not detect a one-month misalignment.
    Measured across six sampler seeds, the probe is caught at NONE of them: the
    healthy ratios are 17.6, 162.5, 52.6, 365.2, 395.4 and 17.5, and with
    April's observation written into March's column they become 49.5, 37.8,
    16.9, 22.9, 109.8 and 320.4 -- every one still above the asserted 10, and
    two of them higher than the healthy value. (Round 1 of this task reported
    "2 of 4 seeds" on a different vintage; the correct count there was 1 of 4,
    and on an honest vintage it is 0 of 6.) One post-target month, published by
    eight of the fifteen series, is not enough signal for this statistic to
    separate the cases. The structural
    guarantee is elsewhere (the Octave-pinned quarterly aggregation, plus the
    panel's deterministic alignment tests); this is a consistency check on top
    of it, and Plan C should add a vintage-pair test when more than one
    post-target month exists.

    Thresholds from the same six seeds: the post-target move was 0.0008, 0.0046,
    0.0060, 0.0064, 0.0106 and 0.0134pp, and the ratio never fell below 17.5 --
    in EITHER basin, which is why the ratio rather than the level is what this
    test asserts.
    """
    _, ssm, t_now = fitted
    monthly = np.array([f == "m" for f in spec.frequency])
    inside = (panel.dates >= TARGET_QUARTER[0]) & (panel.dates <= TARGET_QUARTER[1])
    after = panel.dates > TARGET_QUARTER[1]
    # Three columns after the target quarter, but only April carries data: the
    # fastest series in the panel has a 34-day lag, so May and June had not been
    # published at this vintage. Eight of the twelve monthly series had April.
    assert after.sum() == 3
    assert np.isfinite(panel.Y[np.ix_(monthly, after)]).sum() == 8, (
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
    settles with GDP's Global loading near 1.3, and every sensitivity number in
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
def test_the_gdp_loading_is_bimodal_across_seeds(panel, spec, fitted, collapsed_result):
    """A finding, pinned as a measurement so it cannot be mistaken for noise.

    THE PREMISE, measured on the panel rather than asserted: GDP loads only the
    Global factor and the COVID factor; the COVID factor is active for 22 months
    (March 2020 to December 2021); and those 22 months hold **8 of GDP's 143
    observations but 64.5% of its standardised sum of squares**, including all
    five of its largest absolute values. A factor confined to that window can fit
    the biggest moves in the target series almost perfectly.

    THE MECHANISM IS A TWO-SIDED HANDOVER, not just the COVID factor taking
    over. When GDP's Global loading collapses (1.334 -> 0.011 between the two
    seeds here) its COVID loading rises only 1.036 -> 1.318, which cannot absorb
    the difference -- the COVID factor is zero outside its 22 months and the
    other 135 observations still need explaining. What takes them is GDP's own
    idiosyncratic stochastic volatility, and it rises OUTSIDE the window too:
    0.875 -> 1.107 between these two seeds, and 0.788 -> 1.119 between the two
    basins' means over ten seeds. So COVID takes the in-window variance and
    GDP's own error takes the out-of-window variance the Global loading used to
    carry, which is why the result is a series explained by itself.

    A LIKELY ENABLER, worth Plan C's attention: the Global factor is normalised
    by household spending, which starts in 2012, so only 164 of the panel's 438
    months pin that factor's scale at all.

    These are separate basins, not tails of one distribution. A chain picks one
    in its first sweeps and stays: measured at seed 321 over 400 stored draws,
    GDP's Global loading has a 5-95% range of -0.45..0.31 with the first and
    last fifty draws averaging -0.16 and -0.01, while at seed 1 the same range
    is 1.22..1.55. Lengthening the chain to 2,000 sweeps does not resolve it,
    and five of ten seeds land in each basin.

    THIS IS WHY THE GATE DECLARES ITS SEED and why ``state_space`` refuses a
    collapsed chain outright. The NY Fed does not face the coin flip because
    ``initval.mat`` ships a fitted starting point that puts the chain in the
    right basin; Australia starts from a bland one. Plan C needs a starting
    point with that job, or a spec that does not make a 22-month factor compete
    with the Global factor for the target series.
    """
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

    identified_result, _, _ = fitted
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
def test_a_collapsed_chain_is_refused_rather_than_turned_into_a_number(
    panel, collapsed_result
):
    """The guard the re-review asked for, and the reason it is not just a default.

    ``estimate_short`` and ``quick_nowcast`` used to default to seed 321 -- the
    seed this module's own bimodality test asserts lands in the collapsed basin.
    A caller taking the defaults got a plausible 2.83% number from a model whose
    response to its entire monthly panel was 0.015pp. Switching the default is
    not the fix, because five of ten seeds collapse and the next caller passes
    their own; the fix is that the model detects its own collapse from a
    quantity it already computes and refuses.

    Both arms are exercised: the funnel (``state_space``) and the entry point
    (``quick_nowcast``), because it is the entry point the README advertises.
    """
    with pytest.raises(CollapsedFactorError, match=r"gdp's loading"):
        state_space(panel, collapsed_result)

    with pytest.raises(CollapsedFactorError):
        quick_nowcast(panel, n_gs=N_GS, n_burn=N_BURN, seed=COLLAPSED_SEED)

    # ...and the identified basin is not refused, or the guard would just be a
    # blanket refusal that happens to look right.
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
