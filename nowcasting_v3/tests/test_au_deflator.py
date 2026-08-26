"""The household spending deflator, tested offline against recorded payloads.

No test here touches the network. Everything in ``nyfed.au.deflator`` except
``fetch_deflator_sources`` is pure, and the three ABS payloads it splices are
committed whole -- not tailed -- because the OVERLAPS are what a ratio splice is
made of and a 36-row tail would delete them.

Re-record with ``tools/record_au_deflator_fixtures.py``.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from nyfed.au.deflator import (
    DEFLATOR_SOURCES,
    build_deflator,
    deflate,
    quarterly_to_monthly,
    real_household_spending,
    splice,
)
from nyfed.au.fetch_abs import CEASED_CATALOGUE_URLS, parse_abs_frame
from nyfed.au.sources import AU_SERIES

FIXTURES = Path(__file__).parent / "fixtures" / "au"

# The live monthly tier deliberately reads the REGISTRY's fixture. It is the
# same ABS series as the panel's `cpi` row, and pointing both at one file is
# what stops the panel's price measure and the consumption deflator drifting
# into being two different numbers for the same month.
FIXTURE_FILES = {
    "cpi_monthly_live": "abs_cpi.csv",
    "cpi_monthly_ceased": "abs_cpi_monthly_ceased.csv",
    "cpi_quarterly": "abs_cpi_quarterly.csv",
}
_PERIOD_FREQ = {"m": "M", "q": "Q-DEC"}

# Measured on the committed fixtures, 2026-08-26. Pinned rather than recomputed
# in the assertions, so that a re-record which moves them is visible.
SEAM_LIVE_OVER_CEASED_RATIO = 0.809277
SEAM_MONTHLY_OVER_QUARTERLY_RATIO = 1.045819


def _series(key: str) -> pd.Series:
    source = next(s for s in DEFLATOR_SOURCES if s.key == key)
    frame = pd.read_csv(FIXTURES / FIXTURE_FILES[key], index_col=0)
    frame.index = pd.PeriodIndex(
        frame.index.astype(str), freq=_PERIOD_FREQ[source.frequency]
    )
    return parse_abs_frame(frame, source.locator.split(":")[1])


def _sources() -> dict[str, pd.Series]:
    return {s.key: _series(s.key) for s in DEFLATOR_SOURCES}


def _nominal_household_spending() -> pd.Series:
    frame = pd.read_csv(FIXTURES / "abs_household_spending_full.csv", index_col=0)
    frame.index = pd.PeriodIndex(frame.index.astype(str), freq="M")
    return parse_abs_frame(frame, "A130200584T")


# --- fixture discipline ----------------------------------------------------


@pytest.mark.parametrize("key", list(FIXTURE_FILES), ids=lambda k: k)
def test_each_fixture_header_is_the_series_id_the_registry_asks_for(key):
    """Task 2's lesson, applied to the new payloads.

    ``parse_abs_frame`` falls back to the single column of an unlabelled frame,
    so a fixture recorded under one id and requested under another passed every
    test in this project until Task 2 closed it. Assert the header directly.
    """
    header = pd.read_csv(FIXTURES / FIXTURE_FILES[key], nrows=0).columns[-1]
    wanted = next(s for s in DEFLATOR_SOURCES if s.key == key).locator.split(":")[1]
    assert header == wanted


def test_the_household_spending_fixture_is_the_registry_series_recorded_whole():
    header = pd.read_csv(FIXTURES / "abs_household_spending_full.csv", nrows=0).columns[-1]
    registry = next(s for s in AU_SERIES if s.key == "household_spending")
    assert header == registry.locator.split(":")[1]
    nominal = _nominal_household_spending()
    assert nominal.index[0] == pd.Timestamp("2012-07-01")
    assert len(nominal) >= 168, "the fixture was tailed; the deflator needs the history"


def test_the_live_tier_is_the_panels_own_cpi_series():
    """The deflator's best tier and the panel's `cpi` row must be one series."""
    live = next(s for s in DEFLATOR_SOURCES if s.key == "cpi_monthly_live")
    cpi = next(s for s in AU_SERIES if s.key == "cpi")
    assert live.locator == cpi.locator
    assert FIXTURE_FILES["cpi_monthly_live"] == "abs_cpi.csv"


def test_the_ceased_catalogue_override_exists_and_is_needed_by_exactly_one_tier():
    """6484.0 is gone from the ABS Time Series Directory, so readabs cannot
    resolve it; the frozen landing page is the only route. Nothing in the
    registry may depend on that route -- it is a deflator-only concession."""
    assert "6484.0" in CEASED_CATALOGUE_URLS
    assert CEASED_CATALOGUE_URLS["6484.0"].startswith("https://www.abs.gov.au/")
    assert [s.key for s in DEFLATOR_SOURCES
            if s.locator.split(":")[0] in CEASED_CATALOGUE_URLS] == ["cpi_monthly_ceased"]
    assert not [s.key for s in AU_SERIES
                if s.locator.split(":")[0] in CEASED_CATALOGUE_URLS]


# --- the pieces ------------------------------------------------------------


def test_quarterly_to_monthly_keeps_the_quarterly_values_and_interpolates_between():
    q = pd.Series(
        [100.0, 103.0],
        index=pd.DatetimeIndex(["2020-03-01", "2020-06-01"]),
    )
    m = quarterly_to_monthly(q)
    assert list(m.index.strftime("%Y-%m")) == ["2020-03", "2020-04", "2020-05", "2020-06"]
    assert m.loc["2020-03"].item() == pytest.approx(100.0)
    assert m.loc["2020-06"].item() == pytest.approx(103.0)
    assert m.loc["2020-04"].item() == pytest.approx(100.0 + 3.0 * 31 / 92, abs=0.02)


def test_quarterly_to_monthly_refuses_start_of_quarter_dating():
    """The failure Task 2 nearly shipped, in the one place it would be silent.

    Start-of-quarter dates would interpolate over the wrong three months AND be
    dropped by ``panel._align``'s ``{3, 6, 9, 12}`` mask."""
    q = pd.Series([100.0, 103.0], index=pd.DatetimeIndex(["2020-01-01", "2020-04-01"]))
    with pytest.raises(ValueError, match="last month of its quarter"):
        quarterly_to_monthly(q)


def test_splice_rescales_the_older_series_to_the_preferred_ones_level():
    older = pd.Series(
        np.arange(100.0, 112.0), index=pd.date_range("2020-01-01", periods=12, freq="MS")
    )
    preferred = older.iloc[6:] * 2.0   # same series, twice the base
    joined, seam = splice(preferred, older)

    assert seam.n_overlap == 6
    assert seam.ratio == pytest.approx(2.0)
    assert seam.max_abs_deviation == pytest.approx(0.0, abs=1e-12)
    # The rebased join is the original series on the preferred base, everywhere.
    pd.testing.assert_series_equal(joined, older * 2.0, check_names=False)


def test_splice_never_alters_the_preferred_series():
    older = pd.Series(
        np.arange(100.0, 112.0), index=pd.date_range("2020-01-01", periods=12, freq="MS")
    )
    preferred = older.iloc[6:] * 2.0 + np.array([0.0, 1.0, -1.0, 2.0, -2.0, 0.5])
    joined, _ = splice(preferred, older)
    pd.testing.assert_series_equal(
        joined.loc[preferred.index], preferred, check_names=False
    )


def test_splice_refuses_two_series_that_do_not_overlap():
    a = pd.Series([1.0, 2.0], index=pd.date_range("2020-01-01", periods=2, freq="MS"))
    b = pd.Series([1.0, 2.0], index=pd.date_range("2021-01-01", periods=2, freq="MS"))
    with pytest.raises(ValueError, match="do not overlap"):
        splice(b, a)


def test_splice_refuses_an_overlap_too_short_to_fit_a_ratio_over():
    """A one-month overlap is the dangerous case, not the obviously broken one.

    It yields a ratio with no evidence behind it AND a `Seam` whose
    `max_abs_deviation` is identically 0.0 -- so the audit record looks flawless
    exactly when it is emptiest. Both seams in the real deflator have 18 and 106
    months, so the floor costs nothing.
    """
    older = pd.Series(
        np.arange(100.0, 112.0), index=pd.date_range("2020-01-01", periods=12, freq="MS")
    )
    single = older.iloc[11:] * 2.0
    with pytest.raises(ValueError, match="only 1 month"):
        splice(single, older)

    # And the seam it would have produced would have looked perfect.
    _, seam = splice(single, older, min_overlap=1)
    assert seam.n_overlap == 1
    assert seam.max_abs_deviation == 0.0

    three = older.iloc[9:] * 2.0
    with pytest.raises(ValueError, match="only 3 month"):
        splice(three, older)

    six = older.iloc[6:] * 2.0
    assert splice(six, older)[1].n_overlap == 6   # the floor itself is accepted


# --- the built deflator ----------------------------------------------------


def test_every_tier_contributes_the_coverage_the_precedence_implies():
    coverage = build_deflator(_sources()).coverage()
    assert set(coverage) == {"cpi_monthly_live", "cpi_monthly_ceased", "cpi_quarterly"}

    live_start, live_end, n_live = coverage["cpi_monthly_live"]
    assert (live_start, live_end) == (pd.Timestamp("2024-04-01"), pd.Timestamp("2026-07-01"))
    assert n_live == 28

    ceased_start, ceased_end, n_ceased = coverage["cpi_monthly_ceased"]
    assert ceased_start == pd.Timestamp("2017-09-01")
    assert ceased_end == pd.Timestamp("2024-03-01"), (
        "the ceased tier must stop where the live one starts, not overlap it"
    )
    assert n_ceased == 79

    q_start, q_end, _ = coverage["cpi_quarterly"]
    assert q_start == pd.Timestamp("1948-09-01")
    assert q_end == pd.Timestamp("2017-08-01"), (
        "the interpolated tier must fill only what no monthly series reaches"
    )


def test_the_deflator_is_a_gapless_positive_monthly_index():
    index = build_deflator(_sources()).index
    assert isinstance(index.index, pd.DatetimeIndex)
    assert index.index.is_monotonic_increasing and index.index.is_unique
    assert not index.isna().any()
    assert (index > 0).all()
    assert (index.index == pd.date_range(index.index[0], index.index[-1], freq="MS")).all()
    assert index.index[0] == pd.Timestamp("1948-09-01")


def test_the_two_monthly_cpi_measures_agree_at_their_seam():
    """The live 6401.0 series and the ceased 6484.0 indicator over 2024-04..2025-09.

    Measured 2026-08-26: ratio 0.809277, mean absolute deviation 0.073%, worst
    month 0.162% (2024-11). Two ABS measures of the same thing, so they should
    very nearly coincide once rebased -- and they do.
    """
    seam = build_deflator(_sources()).seams[0]
    assert seam.older == "cpi_monthly_ceased"
    assert seam.n_overlap == 18
    assert (seam.overlap_start, seam.overlap_end) == (
        pd.Timestamp("2024-04-01"), pd.Timestamp("2025-09-01")
    )
    assert seam.ratio == pytest.approx(SEAM_LIVE_OVER_CEASED_RATIO, abs=5e-5)
    assert seam.mean_abs_deviation < 0.001
    assert seam.max_abs_deviation < 0.005


def test_the_spliced_monthly_deflator_and_the_quarterly_one_agree_within_1_percent():
    """The brief's seam test, and the one place it does not quite hold.

    Over the 106-month overlap (2017-09..2026-06) the spliced monthly deflator
    and the rebased quarterly-interpolated one agree to a mean of 0.22% and a
    median of 0.17%. EXACTLY ONE month exceeds 1%: July 2020, at 1.088%.

    That month is not a rebasing error, it is the free-childcare episode --
    quarterly CPI fell 1.9% in 2020Q2 and rebounded in Q3, the sharpest
    within-quarter price movement in the modern Australian series. A linear
    interpolation between quarter-end index numbers cannot represent it, and the
    monthly series can. So the exceedance is evidence FOR preferring the monthly
    tiers, which is what the precedence already does.

    The assertions below therefore pin the exception rather than widening the
    tolerance: one named month, bounded, and 1% everywhere else. A bad rebase
    would not produce this -- it would move the whole overlap by the size of the
    ratio error (4.6% at this seam, 19% at the other), failing the mean bound in
    the first assertion.
    """
    deflator = build_deflator(_sources())
    seam = deflator.seams[1]
    assert seam.older == "cpi_quarterly"
    assert seam.n_overlap == 106
    assert seam.ratio == pytest.approx(SEAM_MONTHLY_OVER_QUARTERLY_RATIO, abs=5e-5)

    monthly, _ = splice(_series("cpi_monthly_live"), _series("cpi_monthly_ceased"))
    quarterly = quarterly_to_monthly(_series("cpi_quarterly")) * seam.ratio
    overlap = monthly.index.intersection(quarterly.index)
    deviation = (monthly[overlap] / quarterly[overlap] - 1.0).abs()

    assert deviation.mean() < 0.005, "the level does not match: check the rebasing"
    assert deviation.median() < 0.003

    exceeds = deviation[deviation > 0.01]
    assert list(exceeds.index) == [pd.Timestamp("2020-07-01")], (
        "the 1% agreement now breaks in months other than the 2020 childcare "
        f"episode: {[str(d.date()) for d in exceeds.index]}"
    )
    assert exceeds.iloc[0] < 0.0125
    outside_2020 = deviation[deviation.index.year != 2020]
    assert outside_2020.max() < 0.0075


def test_concatenating_instead_of_splicing_would_put_a_19_percent_step_at_the_seam():
    """Why the splice is by ratio. Not a hypothetical: the ceased indicator is
    based at its own start (2017-09 = 100) and the live one at 2024-04 = 100, so
    end-to-end joining drops the deflator by a fifth in one month -- and `pch`
    would hand the Global factor's normaliser a false +23% month."""
    live, ceased = _series("cpi_monthly_live"), _series("cpi_monthly_ceased")
    concatenated = live.combine_first(ceased)      # no rebasing
    step = concatenated.pct_change().loc[pd.Timestamp("2024-04-01")].item()
    assert step < -0.15

    spliced, _ = splice(live, ceased)
    assert abs(spliced.pct_change().loc[pd.Timestamp("2024-04-01")].item()) < 0.01


# --- deflating household spending ------------------------------------------


def test_the_deflated_series_starts_at_the_same_month_as_the_nominal_one():
    """A deflator that silently truncated history would shorten the panel's
    longest consumption record -- and the one that normalises the Global
    factor -- with the model running on the shortened version."""
    nominal = _nominal_household_spending()
    real = real_household_spending(nominal, _sources())
    assert real.index[0] == nominal.index[0] == pd.Timestamp("2012-07-01")
    assert real.index[-1] == nominal.index[-1]
    assert len(real) == len(nominal)
    assert real.notna().all()


def test_the_deflated_series_is_lower_than_the_nominal_one_after_the_base_month():
    """Prices rose over 2012-2026, so real spending in 2012-07 dollars must sit
    below the current-price series everywhere after the base -- and equal it at
    the base. An inverted or flat deflator fails here."""
    nominal = _nominal_household_spending()
    real = real_household_spending(nominal, _sources())
    base = nominal.index[0]

    assert real.loc[base].item() == pytest.approx(nominal.loc[base].item())
    after = real.index > base
    assert (real[after] < nominal[after]).all()
    # By 2026 the gap is the accumulated 2012-2026 price level, ~45%.
    assert real.iloc[-1].item() / nominal.iloc[-1].item() < 0.75


def test_deflation_removes_the_inflation_v2_measured_in_the_nominal_series():
    """v2's panel notes recorded the defect empirically: through 2024 the
    nominal indicator's mean 3-month change was 0.82% against 0.19% real, with
    real GDP around 0.4%. This deflator reproduces that independently --
    measured 0.812% nominal against 0.214% real -- which is corroboration from a
    different codebase that the deflation is doing the intended job.
    """
    nominal = _nominal_household_spending()
    real = real_household_spending(nominal, _sources())
    nominal_2024 = (nominal.pct_change(3) * 100).loc["2024"].mean()
    real_2024 = (real.pct_change(3) * 100).loc["2024"].mean()
    assert nominal_2024 == pytest.approx(0.82, abs=0.1)
    assert real_2024 == pytest.approx(0.19, abs=0.1)
    assert real_2024 < nominal_2024 - 0.4


def test_no_seam_shows_up_as_a_spike_in_the_deflated_series():
    """The failure ratio-splicing exists to prevent, measured on the output.

    Both seams fall inside household spending's span -- 2017-09 where the
    interpolated tier hands over to the ceased monthly one, and 2024-04 where
    that hands over to the live one. A step change in the deflator becomes one
    large false month in `pch`, so assert the seam months are unremarkable
    against the series' own distribution.
    """
    real = real_household_spending(_nominal_household_spending(), _sources())
    change = (real.pct_change() * 100).dropna().abs()
    ordinary = change.quantile(0.9)
    for seam_month in ("2017-09-01", "2024-04-01"):
        assert change.loc[pd.Timestamp(seam_month)].item() < ordinary, (
            f"{seam_month} is among the largest monthly moves in the deflated "
            "series, which is what a seam artefact looks like"
        )


def test_deflate_refuses_rather_than_truncating_when_the_deflator_starts_late():
    """A LEADING gap is lost history, and it must halt."""
    nominal = _nominal_household_spending()
    short = build_deflator(_sources()).index.loc["2015-01-01":]
    with pytest.raises(ValueError, match="LEADING edge"):
        deflate(nominal, short)


def test_deflate_leaves_a_trailing_gap_as_nan_instead_of_halting_the_build():
    """A TRAILING gap is ragged edge, which is the condition a nowcast lives in.

    The margin here is one release: monthly CPI leads household spending by
    exactly one month, so halting on a short tail would let a single late ABS
    publication take down the whole panel build rather than cost the last month
    of one row. The Kalman filter handles NaN natively.
    """
    nominal = _nominal_household_spending()
    full = build_deflator(_sources()).index
    truncated = full.loc[: pd.Timestamp("2026-03-01")]
    assert truncated.index[-1] == pd.Timestamp("2026-03-01")

    real = deflate(nominal, truncated)

    assert len(real) == len(nominal)
    assert real.index[0] == nominal.index[0]
    assert real.index[-1] == nominal.index[-1]
    missing = real.index[real.isna()]
    assert list(missing) == [
        pd.Timestamp("2026-04-01"), pd.Timestamp("2026-05-01"), pd.Timestamp("2026-06-01")
    ]
    # Everything the deflator does cover is unchanged by the truncation.
    covered = real.index[real.notna()]
    pd.testing.assert_series_equal(
        real[covered], deflate(nominal, full)[covered], check_names=False
    )


def test_deflate_refuses_a_hole_in_the_middle_of_the_deflator():
    """Not ragged edge. A monthly price index does not have holes."""
    nominal = _nominal_household_spending()
    holed = build_deflator(_sources()).index.drop(pd.Timestamp("2019-05-01"))
    with pytest.raises(ValueError, match="gap"):
        deflate(nominal, holed)


# --- tiers that this vintage does not have ---------------------------------


def _cut(key: str, months: int | None) -> dict[str, pd.Series]:
    """The full tiers, with one of them truncated to its first ``months``.

    ``months=None`` empties it. This is what ``build.Vintage.as_of`` does to a
    tier at a vintage earlier than its history: the live 6401.0 monthly series
    begins in 2024-04, so at ``asof="2018-06-01"`` it is legitimately empty, and
    between 2024-06 and 2024-10 it is present but too short to be rebased.
    """
    sources = _sources()
    sources[key] = sources[key].iloc[: 0 if months is None else months]
    return sources


@pytest.mark.parametrize("months", [None, 0, 3])
def test_a_tier_the_vintage_predates_is_skipped_not_fatal(months):
    """The guard that made every vintage before 2024-11 unbuildable.

    ``DEFLATOR_SOURCES`` is explicitly "each entry supplies only the months no
    earlier entry covers", so a tier that supplies nothing supplies nothing.
    Refusing there stopped ``build_panel`` -- the primitive Plan C's backtest
    calls -- from building any vintage before roughly November 2024, and it
    named the wrong cause on the way out.

    Both the empty case and the too-short-to-rebase case are the same
    situation seen a few months apart, so both skip, and the skip is RECORDED
    rather than silent.
    """
    sources = _cut("cpi_monthly_live", months)
    deflator = build_deflator(sources, recorded=_sources())

    assert list(deflator.skipped) == ["cpi_monthly_live"]
    assert set(deflator.coverage()) == {"cpi_monthly_ceased", "cpi_quarterly"}
    assert deflator.index.index[0] == pd.Timestamp("1948-09-01")
    # The fallback tier still reaches the present, so dropping the live one
    # costs precision at the recent end, not coverage. That is the whole reason
    # skipping is safe here and refusing a genuinely broken feed is not.
    assert deflator.index.index[-1] == pd.Timestamp("2026-06-01")
    assert not deflator.index.isna().any()
    assert (deflator.index > 0).all()

    # What is built is exactly the two-tier splice, not a damaged three-tier one.
    expected, _ = splice(
        _series("cpi_monthly_ceased"),
        quarterly_to_monthly(_series("cpi_quarterly")),
    )
    pd.testing.assert_series_equal(
        deflator.index, expected.rename("cpi_spliced"), check_names=False
    )


@pytest.mark.parametrize("months", [None, 0, 3])
def test_a_tier_that_is_empty_when_it_should_have_data_is_still_refused(months):
    """The hazard the original guard was written for, kept.

    A fetcher that returned nothing, or a series id that has moved, produces the
    same empty tier an early vintage does -- and dropping THAT one silently
    would fall the deflator back to interpolated quarterly prices for the recent
    months, which is the approximation the hybrid exists to avoid.

    The discriminator is the recording: here the cut removed nothing, so the
    shortfall is the source's and it raises. Nothing about a date is typed in.
    """
    sources = _cut("cpi_monthly_live", months)
    with pytest.raises(ValueError, match="cut does not explain it"):
        build_deflator(sources, recorded=sources)


@pytest.mark.parametrize("months", [None, 0, 3])
def test_without_a_recording_to_compare_against_an_unusable_tier_refuses(months):
    """No ``recorded=``, no way to tell the two apart, so the strict half wins.

    This is what a direct call gets. ``build.build_panel`` passes the uncut
    vintage and gets the distinction; anyone else gets the behaviour this
    module had before.
    """
    with pytest.raises(ValueError, match="no recording to compare against"):
        build_deflator(_cut("cpi_monthly_live", months))


def test_the_full_history_build_skips_nothing():
    """The ordinary case is unchanged: three tiers in, three tiers used."""
    assert build_deflator(_sources()).skipped == {}
    assert build_deflator(_sources(), recorded=_sources()).skipped == {}


def test_a_recording_missing_a_tier_is_refused_rather_than_ignored():
    sources = _sources()
    recorded = _sources()
    del recorded["cpi_quarterly"]
    with pytest.raises(KeyError, match="cpi_quarterly"):
        build_deflator(sources, recorded=recorded)


def test_build_deflator_refuses_a_missing_tier():
    sources = _sources()
    del sources["cpi_monthly_ceased"]
    with pytest.raises(KeyError, match="cpi_monthly_ceased"):
        build_deflator(sources)
