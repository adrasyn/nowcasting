"""The publish-time coherence check."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from check_payload import check_payload, quarter_key  # noqa: E402


def _ok(**over):
    d = {
        "status": "ok",
        "data_through": "2026-07",
        "prev_level": {"quarter": "2026 Q1", "value": 695945},
        "revision_adjustment": {"pp": 0.08},
        "horizons": [
            {"quarter": "2026 Q2", "kind": "nowcast", "months_with_data": 3},
            {"quarter": "2026 Q3", "kind": "forecast", "months_with_data": 1},
        ],
        "vintages": [{"run_date": "2026-08-31", "target_quarter": "2026 Q2",
                      "months_with_data": 3}],
    }
    d.update(over)
    # Every horizon carries a companion figure consistent with the default
    # revision_adjustment, whether it came from the base dict above or from a
    # caller's own `horizons=[...]` override, so that tests overriding
    # `horizons` for an unrelated reason don't also have to restate this.
    pp = (d.get("revision_adjustment") or {}).get("pp")
    if pp is not None:
        for h in d.get("horizons") or []:
            h.setdefault("qoq_growth_pct", 0.5)
            h.setdefault("expected_first_print_pct", h["qoq_growth_pct"] - pp)
    return d


def test_a_coherent_payload_passes():
    assert check_payload(_ok(), today="2026-09") == []


def test_a_refusal_passes_without_horizons():
    """A refusal is a successful run that declines to publish a number."""
    assert check_payload({"status": "refused", "refusal_reason": "stale input"}) == []


def test_a_target_that_did_not_roll_forward_fails():
    """The failure the check exists for.

    The ABS prints Q2 on the Wednesday. If Monday's run still names Q2 as the
    nowcast, the page headlines an estimate of a quarter already measured.
    """
    d = _ok(prev_level={"quarter": "2026 Q2", "value": 700000})
    bad = check_payload(d, today="2026-09")
    assert any("did not roll forward" in b for b in bad), bad


def test_the_same_payload_passes_once_the_target_rolls():
    d = _ok(
        prev_level={"quarter": "2026 Q2", "value": 700000},
        horizons=[
            {"quarter": "2026 Q3", "kind": "nowcast", "months_with_data": 2},
            {"quarter": "2026 Q4", "kind": "forecast", "months_with_data": 0},
        ],
        vintages=[{"run_date": "2026-09-07", "target_quarter": "2026 Q3",
                   "months_with_data": 2}],
    )
    assert check_payload(d, today="2026-09") == [], "the Monday-after shape"


def test_a_nowcast_with_no_data_of_its_own_fails():
    d = _ok(horizons=[{"quarter": "2026 Q2", "kind": "nowcast",
                       "months_with_data": 0}])
    assert any("months of data" in b for b in check_payload(d, today="2026-09"))


def test_a_zero_month_vintage_must_not_reach_the_chart():
    d = _ok(vintages=[{"run_date": "2026-06-01", "target_quarter": "2026 Q3",
                       "months_with_data": 0}])
    bad = check_payload(d, today="2026-09")
    assert any("should not have been recorded" in b for b in bad), bad


def test_data_through_cannot_be_in_the_future():
    """The bug that had the page claiming August data while August was empty."""
    d = _ok(data_through="2026-09")
    assert any("in the future" in b for b in check_payload(d, today="2026-08"))


def test_a_missing_nowcast_horizon_fails():
    d = _ok(horizons=[{"quarter": "2026 Q3", "kind": "forecast",
                       "months_with_data": 1}])
    assert any("nowcast" in b for b in check_payload(d, today="2026-09"))


def test_quarter_key_orders_across_a_year_boundary():
    assert quarter_key("2026 Q4") < quarter_key("2027 Q1")


def test_a_data_less_nowcast_is_reported_once_not_twice():
    """The runner records that row on purpose; this check must not fight it.

    `run_au_nowcast` exempts the nowcast from its zero-month skip — "a fault to
    surface, not a row to drop". The vintage rule used to reject any zero-month
    row, so the exempted one could never be surfaced: it just blocked the
    publish, complaining about a vintage instead of about the fault.
    """
    d = _ok(
        horizons=[{"quarter": "2026 Q2", "kind": "nowcast",
                   "months_with_data": 0}],
        vintages=[{"run_date": "2026-08-31", "target_quarter": "2026 Q2",
                   "months_with_data": 0}],
    )
    bad = check_payload(d, today="2026-09")
    assert len(bad) == 1, f"the fault should be named once, got: {bad}"
    assert "nowcast 2026 Q2 has 0 months of data" in bad[0]


def test_a_data_less_forecast_vintage_is_still_rejected():
    """Narrowing the rule to forecasts must not disarm it."""
    d = _ok(vintages=[
        {"run_date": "2026-08-31", "target_quarter": "2026 Q2",
         "months_with_data": 3},
        {"run_date": "2026-06-01", "target_quarter": "2026 Q3",
         "months_with_data": 0},
    ])
    bad = check_payload(d, today="2026-09")
    assert any("2026 Q3" in b and "should not have been recorded" in b
               for b in bad), bad


def test_an_expected_first_print_that_disagrees_with_the_adjustment_is_a_bug():
    d = _ok()
    d["horizons"][0]["expected_first_print_pct"] = d["horizons"][0]["qoq_growth_pct"] + 1.0
    assert any("expected_first_print_pct" in p for p in check_payload(d, today="2026-09-07"))


def test_an_implausible_adjustment_is_refused():
    d = _ok()
    d["revision_adjustment"]["pp"] = 0.9
    for h in d["horizons"]:
        h["expected_first_print_pct"] = h["qoq_growth_pct"] - 0.9
    assert any("revision_adjustment" in p for p in check_payload(d, today="2026-09-07"))


def test_a_payload_with_no_adjustment_is_still_coherent():
    d = _ok()
    d["revision_adjustment"] = None
    for h in d["horizons"]:
        h.pop("expected_first_print_pct", None)
    assert check_payload(d, today="2026-09-07") == []
