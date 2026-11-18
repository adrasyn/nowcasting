"""Regression test for the survey release-date schedule in gen_indicators_v2.py.

Guards the "Updated" / "Next release" columns of the indicator grid against the
bug where survey series rode a drifting month-shift heuristic and produced wrong
(and sometimes FUTURE) dates — e.g. ANZ-Roy Morgan showing a release in the next
month. Deterministic: `today` is injected, so it never depends on the wall clock.

Run: python3 nowcasting_v2/tests/test_release_schedule.py
"""
import sys, os, datetime, importlib.util

GEN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "gen_indicators_v2.py")
spec = importlib.util.spec_from_file_location("gen_indicators_v2", GEN)
gen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gen)

TODAY = datetime.date(2026, 7, 20)  # a Monday
sched = gen.SURVEY_SCHEDULE
fails = []


def check(label, got, want):
    ok = str(got) == str(want)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}: got={got} want={want}")
    if not ok:
        fails.append(label)


# NAB Monthly Business Survey: 2nd Tuesday of the month AFTER the reference month.
last, nxt = sched["nab_conf"](2026, 6, TODAY)
check("NAB Jun -> last_release", last, datetime.date(2026, 7, 14))
check("NAB Jun -> next_release", nxt, datetime.date(2026, 8, 11))

# Westpac-MI Consumer Sentiment: 2nd Tuesday of the SAME (data) month.
last, nxt = sched["wmi_sent"](2026, 7, TODAY)
check("Westpac Jul -> last_release", last, datetime.date(2026, 7, 14))
check("Westpac Jul -> next_release", nxt, datetime.date(2026, 8, 11))

# ANZ-Indeed Job Ads: full published schedule (1st Monday of the following month,
# holiday-adjusted; December -> 2nd Monday of January). Validated against ANZ's own
# release-dates table for the 2026 cycle.
ANZ_JOBADS_TABLE = {
    (2025, 12): datetime.date(2026, 1, 12),   # 2nd Monday of Jan (holiday season)
    (2026, 1):  datetime.date(2026, 2, 2),
    (2026, 2):  datetime.date(2026, 3, 2),
    (2026, 3):  datetime.date(2026, 4, 7),     # Easter Monday bump
    (2026, 4):  datetime.date(2026, 5, 4),
    (2026, 5):  datetime.date(2026, 6, 1),
    (2026, 6):  datetime.date(2026, 7, 6),
    (2026, 7):  datetime.date(2026, 8, 4),     # NSW Bank Holiday bump
    (2026, 8):  datetime.date(2026, 9, 7),
    (2026, 9):  datetime.date(2026, 10, 6),    # NSW Labour Day bump
    (2026, 10): datetime.date(2026, 11, 2),
    (2026, 11): datetime.date(2026, 12, 7),
}
for (yy, mm), want in ANZ_JOBADS_TABLE.items():
    check(f"ANZ Job Ads {yy}-{mm:02d} release", gen._anz_jobads_release(yy, mm), want)
# next_release for June data should be the July-data release (4 Aug).
_, nxt = sched["anz_ads"](2026, 6, TODAY)
check("ANZ Job Ads Jun -> next_release", nxt, datetime.date(2026, 8, 4))

# ANZ monthly observations must not acquire a release date from today's clock.
check("ANZ-RM has no wall-clock release rule", "anz_sent" in sched, False)

print("\nRESULT:", "ALL PASS" if not fails else f"{len(fails)} FAILURE(S): {fails}")
sys.exit(1 if fails else 0)
