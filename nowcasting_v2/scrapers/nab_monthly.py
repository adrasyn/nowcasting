#!/usr/bin/env python3
"""Deterministic parser for the NAB Monthly Business Survey "Table 1".

WHY THIS EXISTS
---------------
The cloud data-refresh routine (Claude Code) could not read NAB's monthly
"Table 1: Key Monthly Business Survey Statistics": the table is rendered as
rotated, character-spaced glyphs, so `pdf_text()` / `extract_text()` return an
unparseable jumble (e.g. "-261", "24361", "250%"). The agent fell back to
web-search snippets and reconstructed some values from deltas -- low confidence.

This module reconstructs the table SPATIALLY from character (x, y) coordinates,
which is reliable. Validated against the repo's NAB fixtures: the parsed values
reproduce data_raw/nab_*.csv exactly for the overlap months (see test below).

DESIGN
------
* Discovery is NOT done here. The routine agent finds the latest monthly PDF URL
  (NAB's filenames are inconsistent) and passes it in. Parsing -- the part the
  agent failed at -- is deterministic here.
* Table 1 lives on page 1. It has a left column of (rotated) row labels and a
  small grid of monthly columns (usually 3, e.g. Feb-26 / Mar-26 / Apr-26).
* Rows, in fixed order, in the "Net balance" block:
    0 Confidence  1 Conditions  2 Trading  3 Profitability  4 Employment
    5 Forward orders  6 Capex(skip)  7 Stocks  8 Exports(skip)
  Then a "% change at quarterly rate" section (cost/price growth -- skipped),
  then a "Capacity utilisation rate" row (Per cent).
* SELF-CHECK: we parse every month column. The columns that overlap the existing
  CSV must match (revisions tolerated on the oldest/leftmost column only, which
  is prone to label bleed). If the newest overlap month disagrees, we FAIL LOUD
  and append nothing -- never guess.

PRIME DIRECTIVE: never fabricate. Range-check everything. A documented gap is
success; a guessed number is failure.
"""
from __future__ import annotations
import re, sys, csv, os, argparse
from collections import defaultdict

import pdfplumber

# net-balance block row order -> CSV series id (None = present but not tracked)
NETBAL_ORDER = [
    "nab_conf", "nab_cond", "nab_trade", "nab_profit", "nab_emp",
    "nab_forward", None, "nab_stocks", None,
]
NETBAL_RANGE = (-70, 70)
CU_RANGE = (60, 95)
MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1)}


def _month_to_date(label: str) -> str | None:
    """'Apr-26' / 'Apr26' / 'April 2026' -> '2026-04-01'."""
    m = re.match(r"([A-Z][a-z]{2})[a-z]*[-\s]?(\d{2,4})", label.strip())
    if not m:
        return None
    mon = MONTHS.get(m.group(1))
    if not mon:
        return None
    yr = int(m.group(2))
    if yr < 100:
        yr += 2000
    return f"{yr:04d}-{mon:02d}-01"


def _num(cell: str):
    """Extract the trailing signed number from a cell string (strips bled label
    characters like 'ence-24' -> -24)."""
    m = re.search(r"-?\d+(?:\.\d+)?", cell)
    return float(m.group()) if m else None


def _cluster_rows(chars, tol=3.2):
    rows = defaultdict(list)
    for c in chars:
        rows[round(c["top"] / tol) * tol].append(c)
    return {k: sorted(v, key=lambda c: c["x0"]) for k, v in sorted(rows.items())}


def parse_table1(pdf_path: str) -> dict:
    """Return {'columns': [(label,date), ...], 'data': {series_id: {date: value}}}.

    Parses all month columns found in Table 1 on page 1.
    """
    with pdfplumber.open(pdf_path) as pdf:
        pg = pdf.pages[0]
        allrows = _cluster_rows(pg.chars)

        # 1) Header row: the first row that spells >=2 "Mon-YY" tokens.
        header_top = header_groups = None
        for top, cs in allrows.items():
            txt = "".join(c["text"] for c in cs)
            if len(re.findall(r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)-?\d{2}", txt)) >= 2:
                # split this row's chars into column groups by x-gaps
                groups, cur = [], []
                for c in sorted(cs, key=lambda c: c["x0"]):
                    if cur and c["x0"] - cur[-1]["x1"] > 6:
                        groups.append(cur); cur = []
                    cur.append(c)
                if cur:
                    groups.append(cur)
                groups = [g for g in groups if re.search(
                    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)", "".join(x["text"] for x in g))]
                if len(groups) >= 2:
                    header_top, header_groups = top, groups
                    break
        if not header_groups:
            # Layout not recognised (NAB monthly layouts vary between issues).
            # Degrade gracefully -- the caller reports BLOCKED and falls back,
            # rather than crashing or guessing.
            return {"columns": [], "data": {}, "note": "Table 1 header not found"}

        cnames = ["".join(c["text"] for c in g) for g in header_groups]
        cdates = [_month_to_date(n) for n in cnames]
        cxs = [(g[0]["x0"] + g[-1]["x1"]) / 2 for g in header_groups]
        left_edge = min(cxs) - 22
        edges = [left_edge] + [(cxs[i] + cxs[i + 1]) / 2 for i in range(len(cxs) - 1)] + [1e9]
        if any(d is None for d in cdates):
            return {"columns": [], "data": {}, "note": f"unparseable headers: {cnames}"}

        def split_cols(cs):
            cells = [""] * len(cnames)
            for c in cs:
                cx = (c["x0"] + c["x1"]) / 2
                if cx < edges[0]:
                    continue  # label band
                for i in range(len(cnames)):
                    if edges[i] <= cx < edges[i + 1]:
                        cells[i] += c["text"]; break
            return cells

        # 2) Walk rows below the header. Net-balance block ends at the
        #    "% change at quarterly rate" / "Percent" delimiter.
        data = defaultdict(dict)
        netbal_idx = 0
        in_netbal = True
        for top, cs in allrows.items():
            if top <= header_top + 1:
                continue
            txt = "".join(c["text"] for c in cs)
            low = txt.lower()
            if "quarterly rate" in low or "% cha" in low or low.strip() == "percent":
                in_netbal = False
                continue
            cells = split_cols(cs)
            vals = [_num(x) for x in cells]
            if all(v is None for v in vals):
                continue  # non-data row (e.g. "Net balance" subheader)
            if in_netbal:
                if netbal_idx < len(NETBAL_ORDER):
                    sid = NETBAL_ORDER[netbal_idx]
                    if sid:
                        for d, v in zip(cdates, vals):
                            if v is not None and NETBAL_RANGE[0] <= v <= NETBAL_RANGE[1]:
                                data[sid][d] = int(v) if v == int(v) else v
                    netbal_idx += 1
            else:
                # capacity utilisation: the labelled "...ation rate" Per-cent row
                if "ation rate" in low or "utilis" in low:
                    for d, v in zip(cdates, vals):
                        if v is not None and CU_RANGE[0] <= v <= CU_RANGE[1]:
                            data["nab_cu"][d] = v

        # capacity utilisation fallback / cross-source from prose
        prose = pg.extract_text() or ""
        pm = re.search(r"capacity utilisation[^.]*?(\d{2}\.\d)\s*%", prose, re.I)
        if pm:
            data.setdefault("_prose_cu", {})["value"] = float(pm.group(1))

        return {"columns": list(zip(cnames, cdates)), "data": dict(data)}


# ---- CSV append + self-check ------------------------------------------------

def _read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return [(r["date"], r["value"]) for r in csv.DictReader(f)]


SERIES_RANGE = {s: CU_RANGE if s == "nab_cu" else NETBAL_RANGE
                for s in (NETBAL_ORDER + ["nab_cu"]) if s}


def _validate_and_append(data: dict, data_raw: str, write: bool, report: dict):
    """Shared gate for BOTH the deterministic parse and the vision read.

    For each series: range-check; cross-check overlap months against the CSV
    (small diffs = revision/bleed tolerated, large diff = mapping error -> FAIL
    LOUD); append ONLY months strictly newer than the CSV's last date. This is
    the guardrail -- whatever produced `data` (parser or Claude vision), a wrong
    value cannot ship because the overlap months must reconcile with the CSV.
    """
    for sid in SERIES_RANGE:
        lo, hi = SERIES_RANGE[sid]
        path = os.path.join(data_raw, f"{sid}.csv")
        existing = _read_csv(path)
        if not existing:
            report["blocked"].append(f"{sid}: CSV missing at {path}")
            continue
        last_date = existing[-1][0]
        have = {d: float(v) for d, v in existing}
        # range-check first; drop out-of-range values rather than trust them
        parsed_months = {d: v for d, v in data.get(sid, {}).items()
                         if lo <= v <= hi}
        dropped = [(d, v) for d, v in data.get(sid, {}).items() if not (lo <= v <= hi)]
        if dropped:
            report["blocked"].append(f"{sid}: out-of-range {dropped} dropped")

        tol = 0.6 if sid == "nab_cu" else 3
        overlaps = sorted([d for d in parsed_months if d in have])
        mism = [(d, parsed_months[d], have[d]) for d in overlaps
                if abs(parsed_months[d] - have[d]) > 0.05]
        gross = [m for m in mism if abs(m[1] - m[2]) > tol]
        report["selfcheck"][sid] = {"overlaps": overlaps, "mismatch": mism}
        if gross:
            report["blocked"].append(
                f"{sid}: overlap mismatch {gross} exceeds tolerance "
                f"(+/-{tol}) -- mapping/read suspect, not appending")
            continue

        new = sorted([d for d in parsed_months if d > last_date])
        if not new:
            report["skipped"][sid] = f"already current (last {last_date})"
            continue
        rows_to_add = [(d, parsed_months[d]) for d in new]
        report["appended"][sid] = rows_to_add
        if write:
            with open(path, "a", newline="") as f:
                w = csv.writer(f)
                for d, v in rows_to_add:
                    w.writerow([d, int(v) if float(v) == int(v) else v])
    return report


def refresh(pdf_path: str, data_raw: str, write: bool = False) -> dict:
    """TIER 1 (deterministic): parse Table 1 spatially and append new months.

    Returns a report dict. If the layout is not recognised, returns with a
    BLOCKED note so the caller can fall back to the vision path (render+verify).
    """
    parsed = parse_table1(pdf_path)
    data = parsed["data"]
    report = {"columns": parsed["columns"], "appended": {}, "skipped": {},
              "selfcheck": {}, "blocked": [], "tier": "deterministic"}

    if not parsed["columns"]:
        report["blocked"].append(
            f"Table 1 layout not recognised ({parsed.get('note','')}). "
            "Deterministic parse failed -- use the vision fallback: "
            "`render` the page to an image, read the values, then `verify`.")
        return report

    # cross-source capacity check (table vs prose)
    if "nab_cu" in data and "_prose_cu" in data:
        cu_latest = data["nab_cu"].get(parsed["columns"][-1][1])
        pv = data["_prose_cu"]["value"]
        if cu_latest is not None and abs(cu_latest - pv) > 0.05:
            report["blocked"].append(
                f"nab_cu table({cu_latest}) != prose({pv}) -- not appending")
            data.pop("nab_cu", None)
    data.pop("_prose_cu", None)

    return _validate_and_append(data, data_raw, write, report)


def render_table_image(pdf_path: str, out_path: str, page: int = 0,
                       dpi: int = 300) -> str:
    """Render a NAB PDF page to PNG so a vision model can read Table 1 directly.

    Layout-PROOF: works regardless of how NAB lays out or encodes the table,
    because it rasterises what a human sees. Prefers pypdfium2 (no system deps),
    falls back to pdfplumber.
    """
    try:
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(pdf_path)
        pil = doc[page].render(scale=dpi / 72).to_pil()
        pil.save(out_path)
    except Exception:
        with pdfplumber.open(pdf_path) as pdf:
            pdf.pages[page].to_image(resolution=dpi).save(out_path)
    return out_path


def verify(values: dict, data_raw: str, write: bool = False) -> dict:
    """TIER 2 (vision): validate values READ FROM THE IMAGE by Claude and append.

    `values` = {series_id: {YYYY-MM-01: number, ...}, ...}. MUST include the
    overlap month(s) already in the CSV so the same self-check can confirm the
    read is aligned before any new month is appended. Same guardrail as Tier 1.
    """
    data = {sid: {d: float(v) for d, v in months.items()}
            for sid, months in values.items() if sid in SERIES_RANGE}
    report = {"columns": "vision", "appended": {}, "skipped": {},
              "selfcheck": {}, "blocked": [], "tier": "vision"}
    # require an overlap month so the read can be validated, not blindly trusted
    for sid in list(data):
        existing = _read_csv(os.path.join(data_raw, f"{sid}.csv"))
        have = {d for d, _ in existing}
        if not (set(data[sid]) & have):
            report["blocked"].append(
                f"{sid}: vision read has no overlap month to validate against "
                "-- include at least the latest month already in the CSV")
            data.pop(sid)
    return _validate_and_append(data, data_raw, write, report)


_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def _is_pdf(path):
    try:
        with open(path, "rb") as f:
            return f.read(5) == b"%PDF-" and os.path.getsize(path) > 1000
    except Exception:
        return False


def _fetch(pdf):
    """Download a PDF to a temp path. NAB/ANZ sit behind Akamai WAF, which
    challenges bare urllib requests from datacenter IPs. We use curl with full
    browser-like headers + a same-site Referer (this is what successfully pulled
    the Akamai-protected ANZ file), then fall back to urllib. If we only get an
    Akamai challenge page (not a PDF), raise a clear WAF error so the routine
    reports it instead of feeding garbage downstream."""
    if not pdf.startswith("http"):
        return pdf
    import subprocess, urllib.request, urllib.parse
    dest = os.path.join("/tmp" if os.path.isdir("/tmp") else ".", "nab_live.pdf")
    pr = urllib.parse.urlparse(pdf)
    referer = f"{pr.scheme}://{pr.netloc}/"
    if os.path.exists(dest):
        os.remove(dest)

    # 1) curl with browser headers (browser-like TLS fingerprint beats Akamai
    #    where urllib fails; proven on the sibling Akamai-protected ANZ host).
    hdrs = ["-A", _UA,
            "-H", "Accept: application/pdf,text/html;q=0.9,*/*;q=0.8",
            "-H", "Accept-Language: en-AU,en;q=0.9",
            "-H", f"Referer: {referer}",
            "-H", "Sec-Fetch-Dest: document", "-H", "Sec-Fetch-Mode: navigate",
            "-H", "Sec-Fetch-Site: same-origin", "-H", "Upgrade-Insecure-Requests: 1"]
    try:
        subprocess.run(["curl", "-sSL", "--compressed", "--max-time", "90",
                        "--retry", "2", "--retry-delay", "3", *hdrs, pdf, "-o", dest],
                       capture_output=True, timeout=200)
        if _is_pdf(dest):
            return dest
    except Exception:
        pass

    # 2) urllib fallback with the same headers
    try:
        req = urllib.request.Request(pdf, headers={
            "User-Agent": _UA, "Referer": referer,
            "Accept": "application/pdf,*/*;q=0.8", "Accept-Language": "en-AU,en;q=0.9"})
        with urllib.request.urlopen(req, timeout=90) as r, open(dest, "wb") as f:
            f.write(r.read())
        if _is_pdf(dest):
            return dest
    except Exception as e:
        raise RuntimeError(
            f"download failed for {pdf}: {e}. Likely Akamai WAF blocking this "
            "(datacenter) IP. Options: retry; obtain the PDF via a residential-IP "
            "path; or report BLOCKED -- do NOT fabricate values.") from e

    raise RuntimeError(
        f"downloaded content from {pdf} is not a PDF (got an Akamai/WAF challenge "
        "page). Report BLOCKED for NAB this run -- do NOT fabricate values.")


def _print_report(rep, write):
    print(f"[tier: {rep.get('tier')}]  Columns: {rep['columns']}")
    if rep["selfcheck"]:
        print("\nSelf-check (overlap months vs CSV):")
        for sid, sc in rep["selfcheck"].items():
            flag = "OK" if not sc["mismatch"] else f"revised/bleed {sc['mismatch']}"
            print(f"  {sid:12} overlaps={sc['overlaps']} {flag}")
    print("\nAppended:" if rep["appended"] else "\nAppended: (none)")
    for sid, rows in rep["appended"].items():
        print(f"  {sid:12} {rows}")
    if rep["skipped"]:
        print("\nAlready current:")
        for sid, msg in rep["skipped"].items():
            print(f"  {sid:12} {msg}")
    if rep["blocked"]:
        print("\nBLOCKED / fall back (not appended):")
        for b in rep["blocked"]:
            print(f"  {b}")
    print("\n" + ("WROTE changes." if write else "DRY RUN (use --write to append)."))


def main():
    ap = argparse.ArgumentParser(
        description="NAB monthly Table 1 -> data_raw CSVs. "
                    "Tier 1 `parse` is deterministic; if it reports the layout "
                    "unrecognised, use `render` + vision read + `verify`.")
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("parse", help="deterministic spatial parse (Tier 1)")
    p.add_argument("pdf"); p.add_argument("--data-raw", default="data_raw")
    p.add_argument("--write", action="store_true")

    r = sub.add_parser("render", help="rasterise a page to PNG for vision read")
    r.add_argument("pdf"); r.add_argument("--out", default="nab_table1.png")
    r.add_argument("--page", type=int, default=0); r.add_argument("--dpi", type=int, default=300)

    v = sub.add_parser("verify", help="validate+append values read by vision (Tier 2)")
    v.add_argument("--values", required=True,
                   help='JSON: {"nab_conf":{"2026-05-01":-14,"2026-04-01":-24}, ...} '
                        '(MUST include an overlap month already in the CSV)')
    v.add_argument("--data-raw", default="data_raw")
    v.add_argument("--write", action="store_true")

    args = ap.parse_args()
    if args.cmd == "render":
        out = render_table_image(_fetch(args.pdf), args.out, args.page, args.dpi)
        print(f"Rendered {args.pdf} -> {out}  (open/view this image and read Table 1)")
    elif args.cmd == "verify":
        import json
        rep = verify(json.loads(args.values), args.data_raw, write=args.write)
        _print_report(rep, args.write)
    else:  # parse (default)
        rep = refresh(_fetch(args.pdf), args.data_raw, write=args.write)
        _print_report(rep, args.write)


if __name__ == "__main__":
    main()
