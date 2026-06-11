# Weekly v2 data refresh — local survey routine + the R cron

Post-cutover everything lives on **`main`**. Two mechanisms keep the inputs fresh:

| Piece | Where | Needs R? | Why |
|---|---|---|---|
| **NAB, ANZ job ads, Westpac, ANZ-RM surveys** | **Local Claude Code routine (laptop)** | **No** | Behind Akamai WAF → need a residential IP (the laptop's). Reading them is pure file parsing (Python + vision) — no R. |
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

## Routine prompt (paste this) — surveys only, pushes to main, no R

```
You are the WEEKLY survey-data agent for the Australian GDP "nowcast v2" project,
running locally on James's laptop (residential IP). Refresh ONLY the scraped
survey families and commit to main. The RBA/ABS series and the nowcast model run
in the GitHub Actions cron — do NOT touch them. NEVER fabricate; range-check
everything; a documented gap is success, a guessed number is failure.

SETUP
- cd to the repo; `git checkout main && git pull`.
- `pip install --quiet pdfplumber pypdfium2 openpyxl requests`.
- CSVs: nowcasting_v2/data_raw/<id>.csv, header date,value, FIRST-OF-MONTH, sorted
  ascending. Append ONLY months strictly newer than each file's last row. Most
  weeks nothing is new = normal (make no commit).

A. ANZ-Indeed Job Ads -> data_raw/anz_ads.csv (SA index, range 40-220).
   Current XLSX link on https://www.anz.com.au/newsroom/media/release-dates/
   (date-stamped: folder=release month, filename=data month). Download with curl,
   parse the SA index column with openpyxl/pandas, range-check, append new months.

B. Westpac-MI Consumer Sentiment -> data_raw/wmi_sent.csv (LEVEL, range 50-130).
   https://www.westpaciq.com.au/economics/{YYYY}/{MM}/consumer-sentiment-{month}-{YYYY}
   Read the index LEVEL (not the % change), range-check, append.

C. NAB Monthly Business Survey -> nab_conf/cond/trade/profit/emp/forward/stocks/cu.
   Find the latest monthly survey PDF URL (WebSearch + news.nab.com.au /
   business.nab.com.au). From nowcasting_v2/:
     python scrapers/nab_monthly.py render "<PDF_URL>" --out nab_t1.png
       (download is curl-with-browser-headers; from the laptop's residential IP it
        should clear the WAF.)
     -> OPEN and VIEW nab_t1.png. Read Table 1 "Key Monthly Business Survey
        Statistics": the LATEST month column AND one earlier month already in the
        CSV (for validation). Map Business confidence=nab_conf, Conditions=nab_cond,
        Trading=nab_trade, Profitability=nab_profit, Employment=nab_emp, Forward
        orders=nab_forward, Stocks=nab_stocks, Capacity utilisation rate(%)=nab_cu
        (skip Capex, Exports).
     python scrapers/nab_monthly.py verify --values '{"nab_conf":{"<latest>":..,"<overlap>":..}, ...}' --data-raw data_raw --write
       verify validates your read against the CSV overlap month + range before
       appending; if it rejects, re-view and correct; if still won't reconcile,
       leave BLOCKED and report. Never hand-edit the CSVs.

D. ANZ-Roy Morgan Consumer Confidence -> data_raw/anz_sent.csv (index ~100, range 50-150).
   Source: https://www.roymorgan.com/morgan-poll/consumer-confidence-anz-roy-morgan-australian-cc-monthly-ratings
   WebFetch the monthly-ratings table; take the LATEST month's value (strip any
   footnote markers like * or **), range-check 50-150, append if newer.

COMMIT: `git diff --stat`; confirm only genuine new rows. Commit
("data: weekly v2 surveys <date>") and `git push origin main`. If nothing new,
make no commit. Do NOT run the nowcast or trigger a deploy — the cron does that.

SUMMARY: per series — new month(s)/"already current"/"BLOCKED: reason"; committed?
```

## Notes
- The cloud routine `trig_01Qekn1TeH3r92piEGpytA5X` is **disabled** (WAF-blocked);
  this local routine replaces it.
- The local routine does NOT run `emit` or deploy — it only commits survey data.
  The Monday cron reads those surveys, re-runs the model, and deploys.
- If the laptop is off at the scheduled time, surveys just wait a week; the cron
  still runs the model on whatever data is present.
