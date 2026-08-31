"""Write `data/indicators_v3.json`: the model's inputs, for the site's panel.

SEPARATE FROM THE NOWCAST RUNNER ON PURPOSE. These are the model's INPUTS, not
its output -- no sampler is involved, so tying them to a 95-minute production run
would mean the panel display could only ever be as fresh as the last estimation.
`tools/emit_backtest_json.py` is separate for the same reason.

Shape matches `data/indicators_v2.json` exactly, so the site's existing
`IndicatorGrid` renders it without a v3-specific component. Groups come from the
spec's own `Category` column rather than being mapped onto v2's group names: the
two panels are different, and pretending otherwise would put ABS Building
Approvals under a heading invented for v2's credit aggregates.

    cd nowcasting_v3
    caffeinate -i .venv/bin/python -u tools/emit_indicators.py [--vintage]
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from nyfed.au.build import fetch_vintage, load_vintage
from nyfed.au.sources import AU_SERIES

REPO = Path(__file__).resolve().parents[1]
OUT = REPO.parent / "data" / "indicators_v3.json"
SPEC = REPO / "model_spec_AU.csv"

# How many months of history each sparkline carries. v2's payload holds ~4
# years; matching it keeps the two pages' sparklines visually comparable.
N_MONTHS = 50


def main() -> int:
    if "--vintage" in sys.argv:
        vint = load_vintage(REPO / "tests/fixtures/au/vintage")
    else:
        print("fetching live...", flush=True)
        vint = fetch_vintage()

    with SPEC.open(newline="") as fh:
        spec = {r["SeriesID"]: r for r in csv.DictReader(fh)}

    indicators = []
    for s in AU_SERIES:
        obs = vint.series.get(s.key)
        if obs is None or obs.dropna().empty:
            print(f"  {s.key}: no observations, skipped", flush=True)
            continue
        obs = obs.dropna().tail(N_MONTHS)
        row = spec.get(s.series_id, {})
        last = obs.index[-1]
        indicators.append({
            "id": s.key,
            "name": s.name,
            "group": row.get("Category", "Other"),
            "unit": row.get("Units", ""),
            # The publisher, not the fetcher: a reader wants to know who made the
            # number, not which of our functions retrieved it.
            "source": {"abs": "ABS", "rba": "RBA",
                       "v2": "v2 panel"}.get(s.fetcher, s.fetcher),
            "series": [{"date": f"{d.year}-{d.month:02d}", "value": float(v)}
                       for d, v in obs.items()],
            # What the freshness guard is measuring against, surfaced so a reader
            # can see why the model would refuse rather than only that it did.
            "last_release_date": str(
                (last + pd.Timedelta(days=s.publication_lag_days)).date()),
        })
        print(f"  {s.key:22s} {len(obs):3d} pts through {last.date()}", flush=True)

    payload = {
        "schema": "v3-indicators-1",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "indicators": indicators,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"\nwrote {OUT} ({len(indicators)} indicators)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
