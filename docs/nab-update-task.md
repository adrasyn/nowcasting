# NAB Business Confidence — monthly Claude scheduled task (RETIRED 2026-08-23)

> **This task is retired. It was already deleted from Claude Desktop some time ago,**
> **and replaced by the cloud routine — but that routine only writes the v2 files.**
> **The v1 CSV was left with no feeder at all. That is why May, June and July 2026**
> **all needed manual unblocks. No action is needed from you.**
>
> The v1 CSV (`pipeline/nab_business_confidence_raw.csv`) is now fed automatically
> from the v2 survey scrape by `pipeline/03d_sync_nab_from_v2.R`, which runs at the
> top of `run_complete_nowcast.R`. There is nothing left to paste anywhere.

## Why it was retired

This task scraped investing.com monthly to maintain v1's CSV. It was deleted and
replaced by the cloud/weekly routine — but that routine only writes the **v2**
files (`nowcasting_v2/data_raw/nab_conf.csv`, read from NAB's own survey PDF).
Nothing was left writing v1.

So v1 was **orphaned, not broken**: there was no failing scraper to find. It
missed **May, June and July 2026**.
Because v1's freshness guard hard-stops the run and the v2 workflow step is gated on
`if: success()`, a stale v1 CSV killed the *entire* weekly job — v2 nowcast, commit
and deploy included — while the correct value sat in `nab_conf.csv` the whole time.
That was issue #16.

Retiring the weaker of two fetchers removes the failure class rather than the
symptom. The primary source (NAB's PDF) survived; the aggregator scrape did not.

## What replaced it

`03d_sync_nab_from_v2.R` **mirrors** `nab_conf.csv` into the v1 CSV on every run.
v2 is authoritative and v1's history is not preserved, because v1's history was wrong.

### v1 was one month late

v1 recorded each value one month too late across large parts of 2008-2014. NAB
published business confidence of **12 for September 2013** and **5 for October 2013**
([Inside Retail, Nov 2013](https://insideretail.com.au/news/business-confidence-falls-high-201311)).

| Series | Sep 2013 | Oct 2013 |
|---|---|---|
| v2 (cloud routine, NAB PDF) | 12 | 5 |
| v1 (old, investing.com) | 6 | 12 |

The shift is not a local anomaly. It covers eight runs:

```
2008-03..2008-06   2008-10..2008-12   2009-02..2009-11   2010-02..2010-11
2011-01..2011-10   2011-12..2012-12   2013-02..2013-10   2013-12..2014-08
```

70 of the 89 disagreeing months are this shift. The v1 model therefore read NAB
confidence a month late through the GFC and the recovery.

The mirror corrected **86 months**, added 2, dropped 4, and removed the duplicate
rows for 2008-10, 2009-02 and 2010-12 that the loader never de-duplicated.

### A broken scrape cannot destroy the series

The overwrite only happens if `nab_conf.csv` passes validation: at least 300 rows,
no duplicate dates, all dates first-of-month, all values within [-80, 80]. Any
failure leaves the v1 file untouched and raises a warning.

Tests: `pipeline/tests/test_sync_nab_from_v2.R` (19 tests, run from `pipeline/`).

### Months not carried over

v2 has no data for **2000-05, 2008-02, 2009-12 and 2010-12**, which v1 had. Those v1
values were NOT kept: each sits on the edge of a shift run, so they are very likely a
month out as well. Recovering them from NAB's own history is an open follow-up.

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
