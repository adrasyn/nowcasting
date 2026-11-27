"""Model input completeness and publication contract before ABS GDP.

This is separate from model scheduling and release-lag assumptions: a full
calendar quarter is not evidence that the two models actually used its inputs.
The special run must be before the release *day*, so a date-only archive never
needs to disentangle a live estimate from one that saw the actual.
"""
from datetime import date, datetime, time, timedelta
import re
from zoneinfo import ZoneInfo

SYDNEY = ZoneInfo("Australia/Sydney")
MIN_RUN_HOUR = 14


def quarter_parts(quarter):
    if not isinstance(quarter, str) or not re.fullmatch(r"\d{4} Q[1-4]", quarter):
        raise ValueError("Invalid target quarter")
    return int(quarter[:4]), int(quarter[-1])


def release_slot(calendar, now):
    """Return a guarded run window using the release date on the site."""
    release = date.fromisoformat(calendar["next_gdp_release_date"])
    day = release - timedelta(days=1)
    local = now.astimezone(SYDNEY)
    if local.date() != day or local.hour < MIN_RUN_HOUR:
        return None
    target = calendar.get("target_quarter")
    year, q = quarter_parts(target)
    prior = f"{year} Q{q - 1}" if q > 1 else f"{year - 1} Q4"
    if (calendar.get("latest_actual") or {}).get("quarter") != prior:
        raise ValueError("Calendar and latest GDP actual disagree")
    if (release.year, release.month) != (year + (q == 4), (q % 4 + 1) * 3):
        raise ValueError("GDP release does not belong to the target quarter")
    return {"quarter": target, "run_date": day.isoformat(),
            "release_at": datetime.combine(release, time(11, 30), SYDNEY).isoformat()}


def quarter_months(quarter):
    year, q = quarter_parts(quarter)
    return [f"{year}-{m:02d}" for m in range(q * 3 - 2, q * 3 + 1)]


def release_instant(quarter, release_date):
    year, q = quarter_parts(quarter)
    release = date.fromisoformat(release_date)
    if (release.year, release.month) != (year + (q == 4), (q % 4 + 1) * 3):
        raise ValueError("GDP release does not belong to the target quarter")
    return datetime.combine(release, time(11, 30), SYDNEY)


def monthly_input_coverage(observed, *, quarter, monthly_keys):
    """Months consumed by v3, after its lag/transform cut, not display dates."""
    year, _ = quarter_parts(quarter)
    months = quarter_months(quarter)
    missing = []
    incomplete = set()
    for key in monthly_keys:
        values = observed.get(key, set())
        absent = [m for m in months if m not in values]
        # Ai Group ordinarily skips either December or January. Only excuse
        # one turn-of-year slot, not a dead feed: require its adjoining month.
        other = {f"{year}-01": f"{year - 1}-12", f"{year}-12": f"{year + 1}-01"}
        if key == "aig_pmi":
            absent = [m for m in absent if other.get(m) not in values]
        incomplete.update(absent)
        missing.extend(f"{key} ({m})" for m in absent)
    return [m for m in months if m not in incomplete], missing


def missing_monthly_inputs(observed, **kwargs):
    return monthly_input_coverage(observed, **kwargs)[1]


def checked_final_stamp(combo, v2, v3, slot, generated_at):
    """Certify the exact published vintage, never a carry or ordinary update."""
    day, quarter = slot["run_date"], slot["quarter"]
    if combo.get("status") != "ok" or combo.get("as_of") != day:
        raise ValueError("No successful same-day combination")
    for model in (v2, v3):
        if (model.get("as_of") != day or model.get("target_quarter") != quarter
                or model.get("final_input_check") != slot):
            raise ValueError("Both models must certify complete inputs on the final day")
    components = combo.get("components", {})
    if (components.get("v2", {}).get("run_date") != day
            or components.get("v2", {}).get("stale_days", 0) != 0
            or components.get("v3", {}).get("as_of") != day):
        raise ValueError("A carried model cannot be final")
    horizon = combo["horizons"][0]
    rows = [r for r in combo["vintages"] if r.get("target_quarter") == quarter]
    latest = max(rows, key=lambda r: r["run_date"], default={})
    if (combo.get("target_quarter") != quarter or horizon.get("quarter") != quarter
            or horizon.get("kind") != "nowcast" or horizon.get("months_with_data") != 3
            or latest.get("run_date") != day or latest.get("v2_run_date") != day
            or latest.get("horizon") != "current"
            or any(latest.get(k) is None or latest.get(k) != horizon.get(k)
                   for k in ("qoq_growth_pct", "ci_68_low", "ci_68_high",
                             "ci_95_low", "ci_95_high"))):
        raise ValueError("The published horizon and final chart point disagree")
    return {**slot, "generated_at": generated_at}


def lock_active(payload, gdp, now):
    lock = payload.get("final_estimate") or {}
    target = lock.get("quarter")
    if not target or target != payload.get("target_quarter"):
        return False
    if any(row.get("quarter") == target for row in gdp):
        return False
    return (payload.get("status") == "ok" and
            lock.get("run_date") == payload.get("as_of") and
            lock.get("generated_at") == payload.get("generated_at") and
            datetime.fromisoformat(lock["generated_at"]) <= now <
            datetime.fromisoformat(lock["release_at"]))


def coverage_stamp(combo, gdp, now):
    """The latest complete estimate stays eligible for revisions until GDP day."""
    if combo.get("status") != "ok":
        return None
    target, day = combo.get("target_quarter"), combo.get("as_of")
    components = combo.get("components", {})
    if (components.get("v2", {}).get("run_date") != day
            or components.get("v2", {}).get("stale_days", 0)
            or components.get("v3", {}).get("as_of") != day
            or now.astimezone(SYDNEY).date().isoformat() != day
            or any(r.get("quarter") == target for r in gdp)):
        return None
    h = next((h for h in combo["horizons"] if h.get("kind") == "nowcast"
              and h.get("quarter") == target), None)
    if not h or h.get("complete_months") != quarter_months(target):
        return None
    release = release_instant(target, h["release_date"])
    if now.astimezone(SYDNEY).date() >= release.date():
        return None
    return {"quarter": target, "run_date": day, "release_at": release.isoformat(),
            "generated_at": combo["generated_at"]}
