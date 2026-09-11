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

TWO PAYLOADS, ONE SET OF INVARIANTS. `data/latest_combo.json` — the
equal-weight average of v2 and v3 that the homepage publishes — is written in
this same schema and goes through this same function; the weekly job runs it
twice, once per file. Everything above holds for both, and the combination adds
two facts of its own: that the published figure really is the mean of the two
component figures, and that it sits inside its own 68% band.

ONE INVARIANT HAD TO BE GATED, AND HERE IS WHY. v3's headline is arithmetic:
the model's figure less its rolling miss. The combination's is not. It averages
two figures that have each ALREADY had their own correction taken off, and it
copies v3's `bias_correction` across as provenance for its v3 half, so
`qoq_growth_pct` equals `model_qoq_growth_pct` and differs from
`model_qoq_growth_pct - bias_correction.pp` by exactly v3's correction. That is
correct for an average and would fail the v3 identity on every combination
payload ever published, so the identity check is keyed on the payload's own
`schema`: a `combo-` schema gets the component-mean check in its place. The
correction's presence and plausible range are still asserted on both, because
the combination's v3 half is still built from it.

Usage:  python tools/check_payload.py [--file path] [path-to-latest_v3.json]
Exits 1 and prints ::error:: lines on failure, so the workflow fails and the
existing alert path opens an issue.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

__all__ = ["check_payload", "quarter_key"]

# The combination payloads declare themselves in `schema` ("combo-1"), which is
# what selects the invariants above. `method` says the same thing in prose and
# is checked too, so a payload that carries the combination's method under some
# other schema is not silently run through v3's arithmetic.
COMBO_SCHEMA_PREFIX = "combo-"
COMBO_METHOD_PREFIX = "equal-weight average"


def quarter_key(label: str) -> tuple[int, int]:
    """``"2026 Q2"`` -> ``(2026, 2)``, so quarters compare in calendar order."""
    year, q = label.split(" Q")
    return int(year), int(q)


def is_combination(d: dict) -> bool:
    """True for the equal-weight v2+v3 payload, which reports itself as such."""
    schema = d.get("schema") or ""
    method = d.get("method") or ""
    return (isinstance(schema, str) and schema.startswith(COMBO_SCHEMA_PREFIX)) or (
        isinstance(method, str) and method.startswith(COMBO_METHOD_PREFIX))


def _combination_problems(d: dict) -> list[str]:
    """The two invariants that belong to an average and not to a single model.

    THE PUBLISHED FIGURE IS THE MEAN, TO THE DIGIT. Equal weights are the whole
    claim the page makes about how the two models are put together, and it is
    the one thing a reader cannot check: both component figures are printed
    beside the average, so a weight that had quietly drifted would look like
    arithmetic nobody had done. Checked on every horizon and every vintage,
    because the evolution chart is drawn from the vintages and a weight that
    was right today and wrong in June is still wrong on the page.

    AND IT SITS INSIDE ITS OWN BAND. The bands are the average's past absolute
    errors placed either side of the point, so a point outside its own 68% band
    is not a wide interval but a band computed from something other than the
    figure it is drawn around.
    """
    bad: list[str] = []

    def check(where: str, qoq, parts: dict, lo, hi) -> None:
        missing = [k for k in ("v2", "v3")
                   if not isinstance(parts.get(k), (int, float))
                   or isinstance(parts.get(k), bool)]
        if missing:
            bad.append(f"{where}: the combination carries no {'/'.join(missing)} "
                       f"components, so nothing says what it is the average of")
        else:
            mean = round((parts["v2"] + parts["v3"]) / 2, 4)
            if not isinstance(qoq, (int, float)) or isinstance(qoq, bool) or \
                    abs(qoq - mean) > 1e-4:
                bad.append(f"{where}: qoq_growth_pct {qoq!r} is not the mean of its "
                           f"components (v2 {parts['v2']!r}, v3 {parts['v3']!r} -> "
                           f"{mean}); the page claims equal weights")
        if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) and \
                isinstance(qoq, (int, float)):
            if not (lo < qoq < hi):
                bad.append(f"{where}: the point {qoq!r} is outside its own 68% band "
                           f"[{lo!r}, {hi!r}]")
        else:
            bad.append(f"{where}: no 68% band, which the page draws around every point")

    for h in d.get("horizons") or []:
        check(h.get("quarter", "?"), h.get("qoq_growth_pct"),
              h.get("components") or {}, h.get("ci_68_low"), h.get("ci_68_high"))
    for v in d.get("vintages") or []:
        parts = {"v2": v.get("v2_qoq_growth_pct"), "v3": v.get("v3_qoq_growth_pct")}
        check(f"vintage {v.get('run_date', '?')} for {v.get('target_quarter', '?')}",
              v.get("qoq_growth_pct"), parts, v.get("ci_68_low"), v.get("ci_68_high"))
    return bad


def check_payload(d: dict, *, today: str | None = None) -> list[str]:
    """Return a list of problems. Empty means the payload is coherent."""
    bad: list[str] = []
    combo = is_combination(d)
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

    # No FORECAST with zero months may reach the evolution chart.
    # `run_au_nowcast` declines to record those rows because the model
    # conditioning on nothing returns the trend anchor, and a flat line of
    # anchors reads as a settled view rather than the absence of one.
    #
    # THE NOWCAST'S OWN ROW IS EXEMPT, and the two halves have to agree on that
    # or the exemption is dead. `run_au_nowcast` records a data-less nowcast on
    # purpose — "a fault to surface, not a row to drop" — and this loop used to
    # reject any zero-month vintage, so that row could never be surfaced; it
    # only blocked the week's publish, with a message about a vintage rather
    # than about the fault. The check above already names that fault directly,
    # so this one stays out of its way.
    for v in d.get("vintages") or []:
        if v.get("target_quarter") == nowcast["quarter"]:
            continue
        if v.get("months_with_data") == 0:
            bad.append(
                f"vintage {v['run_date']} for {v['target_quarter']} has no "
                "month of data and should not have been recorded")

    # THE HEADLINE IS ARITHMETIC ON THE MODEL'S FIGURE -- ON V3'S PAYLOAD.
    # `qoq_growth_pct` is the
    # published nowcast of the ABS's first print: the model's own estimate less
    # the model's rolling miss against past first prints. If the two stop
    # agreeing, the page headlines a number nothing on it explains. An 'ok'
    # payload without a correction has not had the bias taken off at all, so its
    # headline is mislabelled rather than merely unexplained. And the correction
    # itself is a mean of eight quarterly errors, historically inside +-0.35pp
    # each; one outside +-0.6 is a broken estimate, not a finding.
    #
    # THE IDENTITY IS SKIPPED ON THE COMBINATION, for the reason in the module
    # docstring: an average of two already corrected figures cannot satisfy it.
    # `_combination_problems` asserts the mean instead, so neither payload goes
    # unchecked on how its headline was made.
    adj = d.get("bias_correction")
    if adj is None:
        bad.append("status is 'ok' but bias_correction is absent: the published "
                   "figure is the model less its rolling miss and needs the correction "
                   "that made it")
    else:
        pp = adj.get("pp")
        if not isinstance(pp, (int, float)) or isinstance(pp, bool) or abs(pp) > 0.6:
            bad.append(f"bias_correction.pp is {pp!r}; expected a number within +-0.6")
        elif not combo:
            for h in horizons:
                model = h.get("model_qoq_growth_pct")
                if model is None or abs(h["qoq_growth_pct"] - (model - pp)) > 1e-3:
                    bad.append(f"{h['quarter']}: qoq_growth_pct {h['qoq_growth_pct']!r} is not "
                               f"model_qoq_growth_pct - bias_correction.pp ({model!r} - {pp})")

    # NO FIELD FROM A RETIRED DESIGN, anywhere. `revision_adjustment` (the mean
    # ABS revision, subtracted from a model trained on the revised vintage) and
    # `expected_first_print_pct` (a second headline figure beside the raw one)
    # each named the published quantity at some point. A payload carrying one of
    # them alongside `bias_correction` has been through half a migration, and
    # nothing downstream could say which field made its figures.
    retired = ("revision_adjustment", "expected_first_print_pct")
    for key in retired:
        if key in d:
            bad.append(f"the payload carries {key}, a field retired when the published "
                       "figure became the first-print model less its rolling miss")
    for h in horizons:
        for key in retired:
            if key in h:
                bad.append(f"{h['quarter']} carries {key}, a field retired when the "
                           "published figure became the first-print model less its "
                           "rolling miss")

    # AND THE PAYLOAD HAS TO SAY WHICH FIGURE IT IS. `basis` is what the site
    # reads to label the headline and the track record's actual column. An
    # arithmetically correct first-print nowcast carrying no basis, or another
    # one, is published under the wrong name.
    if d.get("basis") != "abs_first_print":
        bad.append(f"basis is {d.get('basis')!r}; the published figure is the "
                   "first-print nowcast and must say so")

    # AND WHICH TARGET THE MODEL BEHIND IT WAS FITTED ON. The rolling miss is
    # measured on a model trained on first prints; subtracting it from a model
    # trained on the revised vintage would double-count the ABS's average
    # revision. `run_au_nowcast.py` refuses that pairing outright, and this is
    # the last place it could still reach the site.
    if d.get("target") != "first_print":
        bad.append(f"target is {d.get('target')!r}; the model behind a published "
                   "figure must have been fitted on 'first_print' GDP")

    # `data_through` names the last month carrying an observation. A month in
    # the future means the panel was padded into the payload, which is the bug
    # that had the page claiming August data while August was empty.
    now = today or datetime.now(UTC).strftime("%Y-%m")
    through = d.get("data_through")
    if through and through > now:
        bad.append(f"data_through {through} is in the future (now {now})")

    if combo:
        bad.extend(_combination_problems(d))

    return bad


def main(argv: list[str] | None = None) -> int:
    default = Path(__file__).resolve().parents[2] / "data" / "latest_v3.json"
    ap = argparse.ArgumentParser(description=__doc__)
    # `--file` is what the workflow uses, so the two invocations read as two
    # named files rather than one named and one implied. The bare positional is
    # kept because every earlier caller and runbook passes the path that way.
    ap.add_argument("--file", dest="file", default=None)
    ap.add_argument("path", nargs="?", default=None)
    args = ap.parse_args(argv)
    path = Path(args.file or args.path or default)
    problems = check_payload(json.loads(path.read_text()))
    for p in problems:
        print(f"::error::{path.name}: {p}", file=sys.stderr)
    if problems:
        return 1
    print(f"{path.name}: coherent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
