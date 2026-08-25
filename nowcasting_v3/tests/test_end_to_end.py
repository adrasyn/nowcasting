"""Task 9: the end-to-end gate.

Every deterministic function in this port is pinned to an Octave fixture. This
module is the only test that shows the assembled whole reaches the numbers the
New York Fed actually published.

Expected values come from ``tests/fixtures/published_nowcasts.npz``, read out of
the drop's own ``nyfed_matlab/output/Update_*.mat`` by
``tools/extract_published.py``. Never from memory, and never from the
``nowcast_us`` fixtures -- those build their two state spaces from disjoint
halves of the Gibbs output on a 60-column window, deliberately, so that the
parameter-revision row is exercised. They land at 2.1732 against the published
2.0242 and are not an oracle for this gate.

WHICH WEEK IS THE GATE
----------------------

The drop ships **one** estimate file, ``Estimates_2023_09_20.mat``, and
``example_nowcast.m`` ships configured for the **2023-09-29** week. That week
reproduces completely: the headline and all nine per-series release impacts.

The **2023-10-06** week does not, because the published figures for that week
were produced from an estimate file the drop does not contain. That is not a
hypothesis; it is measured, and pinned by
``test_the_1006_published_forecasts_need_parameters_this_drop_lacks`` below.

Its headline *passes* a Monte Carlo comparison, and that is exactly why it does
not gate: the headline is a sum in which a 9.5-sigma error in the revisions term
is masked by an ordinary noise excursion in another component. See
``test_the_1006_residual_is_a_bias_that_sits_in_the_revisions_term``.

``example_nowcast.m``'s own comment calls ``date_estimate_new`` the "estimate
file for current week", so the estimate file rolls forward weekly and only one
week's was published.

TOLERANCES ARE MEASURED, NOT CHOSEN
-----------------------------------

MATLAB's published figures average 1,250 ``S_update`` draws off ``rng(321)``.
numpy cannot reproduce that stream, so the port converges to the same limit by a
different path with Monte Carlo error around it. Whether that error fits inside
any particular tolerance is an empirical question, so it was measured -- BEFORE
this file was run against the published targets -- rather than assumed.

Step 0 measured five seeds. Those five turned out to be an unusually tight
cluster, so **every constant in force below was re-measured over fifteen seeds**;
the provenance, the command and the reason are in the constants block further
down, which is the single source of truth for them. ``README.md`` carries the
full table and the five-seed comparison.

The tolerance is ``3 * sqrt(2) * sd``. The comparison is between TWO
independent 1,250-draw averages -- ours and MATLAB's -- so the difference has
variance ``2 * sd**2`` and a three-sigma bound on it is ``3 * sqrt(2) * sd =
4.243 * sd``. A bound of ``3 * sd`` would be right only if the published figure
were exact, which it is not: MATLAB does not reproduce itself across seeds
either, which is why the plan's own note says an exact match "cannot be met".

**Two things the `sqrt(2)` rests on, stated as the assumptions they are.**

1. *MATLAB's per-run standard deviation equals this port's.* Both average 1,250
   draws of the same `S_update` from the same posterior, so it is a reasonable
   assumption -- but it is an ASSUMPTION, not a measurement. Only one MATLAB run
   was ever published, so its sd cannot be estimated from here at all, and no
   amount of work on this side would change that. If MATLAB's sd were larger
   than ours, `sqrt(2)` would understate the right factor; if smaller, overstate
   it.
2. *`sd` is known.* It is not: each figure below is estimated from a handful of
   seeds, and the relative standard error of an sd from `n` samples is about
   `1/sqrt(2*(n-1))` -- 35% at n=5, 19% at n=15, which is what the constants
   below are measured over. So a comparison landing near 1.0x of tolerance is
   not meaningfully distinguishable from one landing just over it, and none of
   the conclusions here rest on such a case: after the re-measurement the worst
   is 0.47x.

Neither point moves the substantive results: the 2023-09-29 headline passes
under `abs=0.01`, under `3*sd` and under `3*sqrt(2)*sd` alike, and the
2023-10-06 residual is a bias rather than a Monte Carlo excursion, which no
choice of sigma multiple can turn into a pass.

The headline additionally keeps the plan's ``0.01``pp floor, the precision the
figure is published to. The per-series impacts get NO such floor: four of the
nine published impacts for 2023-09-29 are smaller in magnitude than ``0.01``, so
a flat ``abs=0.01`` would pass on those series even if the port returned exactly
zero -- the one thing the per-series test exists to catch.
"""

from __future__ import annotations

import numpy as np
import pytest

from nyfed.model import Latent, construct_ssm
from nyfed.nowcast import news_table, point_nowcast
from nyfed.parameters import map_parameter
from nyfed.run_us_reference import (
    MATLAB_DIR,
    SPEC_FILE,
    VINTAGE_PAIRS,
    load_estimates,
    load_spec,
    load_vintage,
    run_reference_week,
)

WEEKS = sorted(VINTAGE_PAIRS)

#: The week this drop's estimate file can reproduce in full. See the module
#: docstring, and the two tests that pin why the other week cannot.
GATE_WEEK = "2023-09-29"


def _key(week: str) -> str:
    """``2023-09-29`` -> the fixture's ``2023_09_29`` suffix."""
    return week.replace("-", "_")


# --------------------------------------------------------------------------- #
# The measured spreads.
#
# Step 0 measured five seeds (321, 1, 2, 3, 4). The review asked for the two
# tightest per-series comparisons to be re-measured over more seeds, and doing
# so showed that a five-sample sd is not good enough here: AMDMTI's came out
# 2.0x larger and AMDMUO's 2.3x larger on fifteen seeds, and the 2023-09-29
# HEADLINE sd came out 2.1x larger (0.008112 -> 0.017331). The first five seeds
# were simply a tight cluster.
#
# So every figure below is measured over FIFTEEN seeds, 5..19, at full
# 1,250-draw production settings. Those seeds are DISJOINT from seed 321, which
# every assertion in this file runs at, so no tolerance is estimated from the
# run it then judges. The five-seed values are kept in the task report for
# comparison, not here, so there is one set of numbers in the code and no doubt
# about which is in force.
#
# Reproduce, one command per week (each ran as three parallel five-seed chunks
# for wall clock; a single invocation reports the same sd across all fifteen):
#
#     .venv/bin/python -m nyfed.run_us_reference 2023-09-29 \
#         --seeds 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 \
#         --density-draws 2 --quiet
#     .venv/bin/python -m nyfed.run_us_reference 2023-10-06 \
#         --seeds 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 \
#         --density-draws 2 --quiet
#
# --density-draws is safe to cut here and cannot touch a measured quantity: the
# density loop runs after the point nowcast and the news table are computed and
# feeds nothing back into them.
#
# An sd from n samples has a relative standard error of about 1/sqrt(2*(n-1)):
# 35% at n=5, 19% at n=15. That is still not negligible, which is why nothing
# here rests on a comparison landing near 1.0x of tolerance -- after the
# re-measurement the worst is 0.47x.
# --------------------------------------------------------------------------- #

#: Three-sigma bound on the difference of two independent 1,250-draw averages.
SIGMA_MULTIPLE = 3.0 * np.sqrt(2.0)

#: Seed-to-seed sd of the headline nowcast, in pp of annualised GDP growth.
HEADLINE_SD: dict[str, float] = {
    "2023-09-29": 0.017331,
    "2023-10-06": 0.014124,
}

#: Seed-to-seed sd of the 2023-10-06 revisions and release totals. The two are
#: very different animals and that difference is the finding: the revisions term
#: is stable across seeds and carries a large offset from the published value,
#: while the release total is noisy and carries none.
REVISIONS_SD_1006 = 0.002028
RELEASES_SD_1006 = 0.005401

#: Seed-to-seed sd of each series' first-horizon impact, in pp.
IMPACT_SD: dict[str, dict[str, float]] = {
    "2023-09-29": {
        "AMDMTI": 0.000038, "AMDMUO": 0.000014, "AMDMVS": 0.000502,
        "DGORDER": 0.000919, "DSPIC96": 0.001282, "HSN1F": 0.000392,
        "PCEC96": 0.000475, "PCEPI": 0.000318, "PCEPILFE": 0.000263,
    },
    "2023-10-06": {
        "ADPMNUSNERSA": 0.000225, "BOPTEXP": 0.000632, "BOPTIMP": 0.001185,
        "JTSJOL": 0.000376, "PAYEMS": 0.004628, "TTLCONS": 0.000012,
        "UNRATE": 0.000354,
    },
}


#: The published 2023-10-06 revisions term. Derived from the two committed
#: fixtures with no new computation:
#:     published_1006 - published_0929 - sum(published 10-06 impacts)
#: which is exactly what `example_nowcast.m` prints as "Impact from parameter
#: and data revisions" -- a published quantity, not a reconstruction of one.
PUBLISHED_1006_REVISIONS = 0.1618111034766129


def headline_tolerance(week: str) -> float:
    """``max(0.01, 4.243 * sd)`` on Step 0's measured sd."""
    return max(0.01, SIGMA_MULTIPLE * HEADLINE_SD[week])


def impact_tolerance(week: str, series_id: str) -> float:
    """``4.243 * sd`` for this series. No 0.01 floor -- see the module docstring."""
    return SIGMA_MULTIPLE * IMPACT_SD[week][series_id]


# --------------------------------------------------------------------------- #
# One production-settings run per week, shared across the tests below
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def estimates():
    """``Estimates_2023_09_20.mat``, or a skip.

    It is 21 MB and not committed, so a working copy without the NY Fed drop
    skips rather than fails -- the same contract ``conftest.load_fixture`` gives
    the Octave fixtures.
    """
    try:
        return load_estimates()
    except FileNotFoundError as exc:
        pytest.skip(str(exc))


@pytest.fixture(scope="module")
def spec():
    return load_spec(MATLAB_DIR / SPEC_FILE)


@pytest.fixture(scope="module")
def reference(estimates, spec):
    """Memoised ``run_reference_week``: each week is reproduced exactly once."""
    cache: dict[str, object] = {}

    def get(week: str):
        if week not in cache:
            cache[week] = run_reference_week(week, seed=321, estimates=estimates,
                                             spec=spec)
        return cache[week]

    return get


# --------------------------------------------------------------------------- #
# The gate
# --------------------------------------------------------------------------- #


@pytest.mark.slow
@pytest.mark.fixtures
def test_reproduces_the_published_nowcast(fixture, reference):
    """The whole port, against the number the New York Fed published.

    2023-09-29 only. The 2023-10-06 headline lands close, but its residual is a
    BIAS, not a Monte Carlo excursion, so a Monte Carlo tolerance is the wrong
    instrument for it: passing under `3*sqrt(2)*sd` would say only that the bias
    currently happens to sit under 4.24 sigma-hat. It is pinned as a two-sided
    observation instead, in
    `test_the_1006_residual_is_a_bias_that_sits_in_the_revisions_term`.

    TWO ASSERTIONS, AND THE TIGHTER ONE IS THE GATE. The plan's criterion is a
    literal +-0.01pp, and the measured deviation of 0.008416 meets it. That is
    the result. `headline_tolerance` is the wider Monte Carlo statement, and
    after the sd re-measurement it is 0.073529 -- wide enough that it would no
    longer catch a gross defect: deleting the entire 1,250-draw `S_update`
    averaging moves the headline to 0.040760, which sits INSIDE the sigma band
    and outside the floor. So the floor is asserted too, and it is the assertion
    that does the work. See README.md, "Is the gate falsifiable?".

    The floor holds at 0.84x with no margin to spare, and it is a statement
    about SEED 321, not about every seed: the seed-to-seed sd of this headline
    is 0.017331, so other seeds miss +-0.01pp routinely. That is not fragility
    here -- the seed is fixed and numpy's PCG64 stream is deterministic -- but
    it is why the wider Monte Carlo band is kept alongside rather than deleted,
    and why README.md quotes the spread next to the point estimate.
    """
    week = GATE_WEEK
    expected = fixture("published_nowcasts")[f"published__{_key(week)}"].item()
    got = reference(week)
    deviation = abs(got.nowcast - expected)
    # The plan's criterion. Measured 0.008416 against 0.01.
    assert deviation <= 0.01, deviation
    # And the wider Monte Carlo statement, which it also clears at 0.11x.
    assert got.nowcast == pytest.approx(expected, abs=headline_tolerance(week))


@pytest.mark.slow
@pytest.mark.fixtures
def test_reproduces_the_release_impacts(fixture, reference):
    """Every series' impact must match, not just the total - a compensating pair
    of errors can leave the headline right while both components are wrong.

    2023-09-29 only. 2023-10-06's published table came out of an estimate file
    the drop does not ship, so it is not an oracle for the port; the size of
    that gap is pinned by the two tests below rather than hidden by omitting it.

    HORIZON 1 ONLY. example_nowcast.m:174 linear-indexes an (n, T, 2) weights
    array with an (n, T) mask, so the published Weight/Impact columns cover the
    first t_now and nothing else. Comparing horizon 2 against them would compare
    our real numbers to MATLAB's dropped ones and pass or fail for no reason.
    """
    week = GATE_WEEK
    d = fixture("published_nowcasts")
    assert d["horizon"].item() == 1
    got = reference(week)

    published_ids = d[f"news_{_key(week)}__series_id"]
    published_impacts = d[f"news_{_key(week)}__impact"]
    assert published_ids.size == 9

    # The set of releases must match first: an impact this port never computed
    # would otherwise never be compared.
    assert sorted(got.table["series_id"]) == sorted(str(s) for s in published_ids)

    misses = []
    for series_id, impact in zip(published_ids, published_impacts, strict=True):
        series_id = str(series_id)
        tolerance = impact_tolerance(week, series_id)
        deviation = abs(got.impact_for(series_id, horizon=0) - impact.item())
        if deviation > tolerance:
            misses.append(f"{series_id}: |dev| = {deviation:.6f} > {tolerance:.6f}")
    assert not misses, "\n".join(misses)


# --------------------------------------------------------------------------- #
# The 2023-10-06 gap, and its cause
# --------------------------------------------------------------------------- #


def _median_param_forecasts(estimates, spec, week, param_vec):
    """Published-unit forecasts from a parameter vector and the mean latents.

    No ``S_update``: this asks how sensitive the forecasts are to the PARAMETERS,
    and the latents' contribution is two orders of magnitude smaller. Step 0's
    seed-321 and seed-4 runs put JTSJOL's forecast at 119.03 and 119.62 - a
    0.6-unit spread on a value of 119, against the 17-unit gap this function is
    about.
    """
    vintage_old, vintage_new = VINTAGE_PAIRS[week]
    Y_old = load_vintage(vintage_old, estimates)
    Y_new = load_vintage(vintage_new, estimates)
    i_now = spec.series_id.index("GDPC1")
    T = Y_new.shape[1]
    t_now = np.arange(int(np.flatnonzero(~np.isnan(Y_new[i_now]))[-1]) + 3, T, 3)
    latent = Latent(sigma=estimates.sigmas.mean(axis=2),
                    s=estimates.ss.mean(axis=2))
    ssm = construct_ssm(map_parameter(param_vec, estimates.dimvec), latent,
                        estimates.restrict)
    result = point_nowcast(Y_old, Y_new, ssm, ssm, i_now, t_now)
    table = news_table(result, spec, estimates.y_location, estimates.y_scale)
    return dict(zip(table["series_id"], table["forecast"], strict=True))


@pytest.mark.fixtures
def test_the_1006_published_forecasts_need_parameters_this_drop_lacks(
    fixture, estimates, spec
):
    """WHY 2023-10-06 is not the gate week, measured rather than asserted.

    Each published Forecast is what the model expected of that series before the
    release. It is a sharp function of the parameter vector: across four single
    draws from ``param_Gibbs`` every one of them moves by at least 1.4% of its
    published value, and most by 20-78%. So reproducing one to a fraction of a
    percent pins the parameters, and failing to is evidence that different
    parameters were used.

    Measured with ``median(param_Gibbs)`` from ``Estimates_2023_09_20.mat``,
    worst relative error over the week's published Forecast column:

      * 2023-09-29 -- **0.41%** (DGORDER 0.07%, HSN1F 0.05%, PCEC96 0.28%)
      * 2023-10-06 -- **16.59%** (JTSJOL published 100.47, this drop 117.14;
        UNRATE 6.42%, BOPTEXP 4.15%, ADPMNUSNERSA 3.53%, PAYEMS 1.26%)

    Forty times worse, on the same code, the same estimate file and the same
    parameter sensitivity. Scaled by what parameter uncertainty spans, the
    median series is off by 0.4% of the draw spread for 2023-09-29 and 6.4% of
    it for 2023-10-06. The 2023-10-06 update was published from a later estimate
    file, which the drop does not include.

    Corroboration already committed elsewhere: the published ``Actual`` column
    reproduces to 1e-14 for BOTH weeks
    (``test_news_table_pairs_each_series_with_its_own_actual``). ``Actual`` is
    ``Y_location + Y_scale .* Y_new``, and ``Y_location`` / ``Y_scale`` are
    pre-2020 statistics -- identical whatever the estimate vintage. Exactly the
    signature of a re-estimated parameter file over unchanged standardisation.
    """
    d = fixture("published_nowcasts")
    median_param = np.median(estimates.param_gibbs, axis=1)
    worst: dict[str, float] = {}
    median_ratio: dict[str, float] = {}
    spreads: list[float] = []
    for week in WEEKS:
        published = dict(zip(
            (str(s) for s in d[f"news_{_key(week)}__series_id"]),
            d[f"news_{_key(week)}__forecast"], strict=True))
        got = _median_param_forecasts(estimates, spec, week, median_param)
        assert set(got) == set(published)

        # These forecasts have to be parameter-sensitive for any of this to mean
        # anything: if they were flat in the parameters, agreement would be luck
        # and disagreement would be unexplained.
        draws = [_median_param_forecasts(estimates, spec, week,
                                         estimates.param_gibbs[:, k])
                 for k in (0, 150, 300, 450)]
        errors, ratios = [], []
        for series_id, value in published.items():
            error = abs(got[series_id] - value) / abs(value)
            spread = (max(t[series_id] for t in draws)
                      - min(t[series_id] for t in draws)) / abs(value)
            errors.append(error)
            ratios.append(error / spread)
            spreads.append(spread)
        worst[week] = max(errors)
        median_ratio[week] = float(np.median(ratios))

    # Sensitivity. Measured minimum over all 16 series: 1.39% (PCEPI); the
    # median is 36.6% and the maximum 77.8% (PCEC96).
    assert min(spreads) > 0.01, min(spreads)
    # The gate week's parameters are this drop's parameters.
    assert worst["2023-09-29"] < 0.005, worst
    # The other week's are not, by a margin far outside anything the latents or
    # the seeds can produce.
    assert worst["2023-10-06"] > 0.05, worst
    # Guard against the comparison going numerically dead: if the two numbers
    # ever converge, this must fail rather than keep asserting a closed gap.
    assert worst["2023-10-06"] > 10 * worst["2023-09-29"], worst
    # Measured: 0.004 and 0.064. A robust statistic, so one awkward series
    # (PCEPI, whose forecast is the least parameter-sensitive of the sixteen)
    # cannot carry the conclusion on its own.
    assert median_ratio["2023-09-29"] < 0.02 < median_ratio["2023-10-06"], median_ratio


@pytest.mark.slow
@pytest.mark.fixtures
def test_the_1006_residual_is_a_bias_that_sits_in_the_revisions_term(
    fixture, reference
):
    """The 2023-10-06 headline residual is a fixed offset, and it is localised.

    Demoted from the gate deliberately. A Monte Carlo tolerance is the wrong
    instrument for a bias: a pass under `3*sqrt(2)*sd` would say only that the
    offset currently sits under 4.24 sigma-hat, not that the port is right.

    WHERE THE BIAS IS, measured directly over fifteen seeds (5-19), port minus
    published, each in units of its own seed-to-seed sd:

        component            mean gap        sd        in sigma
        2023-09-29 level     -0.010291    0.017331        0.59
        release total        -0.000522    0.005401        0.10
        REVISIONS TERM       +0.019197    0.002028        9.46
        ---------------------------------------------------------
        headline residual    +0.008383    0.014124        0.59

    Read that column. Two of the three components are indistinguishable from the
    published values, and the third is off by **nine and a half sigma**. And the
    headline -- the sum -- is back at 0.59 sigma, because the level term happens
    to be negative and cancels most of the revisions bias.

    THAT IS THE ARGUMENT FOR DEMOTING THIS WEEK FROM THE GATE. It is not that
    the headline fails; it passes. It is that the headline CANNOT SEE a
    9.5-sigma error in one of its own components, because another component's
    ordinary noise excursion happens to offset it. A gate assertion on the
    headline would report success while the decomposition underneath it is
    wrong -- which is the compensating-errors failure the plan's per-series test
    was written to catch, arriving through the revision terms instead of the
    releases.

    (An earlier version of this argument compared the two weeks' HEADLINE sds --
    2023-10-06's 0.005128 being smaller than 2023-09-29's 0.008112, so a
    revisions term carrying +-0.02 of noise was impossible. The conclusion was
    right, but both were five-sample sds and re-measurement moved them to
    0.014124 and 0.017331. The direct measurement above needs no such comparison
    and is far stronger.)

    WHY THE REVISIONS TERM. `rev_SSM` is by construction the effect of swapping
    `ssm_old` for `ssm_new`. In this drop `param_old == param_new`, so this
    port's `rev_SSM` measures the LATENT revision and nothing else. If MATLAB's
    2023-10-06 run used a later `param_new` -- which
    `test_the_1006_published_forecasts_need_parameters_this_drop_lacks`
    establishes on three independent legs -- then its `rev_SSM` also contained a
    genuine parameter revision, which this port cannot compute at all, because
    the parameters that would produce it are not in the drop.

    MEASURED, and sufficient: perturbing `param_new` away from
    `median(param_Gibbs)` by exactly the size the forecast comparison measures
    (median 6.4% of the parameter-draw spread) shifts the revisions term by
    -0.055, -0.023, +0.010 and +0.011 for four different draw directions. The
    +0.0192 that has to be explained is squarely inside that range, and one of
    the four reproduces it to 1.18x. `rev_data` barely moves across all of them
    (0.138 to 0.193) while `rev_SSM` carries the shift -- the mechanism above.
    So the missing estimate file is a SUFFICIENT explanation of the whole gap.
    Note what that does and does not establish. It is a scale test: it kills the
    null that a parameter difference of the measured size is too small to move
    the revisions term by 0.02, and it kills it cleanly, with a genuine control
    (`rev_SSM` is exactly 0.000000 when both sides use the same parameters) and a
    falsifier stated before the run. But 2 of the 4 directions carry the right
    sign, which is a coin flip, and a range spanning +-0.055 would absorb any
    additive defect smaller than that. So the correct reading is **no defect
    detected in the revisions path**, not "a defect there is ruled out" -- and
    `test_the_0929_revisions_term_has_no_published_counterpart` below records
    that on the gate week those terms are pinned against nothing at all. See the
    task report, experiment (a).

    The bounds below are two-sided so that the day somebody obtains the real
    2023-10-06 estimate file, this fails and says to promote the week into
    `test_reproduces_the_published_nowcast`.
    """
    d = fixture("published_nowcasts")
    got = reference("2023-10-06")

    d_headline = got.nowcast - d["published__2023_10_06"].item()
    d_releases = got.releases_impact - d["news_2023_10_06__impact"].sum().item()
    d_revisions = got.revisions_impact - PUBLISHED_1006_REVISIONS

    # The decisive quantity, and the only one that fails. Per-seed values over
    # seeds 5-19 span +0.016456 to +0.024281; seed 321 sits at +0.021522.
    assert 0.012 < d_revisions < 0.029, d_revisions
    # An offset, not an excursion: nine and a half sigma outside its own band.
    assert abs(d_revisions) > SIGMA_MULTIPLE * REVISIONS_SD_1006, d_revisions

    # The other two components, judged on exactly the same instrument, pass.
    # The contrast is the finding: one component is inconsistent with the
    # published figure and the rest of the decomposition is not.
    assert abs(d_releases) < SIGMA_MULTIPLE * RELEASES_SD_1006, d_releases
    assert abs(d_headline) < SIGMA_MULTIPLE * HEADLINE_SD["2023-10-06"], d_headline


@pytest.mark.fixtures
def test_the_0929_revisions_term_has_no_published_counterpart(fixture):
    """Record the check that CANNOT be made, so nobody assumes it was made.

    `test_the_1006_residual_is_a_bias_that_sits_in_the_revisions_term` compares
    this port's revisions term against the published one, which is derivable for
    2023-10-06 as `published_1006 - published_0929 - sum(published 10-06
    impacts)`. The same derivation for 2023-09-29 needs the 2023-09-22 headline,
    and the drop ships no `Update_2023_09_22.mat`. So the gate week's revisions
    term -- the one week whose parameters this drop can reproduce -- has no
    published counterpart at all, and is checked only by the internal identity
    in `test_the_decomposition_adds_up_to_the_headline`.

    That matters for Plan D, whose headline deliverable is a decomposition panel
    built on exactly these terms: the release impacts are pinned against the
    published table, and the revision terms are not pinned against anything.

    Asserted rather than written in a comment so that if the missing file ever
    turns up, this fails and says to add the check.
    """
    assert not (MATLAB_DIR / "output" / "Update_2023_09_22.mat").exists(), (
        "Update_2023_09_22.mat now exists: derive the published 2023-09-29 "
        "revisions term from it and assert it, then delete this test."
    )
    assert "published__2023_09_22" not in fixture("published_nowcasts")


@pytest.mark.slow
@pytest.mark.fixtures
def test_the_1006_release_impacts_miss_by_more_than_monte_carlo_error(
    fixture, reference
):
    """Pin the 2023-10-06 gap so it stays visible and so its repair is noticed.

    Four of the seven per-series impacts miss the measured Monte Carlo bound,
    the worst by 6.72x (TTLCONS), then ADPMNUSNERSA at 6.58x -- whose published
    weight is +3.4e-5 and ours -3.0e-5, a near-zero weight whose sign is not
    stable across parameter draws, so the sign flip is a symptom of the
    parameter difference and not of a porting error.

    (On the superseded five-seed sds this read five of seven, worst 6.45x.
    BOPTEXP moved under the line when its sd was re-measured 1.8x larger.)

    The bounds below are two-sided on purpose. The upper bound keeps this from
    becoming a test that any breakage would satisfy. The lower bound means that
    the day somebody obtains the real 2023-10-06 estimate file, this test fails
    and says to promote the week into ``test_reproduces_the_release_impacts``.
    """
    week = "2023-10-06"
    d = fixture("published_nowcasts")
    got = reference(week)
    published = dict(zip(
        (str(s) for s in d[f"news_{_key(week)}__series_id"]),
        d[f"news_{_key(week)}__impact"], strict=True))

    ratios = {s: abs(got.impact_for(s) - published[s].item())
                 / impact_tolerance(week, s) for s in published}
    over = sorted(s for s, r in ratios.items() if r > 1.0)
    # Measured on the re-measured 15-seed sds: 4 of 7 over, worst 6.72x
    # (TTLCONS), then ADPMNUSNERSA 6.58x, JTSJOL 2.23x, BOPTIMP 1.70x. On the
    # original 5-seed sds it read 5 of 7, worst 6.45x - BOPTEXP moved under the
    # line because its sd had been underestimated by 1.8x.
    assert len(over) >= 3, ratios
    assert max(ratios.values()) > 4.0, ratios
    # ... but the whole path still works: nothing is off by an order of
    # magnitude.
    assert max(ratios.values()) < 25.0, ratios
    # The release TOTAL is checked in
    # test_the_1006_residual_is_a_bias_that_sits_in_the_revisions_term, against
    # the measured seed-to-seed sd of the total rather than a round number. It
    # is not repeated here: the release total's seed-to-seed sd is 0.005401 over
    # the fifteen seeds in force (0.008262 over the original five), so a bound
    # tight enough to look impressive would be encoding seed 321's particular
    # draw. A 0.005 bound fails at seed 1, whose gap is -0.015973.


# --------------------------------------------------------------------------- #
# Structural checks that hold for both weeks whatever the estimate file
# --------------------------------------------------------------------------- #


@pytest.mark.slow
@pytest.mark.fixtures
@pytest.mark.parametrize("week", WEEKS)
def test_news_table_pairs_each_series_with_its_own_actual(week, fixture, reference):
    """Row-wise pairing, which the Task 8 tests cannot check.

    Those compare sorted multisets, so a permutation between ``series_id`` and
    ``actual`` would pass them. ``actual`` is the raw new-vintage datum
    de-standardised, so it is deterministic, independent of the estimate file,
    and agrees with the published table for both weeks.

    Tier 1 tolerance with an explicit atol. ``actual`` is computed as
    ``Y_scale .* news + forecasts``, which cancels to ``Y_location + Y_scale .*
    Y_new`` only up to rounding, so an absolute floor is unavoidable, and it is
    derived from the array rather than picked. The floor is load-bearing here
    and not just belt and braces: 2023-10-06 releases UNRATE with a published
    Actual of -0.0, on which the relative check is meaningless (measured
    relative deviation 1.0 on a value of 1.4e-14).

    Measured: worst absolute deviation over both weeks 1.4e-14, against floors
    of 8.7e-12 (2023-09-29, max |Actual| = 8.66) and 6.9e-10 (2023-10-06, max
    |Actual| = 690.0, JTSJOL). Margin: 500x and 49000x.
    """
    d = fixture("published_nowcasts")
    got = reference(week)
    pairs = dict(zip((str(s) for s in d[f"news_{_key(week)}__series_id"]),
                     d[f"news_{_key(week)}__actual"], strict=True))
    table = got.table
    assert set(table["series_id"]) == set(pairs)
    want = np.array([pairs[s] for s in table["series_id"]])
    atol = 1e-12 * np.max(np.abs(want))
    assert np.allclose(table["actual"].to_numpy(), want, rtol=1e-10, atol=atol)


@pytest.mark.slow
@pytest.mark.fixtures
@pytest.mark.parametrize("week", WEEKS)
def test_the_decomposition_adds_up_to_the_headline(week, reference):
    """Last week's nowcast + parameter revision + data revision + release
    impacts = this week's nowcast, in the published units.

    This is what ``example_nowcast.m`` prints as "Total impact", and it is the
    arithmetic the site's release-impact panel will rest on. It holds by
    construction on the four rows of ``point_nowcast`` -- so what it actually
    tests is the de-standardisation and the ``impacts`` assembly around them:
    the ``Y_scale(i_now)*(weights./Y_scale)`` rescaling cancels only if the
    right scale is applied on both sides.

    Tier 1, deterministic given the run: ``rel=1e-12`` with ``atol=0.0``. Both
    sides are of order 2, so no absolute floor is needed. Measured relative
    deviation: 3.8e-16 for 2023-09-29 and 5.4e-16 for 2023-10-06 -- a margin of
    about three orders of magnitude on a quantity already at the
    double-precision floor.
    """
    got = reference(week)
    identity = got.pnt_nowcast_old[0] + got.revisions_impact + got.releases_impact
    assert identity == pytest.approx(got.nowcast, rel=1e-12, abs=0.0)
    # And the pieces must be real, not a pair of zeros that trivially adds up.
    assert abs(got.releases_impact) > 1e-6
    assert got.nowcast != got.pnt_nowcast_old[0]


@pytest.mark.slow
@pytest.mark.fixtures
def test_the_two_weeks_chain(reference):
    """2023-10-06's "last week" row must BE 2023-09-29's headline.

    Row 1 of the 10-06 decomposition is ``fast_smoother(Y_old, SSM_old)`` with
    ``Y_old`` the 2023-09-29 vintage and ``SSM_old`` built from the latent chain
    that vintage drives - which is exactly row 4 of the 09-29 week: same data,
    same state space, same seed. So the two must agree, and the chain of weekly
    figures is internally consistent.

    This catches a whole class of assembly error the headline test cannot: a
    mis-selected vintage pair, a mis-seeded latent loop, or an old/new mix-up
    would move one of these two numbers and not the other. It is also why the
    per-week vintage selection matters - with a single hard-coded pair of data
    files this test could not exist.

    Tier 1 (``rel=1e-12``, ``atol=0.0``): both sides run the same code on
    bit-identical inputs. Measured deviation: 0.0 exactly.
    """
    old = reference("2023-10-06")
    new = reference("2023-09-29")
    assert old.seed == new.seed
    assert old.pnt_nowcast_old[0] == pytest.approx(new.nowcast, rel=1e-12, abs=0.0)


@pytest.mark.slow
@pytest.mark.fixtures
@pytest.mark.parametrize("week", WEEKS)
def test_the_density_nowcast_brackets_the_point_nowcast(week, reference):
    """Tier 2. 1,250 draws from the production path, checked against the point
    nowcast within Monte Carlo error rather than exactly."""
    got = reference(week)
    draws = got.density[:, 0]
    assert draws.shape == (1250,)
    assert draws.std(ddof=1) > 0
    mc_se = draws.std(ddof=1) / np.sqrt(draws.size)
    assert draws.mean() == pytest.approx(got.nowcast, abs=4.0 * mc_se)
