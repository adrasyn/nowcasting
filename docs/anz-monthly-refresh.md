# ANZ–Roy Morgan monthly refresh

Keep ANZ consumer confidence and Westpac consumer sentiment as separate series.
ANZ's `anz_sent.csv` stores the official Australian **monthly** index. A weekly
headline, four-week moving average, New Zealand index, or locally averaged set
of weekly observations is not a substitute.

## Source and initial audit

Use the [official monthly-ratings table](https://www.roymorgan.com/morgan-poll/consumer-confidence-anz-roy-morgan-australian-cc-monthly-ratings).
`**` means an indicative average of the completed weeks so far. Preserve that
flag even on a previous calendar month; do not infer finality from month end.
Treat the current calendar month as provisional even if its flag is missing.
The source's publication date is not supplied by this table. Retrieval time
must never be represented as its release date.

The 18 November 2026 audit compared all 578 existing observations with that
table. Exactly two differed:

| Month | Preserved CSV | Current table | Decision |
| --- | ---: | ---: | --- |
| May 2026 | 66.5 | 66.0 | Original panel metadata identifies 66.5 as indicative. Preserve and label provisional. |
| July 2026 | 75.0 | 75.4 | Added by `8a1379b4ab7a75c778a1a3e11894231a77c15d7a` on 20 July, before month end. Original aggregation is not archived. Preserve and conservatively label provisional. |

No old numerical value was rewritten. All other 576 observations matched.
The new source supplied August 74.4 and September 74.6 without flags, October
67.7** and November 65.3**. All four can be appended with their source status;
October and November must be shown as provisional. They are monthly figures,
not the 17 November weekly headline of 66.6. The complete monthly table excerpt
and its SHA-256 are archived under `nowcasting_v2/data_sources/anz_sent/` and in
`anz_sent.meta.json`. The excerpt was obtained through the web reader because
this Cloud environment's direct Roy Morgan request was blocked by its domain
allowlist. This records a retrieved source snapshot, not a claimed release date.

## Vintage policy

The existing history through July 2026 is frozen. The two documented source
differences are allowed audit differences, not permission to rewrite those rows.
New unexpected legacy differences stop the ANZ refresh for review. Newly managed
months retain their accepted value, provisional status and source marker in
`anz_sent.meta.json`. Every accepted append, provisional update or finalization
adds a vintage with the old/new values, retrieval time, source URL, snapshot hash
and audit. Snapshots and earlier ledger events are append-only.

Only a **managed provisional** month can update automatically from the official
monthly table. This includes replacing an indicative value with the subsequently
published unflagged value. Once final, a numerical revision requires explicit
review; preserve it and report the conflict. Never rewrite previously published
GDP/nowcast histories. A change in these inputs is read by the model's next normal
weekly run; this refresh neither runs a model nor changes its specification.

## Scheduled procedure

The existing Sunday 09:00 Australia/Sydney survey scan should add this source.
That leaves time before the Sunday 19:00 UTC v2 run. Weekly checks are sufficient
for the monthly model input; no separate daily automation is required. The actual
prompt and schedule are managed in Codex; this repository file does not change them.

From the repository root, fetch and inspect a dry run:

```bash
python3 nowcasting_v2/scrapers/anz_monthly.py
```

If direct fetching is blocked, retrieve the same official monthly page using an
authorized web/browser reader. Save a **verbatim extraction** of its title,
entire YEAR/JAN…DEC/YEARLY AVERAGE table and footnotes to a temporary UTF-8 file.
Use the tool's actual retrieval time, not an invented source release date. Do not
manually transcribe individual numbers or use search snippets, weekly reports,
test fixtures, an old repository snapshot, or an alternate aggregator.

```bash
python3 nowcasting_v2/scrapers/anz_monthly.py --source-file /tmp/anz-monthly.txt --retrieved-at '<actual ISO-8601 UTC retrieval time>'
```

Inspect changes and the full overlap audit. The command validates the monthly
header and column order, unique dates, 50–150 range, no future observations,
complete existing coverage, at least two recent matching overlap months,
continuous new months, frozen-history exceptions and the vintage ledger. It
rejects old/future/naive retrieval timestamps. Any source or validation failure is
BLOCKED for ANZ only; leave its files untouched and continue unrelated surveys.
There is no automatic fixture fallback.

Run the same command with `--write` after the dry run passes. Repeating an
unchanged successful check writes nothing. Validate:

```bash
python3 -m unittest discover -s nowcasting_v2/scrapers -p test_anz_monthly.py
git diff --check
git diff -- nowcasting_v2/data_raw/anz_sent.csv nowcasting_v2/data_raw/anz_sent.meta.json nowcasting_v2/data_sources/anz_sent/
```

Stage those three ANZ paths alongside other independently validated survey
updates. Report new months, any provisional update/finalization, preserved
conflicts, source URL, source hash and retrieval time. Do not claim that current
published forecasts have already incorporated the new input. The normal model
job regenerates its indicator JSON after consuming the committed CSV.

`--sync-display` is an explicit display-repair option. It updates only ANZ in
`data/indicators_v2.json` and `data/indicators_combo.json`; it never touches model
payloads, other indicators or the "fed this run" record. The initial repair uses
this option to correct the website immediately. Routine scans should omit it.

The old R ANZ/IVI batch writer no longer owns consumer confidence. Its historical
parser remains for fixtures, but do not call its `fetch_anz_sent` function to
overwrite the guarded CSV. A source contract or vintage-policy change needs a
separate review rather than weakening these checks.
