# Weekly v2 data refresh — local survey routine + the R cron

Post-cutover everything lives on **`main`**. Two mechanisms keep the inputs fresh:

| Piece | Where | Needs R? | Why |
|---|---|---|---|
| **NAB, ANZ job ads, Westpac, Ai Group PMI** | **Scheduled Claude Code routine** | **No** | NAB/ANZ sit behind an Akamai WAF → need a residential IP. Reading them is pure file parsing (Python + vision) — no R. `aig_pmi` is consumed by **v3**, not v2. |
| RBA/ABS series (credit_card, credit, yields, spreads, BBSW, employment, MHSI, exports, building approvals) | **GitHub Actions weekly cron** (`main`) | Yes (R fetchers; gov CSV/XLSX, no WAF) | Always-on; not WAF-blocked. |
| **Nowcast emit** (`emit_v2_json.R`) | **GitHub Actions weekly cron** (`main`) | **Yes** | The DFM + MIDAS *model* (via `midasr`) — must run in R. |

R only ever runs in the cron (the model + the gov fetchers). The local routine is
R-free. The local routine commits the *survey data*; the cron re-runs the model
(reading those surveys) on its next run, so the site reflects them then.

Why local (not the cloud routine): NAB/ANZ are Akamai-WAF-blocked from cloud
datacenter IPs. The laptop's residential IP clears the WAF — plain `curl` is
usually enough; a browser is only a last-resort fallback.

## Setting up the local Claude Code routine

Schedule Claude Code headless on the laptop (Windows Task Scheduler), weekly —
e.g. **Sunday ~9am** (before Monday's cron emit), laptop on. The scheduled action
runs Claude Code in the repo with the prompt below, e.g.:

```
claude -p "<the prompt below>" --allowedTools "Bash,Read,Write,Edit,Glob,Grep,WebFetch,WebSearch"
```

(Run it from the repo root. Claude Code has git, so it can commit + push to `main`.)

## Routine prompt (paste this) — surveys, pushes to main

> **Synced 2026-08-27 from the live scheduled task.** The block below had drifted from
> what actually runs — it still described an ANZ-Roy Morgan step that the live routine
> no longer has. If you edit the scheduled task, re-paste it here; a stale copy of this
> prompt is worse than none, because it gets read as authoritative.

```
You are the WEEKLY data-refresh agent for the Australian GDP "nowcast v2" project. You run every Sunday. Pull the latest values for the SCRAPED monthly survey series from their official public sources and append any genuinely-new months to the input CSVs, then commit and push. These are series the automated cron CANNOT fetch (no clean API), so this run keeps them current.

CADENCE: these surveys publish MONTHLY but you run WEEKLY, so MOST weeks there is NO new data - that is the normal, successful outcome. When a series is already current, report "already current" and make NO commit. Only append + commit the week a new month appears. Never invent a value to fill a week.

## PRIME DIRECTIVE
NEVER fabricate. Every value must trace to the official source fetched this run. If a source is unreachable / unparseable / fails a range check, SKIP that series, leave its CSV untouched, and report it loudly. A documented gap is success; a guessed number is failure.

## SETUP
1. `git checkout main && git pull` (post-cutover: all v2 data + scrapers live on main; the live weekly pipeline reads data_raw from main, so surveys MUST land on main).
2. If git needs identity: `git config user.name "nowcast-bot"; git config user.email "nowcast-bot@users.noreply.github.com"`.
3. `pip install --quiet pdfplumber pypdfium2 openpyxl requests`.
4. CSVs at `nowcasting_v2/data_raw/<id>.csv`: header `date,value`, sorted ascending, FIRST-OF-MONTH dates. Read each last row first; append ONLY rows strictly later; never rewrite existing rows.

## A. ANZ-Indeed Job Ads -> data_raw/anz_ads.csv
SEASONALLY ADJUSTED index (2019=100), range 40-220. DATE-STAMPED XLSX (not static). Find the current link on https://www.anz.com.au/newsroom/media/release-dates/ . Pattern: https://www.anz.com.au/content/dam/anzcomau/mediacentre/pdfs/jobads/{YEAR}/{release-month-lowercase}/ANZ-Indeed%20Australian%20Job%20Ads%20data_{Mon}{YY}.xlsx (folder=RELEASE month, filename=DATA month; May data released June -> .../2026/june/...data_May26.xlsx). Verify with `curl -sSLI`. Download (`curl -sSL -A 'Mozilla/5.0'`), parse the SA index column with python (openpyxl/pandas), cross-check implied %m/m vs printed, range-check 40-220.

## B. Westpac-MI Consumer Sentiment -> data_raw/wmi_sent.csv
Headline index LEVEL (e.g. 80.6), range 50-130. Source: https://www.westpaciq.com.au/economics/{YYYY}/{MM}/consumer-sentiment-{month-lowercase}-{YYYY} . WebFetch, extract the LEVEL (NOT %-change), range-check.

## C. NAB Monthly Business Survey -> eight CSVs (nab_conf, nab_cond, nab_trade, nab_profit, nab_emp, nab_forward, nab_stocks, nab_cu)
USE nowcasting_v2/scrapers/nab_monthly.py. Do NOT read NAB from web-search snippets or hand-type values. Discovery is YOUR job (filenames inconsistent): find the latest NAB Monthly Business Survey PDF URL via WebSearch + the NAB economics news hub (news.nab.com.au / business.nab.com.au). NAB's Table 1 layout CHANGES between issues, so VISION is the PRIMARY method (it is layout-proof). From the nowcasting_v2/ directory:

PRIMARY - vision read:
  1. `python scrapers/nab_monthly.py render "<PDF_URL>" --out nab_t1.png`  (rasterises page 1; add --dpi 400 or re-crop if too small to read).
  2. OPEN AND VIEW nab_t1.png yourself (you are vision-capable). Read Table 1 = "Key Monthly Business Survey Statistics": for the LATEST month column AND at least one earlier month ALREADY in the CSV (needed for validation), read all eight rows -> Business confidence=nab_conf, Business conditions=nab_cond, Trading=nab_trade, Profitability=nab_profit, Employment=nab_emp, Forward orders=nab_forward, Stocks=nab_stocks, Capacity utilisation rate(%)=nab_cu. (Skip Capex and Exports - not tracked.)
  3. `python scrapers/nab_monthly.py verify --values '{"nab_conf":{"2026-05-01":-14,"2026-04-01":-24}, "nab_cond":{...}, ...}' --data-raw data_raw --write`
     verify re-checks your read against the CSV overlap month + range before appending. If your overlap-month read doesn't reconcile with the CSV it REJECTS the read - re-view the image and correct. If a series still won't reconcile after a careful re-read, leave it BLOCKED and report it (never force it).

OPTIONAL cross-check - deterministic (extra confidence, not required):
  `python scrapers/nab_monthly.py parse "<PDF_URL>" --data-raw data_raw`  (dry-run, no --write). If it parses, it will agree with your vision read. It only handles some layouts; "Table 1 layout not recognised" is expected - just rely on the vision read.

Never hand-edit the NAB CSVs; always go through verify so the guardrail runs.

## D. Ai Group Australian PMI -> data_raw/aig_pmi.csv
NET BALANCE centred on zero (e.g. -19.6), range -60 to +40. Published MONTHLY, ~1st of the following month (Aug data -> 01 Sep).

PRIMARY SOURCE: https://au.investing.com/economic-calendar/aig-manufacturing-index-203 - the release table, which gives Release Date / Reference Month / Actual / Previous and carries history. This is the source v2's existing history came from and it matches the CSV exactly.

*** RECORD FIRST VINTAGES, NEVER REVISED VALUES. Ai Group REVISES this series every month, and the CSV holds what was published at the time - which is what a real-time nowcast needs. Worked example: May 2026 was first published -22.4 (the CSV value) and later revised to -21.3; June was first published -16.8 and later revised to -13.9. The investing.com "Actual" column is the first vintage. Take that. ***

*** DO NOT reconcile using Ai Group's own prose. Its landing page says things like "the Australian PMI (manufacturing) declined 5.7 points to -19.6" - that change is computed against the REVISED prior month (-13.9), not the first vintage in the CSV (-16.8), so it will NEVER reconcile and is not evidence of an error. ***

VALIDATE before appending (this replaces any point-change arithmetic):
  1. OVERLAP: the last 2-3 months already in the CSV must equal the "Actual" for those same reference months in the table. If they do not, STOP - you are reading the wrong index or the wrong column - report BLOCKED.
  2. RANGE: -60..+40.
  3. STRICTLY NEWER: the reference month must be later than the CSV's last row.
  4. NOT-YET-RELEASED: the table shows a row for the UPCOMING release with a forecast in the Actual position. Check the release date is in the PAST. Never append a month whose release date has not happened.

Beware a genuinely different index with a similar name: the overall "Australian Industry Index" covers all sectors (June 2026 = -30.0). This CSV is the MANUFACTURING index (June 2026 = -16.8).

If investing.com 403s from this runner, fall back to https://tradingeconomics.com/australia/industry-index-manufacturing (it agrees, and flags revisions in prose), or report BLOCKED. A persistent block is the trigger to consider replacing this series with the Judo Bank / S&P Global Australia Manufacturing PMI - that is James's decision, not this run's.

WHY THIS EXISTS: v2 does NOT consume aig_pmi - its live panel spec B3_nab_wmi excludes the AiG block. This series is maintained for nowcast **v3**, which does consume it. Do NOT drop this step on the grounds that v2 ignores the file; that is exactly how it went three months stale.

STATUS as at 2026-08-27: backfilled to 2026-07 (Jun -16.8, Jul -19.6), overlap-validated on Feb-May. Next expected month is 2026-08, ~01 Sep.

## E. ABS / RBA fetchers (BEST-EFFORT)
R fetchers nowcasting_v2/R/fetch/{fetch_abs_panel.R,fetch_rba_panel.R} need R, which is NOT in this cloud image. Check `which Rscript`; if absent, SKIP and note ABS/RBA refresh (incl. credit_card) is handled elsewhere (R pipeline). Do not let missing R fail the run.

## VALIDATION & COMMIT
`git diff --stat`; show exact new rows per CSV. Confirm each appended date is a new first-of-month later than the prior last row, passed its range check, no existing row changed. Commit (`data: weekly v2 surveys <date>`) and `git push origin main`. If nothing new, no commit - say so.

## FINAL SUMMARY (always)
Per-series: source, new month(s) or "already current"/"BLOCKED: reason", value(s), range-check pass/fail, and for NAB whether vision or the deterministic cross-check was used. For Ai Group state which of the two indices you read and whether the point change reconciled. List anything not updated and why. State whether you committed + pushed.
```

## Notes
- The cloud routine `trig_01Qekn1TeH3r92piEGpytA5X` is **disabled** (WAF-blocked);
  this local routine replaces it.
- The local routine does NOT run `emit` or deploy — it only commits survey data.
  The Monday cron reads those surveys, re-runs the model, and deploys.
- If the laptop is off at the scheduled time, surveys just wait a week; the cron
  still runs the model on whatever data is present.
