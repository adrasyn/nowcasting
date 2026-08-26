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
   through 2026-03, so Q2 2026 is what the model is nowcasting, and Q2's
   monthly observations are exactly what it is supposed to read. A nowcast that
   ignored them would be a broken nowcast, not a leak-free one. The leak worth
   testing for is the one that cleared v2: data from AFTER the target quarter
   being read as though it belonged to the target quarter.

2. A blanking test passes whenever the nowcast does not move, INCLUDING when
   the pipeline is dead. Blanking is also a weak instrument in its own right:
   measured here, removing all three of Q2's months moves the nowcast by
   0.008pp -- not because the model ignores them but because they came in close
   to what it expected. Removal measures how surprising the data was, not
   whether the data is read.

So the instrument is a one-sigma SHOCK, applied to the same rows, through the
same state space, in two places:

* the target quarter's own months (April-June 2026) -> the nowcast moves
  1.087pp;
* the months after it (July 2026) -> it moves 0.004pp, some 250 times less.

WHERE THE NO-LEAK GUARANTEE ACTUALLY COMES FROM. Not from the number above.
Structurally, a post-target observation can only reach the Q2 fitted value
through the smoothed state, because the Mariano-Murasawa aggregation in
``construct_ssm`` -- weights ``[1 2 3 2 1]/9`` over the quarter's own months --
is what maps months onto a quarterly observation, and that is engine code
pinned against Octave in Task 1. What is left to check on the Australian side
is that the panel puts each observation in the right column, which
``test_quarterly_rows_sit_in_the_last_month_of_their_quarter`` and the fetch
tests' date pinning do deterministically.

THE NUMERICAL CHECK IS A CONSISTENCY CHECK, NOT A LEAK DETECTOR, and saying
otherwise would be a false claim about a real guard. Measured: a genuine
one-month misalignment -- July's observation written into June's column, which
is what an off-by-one in ``panel._align`` would produce -- takes the ratio from
252 to 25 at seed 321 and from 30 to 7 at seed 1, but leaves it at 47 and 29 at
seeds 3 and 7. At this vintage only ONE post-target month exists and only seven
of the fifteen series have published it, so there is too little post-target data
for the ratio to separate the two cases reliably. A vintage-pair leakage test
(build at two dates, compare) is the instrument that would, and it belongs to
Plan C, where more than one post-target month is available.

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
from nyfed.au.restrict import build_restrict
from nyfed.au.sources import AU_SERIES, SPEC_PATH
from nyfed.model import construct_ssm
from nyfed.spec import load_spec

FIXTURES = Path(__file__).parent / "fixtures" / "au"
VINTAGE = FIXTURES / "vintage"

# The vintage the model path is built at. Chosen by measurement, not taste:
# `aig_pmi` died in May 2026, so any later vintage is refused by the freshness
# guard (correctly -- see `test_a_build_today_is_refused_because_the_pmi_is
# _dead`), and any earlier one ends inside the target quarter and leaves no
# post-target month to shock. 2026-07-01 is the only vintage at which every
# series passes its budget honestly AND a month beyond the target quarter
# exists.
ASOF = "2026-07-01"

# GDP is observed through 2026-03, so the target quarter is Q2 2026.
TARGET_QUARTER = (pd.Timestamp("2026-04-01"), pd.Timestamp("2026-06-01"))

# A short run: enough to show the sampler completes and does not collapse. Not
# an accuracy check -- there is nothing to check against.
N_GS, N_BURN, SEED = 200, 100, 321


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
    assert last_gdp == pd.Timestamp("2026-03-01")
    assert list(panel.dates[t_now]) == [pd.Timestamp("2026-06-01")]


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
    vintage = load_vintage(VINTAGE)
    asof = pd.Timestamp(ASOF)
    nominal = vintage.series["household_spending"]
    nominal = nominal[nominal.index <= asof]
    real = real_household_spending(
        nominal, {k: s[s.index <= asof] for k, s in vintage.deflator_sources.items()}
    )
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


def test_a_build_today_is_refused_because_the_pmi_is_dead():
    """Not a bug: the guard doing its job, pinned so it cannot be quietly lost.

    ``aig_pmi``'s last observation is 2026-05-01. Ai Group folded its
    Manufacturing PMI into a broader index in May 2026 with no separate release
    since, and v2's scraper stopped seeing releases; the series is dead, not
    late. Against a 75-day monthly budget every build from mid-July 2026 onward
    refuses, and the way to nowcast again is to replace the series, not to widen
    the budget or add a bypass.

    Four healthy ABS monthly series -- building approvals, household spending,
    exports and imports -- are ALSO named at 86 days on 2026-08-26, and they
    are not dead: all four are dated to the start of their reference month and
    published about two months later, so 86 days is an ordinary age for them
    and the 75-day budget is too tight. That is a separate finding, reported
    with Task 10 rather than fixed here, and it is asserted below so the next
    reader meets it rather than rediscovering it.
    """
    with pytest.raises(StaleSeriesError) as excinfo:
        build_panel(asof=str(pd.Timestamp.today().date()), vintage=VINTAGE)

    stale = {key: age for key, age, _ in excinfo.value.stale}
    assert "aig_pmi" in stale
    assert stale["aig_pmi"] > 100
    assert "aig_pmi" in str(excinfo.value)
    assert {"building_approvals", "exports", "imports"} <= set(stale), (
        "the monthly-budget finding this test records has changed; re-measure "
        "before editing the assertion"
    )


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
            continue      # the v2 CSVs are read from v2's tree, not recorded here
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

    Threshold from measurement across six sampler seeds, not from the one seed
    this runs at: a one-sigma shock across April-June 2026 moved the nowcast by
    0.149, 0.350, 0.573, 1.087, 2.115 and 2.855pp. The spread is large because
    300 sweeps from a bland start is a short chain; the floor is set an order of
    magnitude below the smallest of them.

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

    move = _shock_move(panel, ssm, t_now, monthly, inside, base)
    assert move > 0.10, (
        f"a one-sigma shock to the target quarter's own months moved the "
        f"nowcast by only {move:.4f}pp; the model is not reading them"
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

    The target quarter is Q2 2026; July 2026 is in the panel because seven of
    the fifteen series had published it by this vintage. A one-sigma shock to
    those July observations moves the Q2 nowcast by 0.004pp against 1.087pp for
    the same shock inside Q2. Not zero, and it should not be: the smoother is
    two-sided, so a later month legitimately carries a little information about
    the factor path in June.

    WHAT THIS DOES NOT ESTABLISH. It does not detect a one-month misalignment.
    Measured, by writing July's observation into June's column -- what an
    off-by-one in ``panel._align`` would do -- the ratio falls from 252 to 25 at
    seed 321 and from 30 to 7 at seed 1, but stays at 47 and 29 at seeds 3 and
    7, inside the healthy range. One post-target month, published by seven of
    fifteen series, is not enough signal to separate the cases. The structural
    guarantee is elsewhere (the Octave-pinned quarterly aggregation, plus the
    panel's deterministic alignment tests); this is a consistency check on top
    of it, and Plan C should add a vintage-pair test when more than one
    post-target month exists.

    Thresholds from the same six seeds: the post-target move was 0.003, 0.007,
    0.013, 0.038 and 0.071pp, and the ratio never fell below 29.6.
    """
    _, ssm, t_now = fitted
    monthly = np.array([f == "m" for f in spec.frequency])
    inside = (panel.dates >= TARGET_QUARTER[0]) & (panel.dates <= TARGET_QUARTER[1])
    after = panel.dates > TARGET_QUARTER[1]
    assert after.sum() == 1
    assert np.isfinite(panel.Y[np.ix_(monthly, after)]).sum() >= 5, (
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
