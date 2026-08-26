"""Re-record the trimmed ABS fixtures behind tests/test_au_fetch_abs.py.

Run from the ``nowcasting_v3`` directory, with network access:

    caffeinate -i .venv/bin/python tools/record_au_fixtures.py

Each fixture is the last 36 observations of one ABS series, written with the
``PeriodIndex`` readabs returns rendered verbatim -- ``2026-07`` monthly,
``2026Q1`` quarterly. Do not pre-convert the index here: the test rebuilds it,
so that ``parse_abs_frame`` is exercised on the exact shape a real fetch hands
it, quarterly period dating included.

The pinned observations in ``test_a_verified_observation_pins_the_series_id``
are seasonally adjusted and ABS revises them, so a pin can start failing after
a re-record. That is the check working. Re-verify the value against the ABS
release named in the test's ``source`` string and update both together --
never edit the pin to match the data.
"""

from pathlib import Path

import readabs as ra

from nyfed.au.sources import AU_SERIES

out = Path("tests/fixtures/au")
out.mkdir(parents=True, exist_ok=True)
for s in AU_SERIES:
    if s.fetcher != "abs":
        continue
    cat, sid = s.locator.split(":")
    frame, _ = ra.read_abs_series(cat=cat, series_id=sid)
    frame.tail(36).to_csv(out / f"abs_{s.key}.csv")
    print(f"wrote {s.key} ({s.locator}): {len(frame.tail(36))} rows")
