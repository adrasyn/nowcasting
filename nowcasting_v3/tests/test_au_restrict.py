"""Restrictions, and the COVID window that spec decision D3 specifies."""

import numpy as np
import pandas as pd
import pytest

from nyfed.au.panel import Panel
from nyfed.au.restrict import COVID_END, COVID_START, build_restrict
from nyfed.au.sources import SPEC_PATH
from nyfed.spec import load_spec


def _panel(T: int = 440) -> Panel:
    spec = load_spec(SPEC_PATH)
    n = len(spec.series_id)
    dates = pd.date_range("1990-01-01", periods=T, freq="MS")
    return Panel(
        Y=np.zeros((n, T)),
        y_location=np.zeros((n, 1)),
        y_scale=np.full((n, 1), 2.0),
        dates=dates,
        series_id=list(spec.series_id),
        i_now=spec.series_id.index("gdp"),
    )


def test_lambda_is_the_spec_block_pattern():
    spec = load_spec(SPEC_PATH)
    r = build_restrict(_panel(), spec)
    assert np.array_equal(r.Lambda, spec.blocks, equal_nan=True)


def test_iota_is_the_trend_divided_by_the_panel_scale():
    """example_estimate.m:72. Built from raw trend instead, the trend enters on
    the wrong scale and the model fits around it."""
    spec = load_spec(SPEC_PATH)
    panel = _panel()
    r = build_restrict(panel, spec)
    assert r.iota == pytest.approx(spec.trend / panel.y_scale.ravel())


def test_isquart_marks_exactly_the_three_quarterly_series():
    spec = load_spec(SPEC_PATH)
    r = build_restrict(_panel(), spec)
    assert r.isquart.dtype == bool
    assert r.isquart.sum() == 3
    assert r.isquart[spec.series_id.index("gdp")]
    assert not r.isquart[spec.series_id.index("employment")]


def test_the_covid_factor_is_isolated_in_the_factor_var():
    """example_estimate.m:80-82: its row and column are zeroed, only its own
    diagonal stays free, so it neither drives nor is driven by other factors."""
    spec = load_spec(SPEC_PATH)
    r = build_restrict(_panel(), spec, p_f=4)
    i = spec.block_names.index("COVID")
    off_row = np.delete(r.Phi[i, :, :], i, axis=0)
    off_col = np.delete(r.Phi[:, i, :], i, axis=0)
    assert (off_row == 0).all()
    assert (off_col == 0).all()
    assert np.isnan(r.Phi[i, i, :]).all()


def test_other_factors_keep_a_free_factor_var():
    spec = load_spec(SPEC_PATH)
    r = build_restrict(_panel(), spec, p_f=4)
    i = spec.block_names.index("COVID")
    j = 0 if i != 0 else 1
    assert np.isnan(r.Phi[j, j, :]).all()


def test_f_active_is_false_outside_the_window_and_true_inside():
    """The inversion is the bug to guard against: a mask that switches the
    pandemic factor on for the whole sample except the pandemic looks
    completely plausible and is exactly backwards."""
    spec = load_spec(SPEC_PATH)
    panel = _panel()
    r = build_restrict(panel, spec)
    i = spec.block_names.index("COVID")
    inside = (panel.dates >= COVID_START) & (panel.dates <= COVID_END)
    assert r.f_active[i, inside].all()
    assert not r.f_active[i, ~inside].any()
    assert inside.sum() == 22, "March 2020 to December 2021 inclusive"


def test_every_other_factor_is_active_throughout():
    spec = load_spec(SPEC_PATH)
    r = build_restrict(_panel(), spec)
    i = spec.block_names.index("COVID")
    others = [j for j in range(r.f_active.shape[0]) if j != i]
    assert r.f_active[others, :].all()


def test_f_active_spans_the_whole_panel():
    spec = load_spec(SPEC_PATH)
    panel = _panel(T=300)
    r = build_restrict(panel, spec)
    assert r.f_active.shape == (5, 300)
