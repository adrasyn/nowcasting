#!/usr/bin/env python3
"""Guarded ANZ–Roy Morgan MONTHLY refresh; no weekly substitution or fixture fallback.

Existing legacy vintages and final managed observations are immutable. Only newly
managed provisional months can be updated, with every version archived in metadata.
The default is a dry run. See docs/anz-monthly-refresh.md for the source policy.
"""
import argparse
import copy
import csv
import datetime as dt
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
URL = "https://www.roymorgan.com/morgan-poll/consumer-confidence-anz-roy-morgan-australian-cc-monthly-ratings"
HEADER = ["YEAR", "JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC", "YEARLY AVERAGE"]


class TableReader(HTMLParser):
    def __init__(self):
        super().__init__(); self.rows = []; self.row = None; self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr": self.row = []
        elif tag in ("td", "th") and self.row is not None: self.cell = ""

    def handle_data(self, data):
        if self.cell is not None: self.cell += data

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            self.row.append(self.cell.strip()); self.cell = None
        elif tag == "tr" and self.row is not None:
            self.rows.append(self.row); self.row = None


def parse_monthly(text, today):
    """Accept official HTML or verbatim browser-extracted monthly table text."""
    if not re.search(r"Australian CC Monthly Ratings", text, re.I):
        raise ValueError("Not the Australian monthly-ratings source (weekly data rejected)")
    if "<tr" in text.lower():
        parser = TableReader(); parser.feed(text); rows = parser.rows
    else:
        rows = [[c.strip() for c in line.split("|")] for line in text.splitlines() if "|" in line]
    rows = [[re.sub(r"\s+", " ", c).strip() for c in row] for row in rows]
    headers = [i for i, row in enumerate(rows) if [c.upper() for c in row] == HEADER]
    if len(headers) != 1:
        raise ValueError("Monthly header missing, duplicated or reordered")
    out = {}
    for row in rows[headers[0]+1:]:
        if not row or not re.fullmatch(r"\d{4}", row[0]): continue
        if len(row) != 14: raise ValueError("Wrong monthly column count")
        for month, cell in enumerate(row[1:13], 1):
            if not cell: continue
            match = re.fullmatch(r"(\d+(?:\.\d+)?)(\*\*|\*|#)?", cell)
            if not match: raise ValueError(f"Invalid monthly cell: {cell!r}")
            period = f"{row[0]}-{month:02d}-01"
            if period in out: raise ValueError("Duplicate monthly observation")
            if period[:7] > today.strftime("%Y-%m"): raise ValueError("Future observation")
            value = float(match[1])
            if not 50 <= value <= 150: raise ValueError("ANZ value outside 50–150")
            out[period] = {"value": value, "source_marker": match[2] or "",
                           "provisional": match[2] == "**" or period[:7] == today.strftime("%Y-%m")}
    if not out: raise ValueError("Empty monthly table")
    return dict(sorted(out.items()))


def read_csv(path):
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != ["date", "value"]: raise ValueError("Unexpected CSV schema")
        rows = list(reader)
    dates = [r["date"] for r in rows]
    if not dates or dates != sorted(set(dates)): raise ValueError("CSV dates not unique and ascending")
    for row in rows:
        if dt.date.fromisoformat(row["date"]).day != 1: raise ValueError("CSV date is not first of month")
        if not 50 <= float(row["value"]) <= 150: raise ValueError("CSV value outside range")
    return rows


def plan(rows, source, state, checked_at):
    """Pure validation and planning: all errors occur before any writes."""
    state = copy.deepcopy(state)
    old = {r["date"]: float(r["value"]) for r in rows}
    for day, point in state["observations"].items():
        if day > state["legacy_through"] and old.get(day) != point["value"]:
            raise ValueError("CSV and vintage metadata disagree")
    if set(old) - set(source): raise ValueError("Source truncated: missing existing months")
    audit = [{"date": day, "stored": value, "source": source[day]["value"]}
             for day, value in old.items() if value != source[day]["value"]]
    recent = list(old)[-12:]
    if sum(old[d] == source[d]["value"] for d in recent) < 2:
        raise ValueError("Insufficient matching recent overlap")
    frozen = {r["date"]: r for r in state["frozen_conflicts"]}
    changes = []
    for day, point in source.items():
        if day <= state["legacy_through"]:
            if day in old and old[day] != point["value"]:
                expected = frozen.get(day)
                if expected != {"date": day, "stored": old[day], "source": point["value"]}:
                    raise ValueError(f"Unreviewed legacy conflict at {day}; preserve history and report")
            continue
        previous = state["observations"].get(day)
        if day in old:
            if previous is None or previous["value"] != old[day]:
                raise ValueError("CSV and vintage metadata disagree")
            if previous["value"] == point["value"] and previous["provisional"] == point["provisional"]:
                continue
            if not previous["provisional"]:
                raise ValueError(f"Final observation revised at {day}; needs explicit review")
        changes.append({"date": day, "old": old.get(day), **point})
    dates = sorted(set(old) | {c["date"] for c in changes})
    new_dates = [d for d in dates if d > state["legacy_through"]]
    anchor = dt.date.fromisoformat(state["legacy_through"])
    for day in new_dates:
        year, month = (anchor.year+1, 1) if anchor.month == 12 else (anchor.year, anchor.month+1)
        if day != f"{year}-{month:02d}-01": raise ValueError("Gap in new monthly data; do not impute")
        anchor = dt.date.fromisoformat(day)
    for change in changes:
        state["observations"][change["date"]] = {
            k: change[k] for k in ("value", "source_marker", "provisional")}
    return changes, state, {"compared": len(old), "differences": audit, "checked_at": checked_at}


def update_indicator(ind, rows, state):
    """Display only; never touch model payloads or claim an observation was released today."""
    start = ind["series"][0]["date"]
    ind["series"] = []
    for row in rows:
        if row["date"][:7] < start: continue
        point = {"date": row["date"][:7], "value": float(row["value"])}
        if state["observations"].get(row["date"], {}).get("provisional"):
            point["provisional"] = True
        ind["series"].append(point)
    ind["latest_period"] = rows[-1]["date"][:7]
    ind["source"] = "ANZ–Roy Morgan (monthly)"
    ind["source_url"] = URL
    ind["source_checked_at"] = state["latest_source"]["retrieved_at"]
    ind["data_note"] = "Monthly average; provisional observations are labelled. Historical vintages are preserved."
    ind.pop("last_release_date", None)
    ind.pop("next_release_estimate", None)


def refresh(root, text, checked_at, source_format, write=False, sync_display=False):
    stamp = dt.datetime.fromisoformat(checked_at.replace("Z", "+00:00"))
    now = dt.datetime.now(dt.timezone.utc)
    if stamp.tzinfo is None or stamp > now: raise ValueError("Retrieval time must be timezone-aware and not in future")
    if now - stamp > dt.timedelta(days=7): raise ValueError("Saved retrieval is over a week old; fetch a fresh source")
    source = parse_monthly(text, stamp.date())
    csv_path = root/"nowcasting_v2/data_raw/anz_sent.csv"
    meta_path = root/"nowcasting_v2/data_raw/anz_sent.meta.json"
    rows = read_csv(csv_path); state = json.loads(meta_path.read_text())
    legacy = b"".join(line for line in csv_path.read_bytes().splitlines(keepends=True)
                       if line.startswith(b"date,") or line.split(b",")[0].decode() <= state["legacy_through"])
    if hashlib.sha256(legacy).hexdigest() != state["legacy_sha256"]:
        raise ValueError("Frozen legacy CSV bytes changed; preserve history and report")
    previous_check = state.get("latest_source", {}).get("retrieved_at")
    if previous_check and stamp < dt.datetime.fromisoformat(previous_check.replace("Z", "+00:00")):
        raise ValueError("Retrieval predates the accepted source; do not regress a provisional vintage")
    changes, state, audit = plan(rows, source, state, checked_at)
    result = {"changes": changes, "audit": audit, "write": write}
    if not changes or not write: return result
    digest = hashlib.sha256(text.encode()).hexdigest()
    archive = Path("nowcasting_v2/data_sources/anz_sent")/(digest+".txt")
    provenance = {"source_url": URL, "source_sha256": digest, "source_path": str(archive),
                  "source_format": source_format, "retrieved_at": checked_at,
                  "release_date": None}
    state["latest_source"] = provenance
    state["vintages"].append({**provenance, "changes": changes, "audit": audit})
    replacements = {c["date"]: c["value"] for c in changes}
    # Preserve the exact bytes of every existing row unless it is an explicitly
    # managed provisional update. Archives retain all such prior versions.
    original = csv_path.read_bytes().decode("utf-8")
    csv_text = "".join(
        f"{line.split(',')[0]},{replacements.pop(line.split(',')[0]):.1f}" + ("\r\n" if line.endswith("\r\n") else "\n")
        if line.split(',')[0] in replacements else line for line in original.splitlines(keepends=True))
    if replacements and not csv_text.endswith("\n"): csv_text += "\n"
    csv_text += "".join(f"{day},{value:.1f}\n" for day, value in sorted(replacements.items()))
    new_rows = list(csv.DictReader(csv_text.splitlines()))
    display_writes = {}
    for name in (("indicators_v2.json", "indicators_combo.json") if sync_display else ()):
        path = root/"data"/name
        if not path.exists(): continue
        doc = json.loads(path.read_text())
        for ind in doc["indicators"]:
            if ind["id"] == "anz_sent":
                update_indicator(ind, new_rows, state)
                ind["updated_this_run"] = False  # the model has not been rerun
        display_writes[path] = json.dumps(doc, indent=2)+"\n"
    # Every parse, overlap and final-vintage check has succeeded before writing.
    target = root/archive; target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.read_text() != text: raise ValueError("Archive hash collision")
    target.write_text(text)
    meta_path.write_text(json.dumps(state, indent=2)+"\n")
    csv_path.write_text(csv_text)
    for path, value in display_writes.items(): path.write_text(value)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-file", type=Path, help="Verbatim official HTML or browser-extracted monthly table")
    parser.add_argument("--retrieved-at", help="Actual UTC retrieval time; required for a saved source")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--sync-display", action="store_true", help="Repair only ANZ display artifacts without running a model")
    args = parser.parse_args()
    if args.source_file:
        if not args.retrieved_at: parser.error("--source-file requires --retrieved-at")
        text = args.source_file.read_text()
        kind = "saved-html" if "<tr" in text.lower() else "browser-extracted-monthly-table"
    else:
        # No fixture or stale-cache fallback. A network/source failure is BLOCKED.
        with urllib.request.urlopen(URL, timeout=30) as response: text = response.read().decode("utf-8")
        kind = "live-html"
    checked = args.retrieved_at or dt.datetime.now(dt.timezone.utc).isoformat()
    print(json.dumps(refresh(args.root, text, checked, kind, args.write, args.sync_display), indent=2))


if __name__ == "__main__":
    try: main()
    except (ValueError, OSError) as exc: raise SystemExit(f"BLOCKED ANZ monthly refresh: {exc}") from exc
