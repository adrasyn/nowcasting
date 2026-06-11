# Weekly v2 data refresh — split between Cowork (surveys) and the R pipeline

## The split (and why)

| Piece | Where | Needs R? | Why |
|---|---|---|---|
| **NAB, ANZ, Westpac surveys** | **Cowork (laptop)** | **No** | Behind Akamai WAF → need a residential IP / browser, which the laptop has. Reading them is pure file parsing (Python + your vision) — no R. |
| RBA/ABS series (credit_card, credit, yields, spreads, BBSW, employment, MHSI, exports, building approvals) | GitHub Actions cron | Yes (fetchers are R, but gov CSV/XLSX — no WAF, runs fine in cloud) | Not WAF-blocked, so no need for the laptop. |
| **Nowcast emit** (`emit_v2_json.R`) | GitHub Actions cron | **Yes** | This is the DFM + MIDAS *model* (via `midasr`), not a file you open — it must run in R. |

R is only ever needed for the **model** and the (R-written) gov-data fetchers —
both of which belong in the cron, not on your laptop. **Cowork stays R-free.**

Interim (until the v2 cron is wired as part of cutover): run the R half manually
with `pwsh nowcasting_v2/scrapers/refresh_local.ps1` (fetches RBA/ABS + re-runs
the nowcast). That's the only place R is used, and it's not part of the Cowork task.

## Cowork task setup

1. Claude Cowork (desktop) → scheduled task, weekly (e.g. **Sunday ~9am**, laptop on).
2. Repo `adrasyn/nowcasting`, branch `nowcast-v2`.
3. Paste the prompt below.

## Cowork task prompt (paste this) — surveys only, no R

```
You are the WEEKLY survey-data agent for the Australian GDP "nowcast v2" project,
running on James's laptop (residential IP + browser). Refresh ONLY the three
scraped survey families and commit. The RBA/ABS series and the nowcast model run
elsewhere (R pipeline) — do NOT touch them. NEVER fabricate; range-check
everything; a documented gap is success, a guessed number is failure.

SETUP
- cd to the repo; `git checkout nowcast-v2 && git pull`.
- `pip install --quiet pdfplumber pypdfium2 openpyxl requests`.
- CSVs: nowcasting_v2/data_raw/<id>.csv, header date,value, FIRST-OF-MONTH, sorted
  ascending. Append ONLY months strictly newer than each file's last row. Most
  weeks nothing is new = normal (make no commit).

A. ANZ-Indeed Job Ads -> data_raw/anz_ads.csv (SA index, range 40-220).
   Current XLSX link on https://www.anz.com.au/newsroom/media/release-dates/
   (date-stamped: folder=release month, filename=data month). Download (curl, or
   the browser if blocked), parse the SA index column with openpyxl/pandas, range-
   check, append new months.

B. Westpac-MI Consumer Sentiment -> data_raw/wmi_sent.csv (LEVEL, range 50-130).
   https://www.westpaciq.com.au/economics/{YYYY}/{MM}/consumer-sentiment-{month}-{YYYY}
   Read the index LEVEL (not the % change), range-check, append.

C. NAB Monthly Business Survey -> nab_conf/cond/trade/profit/emp/forward/stocks/cu.
   Find the latest monthly survey PDF URL (WebSearch + news.nab.com.au /
   business.nab.com.au). From nowcasting_v2/:
     python scrapers/nab_monthly.py render "<PDF_URL>" --out nab_t1.png
       (download is curl-with-browser-headers; if WAF still blocks it, fetch the
        PDF via the BROWSER and pass the saved path instead.)
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
("data: weekly v2 surveys <date>") and `git push origin nowcast-v2`. If nothing
new, no commit.

SUMMARY: per series — new month(s)/"already current"/"BLOCKED: reason"; committed?
```

## The cloud routine
`trig_01Qekn1TeH3r92piEGpytA5X` (cloud) is WAF-blocked for NAB/ANZ, so this
Cowork task supersedes it for the surveys. Disable it, or leave it as a
Westpac-only backup — your call.
