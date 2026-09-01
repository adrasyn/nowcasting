"""Assert the published payload is coherent. Run after the weekly nowcast.

WHY THIS EXISTS. The weekly job already alerts when a step THROWS — the
workflow's failure handler opens an issue. It says nothing when the job succeeds
and publishes something wrong, and the case that matters is the quarter
transition: the ABS prints a quarter on the Wednesday and the target has to roll
forward on the Monday. Getting that wrong publishes a nowcast of a quarter the
ABS has already measured, which is not a bad estimate but a category error, and
nothing downstream would notice.

These are invariants, not thresholds. Every one of them is true of any correct
payload in any week, so a failure here is a bug and not a judgement call. That is
the bar for putting a check in front of a publish: a check that needs a human to
decide whether it matters will eventually be ignored.

Usage:  python tools/check_payload.py [path-to-latest_v3.json]
Exits 1 and prints ::error:: lines on failure, so the workflow fails and the
existing alert path opens an issue.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

__all__ = ["check_payload", "quarter_key"]


def quarter_key(label: str) -> tuple[int, int]:
    """``"2026 Q2"`` -> ``(2026, 2)``, so quarters compare in calendar order."""
    year, q = label.split(" Q")
    return int(year), int(q)


def check_payload(d: dict, *, today: str | None = None) -> list[str]:
    """Return a list of problems. Empty means the payload is coherent."""
    bad: list[str] = []
    status = d.get("status")
    if status not in {"ok", "refused"}:
        return [f"status is {status!r}, expected 'ok' or 'refused'"]
    if status == "refused":
        # A refusal is a successful run that declines to publish a number. It
        # carries no horizons by design, so there is nothing further to check.
        return bad

    horizons = d.get("horizons") or []
    if not horizons:
        return ["status is 'ok' but there are no horizons"]

    nowcast = next((h for h in horizons if h.get("kind") == "nowcast"), None)
    if nowcast is None:
        bad.append("no horizon is marked 'nowcast'")
        return bad

    # THE ONE THAT MATTERS. The nowcast target must be a quarter the ABS has not
    # published. `prev_level` names the last published quarter, so the target has
    # to sit strictly after it. If the target ever fails to roll forward after a
    # print, the page headlines an estimate of a quarter that is already
    # measured — the failure this whole check exists for.
    prev = (d.get("prev_level") or {}).get("quarter")
    if prev:
        if quarter_key(nowcast["quarter"]) <= quarter_key(prev):
            bad.append(
                f"nowcast target {nowcast['quarter']} is not after the last "
                f"published quarter {prev} — the target did not roll forward")

    # A nowcast with no month of its own data is not a nowcast. The forecast
    # horizons are allowed to have none; they are simply not recorded.
    months = nowcast.get("months_with_data")
    if months is not None and months < 1:
        bad.append(f"nowcast {nowcast['quarter']} has {months} months of data")

    # Nothing with zero months may reach the evolution chart. `run_au_nowcast`
    # declines to record those rows because the model conditioning on nothing
    # returns the trend anchor, and a flat line of anchors reads as a settled
    # view rather than the absence of one.
    for v in d.get("vintages") or []:
        if v.get("months_with_data") == 0:
            bad.append(
                f"vintage {v['run_date']} for {v['target_quarter']} has no "
                "month of data and should not have been recorded")

    # `data_through` names the last month carrying an observation. A month in
    # the future means the panel was padded into the payload, which is the bug
    # that had the page claiming August data while August was empty.
    now = today or datetime.now(UTC).strftime("%Y-%m")
    through = d.get("data_through")
    if through and through > now:
        bad.append(f"data_through {through} is in the future (now {now})")

    return bad


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        Path(__file__).resolve().parents[2] / "data" / "latest_v3.json")
    problems = check_payload(json.loads(path.read_text()))
    for p in problems:
        print(f"::error::{path.name}: {p}", file=sys.stderr)
    if problems:
        return 1
    print(f"{path.name}: coherent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
