# v2 data updates + CI band maintenance

Answers to the 11-Jun feedback items 5 (how do the new series stay current?) and
6 (do the CI bands need monthly recalculation?).

## 5. Keeping the v2 input series up to date

The v2 panel splits cleanly into **auto-fetchable** (free APIs, runs unattended in
the weekly cron) and **scraped** (no API — needs a scraper or a manual/Cowork drop).

| Series | Source | In the weekly cron? | Notes |
|---|---|---|---|
| Labour: emp, ft_emp, pt_emp, ue, ud, hours | ABS 6202 | **Yes** — `fetch_abs_panel.R` | v1 already auto-fetches ABS via `readabs` in its cron, so this is proven on the GitHub runner. |
| Household spending (MHSI) | ABS 5682 | **Yes** — `fetch_abs_panel.R` | |
| Exports, Building approvals | ABS 5368 / 8731 | **Yes** — `fetch_abs_panel.R` | |
| Credit (total/housing/business), Credit card | RBA D2 / C1 | **Yes** — `fetch_rba_panel.R` | RBA statistical tables are plain CSV. |
| AGS yields 3/5/10, spreads 3/5/10, BBSW | RBA F2/F1 | **Yes** — `fetch_rba_panel.R` | Daily market data; trivially current. |
| NAB business survey (conf + 7 sub-indices) | NAB monthly PDF | **Partly** | `nab_conf` is already updated monthly by James's external Claude/Cowork task (writes the CSV the repo reads). The 7 sub-indices need `scrape_nab_full.R` run on the PDF — works locally; PDF parsing in the GH runner is feasible but unproven. |
| ANZ job ads, ANZ-RM consumer confidence | ANZ-Indeed PDF / Roy Morgan HTML | **No (gap)** | `scrape_anz_ivi.R` exists but isn't on a schedule — that's why **job ads is stale (last = March)**. Consumer confidence (Roy Morgan HTML) is scrapeable headless; job ads is a PDF parse. |
| Consumer sentiment (Westpac, `wmi_sent`) | investing.com batch | **No (gap)** | No automated updater yet. Per the earlier scrape assessment: parse the **free official Westpac release** in the cron, with a **local Cowork task** as fallback (investing.com needs a real browser, so it can't run on the GH runner). This is the open task #9. |

**Bottom line for the headline model:** of the series the headline actually selects
(labour, household spending, housing credit, the spreads + BBSW, credit card, NAB
confidence, Westpac sentiment), **all but Westpac auto-update** in the cron (or via
James's NAB task). **Westpac sentiment is the one genuine gap** — it needs either an
official-release parser or the local Cowork task. ANZ job ads is stale but is *not*
selected by the headline, so it doesn't affect the nowcast (only the indicators grid).

**Recommended plan:**
1. The v2 weekly cron runs `fetch_abs_panel.R` + `fetch_rba_panel.R` (covers ~all
   ABS/RBA series, including most selected ones). Low risk — mirrors v1.
2. Keep James's monthly NAB Cowork task for `nab_conf`; add the NAB sub-indices via
   `scrape_nab_full.R` if we want them fresh.
3. Build the Westpac feed (task #9): official-release parser in-cron + Cowork fallback.
4. Schedule the ANZ scraper (cron for the HTML one; Cowork for the job-ads PDF).

This is wired up as part of the cutover/cron work, which is gated on your approval.

## 6. CI bands — recalculation cadence

**No, they do not need monthly recalculation.** The bands come from the model's
**out-of-sample backtest error distribution** (post-COVID quarters), which is stable
and moves slowly. Recalculate them when the backtest gains a new data point — i.e.
**quarterly, after each ABS GDP release** adds one realised quarter to the backtest.

The mechanism already exists and is one command:

```
cd pipeline && Rscript compute_ci_params.R <v2_backtest.csv> seed/ci_params_v2.json
```

So the quarterly refresh is: (1) the new GDP actual lands → (2) re-run the v2 backtest
to append that quarter's error → (3) re-run `compute_ci_params.R` → bands updated.
Steps 2–3 belong in a quarterly (post-GDP-release) job, not the weekly cron.

**Known follow-up (from the Fable review):** the current `ci_params_v2.json` was
calibrated on the backtest's *coarser* publication lags, while the live emit now uses
accurate lags. The next backtest refresh should re-run with the accurate lags so the
bands are calibrated on the same information set the live nowcast uses. The methodology
panel already discloses the bands as "approximate," so this is a refinement, not a
correctness bug.
