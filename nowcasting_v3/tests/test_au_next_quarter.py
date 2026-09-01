"""The second horizon: padding the panel, and recording a row per target.

The ABS prints a quarter about nine weeks after it ends, so for roughly two
months in three the page's only horizon was a quarter that had already closed.
These cover the two mechanisms that fixed it.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from nyfed.au.build import target_periods
from nyfed.au.panel import Panel

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from run_au_nowcast import (  # noqa: E402
    _record,
    months_with_data,
    pad_to_next_quarter,
)


def _panel(n_months: int, gdp_last: int) -> Panel:
    """A panel of `n_months` whose GDP row is observed up to column `gdp_last`.

    GDP is quarterly, so it sits on every third column ending at `gdp_last`,
    which is where `panel._align` puts a quarterly observation. The monthly
    rows run three months past it — through `gdp_last + 3`, the nowcast
    quarter's last month — which is the real shape: the monthly panel is
    complete for a quarter well before the ABS publishes GDP for it.
    """
    Y = np.full((3, n_months), np.nan)
    Y[0, : gdp_last + 4] = 1.0
    Y[1, : gdp_last + 4] = 1.0
    for j in range(gdp_last, -1, -3):
        Y[2, j] = 1.0
    return Panel(Y=Y, y_location=np.zeros((3, 1)), y_scale=np.ones((3, 1)),
                 dates=pd.date_range("1980-01-01", periods=n_months, freq="MS"),
                 series_id=["a", "b", "gdp"], i_now=2)


def test_without_padding_there_is_only_one_horizon():
    """The bug, stated as a test.

    This is the shipping shape on 2026-08-31: GDP observed through the quarter
    that ended two months earlier, a panel running to the as-of month, and
    `target_periods` therefore able to reach exactly one quarter.
    """
    p = _panel(n_months=10, gdp_last=4)
    assert len(target_periods(p)) == 1


def test_padding_buys_exactly_one_more_horizon():
    p = _panel(n_months=10, gdp_last=4)
    added = pad_to_next_quarter(p)
    assert added == 1
    t = target_periods(p)
    assert len(t) == 2
    # Three months apart, and the second is the quarter after the first.
    assert int(t[1]) - int(t[0]) == 3


def test_padding_adds_only_empty_months():
    """The added columns must be missing, not zero.

    A zero is an observation of no change and the filter would treat it as one.
    The whole claim of this feature is that the second horizon is a FORECAST --
    the model conditioning on nothing for months that have not happened.
    """
    p = _panel(n_months=10, gdp_last=4)
    before = p.Y.shape[1]
    pad_to_next_quarter(p)
    assert np.isnan(p.Y[:, before:]).all()


def test_padding_extends_the_dates_to_match():
    p = _panel(n_months=10, gdp_last=4)
    pad_to_next_quarter(p)
    assert len(p.dates) == p.Y.shape[1]
    # Consecutive months, no gap at the join.
    gaps = {(b.year - a.year) * 12 + b.month - a.month
            for a, b in zip(p.dates[:-1], p.dates[1:])}
    assert gaps == {1}


def test_padding_is_idempotent():
    """The weekly job runs on a panel that may already reach far enough.

    Late in a quarter the as-of date is already past the next quarter's aligned
    column, and padding again would push a third horizon onto the page.
    """
    p = _panel(n_months=10, gdp_last=4)
    assert pad_to_next_quarter(p) == 1
    assert pad_to_next_quarter(p) == 0
    assert len(target_periods(p)) == 2


def test_months_with_data_counts_the_quarter_not_the_panel():
    p = _panel(n_months=10, gdp_last=4)
    pad_to_next_quarter(p)
    t = target_periods(p)
    # The nowcast quarter's three months are all populated on the monthly rows;
    # the forecast quarter's are the padded, empty ones.
    assert months_with_data(p, int(t[0])) == 3
    assert months_with_data(p, int(t[1])) == 0


def test_record_keys_on_run_date_and_target_together(tmp_path, monkeypatch):
    """Two rows now share a run date, so the old key would drop one.

    `_record` used to de-duplicate on run date alone. With a nowcast and a
    forecast written from the same Monday, that made each evict the other and
    left whichever happened to be appended last.
    """
    import run_au_nowcast as mod

    hist = tmp_path / "history.json"
    monkeypatch.setattr(mod, "HISTORY", hist)

    rows = [
        {"run_date": "2026-08-31", "target_quarter": "2026 Q2",
         "kind": "nowcast", "qoq_growth_pct": 0.64},
        {"run_date": "2026-08-31", "target_quarter": "2026 Q3",
         "kind": "forecast", "qoq_growth_pct": 0.78},
    ]
    mine = _record(rows, ["2026 Q2", "2026 Q3"])
    assert len(mine) == 2
    assert {r["target_quarter"] for r in mine} == {"2026 Q2", "2026 Q3"}

    # Re-running the same Monday corrects both rows rather than duplicating.
    rows[0]["qoq_growth_pct"] = 0.70
    mine = _record(rows, ["2026 Q2", "2026 Q3"])
    assert len(mine) == 2
    q2 = next(r for r in mine if r["target_quarter"] == "2026 Q2")
    assert q2["qoq_growth_pct"] == 0.70


def test_record_leaves_other_quarters_alone(tmp_path, monkeypatch):
    """Last quarter's record is this model's live score for it. It is not
    rewritten by a run targeting a later quarter."""
    import json

    import run_au_nowcast as mod

    hist = tmp_path / "history.json"
    hist.write_text(json.dumps({"schema": "v3-history-1", "runs": [
        {"run_date": "2026-05-04", "target_quarter": "2026 Q1",
         "kind": "nowcast", "qoq_growth_pct": 0.31}]}))
    monkeypatch.setattr(mod, "HISTORY", hist)

    _record([{"run_date": "2026-08-31", "target_quarter": "2026 Q2",
              "kind": "nowcast", "qoq_growth_pct": 0.64}], ["2026 Q2"])
    runs = json.loads(hist.read_text())["runs"]
    assert len(runs) == 2
    old = next(r for r in runs if r["target_quarter"] == "2026 Q1")
    assert old["qoq_growth_pct"] == 0.31


def test_a_backfilled_row_never_replaces_a_live_one(tmp_path, monkeypatch):
    """`--backfill` walks Mondays the weekly job may already have run for real.

    A live row is what the model published that day, on the data it had. A
    replay reconstructs it from today's revisions and parameters — close, but a
    different object. On 2026-09-01 a backfill rewrote the 2026-08-31 live row
    (0.6354 -> 0.6362, provenance flag flipped), which is exactly the
    "fabricated a tidier version" failure the module warns about.
    """
    import json

    import run_au_nowcast as mod

    hist = tmp_path / "history.json"
    hist.write_text(json.dumps({"schema": "v3-history-1", "runs": [
        {"run_date": "2026-08-31", "target_quarter": "2026 Q2",
         "kind": "nowcast", "qoq_growth_pct": 0.6354}]}))
    monkeypatch.setattr(mod, "HISTORY", hist)

    _record([{"run_date": "2026-08-31", "target_quarter": "2026 Q2",
              "kind": "nowcast", "qoq_growth_pct": 0.6362,
              "backfilled": True}], ["2026 Q2"])
    runs = json.loads(hist.read_text())["runs"]
    assert len(runs) == 1
    assert runs[0]["qoq_growth_pct"] == 0.6354, "the live figure must survive"
    assert not runs[0].get("backfilled"), "and keep its provenance"


def test_a_backfilled_row_still_fills_a_gap(tmp_path, monkeypatch):
    """The protection is against OVERWRITING, not against backfilling at all."""
    import json

    import run_au_nowcast as mod

    hist = tmp_path / "history.json"
    hist.write_text(json.dumps({"schema": "v3-history-1", "runs": []}))
    monkeypatch.setattr(mod, "HISTORY", hist)

    _record([{"run_date": "2026-06-01", "target_quarter": "2026 Q2",
              "kind": "nowcast", "qoq_growth_pct": 0.63,
              "backfilled": True}], ["2026 Q2"])
    runs = json.loads(hist.read_text())["runs"]
    assert len(runs) == 1 and runs[0]["backfilled"] is True


def test_a_live_row_may_correct_an_earlier_live_row(tmp_path, monkeypatch):
    """Re-running a Monday for real still corrects that Monday.

    The guard keys on the INCOMING row being a backfill, not on the stored one
    being live, so an ordinary weekly re-run is unaffected.
    """
    import json

    import run_au_nowcast as mod

    hist = tmp_path / "history.json"
    hist.write_text(json.dumps({"schema": "v3-history-1", "runs": [
        {"run_date": "2026-08-31", "target_quarter": "2026 Q2",
         "kind": "nowcast", "qoq_growth_pct": 0.6354}]}))
    monkeypatch.setattr(mod, "HISTORY", hist)

    _record([{"run_date": "2026-08-31", "target_quarter": "2026 Q2",
              "kind": "nowcast", "qoq_growth_pct": 0.70}], ["2026 Q2"])
    runs = json.loads(hist.read_text())["runs"]
    assert runs[0]["qoq_growth_pct"] == 0.70


def test_the_track_record_scores_nowcast_rows_only():
    """A quarter is the next-quarter FORECAST before it is the nowcast.

    Those rows are live — published, never revised — but they are a different
    and harder claim: one month of the quarter's data rather than three.
    `emit_backtest_json` picks the last live row per quarter as the model's
    final word, so without this filter a quarter whose nowcast weeks all
    refused would be scored on a forecast and labelled a nowcast.

    Mirrors the selection in `tools/emit_backtest_json.py`.
    """
    rows = [
        {"run_date": "2026-08-10", "target_quarter": "2026 Q3",
         "kind": "forecast", "qoq_growth_pct": 0.76},
        {"run_date": "2026-09-07", "target_quarter": "2026 Q3",
         "kind": "nowcast", "qoq_growth_pct": 0.51},
        # Written before `kind` existed. Every such row is a nowcast.
        {"run_date": "2026-08-31", "target_quarter": "2026 Q2",
         "qoq_growth_pct": 0.6354},
    ]
    live: dict[str, dict] = {}
    for r in rows:
        if r.get("backfilled"):
            continue
        if r.get("kind") == "forecast":
            continue
        q = r["target_quarter"]
        if q not in live or r["run_date"] > live[q]["run_date"]:
            live[q] = r

    assert live["2026 Q3"]["qoq_growth_pct"] == 0.51, "the nowcast, not the forecast"
    assert live["2026 Q2"]["qoq_growth_pct"] == 0.6354, "a legacy row still counts"


def test_the_monday_after_a_print():
    """The quarter transition, in the exact shape 2026-09-07 will have.

    The ABS prints 2026 Q2 on the Wednesday; the weekly job runs the following
    Monday. GDP is then observed through Q2, the panel runs to September, and
    the two horizons become Q3 — which by then holds July and August — and Q4,
    which has not started. Q4 must come back with zero months so the recorder
    declines it and the page's next-quarter box hides itself rather than
    publishing the trend anchor as a forecast.
    """
    # 12 columns ending at September, GDP last observed at column 8 (June, the
    # aligned month for Q2). The monthly rows stop at August: on the Monday
    # after the print, September's indicators do not exist yet. September is a
    # column because `build_panel` runs the panel to the as-of date whether or
    # not anything has been published for it.
    n, gdp_last = 12, 8
    Y = np.full((3, n), np.nan)
    Y[0, : gdp_last + 3] = 1.0          # through August (column 10)
    Y[1, : gdp_last + 3] = 1.0
    for j in range(gdp_last, -1, -3):
        Y[2, j] = 1.0                    # GDP quarterly, last obs = Q2
    p = Panel(Y=Y, y_location=np.zeros((3, 1)), y_scale=np.ones((3, 1)),
              dates=pd.date_range("1980-01-01", periods=n, freq="MS"),
              series_id=["a", "b", "gdp"], i_now=2)

    assert len(target_periods(p)) == 1, "unpadded, only the nowcast is reachable"
    assert pad_to_next_quarter(p) == 3, "three empty months to reach Q4"

    t = target_periods(p)
    assert len(t) == 2
    # Q3 holds July and August; September's data has not been published yet.
    assert months_with_data(p, int(t[0])) == 2
    # Q4 has not started. This is the number the recorder and the page key on.
    assert months_with_data(p, int(t[1])) == 0
