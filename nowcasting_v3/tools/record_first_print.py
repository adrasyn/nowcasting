"""Record the ABS first print and the model's miss against it, BEFORE the nowcast.

WHY IT IS A STEP OF ITS OWN. The published nowcast is the model's estimate less
the mean of that model's own last eight misses against the first print, read out
of `data/first_print_misses.csv` by `tools/run_au_nowcast.py`. Both appends used
to live in `tools/emit_backtest_json.py`, which the weekly workflow runs AFTER
the nowcast — so on the Monday after an ABS print the correction was measured
over a window that stopped one quarter short, and the quarter that had printed
five days earlier only reached the window a week later. The plan's Global
Constraint is that the correction at date d uses every quarter printed at or
before d. This tool exists so the weekly job can satisfy it: it runs first, the
nowcast reads what it wrote.

WHAT IT DOES, in order:

  1. fetch the ABS's published GDP levels (`first_release.published_gdp`),
  2. append the newest quarter to `data/gdp_first_release.csv` if it is new and
     fresh enough to still be a first print (`append_first_print`),
  3. append the model's miss against every newly printed quarter to
     `data/first_print_misses.csv`, taking what the model last said from the
     history log (`append_miss`).

EXIT CODES. 0 whenever the files are usable, including the ordinary case where
nothing is due to be appended -- three weeks in four there is no new print.
1 only when the first-print or misses file cannot be read or written: those two
files feed the PUBLISHED figure, and a nowcast computed from a half-written or
hand-broken misses file would be the wrong number under the right name.

THIS DOES NOT STOP THE WEEK'S NOWCAST. The weekly workflow runs this step with
`continue-on-error: true` and lets the nowcast proceed on the misses file as it
stood: `tools/run_au_nowcast.py` wraps its read of that file in `except
Exception` and publishes a refusal payload rather than a wrong number under the
right name, so the job does not need to stop here to avoid that outcome. The
workflow still fails itself afterward, once the week's payload is out, so a
bad file gets someone's attention instead of silently repeating next week.

A FAILED LIVE FETCH IS NOT THAT CASE. `published_gdp` falls back to the recorded
vintage and says so; if even that fails, this records nothing, says so, and
exits 0 -- the misses file is untouched, so the nowcast can still run on the
window it already had, and `emit_backtest_json.py` will try the same appends
again later in the job.

    cd nowcasting_v3
    .venv/bin/python tools/record_first_print.py
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from nyfed.au.bias_correction import MISSES_CSV, append_miss
from nyfed.au.clock import today_str
from nyfed.au.first_release import (
    FIRST_RELEASE_CSV, append_first_print, load_first_release, published_gdp,
)

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO.parent
HISTORY_JSON = ROOT / "data" / "nowcast_history_v3.json"
FALLBACK_VINTAGE = REPO / "tests" / "fixtures" / "au" / "vintage"


def _history_runs(path: Path) -> list[dict]:
    """The run log, or an empty list where there is none.

    `append_miss` needs it to find what the model last said about a quarter
    before the ABS printed it. A missing log is not an error here: a quarter
    with no surviving live nowcast is skipped loudly by `append_miss` itself.
    """
    if not Path(path).is_file():
        return []
    return json.loads(Path(path).read_text()).get("runs", [])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--first-release", type=Path, default=FIRST_RELEASE_CSV,
                    help="the first-print CSV to append to")
    ap.add_argument("--misses", type=Path, default=MISSES_CSV,
                    help="the misses CSV the bias correction is measured over")
    ap.add_argument("--history", type=Path, default=HISTORY_JSON,
                    help="the run log the model's final nowcast is read from")
    ap.add_argument("--asof", default=None,
                    help="the run date; defaults to today in Sydney")
    args = ap.parse_args(argv)
    # Sydney, not UTC: the weekly job runs Sunday evening UTC and the print it
    # records belongs to the Monday the rest of the run is keyed on.
    asof = args.asof or today_str()

    try:
        gdp = published_gdp(FALLBACK_VINTAGE)
    except Exception as exc:  # noqa: BLE001
        print(f"::warning::no published GDP to record ({type(exc).__name__}: "
              f"{exc}); nothing appended, the nowcast runs on the window it "
              "already has", flush=True)
        return 0

    try:
        recorded = append_first_print(args.first_release, gdp, asof=asof)
        first = load_first_release(args.first_release)
    except Exception as exc:  # noqa: BLE001
        print(f"::error::first-print file unusable ({type(exc).__name__}: "
              f"{exc}); the nowcast's bias correction is measured against it, "
              "nothing written", flush=True)
        return 1

    try:
        added = append_miss(args.misses, _history_runs(args.history), first,
                            asof=asof)
    except Exception as exc:  # noqa: BLE001
        print(f"::error::first-print miss file unusable ({type(exc).__name__}: "
              f"{exc}); the published nowcast's bias correction is measured "
              "from it, nothing written", flush=True)
        return 1

    print(f"first print: {recorded or 'nothing new'}; "
          f"misses appended: {', '.join(added) if added else 'none due'} "
          f"(asof {asof})", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
