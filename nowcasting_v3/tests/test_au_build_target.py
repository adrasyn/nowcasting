"""The first-print target is applied inside build_panel, post-load.

WHICH GDP SERIES THE MODEL LEARNS IS A PROPERTY OF THE PANEL, not of the caller
that happens to build it. Until 2026-09-10 the substitution lived in
``tools/plan_c_backtest.py``, by hand, so an experiment could measure a
first-print model and production could not run one. These tests pin the
substitution to ``build_panel`` and the floor to ``collapse_floor``, so that
every path -- the estimate, the weekly job, the backtest -- gets the same target
and the same guard without doing anything itself.
"""
import numpy as np
import pytest

from nyfed.au import build
from nyfed.au.build import build_panel, collapse_floor, load_vintage
from nyfed.au.first_release import first_release_index, load_first_release

VINTAGE = load_vintage("tests/fixtures/au/vintage")
ASOF = "2026-06-01"


def test_the_default_target_is_the_first_print():
    p = build_panel(asof=ASOF, vintage=VINTAGE)
    assert p.target == "first_print"


def test_the_latest_target_is_still_available_and_unchanged():
    """The old behaviour, exactly: the row is latest-vintage annualised growth.

    Counting rows is not enough on its own -- the brief for this task asserted
    one observation per quarter of the cut vintage, which is 265 and the panel
    carries 183, because `DEFAULT_START` opens the window at 1980 and the
    recording's GDP reaches back to 1959. The count that means something is
    "every quarter of the window bar the first, which `pca` consumes"; the
    VALUES are what the test is actually for.
    """
    p = build_panel(asof=ASOF, vintage=VINTAGE, target="latest")
    assert p.target == "latest"
    g = VINTAGE.as_of(ASOF).series["gdp"].dropna()
    in_window = g[(g.index >= p.dates[0]) & (g.index <= p.dates[-1])]
    obs = np.flatnonzero(np.isfinite(p.Y[p.i_now]))
    assert obs.size == in_window.shape[0] - 1
    # De-standardised, the row IS the latest vintage's annualised quarterly
    # growth -- so the location and scale are that series' too.
    row = p.y_location[p.i_now, 0] + p.y_scale[p.i_now, 0] * p.Y[p.i_now]
    annualised = ((g / g.shift(1)) ** 4 - 1) * 100
    assert np.allclose(row[obs], annualised.reindex(p.dates[obs]).to_numpy())


def test_the_first_print_target_changes_the_gdp_row_and_nothing_else():
    a = build_panel(asof=ASOF, vintage=VINTAGE, target="latest")
    b = build_panel(asof=ASOF, vintage=VINTAGE, target="first_print")
    assert a.Y.shape == b.Y.shape and a.i_now == b.i_now
    others = [i for i in range(a.Y.shape[0]) if i != a.i_now]
    assert np.allclose(np.nan_to_num(a.Y[others]), np.nan_to_num(b.Y[others]))
    assert not np.allclose(np.nan_to_num(a.Y[a.i_now]), np.nan_to_num(b.Y[b.i_now]))
    # AND THE ROW IS THE FIRST PRINT, not merely different. De-standardised it
    # is the first-print index's own annualised growth, quarter for quarter.
    fp = first_release_index(load_first_release(), VINTAGE.series["gdp"].dropna())
    assert fp.index[-1] == VINTAGE.series["gdp"].dropna().index[-1]
    row = b.y_location[b.i_now, 0] + b.y_scale[b.i_now, 0] * b.Y[b.i_now]
    obs = np.flatnonzero(np.isfinite(row))
    annualised = ((fp / fp.shift(1)) ** 4 - 1) * 100
    assert np.allclose(row[obs], annualised.reindex(b.dates[obs]).to_numpy())


def test_the_substitution_happens_before_the_as_of_cut():
    """The anchor is the WHOLE recording, so the index does not move with `asof`.

    `first_release_index` pins its cumulated index to the anchor's level at the
    last quarter the two share. Substituting after the release-date cut would
    make that quarter -- and so the index's scale -- a function of the vintage
    date, which is a different target series at every `asof` and would make the
    backtest incomparable across vintages. Growth is what the transform reads,
    so the scale change is invisible in the panel; the guard is here because
    nothing downstream could see it go wrong.
    """
    early = build_panel(asof="2026-03-01", vintage=VINTAGE)
    late = build_panel(asof=ASOF, vintage=VINTAGE)
    k = min(early.Y.shape[1], late.Y.shape[1])
    row_e, row_l = early.Y[early.i_now, :k], late.Y[late.i_now, :k]
    both = np.isfinite(row_e) & np.isfinite(row_l)
    # Standardisation differs (the later panel has more observations), so
    # compare the RAW growth the standardisation was applied to.
    raw_e = early.y_location[early.i_now, 0] + early.y_scale[early.i_now, 0] * row_e
    raw_l = late.y_location[late.i_now, 0] + late.y_scale[late.i_now, 0] * row_l
    assert both.sum() > 100
    assert np.allclose(raw_e[both], raw_l[both])


def test_an_unknown_target_is_refused():
    with pytest.raises(ValueError, match="target"):
        build_panel(asof=ASOF, vintage=VINTAGE, target="revised")


def test_the_floor_is_target_specific_and_overridable(monkeypatch):
    assert collapse_floor("latest") == build.COLLAPSED_GLOBAL_LOADING == 1.0
    assert collapse_floor("first_print") == build.COLLAPSED_GLOBAL_LOADING_FIRST_PRINT
    assert build.COLLAPSED_GLOBAL_LOADING_FIRST_PRINT < build.COLLAPSED_GLOBAL_LOADING
    monkeypatch.setattr(build, "FLOOR_OVERRIDE", -1.0)
    assert collapse_floor("first_print") == -1.0


def test_an_unknown_target_has_no_floor():
    with pytest.raises(ValueError, match="target"):
        collapse_floor("revised")
