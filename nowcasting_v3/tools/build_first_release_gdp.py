"""Build `data/gdp_first_release.csv`: first-release quarterly GDP growth.

Merges two sources into one file the package reads:

  1959Q4-2022Q2  nowcasting_v2/rba_paper/content/Data/rt_dgdp_qtr.csv
                 RBA RDP 2024-04 (Hartigan and Rosewall), who take first-release
                 GDP from Lee, Olekalns, Shields and Wang (2012), the Australian
                 Real-Time Database. NOT nowcasting_v2/data_raw/rt_dgdp_qtr.csv,
                 which is the latest vintage under a misleading name.
  2019Q2-        docs/measurements/2026-09-09-gdp-first-release-vs-latest-2019q2-2026q2.csv
                 parsed from the ABS 5206.0 Key Aggregates spreadsheet of each
                 release (series A2304402X levels, growth within the release).

Where both carry a quarter the ABS figure wins; the two agree to <0.02pp on all
13 overlapping quarters, which is the check that the RBA file really is first
prints. After this tool has run once the weekly job appends new quarters itself
(`nyfed/au/first_release.append_first_print`); re-run this only to rebuild
from scratch.

    cd nowcasting_v3
    .venv/bin/python tools/build_first_release_gdp.py
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from nyfed.au.emit import gdp_release_date

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO.parent
RBA = ROOT / "nowcasting_v2/rba_paper/content/Data/rt_dgdp_qtr.csv"
ABS = ROOT / "docs/measurements/2026-09-09-gdp-first-release-vs-latest-2019q2-2026q2.csv"
OUT = REPO / "data" / "gdp_first_release.csv"

MONTHS = ["jan", "feb", "mar", "apr", "may", "jun",
          "jul", "aug", "sep", "oct", "nov", "dec"]


def main() -> int:
    rba = pd.read_csv(RBA)
    rba["quarter"] = pd.to_datetime(rba["Date"], dayfirst=True).dt.to_period("Q").astype(str)
    rows = {q: {"quarter": q, "qoq_pct": round(float(v), 4), "release_date": "",
                "source": "rba_rdp_2024_04"}
            for q, v in zip(rba["quarter"], rba["RT-DGDP-QTR"])}

    abs_ = pd.read_csv(ABS, dtype={"quarter": str})
    for q, v in zip(abs_["quarter"], abs_["first_release_qoq"]):
        year, n = q.split("Q")
        tag = f"{MONTHS[3 * int(n) - 1]}-{year}"          # 2026Q2 -> jun-2026
        rows[q] = {"quarter": q, "qoq_pct": round(float(v), 4),
                   "release_date": gdp_release_date(f"{year} Q{n}") or "",
                   "source": f"abs_5206.0_{tag}"}

    out = pd.DataFrame(sorted(rows.values(), key=lambda r: pd.Period(r["quarter"], freq="Q")))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(OUT, index=False)
    print(f"wrote {OUT}: {len(out)} quarters {out.quarter.iloc[0]}..{out.quarter.iloc[-1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
