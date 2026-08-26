"""Record one full-history Australian vintage for the end-to-end gate.

Run from the ``nowcasting_v3`` directory, with network access:

    caffeinate -i .venv/bin/python tools/record_au_vintage.py

Writes ``tests/fixtures/au/vintage/`` -- every registered series and every
deflator tier, full history, exactly as the live fetchers return them.
``tests/test_au_end_to_end.py`` replays it instead of fetching, so that the
gate does not depend on four hosts staying up, does not turn a ``readabs``
warning into an unrelated failure under ``filterwarnings = ["error"]``, and
measures the same panel next week as it does today.

The recording is checked, not trusted. ``test_the_recorded_vintage_agrees_with
_the_verified_payloads`` compares it against the trimmed ABS and RBA fixtures,
which are themselves pinned to published releases, and ``load_vintage`` refuses
a recording whose locators no longer match ``sources.py``.

Re-record after a registry locator change, or when the gate should move to a
newer vintage. ABS revises seasonally adjusted series, so the pinned figures in
``tests/test_au_end_to_end.py`` may move with it -- re-verify them against the
release rather than editing them to match.
"""

from pathlib import Path

from nyfed.au.build import fetch_vintage, save_vintage

out = Path("tests/fixtures/au/vintage")
vintage = fetch_vintage()
save_vintage(vintage, out)

for name, group in (("series", vintage.series), ("deflator", vintage.deflator_sources)):
    for key, s in group.items():
        observed = s.dropna()
        print(
            f"{name:9s} {key:22s} n={len(observed):4d}  "
            f"{observed.index[0].date()}..{observed.index[-1].date()}"
        )
print(f"wrote {out} at {vintage.recorded_at}")
