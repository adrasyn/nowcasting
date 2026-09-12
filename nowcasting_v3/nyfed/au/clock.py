"""The run calendar, in Sydney time.

THE JOB'S "TODAY" IS SYDNEY'S, NOT UTC'S. The weekly workflows fire on Sunday
evening UTC (19:00 for v2, 20:30 for v3) so that the whole sequence -- v2,
v3, the combination, the deploy -- is finished before 9 am Sydney on Monday.
In UTC that instant is still Sunday. Every vintage the pipeline writes and
every row of run history is keyed on the MONDAY date, the R side computes its
vintage list from the latest Monday at or before "today", and the ABS's own
release calendar is Sydney time. A UTC date at that hour would key the week's
work to Sunday, put the v2 and v3 halves of the same run on different dates,
and make a Monday-morning release look like tomorrow's news.

So: one timezone constant, one `today()`, used by every tool that needs an
as-of date or a "today" to compare against.

Timestamps are a different thing and stay in UTC: `generated_at` and friends
are absolute instants carrying an explicit offset, so they are unambiguous
wherever they are read.
"""

from __future__ import annotations

import datetime as _dt
from zoneinfo import ZoneInfo

RUN_TZ = "Australia/Sydney"

__all__ = ["RUN_TZ", "now", "today", "today_str"]


def now() -> _dt.datetime:
    """The current instant, as a Sydney-local aware datetime."""
    return _dt.datetime.now(ZoneInfo(RUN_TZ))


def today() -> _dt.date:
    """Today's date in Sydney -- the pipeline's as-of date."""
    return now().date()


def today_str() -> str:
    """Today's Sydney date as ``YYYY-MM-DD``."""
    return today().isoformat()
