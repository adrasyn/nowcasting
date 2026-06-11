#!/usr/bin/env python3
"""Regression test for the NAB monthly Table 1 parser.

Validates the deterministic spatial parse against the repo's PDF fixtures by
checking the parsed values reproduce the curated data_raw/nab_*.csv on the
overlap months. Run:  python scrapers/test_nab_monthly.py
"""
import os, sys, csv
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nab_monthly import parse_table1, NETBAL_ORDER  # noqa

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures", "nab")
RAW = os.path.join(ROOT, "data_raw")


def csv_map(sid):
    p = os.path.join(RAW, f"{sid}.csv")
    with open(p, newline="") as f:
        return {r["date"]: float(r["value"]) for r in csv.DictReader(f)}


def check(fixture, tol_netbal=3, tol_cu=0.6):
    """Classify each parsed series the way the runtime guardrail does:
      - 'trusted' : newest overlap within tolerance -> would be appended.
      - 'blocked' : newest overlap grossly mismatches -> runtime blocks it
                    (falls back to vision). SAFE, not a failure.
    The SAFETY INVARIANT (what we assert): a 'trusted' series must reconcile
    with the CSV on ALL its overlap months. A trusted series that is correct on
    its newest overlap but wrong on an older one would mean a partial mismap the
    newest-overlap gate failed to catch -> a real failure.
    Returns (n_trusted, n_blocked, violations)."""
    parsed = parse_table1(os.path.join(FIX, fixture))
    if not parsed["columns"]:
        return None
    valid = {s for s in NETBAL_ORDER + ["nab_cu"] if s}
    trusted = blocked = 0
    violations = []
    for sid, months in parsed["data"].items():
        if sid not in valid:
            continue
        have = csv_map(sid)
        overlaps = sorted(d for d in months if d in have)
        if not overlaps:
            continue
        tol = tol_cu if sid == "nab_cu" else tol_netbal
        if abs(months[overlaps[-1]] - have[overlaps[-1]]) > tol:
            blocked += 1
            continue
        trusted += 1
        for d in overlaps:  # invariant: a trusted series is consistent throughout
            if abs(months[d] - have[d]) > tol:
                violations.append(f"{sid}@{d}: parsed {months[d]} vs csv {have[d]}")
    return trusted, blocked, violations


def main():
    fixtures = sorted(f for f in os.listdir(FIX) if f.startswith("nab_monthly_"))
    failed = False
    recognised = vision = 0
    for fx in fixtures:
        res = check(fx)
        if res is None:
            vision += 1
            print(f"  {fx:28} layout not recognised -> vision fallback")
            continue
        recognised += 1
        trusted, blocked, viol = res
        if viol:
            failed = True
            print(f"FAIL {fx:28} trusted-but-inconsistent: {viol}")
        else:
            print(f"  OK {fx:28} {trusted} trusted (CSV-reconciled), "
                  f"{blocked} blocked->vision")
    print(f"\n{recognised}/{len(fixtures)} layouts recognised, "
          f"{vision}/{len(fixtures)} -> vision fallback. "
          f"Safety invariant: {'VIOLATED' if failed else 'holds'} "
          "(no series ever trusted unless it reconciles with the CSV).")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
