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
    assert index.index.freqstr is None or True   # a plain DatetimeIndex is fine
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


def test_deflate_refuses_rather_than_truncating_when_the_deflator_is_short():
    nominal = _nominal_household_spending()
    short = build_deflator(_sources()).index.loc["2015-01-01":]
    with pytest.raises(ValueError, match="does not cover"):
        deflate(nominal, short)


def test_build_deflator_refuses_a_missing_tier():
    sources = _sources()
    del sources["cpi_monthly_ceased"]
    with pytest.raises(KeyError, match="cpi_monthly_ceased"):
        build_deflator(sources)
