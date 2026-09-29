# Weekly survey data refresh

This is the current repository guide for the separate **Codex cloud scheduled task** that refreshes monthly survey inputs. The task's exact prompt, schedule, permissions, and run history are configured in Codex; this file does not configure or trigger it. The earlier [local Claude routine](cowork-weekly-refresh.md) is retained as a dated record, not as the current setup guide.

The task checks for new observations weekly and commits only genuinely new survey months to `main`. Most weeks there is no new monthly release, so no commit is normal. It must never invent a value, overwrite an existing vintage, or let a blocked source hold up unrelated series. Record the identified publication or release table, reference month, value, and validation result for each series; report a blocked source explicitly.

| Input | CSV under `nowcasting_v2/data_raw/` | Validation |
| --- | --- | --- |
| ANZ-Indeed Job Ads | `anz_ads.csv` | Seasonally adjusted 2019=100 index from the dated ANZ workbook; range 40–220 and cross-check the published monthly change. |
| Westpac-MI Consumer Sentiment | `wmi_sent.csv` | Headline index **level**, not percentage change; range 50–130. |
| NAB Monthly Business Survey | `nab_conf.csv`, `nab_cond.csv`, `nab_trade.csv`, `nab_profit.csv`, `nab_emp.csv`, `nab_forward.csv`, `nab_stocks.csv`, `nab_cu.csv` | Read Table 1 in the NAB PDF, including an existing overlap month. Use `nowcasting_v2/scrapers/nab_monthly.py verify` to validate and write; do not hand-edit these CSVs. |
| Ai Group Australian PMI (manufacturing) | `aig_pmi.csv` | Zero-centred net balance, range −60 to +40. Record **first-published** values, check two or three overlap months against the release table's “Actual” column, and confirm the release date has passed. Do not reconcile against prose that compares with revised prior values. |

The Ai Group file is consumed by **v3**, even though v2's live panel excludes it. Keep it in the refresh. All CSVs have `date,value` columns, first-of-month dates, and ascending rows; append only dates strictly later than the last committed row. Before committing, inspect the diff and confirm no existing row changed. A no-change run needs no commit or push.

The GitHub Actions [v1/v2 workflow](../.github/workflows/nowcast-weekly.yml) fetches accessible ABS/RBA inputs and runs the R model. The [v3 workflow](../.github/workflows/nowcast-v3-weekly.yml) reads the survey CSVs too. The scheduled survey task does not need R or a local laptop. It must land new values on `main` before **Sunday 19:00 UTC** for the v2 weekly run to use them that Monday; a later commit is picked up by a subsequent run. Source accessibility can vary by cloud runner, so report a blocked source and leave its CSV untouched rather than substituting an unverified number.

For source-specific parsing commands and first-vintage examples, consult the current scheduled task prompt in Codex. A separate untracked prompt file may exist in a working copy; it is not available to cloud checkouts until deliberately committed.
