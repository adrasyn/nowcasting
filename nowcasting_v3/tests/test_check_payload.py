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
        "basis": "abs_first_print",
        "target": "first_print",
        "bias_correction": {"pp": 0.0631},
        "horizons": [
            {"quarter": "2026 Q2", "kind": "nowcast", "months_with_data": 3},
            {"quarter": "2026 Q3", "kind": "forecast", "months_with_data": 1},
        ],
        "vintages": [{"run_date": "2026-08-31", "target_quarter": "2026 Q2",
                      "months_with_data": 3}],
    }
    d.update(over)
    # Every horizon carries the model's own figure and the published one it
    # implies -- the model less the correction -- whether the horizon came from
    # the base dict above or from a caller's own `horizons=[...]` override, so
    # that tests overriding `horizons` for an unrelated reason don't also have
    # to restate the basis.
    pp = (d.get("bias_correction") or {}).get("pp")
    for h in d.get("horizons") or []:
        h.setdefault("model_qoq_growth_pct", 0.5)
        if pp is not None:
            h.setdefault("qoq_growth_pct", h["model_qoq_growth_pct"] - pp)
        else:
            h.setdefault("qoq_growth_pct", h["model_qoq_growth_pct"])
    return d


def _combo(**over):
    """The combination payload's shape: schema `combo-*`, components everywhere.

    Deliberately built so `qoq_growth_pct` is NOT
    `model_qoq_growth_pct - bias_correction.pp`. The combination copies v3's
    correction across as provenance for its v3 half and averages two already
    corrected figures, so the v3 identity does not hold on it; a fixture that
    happened to satisfy it would let a regression in the gating go unnoticed.
    """
    d = {
        "schema": "combo-1",
        "status": "ok",
        "method": "equal-weight average of v2 and v3",
        "data_through": "2026-08",
        "prev_level": {"quarter": "2026 Q2", "value": 699461},
        "basis": "abs_first_print",
        "target": "first_print",
        "bias_correction": {"pp": 0.0631},
        "horizons": [
            {"quarter": "2026 Q3", "kind": "nowcast", "months_with_data": 2,
             "qoq_growth_pct": 0.5352, "model_qoq_growth_pct": 0.5352,
             "components": {"v2": 0.61, "v3": 0.4603},
             "ci_68_low": 0.3913, "ci_68_high": 0.6791,
             "ci_95_low": 0.1839, "ci_95_high": 0.8865},
        ],
        "vintages": [
            {"run_date": "2026-09-07", "target_quarter": "2026 Q3",
             "kind": "nowcast", "months_with_data": 2,
             "qoq_growth_pct": 0.5352,
             "v2_qoq_growth_pct": 0.61, "v3_qoq_growth_pct": 0.4603,
             "ci_68_low": 0.3913, "ci_68_high": 0.6791,
             "ci_95_low": 0.1839, "ci_95_high": 0.8865},
        ],
    }
    d.update(over)
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


def test_a_nowcast_that_is_not_the_model_less_the_correction_is_a_bug():
    d = _ok()
    d["horizons"][0]["qoq_growth_pct"] = d["horizons"][0]["model_qoq_growth_pct"] + 1.0
    assert any("model_qoq_growth_pct" in p for p in check_payload(d, today="2026-09-07"))


def test_an_ok_payload_without_a_correction_is_incoherent():
    d = _ok()
    d["bias_correction"] = None
    assert any("bias_correction" in p for p in check_payload(d, today="2026-09-07"))


def test_an_implausible_correction_is_refused():
    """The rolling miss is a mean of eight quarterly errors near +0.06pp. One
    outside +-0.6 is a broken estimate, not a finding."""
    d = _ok()
    d["bias_correction"]["pp"] = 0.9
    for h in d["horizons"]:
        h["qoq_growth_pct"] = h["model_qoq_growth_pct"] - 0.9
    assert any("bias_correction" in p for p in check_payload(d, today="2026-09-07"))


def test_a_correction_that_is_not_a_number_is_refused():
    """`True` is an `int` in Python, and `pp: true` would otherwise pass the
    range test and then shift every figure by one whole point."""
    d = _ok()
    d["bias_correction"]["pp"] = True
    assert any("bias_correction" in p for p in check_payload(d, today="2026-09-07"))


def test_a_leftover_expected_first_print_field_is_a_bug():
    d = _ok()
    d["horizons"][0]["expected_first_print_pct"] = 0.5
    assert any("expected_first_print_pct" in p for p in check_payload(d, today="2026-09-07"))


def test_a_leftover_revision_adjustment_is_a_bug():
    """The retired design. A payload carrying both keys has been through half a
    migration, and there is no telling which of the two made its figures."""
    d = _ok()
    d["revision_adjustment"] = {"pp": 0.1}
    assert any("revision_adjustment" in p for p in check_payload(d, today="2026-09-07"))


def test_a_payload_that_does_not_name_its_basis_is_incoherent():
    """The arithmetic can be right and the label still missing."""
    d = _ok()
    del d["basis"]
    assert any("basis" in p for p in check_payload(d, today="2026-09-07"))


def test_a_payload_that_does_not_name_its_target_is_incoherent():
    """`target` says the MODEL was fitted on first-print GDP.

    A model fitted on the revised vintage, less a rolling miss measured against
    first prints, is a different and unvalidated quantity. The runner refuses
    that combination; this is the last place it could still reach the site.
    """
    d = _ok()
    d["target"] = "latest"
    assert any("target" in p for p in check_payload(d, today="2026-09-07"))
    del d["target"]
    assert any("target" in p for p in check_payload(d, today="2026-09-07"))


# ---- the combination payload (2026-09-12) ----------------------------------
# `data/latest_combo.json` is written in the same schema, so it goes through the
# same invariants. Two of them differ: the v3 identity check cannot hold on an
# average of two corrected figures, and the average has two extra facts to
# assert -- that it really is the mean of its components, and that it sits
# inside its own band.


def test_a_combination_payload_passes():
    assert check_payload(_combo(), today="2026-09") == []


def test_the_v3_identity_check_does_not_run_on_the_combination():
    """The regression this gating exists for.

    On the real payload `model_qoq_growth_pct == qoq_growth_pct` while
    `bias_correction.pp` is v3's 0.063, so the v3 identity fails by exactly the
    correction. Ungated, the check would reject every combination payload ever
    published.
    """
    d = _combo()
    assert d["horizons"][0]["qoq_growth_pct"] == d["horizons"][0]["model_qoq_growth_pct"]
    assert d["bias_correction"]["pp"] != 0
    assert not any("model_qoq_growth_pct" in p
                   for p in check_payload(d, today="2026-09")), "gating is dead"


def test_a_combination_horizon_that_is_not_the_mean_of_its_components_fails():
    d = _combo()
    d["horizons"][0]["qoq_growth_pct"] = 0.61  # v2's figure, not the average
    bad = check_payload(d, today="2026-09")
    assert any("mean of its components" in b and "2026 Q3" in b for b in bad), bad


def test_a_combination_vintage_that_is_not_the_mean_of_its_components_fails():
    d = _combo()
    d["vintages"][0]["v3_qoq_growth_pct"] = 0.20
    bad = check_payload(d, today="2026-09")
    assert any("mean of its components" in b and "2026-09-07" in b for b in bad), bad


def test_a_combination_horizon_with_no_components_fails():
    """An average with nothing to average is not an average."""
    d = _combo()
    del d["horizons"][0]["components"]
    bad = check_payload(d, today="2026-09")
    assert any("components" in b for b in bad), bad


def test_a_combination_point_outside_its_own_68_band_fails():
    d = _combo()
    d["horizons"][0]["ci_68_low"] = 0.60
    d["horizons"][0]["ci_68_high"] = 0.70
    bad = check_payload(d, today="2026-09")
    assert any("68% band" in b for b in bad), bad


def test_a_combination_vintage_outside_its_own_68_band_fails():
    d = _combo()
    d["vintages"][0]["ci_68_high"] = 0.40
    bad = check_payload(d, today="2026-09")
    assert any("68% band" in b for b in bad), bad


def test_the_combination_invariants_do_not_run_on_a_v3_payload():
    """v3's horizons carry no `components`, and must not be asked for one."""
    assert check_payload(_ok(), today="2026-09") == []


def test_a_combination_refusal_passes_without_horizons():
    assert check_payload({"schema": "combo-1", "status": "refused",
                          "refusal_reason": "no v2 figure"}) == []
