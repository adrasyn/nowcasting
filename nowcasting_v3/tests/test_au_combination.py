"""The equal-weight combination of v2 and v3.

Every function under test is pure: dicts in, dicts out. The tool
(`tools/emit_combination.py`) does the file reading and writing and nothing
else, so the rules that decide what gets published -- which v2 run pairs with
which v3 run, which band a horizon gets, when a live row supersedes a
backtested one -- are all exercised here on hand-built inputs small enough to
check by eye.
"""

import pytest

from nyfed.au.combination import (SAME_SERIES, SCHEMA, fill_next_release,
                                  latest_payload, make_is_current,
                                  mark_updated, merge_indicators, pair_runs,
                                  quarter_shift, refusal_from_v3, track_record,
                                  v2_vintage_rows, with_bands)

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


def test_pairing_matches_the_horizon_as_well_as_the_quarter():
    """A v3 forecast row pairs with v2's next-quarter vintage for the same
    quarter, and the combined row keeps v3's `kind` and records its horizon."""
    v3 = [_v3("2026-09-07", "2026 Q3", 0.46),
          _v3("2026-09-07", "2026 Q4", 0.48, kind="forecast",
              months_with_data=0)]
    v2 = [_v2("2026-09-07", "2026 Q3", 0.61, horizon="current"),
          _v2("2026-09-07", "2026 Q4", 0.30, horizon="next")]
    rows = pair_runs(v3, v2)
    assert [r["kind"] for r in rows] == ["nowcast", "forecast"]
    assert [r["horizon"] for r in rows] == ["current", "next"]
    assert rows[1]["qoq_growth_pct"] == pytest.approx(0.39)


def test_a_v2_next_row_does_not_pair_with_a_quarter_that_is_now_current():
    """THE ROW OUTLIVES ITS HORIZON. v2 writes a next-quarter row for 2026 Q3
    every Monday before 2026 Q2 prints. On 2026-09-07 Q2 has printed and Q3 is
    the CURRENT quarter, so v3's Q3 figure is a two-month nowcast; averaging it
    with a figure v2 made when Q3 had barely begun would put two different
    information sets under one date. Only a v2 row made at the same horizon
    pairs -- here there is none, so nothing is published for the Monday."""
    stale_next = [_v2("2026-09-07", "2026 Q3", 0.78, horizon="next")]
    assert pair_runs([_v3("2026-09-07", "2026 Q3", 0.46)], stale_next) == []
    both = stale_next + [_v2("2026-09-07", "2026 Q3", 0.61, horizon="current")]
    rows = pair_runs([_v3("2026-09-07", "2026 Q3", 0.46)], both)
    assert len(rows) == 1 and rows[0]["v2_qoq_growth_pct"] == 0.61


def test_the_horizon_of_a_paired_row_is_the_one_it_had_on_its_own_day():
    """2026 Q3 is 'next' on the Mondays before 2026 Q2 prints and 'current'
    after, whatever `kind` the v3 row carries: a backfilled v3 row is written
    with today's horizon index, so `kind` says 'nowcast' on rows made when the
    quarter was still the next one."""
    v2 = [_v2("2026-08-24", "2026 Q3", 0.56, horizon="next"),
          _v2("2026-09-07", "2026 Q3", 0.61, horizon="current")]
    rows = pair_runs([_v3("2026-08-24", "2026 Q3", 0.40),
                      _v3("2026-09-07", "2026 Q3", 0.46)], v2)
    assert [r["horizon"] for r in rows] == ["next", "current"]


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

_V3_FORECAST = {"quarter": "2026 Q4", "kind": "forecast",
                "qoq_growth_pct": 0.4784, "annualised_growth_pct": 1.9268,
                "months_with_data": 0, "release_date": "2027-03-03",
                "ci_68_low": 0.0348, "ci_68_high": 0.8807,
                "ci_95_low": -0.3691, "ci_95_high": 1.3323}

_V3_LATEST = {"schema": "v3-preview-3", "status": "ok", "as_of": "2026-09-10",
              "target_quarter": "2026 Q3",
              "bias_correction": {"pp": 0.0631}, "panel": {"n_series": 14},
              "diagnostics": {"seed": 4}, "estimate": {"asof": "2026-09-10"},
              "horizons": [{"quarter": "2026 Q3", "kind": "nowcast",
                            "qoq_growth_pct": 0.4603}, _V3_FORECAST]}

_V2_LATEST = {"schema": "v2-1", "as_of": "2026-09-07"}


def _paired(run_date="2026-09-07"):
    rows = pair_runs(
        [_v3(run_date, "2026 Q3", 0.4603),
         _v3(run_date, "2026 Q4", 0.4784, kind="forecast",
             months_with_data=0)],
        [_v2(run_date, "2026 Q3", 0.61),
         _v2(run_date, "2026 Q4", 0.30, horizon="next")])
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
    # v3's run here is three days after v2's, which the payload says outright.
    assert p["components"]["v2"]["stale_days"] == 3
    assert len(p["vintages"]) == 2


def _unpaired_next():
    """The ordinary state: v3 forecasts the next quarter, v2 has no figure for
    it, so nothing pairs and only the current quarter is averaged."""
    return with_bands(
        pair_runs([_v3("2026-09-07", "2026 Q3", 0.4603)],
                  [_v2("2026-09-07", "2026 Q3", 0.61)]),
        _PARAMS, is_current=make_is_current())


def test_the_next_horizon_is_copied_from_v3_when_v2_has_no_figure():
    """THE PAGE KEEPS ITS NEXT-QUARTER CARD. v3's payload always carries a
    forecast horizon, and the homepage reads it for the waiting card and the
    evolution chart's toggle. Dropping the horizon because there was no v2 half
    to average would make both vanish for the two months in three when the next
    quarter has no data, which is the disappearance commit 7e4bed7 removed."""
    p = latest_payload(_unpaired_next(), v3_latest=_V3_LATEST,
                       v2_latest=_V2_LATEST, gdp_series=_GDP, params=_PARAMS,
                       generated_at="2026-09-12T00:00:00+00:00")
    assert [(h["quarter"], h["kind"]) for h in p["horizons"]] == [
        ("2026 Q3", "nowcast"), ("2026 Q4", "forecast")]
    fc = p["horizons"][1]
    assert fc["qoq_growth_pct"] == 0.4784
    assert fc["components"] == {"v2": None, "v3": 0.4784}
    assert fc["months_with_data"] == 0
    assert fc["v3_months_with_data"] == 0
    assert fc["release_date"] == "2027-03-03"
    assert (fc["ci_68_low"], fc["ci_68_high"]) == (0.0348, 0.8807)
    assert fc["source"] == "v3 only; no v2 figure for this quarter yet"
    # No vintage row: an unpaired figure is v3's, and the evolution chart draws
    # combinations.
    assert all(v["target_quarter"] == "2026 Q3" for v in p["vintages"])


def test_a_copied_forecast_with_data_still_shows_as_waiting():
    """v3 gains the next quarter's first month a week or two before v2 does.
    The copy's own month count is zeroed so the card keeps waiting rather than
    printing a v3-only figure under the combination's name; the true count
    travels as `v3_months_with_data` so nothing is lost."""
    v3 = {**_V3_LATEST,
          "horizons": [_V3_LATEST["horizons"][0],
                       {**_V3_FORECAST, "months_with_data": 1}]}
    p = latest_payload(_unpaired_next(), v3_latest=v3, v2_latest=_V2_LATEST,
                       gdp_series=_GDP, params=_PARAMS,
                       generated_at="2026-09-12T00:00:00+00:00")
    fc = p["horizons"][1]
    assert fc["months_with_data"] == 0
    assert fc["v3_months_with_data"] == 1


def test_no_forecast_is_copied_when_v3_forecasts_a_different_quarter():
    """A preview replays an old Monday against today's v3 payload, whose
    forecast is for a later quarter than that Monday's next one. Copying it
    would label one quarter's figure with another's."""
    v3 = {**_V3_LATEST, "target_quarter": "2026 Q2",
          "horizons": [_V3_LATEST["horizons"][0], _V3_FORECAST]}
    rows = with_bands(pair_runs([_v3("2026-08-31", "2026 Q2", 0.5)],
                                [_v2("2026-08-31", "2026 Q2", 0.5)]),
                      _PARAMS, is_current=make_is_current())
    p = latest_payload(rows, v3_latest=v3, v2_latest=_V2_LATEST,
                       gdp_series=_GDP, params=_PARAMS,
                       generated_at="2026-09-01T00:00:00+00:00")
    assert [h["quarter"] for h in p["horizons"]] == ["2026 Q2"]


def test_the_current_quarter_is_v3s_own_target():
    """v3's target comes from the data the ABS has actually released, which is
    the fact the calendar rule only approximates. When the two disagree -- a
    release moved, or a print landed early -- the payload follows v3."""
    v3 = {**_V3_LATEST, "as_of": "2026-09-01", "target_quarter": "2026 Q3",
          "horizons": [_V3_LATEST["horizons"][0], _V3_FORECAST]}
    # The calendar says 2026 Q2 is still current on 2026-09-01 (it prints on
    # the 2nd); v3 has already rolled forward.
    assert make_is_current()("2026-09-01", "2026 Q2")
    p = latest_payload(_paired(), v3_latest=v3, v2_latest=_V2_LATEST,
                       gdp_series=_GDP, params=_PARAMS,
                       generated_at="2026-09-01T00:00:00+00:00")
    assert p["target_quarter"] == "2026 Q3"
    assert [h["quarter"] for h in p["horizons"]] == ["2026 Q3", "2026 Q4"]


def test_a_stale_v2_carries_the_last_paired_monday_forward():
    p = latest_payload(_paired("2026-09-07"), v3_latest={**_V3_LATEST,
                                                        "as_of": "2026-09-28"},
                       v2_latest=_V2_LATEST, gdp_series=_GDP, params=_PARAMS,
                       generated_at="2026-09-28T00:00:00+00:00")
    assert p["as_of"] == "2026-09-07"
    assert p["components"]["v2"]["stale_days"] == 21
    assert p["target_quarter"] == "2026 Q3"


def test_stale_days_records_any_gap_not_only_a_carried_run():
    """v2 runs at 02:00 on the Monday and v3 at 03:30, so a normal week pairs
    two runs of the same date and the field is absent. ANY earlier v2 run is
    recorded, not only one past the seven-day pairing cutoff: the published
    figure then averages two different days, and 'stale' is the only word the
    payload has for that. The cutoff decides what may be paired at all; this
    field only reports what was."""
    v3_latest = {**_V3_LATEST, "as_of": "2026-09-07"}
    same_day = with_bands(pair_runs([_v3("2026-09-07", "2026 Q3", 0.4603)],
                                    [_v2("2026-09-07", "2026 Q3", 0.61)]),
                          _PARAMS, is_current=make_is_current())
    p = latest_payload(same_day, v3_latest=v3_latest, v2_latest=_V2_LATEST,
                       gdp_series=_GDP, params=_PARAMS,
                       generated_at="2026-09-12T00:00:00+00:00")
    assert "stale_days" not in p["components"]["v2"]

    earlier = with_bands(pair_runs([_v3("2026-09-07", "2026 Q3", 0.4603)],
                                   [_v2("2026-09-04", "2026 Q3", 0.61)]),
                         _PARAMS, is_current=make_is_current())
    p = latest_payload(earlier, v3_latest=v3_latest, v2_latest=_V2_LATEST,
                       gdp_series=_GDP, params=_PARAMS,
                       generated_at="2026-09-12T00:00:00+00:00")
    assert p["components"]["v2"]["run_date"] == "2026-09-04"
    assert p["components"]["v2"]["stale_days"] == 3


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


def test_a_next_horizon_row_is_never_the_live_track_record_figure():
    """A next-horizon row was made before the previous quarter printed;
    scoring it as the final nowcast would score a different and much harder
    call. The row's HORIZON decides that, not its `kind`: v3 writes `kind` from
    the horizon index of the run that produced it, so a backfilled row carries
    today's index rather than the one it had on its own Monday."""
    history = [{"run_date": "2026-06-01", "target_quarter": "2026 Q1",
                "kind": "nowcast", "horizon": "next", "qoq_growth_pct": 9.9,
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


def test_months_with_data_derived_from_data_through_for_old_rows():
    from nyfed.au.combination import _months_with_data
    assert _months_with_data({"months_with_data": 1, "data_through": "2026-05"}, "2026 Q2") == 1
    assert _months_with_data({"data_through": "2026-05"}, "2026 Q2") == 2
    assert _months_with_data({"data_through": "2026-03"}, "2026 Q2") == 0
    assert _months_with_data({"data_through": "2026-08"}, "2026 Q2") == 3
    assert _months_with_data({}, "2026 Q2") is None


# --------------------------------------------------------------------------- #
# The indicator panel the homepage shows
# --------------------------------------------------------------------------- #
#
# The homepage publishes a combination of two models, so its indicator panel
# has to be the union of the two models' inputs: showing v3's fourteen series
# under a figure half of which came from v2 tells the reader the wrong thing
# about what fed it. The union is built here, on the two emitted files, rather
# than in the browser -- the page renders one list and does not know there were
# ever two.


def _ind(id_, name, group, unit, source="ABS", **kw):
    return {"id": id_, "name": name, "group": group, "unit": unit,
            "source": source, "series": [{"date": "2026-07", "value": 1.0}],
            "last_release_date": "2026-08-20", **kw}


def _v3_indicators():
    return {"schema": "v3-indicators-1", "generated_at": "2026-09-12T03:30:00+00:00",
            "indicators": [
                _ind("employment", "Employment", "Labor", "Thousands"),
                _ind("household_spending", "Household Spending (real)",
                     "Retail and Consumption", "Millions of Dollars"),
                _ind("cpi", "Monthly CPI", "Prices", "Index"),
            ]}


def _v2_indicators():
    return {"indicators": [
        _ind("emp", "Employment", "Jobs & labour", "000s persons",
             next_release_estimate="2026-09-24", updated_this_run=False,
             prev_period="2026-06", latest_period="2026-07"),
        _ind("household_spending", "Household spending", "Households", "$m"),
        _ind("fcmygbag10", "10yr govt bond yield", "Financial & credit", "%",
             source="RBA"),
        _ind("nab_conf", "Business confidence", "Business surveys",
             "net balance", source="NAB"),
    ]}


def test_merge_keeps_v3s_order_and_appends_v2s_extras():
    """v3 first, in v3's order: the homepage's panel is the one it already had,
    with v2's series added after it rather than interleaved."""
    out = merge_indicators(_v3_indicators(), _v2_indicators())
    assert out["schema"] == "combo-indicators-1"
    assert [i["id"] for i in out["indicators"]] == [
        "employment", "household_spending", "cpi",
        "household_spending_nominal", "fcmygbag10", "nab_conf"]


def test_a_shared_series_is_merged_not_duplicated():
    """`emp` and `employment` are one series under two ids. The v3 entry wins on
    everything the page renders -- id, name, group, unit, series -- and takes
    from v2 only the release fields v3 does not emit."""
    out = merge_indicators(_v3_indicators(), _v2_indicators())
    emp = next(i for i in out["indicators"] if i["id"] == "employment")
    assert emp["name"] == "Employment"
    assert emp["group"] == "Labor" and emp["unit"] == "Thousands"
    assert emp["series"] == [{"date": "2026-07", "value": 1.0}]
    assert emp["next_release_estimate"] == "2026-09-24"
    assert emp["prev_period"] == "2026-06" and emp["latest_period"] == "2026-07"
    assert emp["updated_this_run"] is False
    assert emp["models"] == ["v2", "v3"]
    assert not any(i["id"] == "emp" for i in out["indicators"])


def test_v3s_own_fields_are_never_overwritten_by_v2s():
    """The merge fills gaps. Where both models carry a field, v3's stands: the
    entry is v3's series, and a release date from the other panel's copy of it
    would describe a different vintage of the same numbers."""
    v3 = _v3_indicators()
    v3["indicators"][0]["next_release_estimate"] = "2026-09-25"
    out = merge_indicators(v3, _v2_indicators())
    emp = next(i for i in out["indicators"] if i["id"] == "employment")
    assert emp["next_release_estimate"] == "2026-09-25"


def test_every_pair_in_the_registry_merges():
    """All six same-series pairs, fixed by id. Matching on values instead would
    pair two series that happen to agree in a quiet month."""
    v3 = {"generated_at": "x", "indicators": [
        _ind(v3id, v3id, "Labor", "Index") for v3id in SAME_SERIES.values()]}
    v2 = {"indicators": [_ind(v2id, v2id, "Jobs & labour", "index")
                         for v2id in SAME_SERIES]}
    out = merge_indicators(v3, v2)
    assert len(out["indicators"]) == len(SAME_SERIES)
    assert all(i["models"] == ["v2", "v3"] for i in out["indicators"])


def test_household_spending_is_two_series_not_one():
    """v2's is NOMINAL and v3's is REAL. They are different numbers under one
    name, so both are published and v2's is renamed to say which it is."""
    out = merge_indicators(_v3_indicators(), _v2_indicators())
    ids = [i["id"] for i in out["indicators"]]
    assert ids.count("household_spending") == 1
    nominal = next(i for i in out["indicators"]
                   if i["id"] == "household_spending_nominal")
    assert nominal["name"] == "Household spending (nominal)"
    assert nominal["unit"] == "$m"
    assert nominal["models"] == ["v2"]


def test_v2s_groups_are_mapped_onto_the_homepages_names():
    out = merge_indicators(_v3_indicators(), _v2_indicators())
    by_id = {i["id"]: i for i in out["indicators"]}
    assert by_id["household_spending_nominal"]["group"] == "Retail and Consumption"
    assert by_id["fcmygbag10"]["group"] == "Financial and credit"
    assert by_id["nab_conf"]["group"] == "Surveys"
    # Everything else about a v2-only entry is v2's.
    assert by_id["fcmygbag10"]["name"] == "10yr govt bond yield"
    assert by_id["fcmygbag10"]["unit"] == "%"
    assert by_id["fcmygbag10"]["source"] == "RBA"


def test_an_unknown_v2_group_travels_unchanged():
    v2 = {"indicators": [_ind("mystery", "Mystery", "Something new", "index")]}
    out = merge_indicators(_v3_indicators(), v2)
    assert out["indicators"][-1]["group"] == "Something new"


def test_every_entry_says_which_panels_it_belongs_to():
    out = merge_indicators(_v3_indicators(), _v2_indicators())
    assert {i["id"]: i["models"] for i in out["indicators"]} == {
        "employment": ["v2", "v3"],
        "household_spending": ["v3"],
        "cpi": ["v3"],
        "household_spending_nominal": ["v2"],
        "fcmygbag10": ["v2"],
        "nab_conf": ["v2"],
    }


def test_the_merged_ids_are_unique():
    out = merge_indicators(_v3_indicators(), _v2_indicators())
    ids = [i["id"] for i in out["indicators"]]
    assert len(ids) == len(set(ids))


def test_an_undeclared_id_collision_is_an_error():
    """A v2 id that equals a v3 id without being declared the same series, or
    renamed, is registry drift: publishing it would give the page two entries
    under one key. Better to fail the run than to render one of them."""
    v2 = {"indicators": [_ind("cpi", "CPI", "Prices", "index")]}
    with pytest.raises(ValueError, match="cpi"):
        merge_indicators(_v3_indicators(), v2)


def test_the_payload_names_both_sources():
    out = merge_indicators(_v3_indicators(), _v2_indicators())
    assert out["generated_at"] == "2026-09-12T03:30:00+00:00"
    assert out["sources"] == {"v3": "2026-09-12T03:30:00+00:00", "v2": None}
    v2 = dict(_v2_indicators(), generated_at="2026-09-12T02:00:00+00:00")
    assert merge_indicators(_v3_indicators(), v2)["sources"]["v2"] == \
        "2026-09-12T02:00:00+00:00"


def test_a_missing_v2_panel_leaves_v3s_intact(capsys):
    """v2's job can fail on a Monday v3's does not. The homepage must lose the
    v2 half of its panel, not the panel."""
    out = merge_indicators(_v3_indicators(), None)
    assert [i["id"] for i in out["indicators"]] == [
        "employment", "household_spending", "cpi"]
    assert all(i["models"] == ["v3"] for i in out["indicators"])
    assert out["sources"] == {"v3": "2026-09-12T03:30:00+00:00", "v2": None}
    assert "v2" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# Filling in a missing next_release_estimate
# --------------------------------------------------------------------------- #


def _row(id_, *, series=(), last_release_date=None, next_release_estimate=None):
    row = {"id": id_, "series": [{"date": d, "value": 1.0} for d in series]}
    if last_release_date is not None:
        row["last_release_date"] = last_release_date
    if next_release_estimate is not None:
        row["next_release_estimate"] = next_release_estimate
    return row


def test_present_estimates_are_left_untouched():
    rows = [_row("gdp", series=["2026-06"], next_release_estimate="2026-09-02")]
    out = fill_next_release(rows, next_gdp_release_date="2026-12-02")
    assert out[0]["next_release_estimate"] == "2026-09-02"
    assert "next_release_basis" not in out[0]


def test_input_is_not_mutated():
    rows = [_row("exports", series=["2026-07"], next_release_estimate="2026-10-01"),
            _row("imports", series=["2026-07"])]
    before = [dict(r) for r in rows]
    fill_next_release(rows, next_gdp_release_date="2026-12-02")
    assert rows == before


def test_imports_takes_exports_date():
    rows = [_row("exports", series=["2026-07"], next_release_estimate="2026-10-01"),
            _row("imports", series=["2026-07"])]
    out = fill_next_release(rows, next_gdp_release_date="2026-12-02")
    imports = next(r for r in out if r["id"] == "imports")
    assert imports["next_release_estimate"] == "2026-10-01"
    assert imports["next_release_basis"] == "sibling"


def test_household_spending_real_takes_the_nominal_sibling():
    rows = [_row("household_spending", series=["2026-07"]),
            _row("household_spending_nominal", series=["2026-07"],
                 next_release_estimate="2026-09-29")]
    out = fill_next_release(rows, next_gdp_release_date="2026-12-02")
    hs = next(r for r in out if r["id"] == "household_spending")
    assert hs["next_release_estimate"] == "2026-09-29"
    assert hs["next_release_basis"] == "sibling"


def test_a_missing_sibling_date_leaves_the_field_absent():
    rows = [_row("exports", series=["2026-07"]),
            _row("imports", series=["2026-07"])]
    out = fill_next_release(rows, next_gdp_release_date="2026-12-02")
    imports = next(r for r in out if r["id"] == "imports")
    assert "next_release_estimate" not in imports
    assert "next_release_basis" not in imports


def test_gdp_gdi_and_ulc_take_the_next_gdp_release_date():
    rows = [_row("gdp", series=["2026-06"]), _row("gdi", series=["2026-06"]),
            _row("unit_labour_cost", series=["2026-06"])]
    out = fill_next_release(rows, next_gdp_release_date="2026-12-02")
    for r in out:
        assert r["next_release_estimate"] == "2026-12-02"
        assert r["next_release_basis"] == "national_accounts"


def test_national_accounts_rows_left_alone_when_no_next_gdp_date():
    rows = [_row("gdp", series=["2026-06"])]
    out = fill_next_release(rows, next_gdp_release_date=None)
    assert "next_release_estimate" not in out[0]


def test_cpi_next_release_is_the_last_wednesday_two_months_after_latest():
    """Latest observation 2026-07, published in August; the next observation
    (2026-08) is due the last Wednesday of September 2026."""
    rows = [_row("cpi", series=["2026-06", "2026-07"])]
    out = fill_next_release(rows, next_gdp_release_date="2026-12-02")
    assert out[0]["next_release_estimate"] == "2026-09-30"
    assert out[0]["next_release_basis"] == "rule"


def test_commodity_prices_next_release_is_the_first_weekday_two_months_after():
    """Latest observation 2026-08, published early September; the next
    observation (2026-09) is due the first business day of October 2026."""
    rows = [_row("commodity_prices", series=["2026-07", "2026-08"])]
    out = fill_next_release(rows, next_gdp_release_date="2026-12-02")
    assert out[0]["next_release_estimate"] == "2026-10-01"
    assert out[0]["next_release_basis"] == "rule"


def test_aig_pmi_next_release_is_one_month_after_the_last_release():
    """2026-09-01 + one month = 2026-10-01, a Thursday: no roll needed."""
    rows = [_row("aig_pmi", series=["2026-08"], last_release_date="2026-09-01")]
    out = fill_next_release(rows, next_gdp_release_date="2026-12-02")
    assert out[0]["next_release_estimate"] == "2026-10-01"
    assert out[0]["next_release_basis"] == "rule"


def test_aig_pmi_next_release_rolls_a_weekend_forward_to_monday():
    """2026-09-04 + one month = 2026-10-04, a Sunday; rolled to 2026-10-05."""
    rows = [_row("aig_pmi", series=["2026-08"], last_release_date="2026-09-04")]
    out = fill_next_release(rows, next_gdp_release_date="2026-12-02")
    assert out[0]["next_release_estimate"] == "2026-10-05"


def test_series_without_a_rule_or_sibling_stays_untouched():
    rows = [_row("nab_conf", series=["2026-08"])]
    out = fill_next_release(rows, next_gdp_release_date="2026-12-02")
    assert "next_release_estimate" not in out[0]
    assert "next_release_basis" not in out[0]


# --------------------------------------------------------------------------- #
# Flagging updated_this_run on the v3-only indicators
# --------------------------------------------------------------------------- #


def _mi(id_, *, series, models=("v3",)):
    return {"id": id_, "series": [{"date": d, "value": 1.0} for d in series],
            "models": list(models)}


def test_a_newer_last_series_date_is_flagged_with_both_periods():
    current = [_mi("imports", series=["2026-06", "2026-07"])]
    previous = [_mi("imports", series=["2026-05", "2026-06"])]
    out = mark_updated(current, previous)
    assert out[0]["updated_this_run"] is True
    assert out[0]["prev_period"] == "2026-06"
    assert out[0]["latest_period"] == "2026-07"


def test_the_same_last_series_date_is_not_flagged():
    current = [_mi("imports", series=["2026-06", "2026-07"])]
    previous = [_mi("imports", series=["2026-06", "2026-07"])]
    out = mark_updated(current, previous)
    assert out[0]["updated_this_run"] is False
    assert "prev_period" not in out[0]
    assert "latest_period" not in out[0]


def test_an_older_last_series_date_is_not_flagged():
    current = [_mi("imports", series=["2026-05"])]
    previous = [_mi("imports", series=["2026-06", "2026-07"])]
    out = mark_updated(current, previous)
    assert out[0]["updated_this_run"] is False
    assert "prev_period" not in out[0]


def test_an_id_missing_from_previous_is_not_flagged():
    current = [_mi("imports", series=["2026-07"])]
    out = mark_updated(current, previous=[_mi("exports", series=["2026-07"])])
    assert out[0]["updated_this_run"] is False
    assert "prev_period" not in out[0]


def test_no_previous_payload_at_all_is_not_flagged():
    current = [_mi("imports", series=["2026-07"])]
    out = mark_updated(current, previous=None)
    assert out[0]["updated_this_run"] is False


def test_a_v2_covered_entry_is_left_exactly_as_it_is():
    """v2's flag already lives on this entry; mark_updated must not touch it,
    even when the series itself has moved on."""
    entry = _mi("employment", series=["2026-06", "2026-07"], models=("v2", "v3"))
    entry["updated_this_run"] = False
    previous = [_mi("employment", series=["2026-05"], models=("v2", "v3"))]
    out = mark_updated([entry], previous)
    assert out[0] is entry
    assert out[0]["updated_this_run"] is False


def test_input_lists_are_not_mutated():
    current = [_mi("imports", series=["2026-06", "2026-07"])]
    previous = [_mi("imports", series=["2026-05", "2026-06"])]
    before = [dict(r) for r in current]
    mark_updated(current, previous)
    assert current == before
