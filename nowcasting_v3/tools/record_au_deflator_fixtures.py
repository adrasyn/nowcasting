"""Re-record the ABS payloads behind tests/test_au_deflator.py.

Run from the ``nowcasting_v3`` directory, with network access:

    caffeinate -i .venv/bin/python tools/record_au_deflator_fixtures.py

Unlike ``record_au_fixtures.py`` these are recorded WHOLE, not tailed. The
deflator is a splice over three overlapping index numbers and its whole point is
the early history: trimming any of them to the last 36 observations would delete
the overlaps the rebasing is computed over, and the fixture would no longer
exercise the code path that matters. They are small -- a CPI index number is
about fifteen bytes a month.

Household spending is recorded whole for the same reason: the test that the
deflated series starts at the same month as the nominal one (2012-07) cannot be
written against a 36-row tail.

The live monthly CPI tier is NOT recorded here. It is the registry's own ``cpi``
series, already recorded as ``abs_cpi.csv`` by ``record_au_fixtures.py``, and
``test_au_deflator.py`` reads that file -- so the two cannot drift apart.
"""

from pathlib import Path


def main() -> None:
    import readabs as ra

    from nyfed.au.deflator import DEFLATOR_SOURCES
    from nyfed.au.fetch_abs import CEASED_CATALOGUE_URLS

    out = Path("tests/fixtures/au")
    out.mkdir(parents=True, exist_ok=True)

    wanted = [
        (s.locator, f"abs_{s.key}.csv")
        for s in DEFLATOR_SOURCES
        if s.key != "cpi_monthly_live"
    ]
    wanted.append(("5682.0:A130200584T", "abs_household_spending_full.csv"))

    for locator, name in wanted:
        cat, series_id = locator.split(":", 1)
        frame, _ = ra.read_abs_series(
            cat=cat, series_id=series_id, url=CEASED_CATALOGUE_URLS.get(cat, "")
        )
        frame.to_csv(out / name)
        print(f"wrote {name} ({locator}): {len(frame)} rows")


if __name__ == "__main__":
    main()
