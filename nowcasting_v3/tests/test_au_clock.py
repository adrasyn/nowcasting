"""The pipeline's as-of date is Sydney's, not UTC's.

The weekly crons fire on Sunday evening UTC so the whole sequence finishes
before 9 am Sydney on Monday. That instant is Monday in Sydney and Sunday in
UTC, and every vintage the pipeline writes is keyed on the Monday, so a UTC
date would key the week's work to the wrong day.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from nyfed.au.clock import RUN_TZ, now, today, today_str


def test_today_returns_a_date():
    d = today()
    assert isinstance(d, dt.date) and not isinstance(d, dt.datetime)
    assert today_str() == d.isoformat()


def test_the_v3_cron_instant_is_the_monday_in_sydney():
    # 20:30 UTC on Sunday 13 September 2026 -- the v3 weekly cron -- is
    # 06:30 on Monday the 14th in Sydney.
    fired = dt.datetime(2026, 9, 13, 20, 30, tzinfo=dt.UTC)
    assert fired.astimezone(ZoneInfo(RUN_TZ)).date() == dt.date(2026, 9, 14)
    assert fired.date() == dt.date(2026, 9, 13)


def test_the_v2_cron_instant_is_the_monday_in_sydney_in_both_halves_of_the_year():
    # 19:00 UTC Sunday, in AEST (UTC+10) and again in AEDT (UTC+11).
    aest = dt.datetime(2026, 8, 30, 19, 0, tzinfo=dt.UTC)
    aedt = dt.datetime(2026, 11, 1, 19, 0, tzinfo=dt.UTC)
    assert aest.astimezone(ZoneInfo(RUN_TZ)).date() == dt.date(2026, 8, 31)
    assert aedt.astimezone(ZoneInfo(RUN_TZ)).date() == dt.date(2026, 11, 2)
    for instant in (aest, aedt):
        assert instant.astimezone(ZoneInfo(RUN_TZ)).weekday() == 0  # Monday


def test_now_is_sydney_local_and_agrees_with_today():
    n = now()
    assert n.tzinfo is not None
    assert n.utcoffset() in (dt.timedelta(hours=10), dt.timedelta(hours=11))
    assert n.date() == today()
