"""Panel assembly.

The panel is data, so it is tested like data: ragged edges, histories that
start decades apart, and quarterly series landing in the right month.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from nyfed.au.panel import Panel, assemble, standardise
from nyfed.au.sources import AU_SERIES

START, END = "1990-01-01", "2026-06-01"
FIXTURES = Path(__file__).parent / "fixtures" / "au"


def _monthly(start: str, end: str, value: float = 1.0) -> pd.Series:
    idx = pd.date_range(start, end, freq="MS")
    return pd.Series(np.arange(len(idx), dtype=float) + value, index=idx)


def _quarterly(start: str, end: str) -> pd.Series:
    idx = pd.date_range(start, end, freq="QE").to_period("M").to_timestamp()
    return pd.Series(np.arange(len(idx), dtype=float), index=idx)


def _panel_inputs() -> dict[str, pd.Series]:
    out = {}
    for s in AU_SERIES:
        out[s.key] = _monthly(START, END) if s.frequency == "m" else _quarterly(START, END)
    return out


def test_standardise_returns_zero_mean_unit_variance_ignoring_nan():
    raw = np.array([[1.0, 2.0, np.nan, 4.0], [10.0, 20.0, 30.0, np.nan]])
    Y, loc, scale = standardise(raw)
    assert loc.shape == (2, 1) and scale.shape == (2, 1)
    assert np.nanmean(Y, axis=1) == pytest.approx([0.0, 0.0], abs=1e-12)
    assert np.nanstd(Y, axis=1, ddof=1) == pytest.approx([1.0, 1.0], abs=1e-12)
    assert np.isnan(Y[0, 2]) and np.isnan(Y[1, 3])


def test_standardise_leaves_a_constant_series_at_zero_rather_than_dividing_by_zero():
    Y, _, scale = standardise(np.array([[3.0, 3.0, 3.0]]))
    assert np.isfinite(Y).all()
    assert scale[0, 0] == 1.0


def test_standardise_refuses_an_all_nan_row_rather_than_warning():
    """``np.nanmean`` of an empty slice emits a RuntimeWarning, which this suite
    turns into an error at an unhelpful place. Worse, an all-NaN row is the
    exact shape of the failure this project has feared most -- an empty GDP
    target the model still runs on -- so it deserves its own message."""
    raw = np.array([[1.0, 2.0, 3.0], [np.nan, np.nan, np.nan]])
    with pytest.raises(ValueError, match=r"row\(s\) \[1\]"):
        standardise(raw)


def test_panel_shape_and_row_order_follow_the_spec():
    panel = assemble(_panel_inputs(), start=START, end=END)
    assert isinstance(panel, Panel)
    assert panel.Y.shape[0] == len(AU_SERIES) == 15
    assert panel.series_id == [s.series_id for s in AU_SERIES]
    assert panel.Y.shape[1] == len(panel.dates)


def test_gdp_is_i_now():
    panel = assemble(_panel_inputs(), start=START, end=END)
    assert panel.series_id[panel.i_now] == "gdp"


def test_quarterly_series_sit_in_the_last_month_of_their_quarter():
    panel = assemble(_panel_inputs(), start=START, end=END)
    row = panel.series_id.index("gdp")
    observed = panel.dates[~np.isnan(panel.Y[row])]
    assert len(observed) > 0
    assert set(observed.month) == {3, 6, 9, 12}


def test_a_real_quarterly_payload_survives_the_alignment_mask():
    """The synthetic ``_quarterly`` helper above builds its own dates, so it
    cannot catch a disagreement between ``_align``'s ``{3, 6, 9, 12}`` mask and
    the dating ``fetch_abs.parse_abs_frame`` actually produces. This test takes
    the recorded GDP payload through the real parser instead.

    That disagreement is not hypothetical: Task 2's first parser dated 2017Q2 to
    2017-04, every quarterly observation was dropped by this mask, and the model
    ran on an all-NaN target without complaint.

    The count is one BELOW the payload's, not equal to it: since Task 5A the
    panel applies the spec's ``pca`` to GDP, and the first quarter in the window
    has no predecessor to grow from. That is arithmetic, not a dropped
    observation -- the failure this test exists for still shows as 0, or as
    months outside ``{3, 6, 9, 12}``.
    """
    from nyfed.au.fetch_abs import parse_abs_frame

    frame = pd.read_csv(FIXTURES / "abs_gdp.csv", index_col=0)
    frame.index = pd.PeriodIndex(frame.index.astype(str), freq="Q-DEC")
    gdp = parse_abs_frame(frame, "A2304402X")

    inputs = _panel_inputs()
    inputs["gdp"] = gdp
    panel = assemble(inputs, start="2018-01-01", end="2026-03-01")

    row = panel.series_id.index("gdp")
    observed = panel.dates[~np.isnan(panel.Y[row])]
    assert len(observed) == len(gdp.loc["2018":"2026-03"]) - 1, (
        "the alignment mask dropped real quarterly observations"
    )
    assert set(observed.month) == {3, 6, 9, 12}


def test_a_series_that_starts_late_is_nan_before_it_starts_not_zero():
    """Household spending starts in 2012. Filling with zero would be inventing
    data; the Kalman filter handles NaN natively."""
    inputs = _panel_inputs()
    inputs["household_spending"] = _monthly("2012-07-01", END)
    panel = assemble(inputs, start=START, end=END)
    row = panel.series_id.index("household_spending")
    before = panel.dates < pd.Timestamp("2012-07-01")
    assert np.isnan(panel.Y[row, before]).all()
    assert not np.isnan(panel.Y[row, ~before]).all()


def test_a_ragged_edge_is_preserved():
    """Series end on different dates. The most recent months are the whole
    point of a nowcast, so a short series must not truncate the panel."""
    inputs = _panel_inputs()
    inputs["nab_conditions"] = _monthly(START, "2026-04-01")
    panel = assemble(inputs, start=START, end=END)
    row = panel.series_id.index("nab_conditions")
    assert np.isnan(panel.Y[row, -2:]).all()
    assert panel.dates[-1] == pd.Timestamp(END)


def test_assembly_refuses_to_label_rows_it_did_not_stack():
    """`Y` is stacked from the registry and `series_id`/`i_now` come from the
    spec. Nothing else ties them together, so a divergence would attach every
    label -- and the nowcast target -- to the wrong row, silently, with the
    model still running. Drop one registry entry and the guard must fire rather
    than produce a 14-row panel carrying 15 labels."""
    sources = tuple(s for s in AU_SERIES if s.key != "cpi_trimmed")
    inputs = _panel_inputs()
    with pytest.raises(ValueError, match="wrong row"):
        assemble(inputs, start=START, end=END, sources=sources)


def test_assembly_refuses_a_registry_reordered_against_the_spec():
    sources = (AU_SERIES[1], AU_SERIES[0], *AU_SERIES[2:])
    with pytest.raises(ValueError, match="same order"):
        assemble(_panel_inputs(), start=START, end=END, sources=sources)


def test_assembly_refuses_a_panel_missing_a_registered_series():
    inputs = _panel_inputs()
    del inputs["exports"]
    with pytest.raises(KeyError, match="exports"):
        assemble(inputs, start=START, end=END)


# --- the negative-imports guard -------------------------------------------
#
# ABS reports imports as a DEBIT, so the series enters the panel negative:
# 2026-06 is -45768.0 against exports at +47696.0. That is correct, and it is
# safe only while `pch` is a ratio. Implemented as a log difference -- the more
# common form, and the vendored MATLAB carries no transform code to copy from --
# every value of a wholly negative series becomes NaN and NOTHING RAISES. The
# panel would quietly lose a series and the model would run on fourteen.


def _recorded(key: str, series_id: str, freq: str = "m") -> pd.Series:
    from nyfed.au.fetch_abs import parse_abs_frame

    frame = pd.read_csv(FIXTURES / f"abs_{key}.csv", index_col=0)
    frame.index = pd.PeriodIndex(
        frame.index.astype(str), freq={"m": "M", "q": "Q-DEC"}[freq]
    )
    return parse_abs_frame(frame, series_id)


def test_the_recorded_imports_payload_really_is_negative():
    """Guards the guard. If ABS ever switched to a credit convention the test
    below would still pass while testing nothing at all."""
    imports = _recorded("imports", "A2718603V")
    exports = _recorded("exports", "A2718577A")
    assert (imports < 0).all(), "imports is no longer negative; re-read the guard below"
    assert (exports > 0).all()
    assert imports.loc[pd.Timestamp("2026-06-01")].item() == pytest.approx(-45768.0)


def test_assembly_accepts_the_real_negative_imports_series():
    inputs = _panel_inputs()
    inputs["imports"] = _recorded("imports", "A2718603V")
    inputs["exports"] = _recorded("exports", "A2718577A")
    panel = assemble(inputs, start="2023-07-01", end="2026-06-01")
    row = panel.series_id.index("imports")
    # 36 months in the window, less the first: since Task 5A the panel applies
    # the spec's `pch` to imports and the first month has no predecessor. A log
    # difference would leave 0, not 35.
    assert np.isfinite(panel.Y[row]).sum() == 35
    assert np.isnan(panel.Y[row, 0])


def test_assembly_refuses_a_panel_whose_imports_row_was_swallowed():
    """What a log-difference `pch` would do to a wholly negative series."""
    inputs = _panel_inputs()
    imports = _recorded("imports", "A2718603V")
    inputs["exports"] = _recorded("exports", "A2718577A")
    with np.errstate(invalid="ignore"):
        inputs["imports"] = np.log(imports)   # every value NaN, no error raised
    assert inputs["imports"].isna().all()

    with pytest.raises(ValueError, match="imports"):
        assemble(inputs, start="2023-07-01", end="2026-06-01")


def test_the_imports_guard_also_catches_a_partial_loss():
    """Not just the all-NaN case: any shortfall against exports over the same
    span means something ate observations."""
    inputs = _panel_inputs()
    imports = _recorded("imports", "A2718603V")
    inputs["exports"] = _recorded("exports", "A2718577A")
    inputs["imports"] = imports.copy()
    inputs["imports"].iloc[-3:] = np.nan

    with pytest.raises(ValueError, match="imports"):
        assemble(inputs, start="2023-07-01", end="2026-06-01")


# --- the spec's transformations, applied (Task 5A) -------------------------


def test_the_assembled_gdp_row_is_a_growth_rate_not_a_level():
    """The panel must reach the engine transformed.

    `Y` itself proves nothing here -- standardising a level gives z-scores that
    are just as small as standardising a growth rate, so a magnitude test on
    `Y` passes whether or not the transform ran. `y_location` and `y_scale` are
    computed from whatever `standardise` was handed, so they are what actually
    distinguishes the two: real GDP in millions of dollars centres near 600,000,
    an annualised quarterly growth rate near 2.

    That also pins the ORDER. Standardise first and difference after, and
    `y_location` would carry the level's mean.
    """
    frame = pd.read_csv(FIXTURES / "abs_gdp.csv", index_col=0)
    frame.index = pd.PeriodIndex(frame.index.astype(str), freq="Q-DEC")
    from nyfed.au.fetch_abs import parse_abs_frame

    gdp = parse_abs_frame(frame, "A2304402X")
    assert gdp.max() > 100_000, "the fixture is not a level; this test is void"

    inputs = _panel_inputs()
    inputs["gdp"] = gdp
    panel = assemble(inputs, start="2018-01-01", end="2026-03-01")
    i = panel.i_now

    assert abs(panel.y_location[i, 0]) < 100
    assert panel.y_scale[i, 0] < 100


def test_the_assembled_gdp_row_is_annualised_by_four_not_twelve():
    """Recover the transformed value from the standardised panel and check it
    against the quarter-on-quarter growth of the recorded level.

    Annualising by 12 would put the last cell near 3.7 instead of 1.1 -- still a
    number a reader would accept, which is why this is checked against the
    arithmetic rather than by eye."""
    from nyfed.au.fetch_abs import parse_abs_frame

    frame = pd.read_csv(FIXTURES / "abs_gdp.csv", index_col=0)
    frame.index = pd.PeriodIndex(frame.index.astype(str), freq="Q-DEC")
    gdp = parse_abs_frame(frame, "A2304402X")

    inputs = _panel_inputs()
    inputs["gdp"] = gdp
    panel = assemble(inputs, start="2018-01-01", end="2026-03-01")
    i = panel.i_now

    recovered = panel.Y[i] * panel.y_scale[i, 0] + panel.y_location[i, 0]
    last = gdp.loc[pd.Timestamp("2026-03-01")].item()
    previous = gdp.loc[pd.Timestamp("2025-12-01")].item()
    expected = 100.0 * ((last / previous) ** 4 - 1.0)

    assert recovered[-1] == pytest.approx(expected, abs=1e-9)
    assert expected != pytest.approx(100.0 * ((last / previous) ** 12 - 1.0))
