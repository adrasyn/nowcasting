"""The equal-weight combination of v2 and v3.

Every function under test is pure: dicts in, dicts out. The tool
(`tools/emit_combination.py`) does the file reading and writing and nothing
else, so the rules that decide what gets published -- which v2 run pairs with
which v3 run, which band a horizon gets, when a live row supersedes a
backtested one -- are all exercised here on hand-built inputs small enough to
check by eye.
"""

import pytest

from nyfed.au.combination import (SCHEMA, latest_payload, make_is_current,
                                  pair_runs, quarter_shift, refusal_from_v3,
                                  track_record, v2_vintage_rows, with_bands)

# --------------------------------------------------------------------------- #
# Quarters and the current/next rule
# --------------------------------------------------------------------------- #


def test_quarter_shift_crosses_the_year():
    assert quarter_shift("2026 Q3", 1) == "2026 Q4"
    assert quarter_shift("2026 Q4", 1) == "2027 Q1"
    assert quarter_shift("2026 Q1", -1) == "2025 Q4"


def test_is_current_is_the_earliest_unprinted_quarter():
    """2026 Q2 prints 2026-09-02, so it is current up to and including the day
    before, and 2026 Q3 is current from the print onward."""
    is_current = make_is_current()
    assert is_current("2026-08-31", "2026 Q2")
    assert not is_current("2026-08-31", "2026 Q3")
    assert not is_current("2026-09-07", "2026 Q2")
    assert is_current("2026-09-07", "2026 Q3")


def test_is_current_on_the_release_day_itself():
    """The quarter prints in the morning, so on its release date the NEXT
    quarter is already the current one."""
    is_current = make_is_current()
    assert not make_is_current()("2026-09-02", "2026 Q2")
    assert is_current("2026-09-02", "2026 Q3")


# --------------------------------------------------------------------------- #
# Pairing
# --------------------------------------------------------------------------- #


def _v3(run_date, quarter, qoq, kind="nowcast", **kw):
    row = {"run_date": run_date, "target_quarter": quarter,
           "qoq_growth_pct": qoq, "data_through": "2026-08",
           "months_with_data": 2, **kw}
    if kind is not None:
        row["kind"] = kind
    return row


def _v2(run_date, quarter, qoq, **kw):
    return {"run_date": run_date, "target_quarter": quarter,
            "qoq_growth_pct": qoq, **kw}


def test_pairing_averages_the_two_models():
    rows = pair_runs([_v3("2026-09-07", "2026 Q3", 0.4603)],
                     [_v2("2026-09-07", "2026 Q3", 0.61)])
    assert len(rows) == 1
    assert rows[0]["qoq_growth_pct"] == pytest.approx(0.5352)
    assert rows[0]["v2_qoq_growth_pct"] == 0.61
    assert rows[0]["v3_qoq_growth_pct"] == 0.4603
    assert rows[0]["v2_run_date"] == "2026-09-07"
    assert rows[0]["kind"] == "nowcast"
    assert rows[0]["months_with_data"] == 2


def test_pairing_takes_the_latest_v2_run_at_or_before_the_monday():
    v2 = [_v2("2026-09-01", "2026 Q3", 0.2),
          _v2("2026-09-04", "2026 Q3", 0.6),
          _v2("2026-09-08", "2026 Q3", 9.9)]  # after the v3 run: not visible
    rows = pair_runs([_v3("2026-09-07", "2026 Q3", 0.4)], v2)
    assert rows[0]["v2_run_date"] == "2026-09-04"
    assert rows[0]["v2_qoq_growth_pct"] == 0.6
    assert rows[0]["qoq_growth_pct"] == pytest.approx(0.5)


def test_pairing_drops_a_v2_run_older_than_the_max_age():
    """v2 skips the occasional Monday, so a run up to a week old still counts;
    anything older is a different information set and is not averaged in."""
    v2 = [_v2("2026-08-30", "2026 Q3", 0.6)]
    assert pair_runs([_v3("2026-09-07", "2026 Q3", 0.4)], v2) == []
    kept = pair_runs([_v3("2026-09-06", "2026 Q3", 0.4)], v2)
    assert len(kept) == 1 and kept[0]["v2_run_date"] == "2026-08-30"


def test_pairing_matches_on_the_quarter_not_the_horizon():
    """A v3 forecast row pairs with v2's next-quarter vintage for the same
    quarter, and the combined row keeps v3's `kind`."""
    v3 = [_v3("2026-09-07", "2026 Q3", 0.46),
          _v3("2026-09-07", "2026 Q4", 0.48, kind="forecast",
              months_with_data=0)]
    v2 = [_v2("2026-09-07", "2026 Q3", 0.61, horizon="current"),
          _v2("2026-09-07", "2026 Q4", 0.30, horizon="next")]
    rows = pair_runs(v3, v2)
    assert [r["kind"] for r in rows] == ["nowcast", "forecast"]
    assert rows[1]["qoq_growth_pct"] == pytest.approx(0.39)


def test_a_v3_row_without_kind_is_a_nowcast():
    rows = pair_runs([_v3("2026-09-07", "2026 Q3", 0.4, kind=None)],
                     [_v2("2026-09-07", "2026 Q3", 0.6)])
    assert rows[0]["kind"] == "nowcast"


def test_a_v3_row_with_no_partner_is_dropped():
    rows = pair_runs([_v3("2026-09-07", "2026 Q3", 0.4),
                      _v3("2026-09-07", "2026 Q4", 0.5, kind="forecast")],
                     [_v2("2026-09-07", "2026 Q3", 0.6)])
    assert [r["target_quarter"] for r in rows] == ["2026 Q3"]


# --------------------------------------------------------------------------- #
# Bands
# --------------------------------------------------------------------------- #

_PARAMS = {"current": {"p68": 0.144, "p95": 0.351},
           "next": {"p68": 0.30, "p95": 0.70}}


def test_bands_come_from_the_horizon_the_run_date_implies():
    rows = with_bands(
        [{"run_date": "2026-09-07", "target_quarter": "2026 Q3",
          "qoq_growth_pct": 0.5},
         {"run_date": "2026-09-07", "target_quarter": "2026 Q4",
          "qoq_growth_pct": 0.4}],
        _PARAMS, is_current=make_is_current())
    cur, nxt = rows
    assert cur["horizon"] == "current"
    assert (cur["ci_68_low"], cur["ci_68_high"]) == (0.356, 0.644)
    assert (cur["ci_95_low"], cur["ci_95_high"]) == (0.149, 0.851)
    assert nxt["horizon"] == "next"
    assert (nxt["ci_68_low"], nxt["ci_68_high"]) == (0.1, 0.7)
    assert (nxt["ci_95_low"], nxt["ci_95_high"]) == (-0.3, 1.1)


def test_the_same_quarter_is_next_before_the_previous_print_and_current_after():
    is_current = make_is_current()
    rows = with_bands([{"run_date": "2026-08-31", "target_quarter": "2026 Q3",
                        "qoq_growth_pct": 0.5},
                       {"run_date": "2026-09-07", "target_quarter": "2026 Q3",
                        "qoq_growth_pct": 0.5}],
                      _PARAMS, is_current=is_current)
    assert [r["horizon"] for r in rows] == ["next", "current"]


def test_a_quarter_beyond_the_next_one_still_gets_the_next_band():
    rows = with_bands([{"run_date": "2026-09-07", "target_quarter": "2027 Q1",
                        "qoq_growth_pct": 0.5}],
                      _PARAMS, is_current=make_is_current())
    assert rows[0]["horizon"] == "next"


# --------------------------------------------------------------------------- #
# The v2 side of the pairing input
# --------------------------------------------------------------------------- #


def test_v2_vintage_rows_adds_the_headline_and_the_next_quarter_model():
    v2 = {"as_of": "2026-09-07",
          "vintages": [{"run_date": "2026-08-31", "target_quarter": "2026 Q2",
                        "qoq_growth_pct": 0.53}],
          "models": {"headline": {"target_quarter": "2026 Q3",
                                  "qoq_growth_pct": 0.61},
                     "next_quarter": {"target_quarter": "2026 Q4",
                                      "qoq_growth_pct": 0.3}}}
    rows = v2_vintage_rows(v2)
    assert {(r["run_date"], r["target_quarter"], r["qoq_growth_pct"])
            for r in rows} == {("2026-08-31", "2026 Q2", 0.53),
                               ("2026-09-07", "2026 Q3", 0.61),
                               ("2026-09-07", "2026 Q4", 0.3)}


def test_v2_vintage_rows_without_a_next_quarter_model():
    """`models.next_quarter` does not exist until v2 gains the horizon; its
    absence is normal, not a fault."""
    v2 = {"as_of": "2026-09-07", "vintages": [],
          "models": {"headline": {"target_quarter": "2026 Q3",
                                  "qoq_growth_pct": 0.61}}}
    assert len(v2_vintage_rows(v2)) == 1


def test_v2_vintage_rows_prefers_the_published_model_over_a_stored_vintage():
    """The headline and the vintage row for the same Monday are the same run;
    the model object is the authoritative copy."""
    v2 = {"as_of": "2026-09-07",
          "vintages": [{"run_date": "2026-09-07", "target_quarter": "2026 Q3",
                        "qoq_growth_pct": 0.60}],
          "models": {"headline": {"target_quarter": "2026 Q3",
                                  "qoq_growth_pct": 0.61}}}
    rows = v2_vintage_rows(v2)
    assert len(rows) == 1 and rows[0]["qoq_growth_pct"] == 0.61


def test_a_vintage_without_a_horizon_field_is_a_current_quarter_row():
    """The committed `latest_v2.json` has no `horizon` on its vintages."""
    v2 = {"as_of": "2026-09-07",
          "vintages": [{"run_date": "2026-08-31", "target_quarter": "2026 Q2",
                        "qoq_growth_pct": 0.53}],
          "models": {"headline": {"target_quarter": "2026 Q3",
                                  "qoq_growth_pct": 0.61}}}
    assert all(r["horizon"] == "current" for r in v2_vintage_rows(v2))


# --------------------------------------------------------------------------- #
# The published payload
# --------------------------------------------------------------------------- #

_GDP = [{"quarter": "2025 Q4", "value": 694551, "qoq_pct": 0.91},
        {"quarter": "2026 Q1", "value": 696539, "qoq_pct": 0.29},
        {"quarter": "2026 Q2", "value": 699461, "qoq_pct": 0.42}]

_V3_LATEST = {"schema": "v3-preview-3", "status": "ok", "as_of": "2026-09-10",
              "bias_correction": {"pp": 0.0631}, "panel": {"n_series": 14},
              "diagnostics": {"seed": 4}, "estimate": {"asof": "2026-09-10"}}

_V2_LATEST = {"schema": "v2-1", "as_of": "2026-09-07"}


def _paired(run_date="2026-09-07"):
    rows = pair_runs(
        [_v3(run_date, "2026 Q3", 0.4603),
         _v3(run_date, "2026 Q4", 0.4784, kind="forecast",
             months_with_data=0)],
        [_v2(run_date, "2026 Q3", 0.61), _v2(run_date, "2026 Q4", 0.30)])
    return with_bands(rows, _PARAMS, is_current=make_is_current())


def test_latest_payload_publishes_both_horizons():
    p = latest_payload(_paired(), v3_latest=_V3_LATEST, v2_latest=_V2_LATEST,
                       gdp_series=_GDP, params=_PARAMS,
                       generated_at="2026-09-12T00:00:00+00:00")
    assert p["schema"] == SCHEMA
    assert (p["status"], p["basis"], p["target"]) == ("ok", "abs_first_print",
                                                      "first_print")
    assert p["as_of"] == "2026-09-07"
    assert p["target_quarter"] == "2026 Q3"
    assert [(h["quarter"], h["kind"]) for h in p["horizons"]] == [
        ("2026 Q3", "nowcast"), ("2026 Q4", "forecast")]
    now = p["horizons"][0]
    assert now["qoq_growth_pct"] == pytest.approx(0.5352)
    assert now["components"] == {"v2": 0.61, "v3": 0.4603}
    assert now["release_date"] == "2026-12-02"
    assert now["gdp_chain_volume_millions"] == round(699461 * 1.005352)
    assert p["prev_level"] == {"value": 699461, "quarter": "2026 Q2"}
    assert p["next_gdp_release_date"] == "2026-12-02"
    assert p["bias_correction"] == _V3_LATEST["bias_correction"]
    assert p["components"]["v2"]["run_date"] == "2026-09-07"
    assert p["components"]["v3"]["as_of"] == "2026-09-10"
    assert "stale_days" not in p["components"]["v2"]
    assert len(p["vintages"]) == 2


def test_the_next_horizon_is_omitted_when_only_v3_forecasts_it():
    """Until v2 publishes a next-quarter figure there is no average to take,
    and v3's own forecast is not a combination."""
    rows = with_bands(
        pair_runs([_v3("2026-09-07", "2026 Q3", 0.4603),
                   _v3("2026-09-07", "2026 Q4", 0.4784, kind="forecast")],
                  [_v2("2026-09-07", "2026 Q3", 0.61)]),
        _PARAMS, is_current=make_is_current())
    p = latest_payload(rows, v3_latest=_V3_LATEST, v2_latest=_V2_LATEST,
                       gdp_series=_GDP, params=_PARAMS,
                       generated_at="2026-09-12T00:00:00+00:00")
    assert [h["quarter"] for h in p["horizons"]] == ["2026 Q3"]


def test_a_stale_v2_carries_the_last_paired_monday_forward():
    p = latest_payload(_paired("2026-09-07"), v3_latest={**_V3_LATEST,
                                                        "as_of": "2026-09-28"},
                       v2_latest=_V2_LATEST, gdp_series=_GDP, params=_PARAMS,
                       generated_at="2026-09-28T00:00:00+00:00")
    assert p["as_of"] == "2026-09-07"
    assert p["components"]["v2"]["stale_days"] == 21
    assert p["target_quarter"] == "2026 Q3"


def test_no_paired_monday_for_the_current_quarter_is_a_refusal():
    old = with_bands(pair_runs([_v3("2026-08-31", "2026 Q2", 0.5)],
                               [_v2("2026-08-31", "2026 Q2", 0.5)]),
                     _PARAMS, is_current=make_is_current())
    with pytest.raises(ValueError, match="no v2 figure for the current quarter"):
        latest_payload(old, v3_latest=_V3_LATEST, v2_latest=_V2_LATEST,
                       gdp_series=_GDP, params=_PARAMS,
                       generated_at="2026-09-12T00:00:00+00:00")


def test_the_provisional_next_band_is_declared_in_the_ci_basis():
    params = {**_PARAMS, "provisional_next": True}
    p = latest_payload(_paired(), v3_latest=_V3_LATEST, v2_latest=_V2_LATEST,
                       gdp_series=_GDP, params=params,
                       generated_at="2026-09-12T00:00:00+00:00")
    assert "provisional" in p["ci_basis"]
    assert p["band_pp"]["provisional_next"] is True


def test_a_v3_refusal_is_passed_through():
    v3 = {"schema": "v3-preview-3", "status": "refused", "as_of": "2026-09-10",
          "refusal_reason": "stale feed",
          "refusal_detail": "labour_force last updated 2026-06"}
    p = refusal_from_v3(v3, generated_at="2026-09-12T00:00:00+00:00")
    assert p["status"] == "refused"
    assert p["schema"] == SCHEMA
    assert p["refusal_reason"] == "stale feed"
    assert p["refusal_detail"] == "labour_force last updated 2026-06"
    assert p["horizons"] == []
    assert "qoq_growth_pct" not in str(p)


# --------------------------------------------------------------------------- #
# The track record
# --------------------------------------------------------------------------- #

_BT = [
    # 2026 Q1: two weekly vintages, the second is the last before the print.
    {"as_of": "2026-05-25", "target": "2026Q1", "first": 0.30,
     "release": "2026-06-03", "v2": 0.50, "v3": 0.40, "combo": 0.45},
    {"as_of": "2026-06-01", "target": "2026Q1", "first": 0.30,
     "release": "2026-06-03", "v2": 0.60, "v3": 0.40, "combo": 0.50},
    # ... and one after it, which no reader saw before the release.
    {"as_of": "2026-06-08", "target": "2026Q1", "first": 0.30,
     "release": "2026-06-03", "v2": 9.9, "v3": 9.9, "combo": 9.9},
    {"as_of": "2026-08-31", "target": "2026Q2", "first": 0.42,
     "release": "2026-09-02", "v2": 0.53, "v3": 0.55, "combo": 0.54},
]
_FIRST = {"2026 Q1": 0.30, "2026 Q2": 0.42}
_SOMP = {"2026 Q2": {"yoy_forecast_pct": 2.0, "somp_release": "2026-08"}}
_GDP_TR = [{"quarter": "2025 Q1", "value": 680000, "qoq_pct": 0.4},
           {"quarter": "2025 Q2", "value": 684000, "qoq_pct": 0.59},
           {"quarter": "2025 Q3", "value": 688000, "qoq_pct": 0.58},
           {"quarter": "2025 Q4", "value": 694551, "qoq_pct": 0.91},
           {"quarter": "2026 Q1", "value": 696539, "qoq_pct": 0.29},
           {"quarter": "2026 Q2", "value": 699461, "qoq_pct": 0.42}]


def test_track_record_scores_the_last_vintage_before_the_print():
    perf = track_record(_BT, [], _GDP_TR, _FIRST, _SOMP)
    q1 = next(e for e in perf["errors"] if e["target_quarter"] == "2026 Q1")
    assert q1["qoq_nowcast_pct"] == 0.5      # the 2026-06-01 row, not 2026-06-08
    assert q1["qoq_actual_pct"] == 0.3
    assert q1["qoq_error_pp"] == 0.2
    assert q1["final_run_date"] == "2026-06-01"
    assert q1["is_live"] is False
    assert q1["model"] == "combination"
    assert perf["n"] == 2
    assert perf["basis"] == "abs_first_print"


def test_a_live_row_supersedes_the_backtest_row():
    history = [
        {"run_date": "2026-05-25", "target_quarter": "2026 Q1",
         "kind": "nowcast", "qoq_growth_pct": 0.2, "v2_qoq_growth_pct": 0.1,
         "v3_qoq_growth_pct": 0.3},
        {"run_date": "2026-06-01", "target_quarter": "2026 Q1",
         "kind": "nowcast", "qoq_growth_pct": 0.35, "v2_qoq_growth_pct": 0.3,
         "v3_qoq_growth_pct": 0.4},
        # After the print: never on the site before the release.
        {"run_date": "2026-06-08", "target_quarter": "2026 Q1",
         "kind": "nowcast", "qoq_growth_pct": 9.9, "v2_qoq_growth_pct": 9.9,
         "v3_qoq_growth_pct": 9.9},
    ]
    perf = track_record(_BT, history, _GDP_TR, _FIRST, _SOMP)
    q1 = next(e for e in perf["errors"] if e["target_quarter"] == "2026 Q1")
    assert q1["is_live"] is True
    assert q1["live_run_date"] == "2026-06-01"
    assert q1["qoq_nowcast_pct"] == 0.35
    assert q1["v2_qoq_nowcast_pct"] == 0.3
    # The quarter with no live history keeps its backtested row.
    q2 = next(e for e in perf["errors"] if e["target_quarter"] == "2026 Q2")
    assert q2["is_live"] is False


def test_a_forecast_row_is_never_the_live_track_record_figure():
    """A forecast was made before the quarter began; scoring it as the final
    nowcast would score a different and much harder call."""
    history = [{"run_date": "2026-06-01", "target_quarter": "2026 Q1",
                "kind": "forecast", "qoq_growth_pct": 9.9,
                "v2_qoq_growth_pct": 9.9, "v3_qoq_growth_pct": 9.9}]
    perf = track_record(_BT, history, _GDP_TR, _FIRST, _SOMP)
    q1 = next(e for e in perf["errors"] if e["target_quarter"] == "2026 Q1")
    assert q1["is_live"] is False
    assert q1["qoq_nowcast_pct"] == 0.5


def test_track_record_levels_and_the_rba_comparison():
    perf = track_record(_BT, [], _GDP_TR, _FIRST, _SOMP)
    q2 = next(e for e in perf["errors"] if e["target_quarter"] == "2026 Q2")
    prev = 696539
    assert q2["final_nowcast"] == round(prev * 1.0054)
    assert q2["actual"] == round(prev * 1.0042)
    # Year-ended on the hybrid basis: three quarters of the latest vintage
    # chained to this quarter's first print.
    assert q2["yoy_actual"] == pytest.approx(
        round(100 * (prev * 1.0042 / 684000 - 1), 2))
    assert q2["yoy_rba"] == 2.0
    assert perf["rba_comparison"]["n"] == 1
    assert perf["mae_pct"] == 0.16
    assert perf["v2_mae_pct"] == 0.21
    assert perf["v3_mae_pct"] == 0.12


def test_the_quarter_in_flight_is_not_scored():
    """The current quarter has combination rows every week and no initial
    estimate until the ABS prints it. It joins the table then, not before."""
    history = [{"run_date": "2026-09-07", "target_quarter": "2026 Q3",
                "kind": "nowcast", "qoq_growth_pct": 0.54,
                "v2_qoq_growth_pct": 0.61, "v3_qoq_growth_pct": 0.46}]
    perf = track_record(_BT, history, _GDP_TR, _FIRST, _SOMP)
    assert [e["target_quarter"] for e in perf["errors"]] == ["2026 Q1", "2026 Q2"]


def test_track_record_needs_a_first_print_for_every_scored_quarter():
    with pytest.raises(ValueError, match="no ABS initial estimate"):
        track_record(_BT, [], _GDP_TR, {"2026 Q1": 0.30}, _SOMP)
