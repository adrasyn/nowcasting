#!/usr/bin/env python3
"""Regenerate data/indicators_v2.json (the indicator-grid display) from data_raw.

WHY: the indicator grid reads data/indicators_v2.json, but nothing rebuilt it, so
its values went stale even though data_raw/*.csv was being refreshed weekly (the
emit only writes latest_v2.json). This generator refreshes every indicator's
`series` from data_raw and advances the release-date fields in step, preserving
all curated metadata (name/group/unit/source, display window, ordering).

Run from repo root:  python nowcasting_v2/gen_indicators_v2.py
Wired into the weekly cron after the v2 emit so the grid stays current.

Design:
  * Uses the EXISTING indicators_v2.json as the metadata template (which
    indicators, their names/groups/units/sources, and each series' start month).
  * For each indicator, reloads its series from data_raw/<id>.csv, keeping the
    same start month (preserves the curated chart window) and matching the
    existing value precision. data_raw is the source of truth, so revisions to
    historical months flow through too.
  * Advances last_release_date / next_release_estimate by however many months the
    data extended (preserves each source's day-of-month release pattern).
  * Clamps last_release_date to today if the shifted heuristic lands in the
    future. Some sources (e.g. RM Consumer Confidence) publish mid-month rolling
    monthly averages, so the data point IS in our file before the heuristic's
    "Nth of next month" release day — a future last_release_date there is
    self-contradicting.
"""
import json, csv, os, calendar, datetime as dt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IND = os.path.join(ROOT, "data", "indicators_v2.json")
V1_IND = os.path.join(ROOT, "data", "indicators.json")
RAW = os.path.join(ROOT, "nowcasting_v2", "data_raw")

# ABS-sourced v2 indicators -> v1 indicators.json ids. The v1 emit
# (04_emit_json.R) scrapes each ABS publication's real "Next Release" date every
# run, so reuse those authoritative dates instead of the fixed-day month-shift
# below, which drifts off the real ABS schedule (ABS moves dates around public
# holidays — e.g. the May-2026 Labour Force release is 25 Jun, not the heuristic
# 15 Jun). v1 runs before this generator in the weekly cron. RBA/survey series
# have no v1 ABS entry and keep the month-shift heuristic.
ABS_DATE_MAP = {
    "emp": "employment", "ft_emp": "employment", "pt_emp": "employment",
    "ue": "unemp_rate", "ud": "unemp_rate", "hours": "hours_worked",
    "household_spending": "household_spending",
    "building_app": "building_approvals", "export": "goods_exp",
}


def ndec(v):
    s = str(v)
    return len(s.split(".")[1]) if "." in s else 0


def month_idx(yyyy_mm):
    y, m = int(yyyy_mm[:4]), int(yyyy_mm[5:7])
    return y * 12 + (m - 1)


def shift_iso_months(iso, n):
    """Shift a YYYY-MM-DD date by n months, clamping the day to month length."""
    y, m, d = (int(x) for x in iso.split("-"))
    idx = y * 12 + (m - 1) + n
    ny, nm = idx // 12, idx % 12 + 1
    return f"{ny:04d}-{nm:02d}-{min(d, calendar.monthrange(ny, nm)[1]):02d}"


def read_raw(series_id):
    p = os.path.join(RAW, f"{series_id}.csv")
    with open(p, newline="") as f:
        return [(r["date"][:7], r["value"]) for r in csv.DictReader(f)]


def load_v1_abs_dates():
    """Real ABS release dates scraped by the v1 emit, keyed by v1 indicator id."""
    if not os.path.exists(V1_IND):
        print("  WARN: data/indicators.json (v1) not found; ABS dates stay on heuristic")
        return {}
    try:
        v1 = json.load(open(V1_IND))
        return {i["id"]: i for i in v1["indicators"]}
    except Exception as e:
        print(f"  WARN: could not read v1 indicators.json ({e}); ABS dates stay on heuristic")
        return {}


def main():
    doc = json.load(open(IND))
    v1_dates = load_v1_abs_dates()
    today_iso = dt.date.today().isoformat()
    advanced = []
    abs_synced = []
    clamped = []
    for ind in doc["indicators"]:
        sid = ind["id"]
        old = ind["series"]
        if not old:
            continue
        decimals = max(ndec(p["value"]) for p in old)
        start = old[0]["date"]            # preserve curated chart start
        old_latest = old[-1]["date"]
        raw = read_raw(sid)
        new = [{"date": ym, "value": round(float(v), decimals)}
               for ym, v in raw if ym >= start]
        if not new:
            print(f"  WARN {sid}: no data_raw rows >= {start}; leaving as-is")
            continue
        new_latest = new[-1]["date"]
        adv = month_idx(new_latest) - month_idx(old_latest)
        if adv > 0:
            for k in ("last_release_date", "next_release_estimate"):
                if ind.get(k):
                    ind[k] = shift_iso_months(ind[k], adv)
            advanced.append(f"{sid} {old_latest}->{new_latest}")
        # ABS series: override the month-shift heuristic with v1's scraped,
        # authoritative ABS release dates (falls back to the heuristic above
        # when v1 is missing or a field is null).
        src = ABS_DATE_MAP.get(sid)
        if src and src in v1_dates:
            for k in ("last_release_date", "next_release_estimate"):
                v = v1_dates[src].get(k)
                if v:
                    ind[k] = v
            abs_synced.append(sid)
        # last_release_date describes a past event — the data is already in
        # our file, so it cannot be in the future. Clamp if the heuristic ran
        # ahead of itself.
        lrd = ind.get("last_release_date")
        if lrd and lrd > today_iso:
            ind["last_release_date"] = today_iso
            clamped.append(f"{sid} {lrd}->{today_iso}")
        ind["series"] = new

    json.dump(doc, open(IND, "w"), indent=2)
    print(f"indicators_v2.json regenerated ({len(doc['indicators'])} indicators).")
    if advanced:
        print("Advanced:", ", ".join(advanced))
    else:
        print("All indicators already current.")
    if abs_synced:
        print(f"ABS dates synced from v1 ({len(abs_synced)}):", ", ".join(abs_synced))
    if clamped:
        print(f"Clamped future last_release_date to today ({len(clamped)}):", ", ".join(clamped))


if __name__ == "__main__":
    main()
