"""Build `data/first_print_misses.csv`: the model's miss against the first print.

Seeds the bias correction (`nyfed/au/bias_correction.py`) from the Plan C
backtest of the model trained on first-print GDP:

  2022Q4-2026Q1  docs/measurements/2026-09-09-plan-c-first-print-target.csv
  2026Q1-2026Q2  docs/measurements/2026-09-10-plan-c-2026q2-extension-first_print.csv

Both files carry one row per (target, asof, seed). The model's FINAL NOWCAST for
a target quarter is the median over seeds at the LAST `asof` for that target --
the last vintage before the ABS printed it, which is the figure a reader would
have been looking at on release morning. The median is over sampler seeds, so it
is the model's central call rather than one chain's. Rows with no `nowcast_qq`
are dropped before any of this; where the two files overlap (2026Q1) they are
concatenated first, so the later file's later vintage wins on its own merits.

`miss_pp` is that nowcast minus the ABS first print for the quarter, both in
percent, so a positive miss is an over-prediction. Release dates come from the
scheduling rule in `nyfed/au/emit.gdp_release_date`.

After this tool has run once the weekly job appends new quarters itself
(`nyfed.au.bias_correction.append_miss`); re-run this only to rebuild the
backtest era from scratch, and expect it to overwrite any `live` rows.

    cd nowcasting_v3
    .venv/bin/python tools/build_first_print_misses.py
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from nyfed.au.emit import gdp_release_date

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO.parent
SOURCES = [
    ROOT / "docs/measurements/2026-09-09-plan-c-first-print-target.csv",
    ROOT / "docs/measurements/2026-09-10-plan-c-2026q2-extension-first_print.csv",
]
OUT = REPO / "data" / "first_print_misses.csv"


def main() -> int:
    frames = [pd.read_csv(p, dtype={"target": str}) for p in SOURCES]
    d = pd.concat(frames, ignore_index=True)
    d = d[d["nowcast_qq"].notna()]

    rows = []
    for target, g in d.groupby("target", sort=True):
        last = g[g["asof"] == g["asof"].max()]
        model = round(float(last["nowcast_qq"].median()), 4)
        first = round(float(last["first_print_qq"].iloc[0]), 4)
        label = f"{target[:4]} Q{target[-1]}"
        # NO DATE MEANS NO ROW. `rolling_miss` selects on `release_date`, so an
        # empty one would sort to the front and quietly drop out of every
        # window; a target label the rule cannot parse is a broken measurement
        # file, not a quarter to record without a date.
        release = gdp_release_date(label)
        if release is None:
            raise ValueError(
                f"{target!r} does not parse as a quarter, so it has no ABS "
                f"release date; fix the target column in {SOURCES}")
        rows.append({
            "quarter": target,
            "release_date": release,
            "model_qoq_pct": model,
            "first_print_qoq_pct": first,
            "miss_pp": round(model - first, 4),
            "source": "backtest",
        })

    out = pd.DataFrame(rows).sort_values("quarter").reset_index(drop=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT, index=False)
    print(f"wrote {OUT}: {len(out)} quarters "
          f"{out.quarter.iloc[0]}..{out.quarter.iloc[-1]}, "
          f"mean miss {out.miss_pp.mean():+.4f}pp, "
          f"last 8 {out.miss_pp.tail(8).mean():+.4f}pp")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
