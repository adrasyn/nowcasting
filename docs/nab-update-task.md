# NAB Business Confidence — monthly Claude scheduled task (RETIRED 2026-08-23)

> **This task is retired. Delete it from Claude Desktop's scheduled-task UI.**
>
> The v1 CSV (`pipeline/nab_business_confidence_raw.csv`) is now fed automatically
> from the v2 survey scrape by `pipeline/03d_sync_nab_from_v2.R`, which runs at the
> top of `run_complete_nowcast.R`. There is nothing left to paste anywhere.

## Why it was retired

This task scraped investing.com monthly to maintain v1's CSV. The weekly survey
routine (`docs/cowork-weekly-refresh.md`) *already* fetched the same number from
NAB's own monthly survey PDF into `nowcasting_v2/data_raw/nab_conf.csv`. Two
automations, two sources, one number.

The v1 task then silently stopped landing commits and missed **June and July 2026**.
Because v1's freshness guard hard-stops the run and the v2 workflow step is gated on
`if: success()`, a stale v1 CSV killed the *entire* weekly job — v2 nowcast, commit
and deploy included — while the correct value sat in `nab_conf.csv` the whole time.
That was issue #16.

Retiring the weaker of two fetchers removes the failure class rather than the
symptom. The primary source (NAB's PDF) survived; the aggregator scrape did not.

## What replaced it

`03d_sync_nab_from_v2.R` copies across any month in `nab_conf.csv` strictly newer
than v1's last row. It is **append-only** and deliberately so:

- The two series disagree on **83 of 347** overlapping months — mostly a clean
  one-month misalignment across 2013-08..2014-08 (`v2[m] == v1[m+1]` exactly),
  plus aggregator noise (2015+: 12 of 139 months differ, max 4).
- Rewriting v1's history from v2 would silently move the v1 model's inputs and the
  **published track record**. So history is frozen and gaps are never backfilled.
- This accepts a source seam at the join. That is the intended trade.

Tests: `pipeline/tests/test_sync_nab_from_v2.R` (run from `pipeline/`).

## Correction to a claim this file used to make

The old version of this doc said:

> "If this task ever fails silently, the weekly nowcast pipeline falls back to the
> last-known value and the site's headline won't break."

**That was wrong.** There is no fallback. `check_nab_data_freshness()` in
`03c_nab_business_confidence.R` calls `stop()`, which halts the whole job. That
mistaken belief is part of why two missed months went unnoticed as a *class* of
problem rather than a one-off.

## Manual top-up (if v2 is ever down)

The escape hatch still exists — from `pipeline/`:

```r
source("03c_nab_business_confidence.R")
update_nab_data("2026-08-01", -4)   # date = first of the REPORTED month
```

NAB releases on the 2nd Tuesday for the previous month. Never fabricate a value:
a documented gap is success, a guessed number is failure.

## Related

- `docs/cowork-weekly-refresh.md` — the weekly routine that is now the single NAB fetcher
- **Known pre-existing bug, not fixed here:** the v1 CSV has duplicate rows for
  2008-10, 2009-02 and 2010-02 with differing values, and the loader does not
  dedupe, so those months are double-weighted. Fixing it means re-running the v1
  backtest.
