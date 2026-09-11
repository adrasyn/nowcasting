"""The equal-weight combination of v2 and v3, as pure functions.

WHY AN AVERAGE AT ALL. The two models are wrong in different directions and
neither dominates: over the weekly vintages of 2022Q4-2026Q2, scored against
the ABS's initial estimate, the simple mean of the two beats both
(`docs/measurements/2026-09-12-v2-v3-weekly-combination.md`). Equal weights,
not fitted ones -- with a dozen scored quarters an estimated weight is fitted
to noise, and the forecast-combination literature's oldest result is that the
mean is hard to beat out of sample.

WHAT THIS MODULE IS NOT. It does no file I/O and no estimation. It takes the
two models' ALREADY PUBLISHED figures -- v3's history log and v2's vintages --
and decides which pair with which, what band each horizon gets, and how the
track record reads. `tools/emit_combination.py` reads the files, calls these
functions and writes the payloads. Keeping the rules here is what lets them be
tested on six-row inputs instead of on a week of real data.

THE PAIRING RULE. A combination exists for a run date and a quarter only where
BOTH models have a figure for that quarter at that date. v2 runs at 02:00 UTC
on Monday and v3 at 03:30, so they normally share a run date; when v2 skips a
Monday its most recent run up to `max_age_days` old is used instead, and beyond
that the pair is dropped rather than averaging in a stale information set.

THE HORIZON RULE. A quarter is CURRENT at a run date if it is the earliest
quarter the ABS has not printed by then; the one after it is NEXT. That is
computed from `gdp_release_date`, the ABS's scheduling rule, so a row written
months ago gets the horizon it had ON ITS OWN DAY rather than the one it would
have today. The same quarter is therefore "next" on the Mondays before its
predecessor prints and "current" on the Mondays after, which is exactly how the
band should change: a figure built on no months of data is not as good as one
built on two.

THE BANDS ARE EMPIRICAL, and this is a real difference from v3's payload. v3's
interval is its posterior's, drawn from the same chain as the point. The
combination has no posterior -- averaging two point estimates does not average
their distributions -- so its band is the spread of its own backtest misses,
per horizon, centred on the point. `ci_basis` says so in the payload, because a
reader comparing the pages must be able to tell the two kinds apart.
"""

from __future__ import annotations

import datetime as _dt

from nyfed.au.emit import gdp_release_date

SCHEMA = "combo-1"
HISTORY_SCHEMA = "combo-history-1"
METHOD = "equal-weight average of v2 and v3"
MAX_AGE_DAYS = 7


# --------------------------------------------------------------------------- #
# Quarters
# --------------------------------------------------------------------------- #


def _parse_quarter(label: str) -> tuple[int, int]:
    year_s, q_s = label.split(" Q")
    return int(year_s), int(q_s)


def quarter_shift(label: str, n: int) -> str:
    """``("2026 Q4", 1) -> "2027 Q1"``."""
    year, q = _parse_quarter(label)
    i = year * 4 + (q - 1) + n
    return f"{i // 4} Q{i % 4 + 1}"


def make_is_current(release_date=gdp_release_date):
    """``is_current(run_date, quarter)`` under the ABS's release calendar.

    A quarter is current at a run date when the ABS has not printed it but HAS
    printed the one before it -- equivalently, when it is the earliest quarter
    whose release date is after the run date. The release date is the morning
    of the print, so on that day the quarter has been printed and the next one
    has become current.
    """

    def is_current(run_date: str, quarter: str) -> bool:
        rel = release_date(quarter)
        prev = release_date(quarter_shift(quarter, -1))
        if rel is None or prev is None:
            return False
        return prev <= run_date < rel

    return is_current


# --------------------------------------------------------------------------- #
# Pairing
# --------------------------------------------------------------------------- #


def _days_between(later: str, earlier: str) -> int:
    return (_dt.date.fromisoformat(later) - _dt.date.fromisoformat(earlier)).days


def v2_vintage_rows(v2_latest: dict) -> list[dict]:
    """v2's published figures as pairing input: its vintages plus its models.

    `latest_v2.json` carries the week's own figures in `models` and the weeks
    before it in `vintages`, so the current Monday would be missing from the
    vintage list on the day. `models.headline` is the current quarter and
    `models.next_quarter` -- absent until v2 gains the horizon, and absent on
    the Mondays where the next quarter has no month of data yet -- is the next.

    A vintage row with no `horizon` is a current-quarter row: every row in the
    committed payload predates the field, and v2 nowcast only the current
    quarter until then. The horizon travels for the record; the pairing itself
    matches on `target_quarter`, which is unambiguous either way.
    """
    rows: dict[tuple[str, str], dict] = {}
    for v in v2_latest.get("vintages") or []:
        row = {"run_date": v["run_date"], "target_quarter": v["target_quarter"],
               "qoq_growth_pct": float(v["qoq_growth_pct"]),
               "horizon": v.get("horizon") or "current"}
        rows[(row["run_date"], row["target_quarter"])] = row
    as_of = v2_latest.get("as_of")
    models = v2_latest.get("models") or {}
    for key, horizon in (("headline", "current"), ("next_quarter", "next")):
        m = models.get(key)
        if not m or as_of is None:
            continue
        row = {"run_date": as_of, "target_quarter": m["target_quarter"],
               "qoq_growth_pct": float(m["qoq_growth_pct"]),
               "horizon": m.get("horizon") or horizon}
        rows[(row["run_date"], row["target_quarter"])] = row
    return sorted(rows.values(), key=lambda r: (r["run_date"], r["target_quarter"]))


def pair_runs(v3_runs: list[dict], v2_vintages: list[dict], *,
              max_age_days: int = MAX_AGE_DAYS) -> list[dict]:
    """One combined row per v3 run that has a v2 partner for the same quarter.

    v2's partner is its latest run for that quarter at or before the v3 run
    date and no more than `max_age_days` old. A v3 row with no partner is
    dropped: half a combination is v3 published under another name.
    """
    by_quarter: dict[str, list[dict]] = {}
    for v in v2_vintages:
        by_quarter.setdefault(v["target_quarter"], []).append(v)
    for rows in by_quarter.values():
        rows.sort(key=lambda r: r["run_date"])

    out = []
    for r in v3_runs:
        quarter, run_date = r["target_quarter"], r["run_date"]
        partner = None
        for v in by_quarter.get(quarter, []):
            if v["run_date"] <= run_date and _days_between(
                    run_date, v["run_date"]) <= max_age_days:
                partner = v
        if partner is None:
            continue
        v2q = float(partner["qoq_growth_pct"])
        v3q = float(r["qoq_growth_pct"])
        row = {
            "run_date": run_date,
            "target_quarter": quarter,
            # A row written before the `kind` field is a nowcast: the forecast
            # horizon was never recorded without it.
            "kind": r.get("kind") or "nowcast",
            "qoq_growth_pct": round((v2q + v3q) / 2, 4),
            "v2_qoq_growth_pct": round(v2q, 4),
            "v2_run_date": partner["run_date"],
            "v3_qoq_growth_pct": round(v3q, 4),
            "months_with_data": r.get("months_with_data"),
            "data_through": r.get("data_through"),
        }
        out.append(row)
    out.sort(key=lambda x: (x["run_date"], x["target_quarter"]))
    return out


# --------------------------------------------------------------------------- #
# Bands
# --------------------------------------------------------------------------- #


def with_bands(rows: list[dict], params: dict, *, is_current=None) -> list[dict]:
    """Add the empirical bands, per horizon, centred on the point.

    `params` carries a `current` and a `next` block, each with `p68` and `p95`
    -- the 68th and 95th percentiles of the combination's own absolute backtest
    error at that horizon. The horizon of a row is decided by its OWN run date,
    not by today's calendar.
    """
    is_current = is_current or make_is_current()
    out = []
    for r in rows:
        horizon = ("current" if is_current(r["run_date"], r["target_quarter"])
                   else "next")
        band = params[horizon]
        q = float(r["qoq_growth_pct"])
        p68, p95 = float(band["p68"]), float(band["p95"])
        out.append({**r, "horizon": horizon,
                    "ci_68_low": round(q - p68, 4), "ci_68_high": round(q + p68, 4),
                    "ci_95_low": round(q - p95, 4), "ci_95_high": round(q + p95, 4)})
    return out


def bands_from_errors(errors) -> dict:
    """`{p68, p95, n, mae, bias}` from a sequence of signed errors (pp).

    The fallback the tool uses until the calibrated parameter file exists: the
    percentiles of the absolute error, which is what the seed file holds.
    """
    import numpy as np

    err = np.asarray(list(errors), dtype=float)
    return {"p68": round(float(np.percentile(np.abs(err), 68)), 4),
            "p95": round(float(np.percentile(np.abs(err), 95)), 4),
            "n": int(err.size),
            "mae": round(float(np.abs(err).mean()), 4),
            "bias": round(float(err.mean()), 4)}


# --------------------------------------------------------------------------- #
# The published payload
# --------------------------------------------------------------------------- #


def _annualised(qoq: float) -> float:
    return round(((1 + qoq / 100) ** 4 - 1) * 100, 4)


def _ci_basis(params: dict) -> str:
    basis = params.get("basis") or (
        "the range holding 68% and 95% of the combination's own backtest "
        "misses against the ABS's initial estimate, weekly vintages, centred "
        "on the point")
    text = f"probability band: {basis} Not a posterior and not a confidence interval."
    if params.get("provisional_next"):
        text += (" The next-quarter band is provisional: it reuses the "
                 "current-quarter parameters until the two-horizon backtest "
                 "has calibrated its own.")
    return text


def _horizon_entry(row: dict, *, kind: str, prev_level: float | None) -> dict:
    q = float(row["qoq_growth_pct"])
    entry = {
        "quarter": row["target_quarter"],
        "kind": kind,
        "qoq_growth_pct": q,
        # The combination has no correction of its own: each component arrives
        # already on the published basis. The field exists because the site's
        # methodology panel reads it as provenance, and here it is the point.
        "model_qoq_growth_pct": q,
        "annualised_growth_pct": _annualised(q),
        "ci_68_low": row["ci_68_low"], "ci_68_high": row["ci_68_high"],
        "ci_95_low": row["ci_95_low"], "ci_95_high": row["ci_95_high"],
        "components": {"v2": row["v2_qoq_growth_pct"],
                       "v3": row["v3_qoq_growth_pct"]},
    }
    if row.get("months_with_data") is not None:
        entry["months_with_data"] = int(row["months_with_data"])
    rel = gdp_release_date(row["target_quarter"])
    if rel:
        entry["release_date"] = rel
    if kind == "nowcast" and prev_level is not None:
        entry["gdp_chain_volume_millions"] = round(prev_level * (1 + q / 100))
    return entry


def latest_payload(rows: list[dict], *, v3_latest: dict, gdp_series: list[dict],
                   params: dict, generated_at: str, v2_latest: dict | None = None,
                   is_current=None, max_age_days: int = MAX_AGE_DAYS) -> dict:
    """`latest_combo.json` in v3's `LatestV3` shape, from banded paired rows.

    The current quarter is the one in force at V3's as-of date, not at the last
    paired Monday: if v2 has gone quiet the page must still say which quarter
    it is talking about. The figure published for it is then the most recent
    paired Monday's, with `components.v2.stale_days` saying how old that is.
    """
    is_current = is_current or make_is_current()
    asof_ref = v3_latest["as_of"]
    banded = [r for r in rows if "ci_68_low" in r]
    if len(banded) != len(rows):
        raise ValueError("latest_payload() wants rows from with_bands(); "
                         f"{len(rows) - len(banded)} row(s) carry no band")

    current_q = next((q for q in {r["target_quarter"] for r in rows}
                      if is_current(asof_ref, q)), None)
    if current_q is None:
        # No paired row is for the quarter in force; derive the label anyway so
        # the refusal can name it.
        current_q = next(q for q in (quarter_shift(f"{asof_ref[:4]} Q1", k)
                                     for k in range(-4, 8))
                         if is_current(asof_ref, q))
    next_q = quarter_shift(current_q, 1)

    def latest_for(quarter: str) -> dict | None:
        cands = [r for r in rows if r["target_quarter"] == quarter]
        return max(cands, key=lambda r: r["run_date"]) if cands else None

    cur = latest_for(current_q)
    if cur is None:
        raise ValueError(
            f"no v2 figure for the current quarter ({current_q}): no run date "
            "has both models nowcasting it")
    nxt = latest_for(next_q)

    quarters = [g["quarter"] for g in gdp_series]
    prev_q = quarter_shift(current_q, -1)
    prev_level = next((float(g["value"]) for g in gdp_series
                       if g["quarter"] == prev_q), None)
    if prev_level is None and quarters:
        prev_q = quarters[-1]
        prev_level = float(gdp_series[-1]["value"])

    horizons = [_horizon_entry(cur, kind="nowcast", prev_level=prev_level)]
    if nxt is not None:
        horizons.append(_horizon_entry(nxt, kind="forecast", prev_level=None))

    vintages = [r for r in rows
                if r["target_quarter"] in (current_q, next_q)]
    vintages.sort(key=lambda r: (r["run_date"], r["target_quarter"]))

    v2_component = {"as_of": (v2_latest or {}).get("as_of"),
                    "run_date": cur["v2_run_date"],
                    "schema": (v2_latest or {}).get("schema")}
    stale = _days_between(asof_ref, cur["v2_run_date"])
    if stale > max_age_days:
        v2_component["stale_days"] = stale

    band_pp = {h: dict(params[h]) for h in ("current", "next") if h in params}
    if params.get("provisional_next"):
        band_pp["provisional_next"] = True

    return {
        "schema": SCHEMA,
        "status": "ok",
        "basis": "abs_first_print",
        "target": "first_print",
        "method": METHOD,
        "generated_at": generated_at,
        "as_of": cur["run_date"],
        "target_quarter": current_q,
        "data_through": cur.get("data_through"),
        "prev_level": ({"value": round(prev_level), "quarter": prev_q}
                       if prev_level is not None else None),
        "horizons": horizons,
        "vintages": vintages,
        "next_gdp_release_date": gdp_release_date(current_q),
        # v3's, not the combination's: it is the correction already taken off
        # one of the two components, published so the reader can see it.
        "bias_correction": v3_latest.get("bias_correction"),
        "ci_basis": _ci_basis(params),
        "band_pp": band_pp,
        "components": {"v2": v2_component,
                       "v3": {"as_of": v3_latest.get("as_of"),
                              "schema": v3_latest.get("schema")}},
        # Provenance for the v3 half. The panel and the sampler are v3's; v2's
        # own inputs are described on its own page.
        "panel": v3_latest.get("panel"),
        "diagnostics": v3_latest.get("diagnostics"),
        "estimate": v3_latest.get("estimate"),
    }


def refusal_from_v3(v3_latest: dict, *, generated_at: str) -> dict:
    """v3's refusal, republished under the combination's schema.

    Half a combination is not a combination, so when v3 declines the page
    declines, for v3's reason. Carries no figure at all: a payload with a stale
    number in it is indistinguishable on the page from a current one.
    """
    return refusal_payload(reason=v3_latest.get("refusal_reason", "v3 refused"),
                           detail=v3_latest.get("refusal_detail", ""),
                           generated_at=generated_at,
                           asof=v3_latest.get("as_of"))


def refusal_payload(*, reason: str, detail: str, generated_at: str,
                    asof: str | None) -> dict:
    return {"schema": SCHEMA, "status": "refused", "method": METHOD,
            "generated_at": generated_at, "as_of": asof,
            "refusal_reason": reason, "refusal_detail": detail,
            "horizons": []}


# --------------------------------------------------------------------------- #
# The track record
# --------------------------------------------------------------------------- #


def _spaced(label: str) -> str:
    """``2026Q2`` -> ``2026 Q2``, the form every payload uses."""
    return f"{label[:4]} Q{label[-1]}" if " " not in label else label


def _final_backtest_rows(backtest_rows: list[dict]) -> dict[str, dict]:
    """The last weekly vintage before each quarter printed, per quarter."""
    out: dict[str, dict] = {}
    for r in backtest_rows:
        label = _spaced(str(r["target"]))
        release = str(r.get("release") or "")
        asof = str(r["as_of"])[:10]
        if release and asof >= release:
            continue
        if label not in out or asof > out[label]["as_of"]:
            out[label] = {"as_of": asof, "v2": float(r["v2"]),
                          "v3": float(r["v3"]), "combo": float(r["combo"])}
    return out


def _final_live_rows(history_rows: list[dict]) -> dict[str, dict]:
    """The last combination row published for each quarter before it printed.

    Forecast rows are excluded: a forecast was made before the quarter began,
    and scoring it as the final nowcast would score a different call. This is
    the same rule `bias_correction._final_nowcast` applies to v3's history.
    """
    out: dict[str, dict] = {}
    for r in history_rows:
        if (r.get("kind") or "nowcast") != "nowcast":
            continue
        label = r["target_quarter"]
        release = gdp_release_date(label)
        run = r["run_date"]
        if release is None or run >= release:
            continue
        if label not in out or run > out[label]["as_of"]:
            out[label] = {"as_of": run,
                          "v2": float(r["v2_qoq_growth_pct"]),
                          "v3": float(r["v3_qoq_growth_pct"]),
                          "combo": float(r["qoq_growth_pct"])}
    return out


def track_record(backtest_rows: list[dict], history_rows: list[dict],
                 gdp_series: list[dict], first_release: dict,
                 somp: dict) -> dict:
    """`performance_combo.json` in the site's `Performance` shape.

    One row per printed quarter, scored as the LAST figure published before the
    ABS printed it against what the ABS then printed. A live row supersedes the
    backtested one for its quarter: a backtest sees the whole sample and a live
    call does not, so reporting the backtest where a live figure exists would
    be quietly flattering.

    Levels are chained off the latest ABS vintage (`gdp.json`) and the
    year-ended figures are therefore hybrid -- three quarters of the revised
    path chained to this quarter's initial estimate -- exactly as v3's track
    record does it, because a first-print level four quarters back does not
    exist within one vintage.
    """
    quarters = [g["quarter"] for g in gdp_series]
    level = {g["quarter"]: float(g["value"]) for g in gdp_series}
    latest_qoq = {g["quarter"]: g.get("qoq_pct") for g in gdp_series}

    backtested = _final_backtest_rows(backtest_rows)
    live = _final_live_rows(history_rows)

    errors = []
    for label in sorted(set(backtested) | set(live),
                        key=lambda s: (int(s[:4]), int(s[-1]))):
        is_live = label in live
        src = live[label] if is_live else backtested[label]
        actual = first_release.get(label)
        if actual is None:
            if label not in backtested:
                # THE QUARTER IN FLIGHT. The combination has rows for it and
                # the ABS has not printed it, so there is nothing to score it
                # against yet. Normal every week; it joins the table on the
                # Monday after its release.
                continue
            raise ValueError(
                f"{label} has no ABS initial estimate in the first-release "
                "series; fill it from that release's Key Aggregates "
                "spreadsheet rather than scoring the row on another basis")
        if label not in quarters:
            # The quarter has a first print but no level in `gdp.json` yet;
            # there is nothing to chain it to.
            continue
        i = quarters.index(label)
        if i == 0:
            continue
        base_prev = level[quarters[i - 1]]
        nc, ac = float(src["combo"]), float(actual)
        nowcast_lvl = base_prev * (1 + nc / 100)
        actual_lvl = base_prev * (1 + ac / 100)

        yoy_nc = yoy_ac = yoy_rba = edge = release = None
        if i >= 4:
            base = level[quarters[i - 4]]
            yoy_nc = round(100 * (nowcast_lvl / base - 1), 2)
            yoy_ac = round(100 * (actual_lvl / base - 1), 2)
            s = somp.get(label)
            if s:
                yoy_rba = float(s["yoy_forecast_pct"])
                release = str(s["somp_release"])
                edge = round(abs(yoy_nc - yoy_ac) - abs(yoy_rba - yoy_ac), 2)

        errors.append({
            "target_quarter": label,
            "final_nowcast": round(nowcast_lvl),
            "actual": round(actual_lvl),
            "error_millions": round(nowcast_lvl - actual_lvl),
            "error_pct": round(100 * (nowcast_lvl - actual_lvl) / actual_lvl, 3),
            "qoq_nowcast_pct": round(nc, 2),
            "qoq_model_nowcast_pct": round(nc, 2),
            # Nothing is taken off the combination: each component arrives with
            # its own correction already applied.
            "bias_correction_pp": None,
            "qoq_actual_pct": round(ac, 2),
            "qoq_error_pp": round(nc - ac, 2),
            "qoq_latest_vintage_pct": latest_qoq.get(label),
            # The two halves, so a reader can see which one moved the average.
            "v2_qoq_nowcast_pct": round(float(src["v2"]), 2),
            "v3_qoq_nowcast_pct": round(float(src["v3"]), 2),
            "model": "combination",
            "is_live": is_live,
            "live_run_date": src["as_of"] if is_live else None,
            "final_run_date": src["as_of"],
            "yoy_nowcast": yoy_nc, "yoy_actual": yoy_ac, "yoy_rba": yoy_rba,
            "somp_release": release, "edge_pp": edge,
        })

    if not errors:
        raise ValueError("no printed quarter has a combination figure to score")

    def mean(xs):
        xs = list(xs)
        return sum(xs) / len(xs)

    err = [e["qoq_nowcast_pct"] - e["qoq_actual_pct"] for e in errors]
    paired = [e for e in errors if e["edge_pp"] is not None]
    return {
        "basis": "abs_first_print",
        "target": "first_print",
        "method": METHOD,
        "n": len(errors),
        "mae_millions": round(mean(abs(e["error_millions"]) for e in errors)),
        "mae_pct": round(mean(abs(x) for x in err), 2),
        "bias_millions": round(mean(e["error_millions"] for e in errors)),
        "bias_pct": round(mean(err), 2),
        # The components over the same rows, which is the only fair comparison:
        # the same quarters, the same vintages, the same target.
        "v2_mae_pct": round(mean(abs(e["v2_qoq_nowcast_pct"] - e["qoq_actual_pct"])
                                 for e in errors), 2),
        "v3_mae_pct": round(mean(abs(e["v3_qoq_nowcast_pct"] - e["qoq_actual_pct"])
                                 for e in errors), 2),
        "n_live": sum(1 for e in errors if e["is_live"]),
        "rba_comparison": {
            "n": len(paired),
            "avg_edge_pp": (round(mean(e["edge_pp"] for e in paired), 2)
                            if paired else None),
            "ours_mae": (round(mean(abs(e["yoy_nowcast"] - e["yoy_actual"])
                                    for e in paired), 2) if paired else None),
            "rba_mae": (round(mean(abs(e["yoy_rba"] - e["yoy_actual"])
                                   for e in paired), 2) if paired else None),
            "we_were_closer": sum(
                1 for e in paired
                if abs(e["yoy_nowcast"] - e["yoy_actual"])
                < abs(e["yoy_rba"] - e["yoy_actual"])) if paired else None,
        },
        "errors": errors,
    }
