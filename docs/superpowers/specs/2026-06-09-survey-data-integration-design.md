# Survey-data integration + hyperparameter sweep for nowcast v2

**Date:** 2026-06-09
**Branch:** nowcast-v2
**Status:** design (overnight autonomous execution authorised)

## Goal

Integrate the newly-scraped long-history Australian survey/sentiment series into
nowcast v2's MAI panel, handle the four documented "traps", and run a go-wide
backtest sweep (panel variants × hyperparameters) to find the best-performing v2
configuration. Deliver a reviewable verdict + comparison graphs by morning,
including a clear v1→v2 cutover recommendation.

Decisions locked with the user:
- **Sweep scope:** go wide — panel variants × hyperparameters (DFM factors `q`,
  MIDAS lag structure, model type, selection α, sentiment start date).
- **Decision rule:** pick the config minimising post-COVID + full-sample RMSE,
  and give a v1→v2 cutover call with the evidence.
- **Overfitting guard:** keep a held-out window; report in-sample-tuned vs
  out-of-sample RMSE separately so a sweep "winner" isn't just curve-fit.
- **Alignment:** match v2's existing reference-month convention (the panel and
  backtest already align on first-of-reference-month + a per-series publication
  lag). Provenance release-dates are retained for a possible future
  vintage-correct pass but are not used now.

## The data (verified on arrival, not trusted from notes)

Six series in `nowcast_new_scrape_results/data/`:

| id | span | scale | action |
|---|---|---|---|
| `nab_cond` | 1997-03 → 2026-05 | net balance, 0-centred | **replace** the short 2023+ panel series |
| `nab_conf` | 1997-03 → 2026-05 | net balance | **replace** short 2023+ series |
| `aig_pmi` | 2001-05 → 2026-05 | −100…+100, 0=neutral | **add** new |
| `aig_pci` | 2005-09 → 2026-05 | −100…+100 | **add** new |
| `aig_psi` | 2003-02 → 2022-11 (frozen) | −100…+100 | **add** new (discontinued; never expects new prints) |
| `wmi_sent` | 1988-05 → 2026-06 | index, 100=neutral | **add** new; start 2008 by default |

## The four traps and how each is handled

1. **AiG scale flip** (now −100…+100, 0=neutral, not 0–100/50=neutral). The model
   z-scores every series in `transform_panel.R`, so absolute scale is washed out.
   No code hard-codes "PMI>50". Handled by standardisation; nothing to special-case.
2. **Reference-month vs release-date.** Use reference-month (`date` as-is), matching
   the existing panel. Real-time faithfulness comes from the backtest's per-series
   publication-lag truncation (`.lag_for_id` + `.truncate_panel`). New lags:
   `aig_*` = +5d (≈1st business day of following month), `wmi_sent` = −15d (Westpac
   releases mid its own reference month, so it is available *before* month-end).
3. **AiG 2023 methodology break** (linear splice). Use `tcode=t1, tlog=FALSE`
   (level/net-balance, like NAB) — a first-difference (t2) straddling the splice
   would inject a spurious jump; the level transform plus rolling-centre is safer.
   No raw cross-break YoY/long-window transforms are introduced.
4. **NAB sub-series reconciliation.** Only `nab_cond`/`nab_conf` are regenerated to
   1997. The other six NAB sub-series stay on the short 2023+ scrape. They remain
   independent panel columns; the ragged panel design already tolerates mixed start
   dates (each series transformed on its own observed span). No joined NAB block is
   built, so mixed starts are safe. Documented, not silently mixed.

## Series wiring (tcode/tlog/group)

All new/extended series join group `S` (survey). Defaults mirror the closest
existing series:

| id | tcode | tlog | mirror | note |
|---|---|---|---|---|
| `nab_cond` | t1 | FALSE | existing nab_cond | net balance |
| `nab_conf` | t1 | FALSE | existing nab_conf | net balance |
| `aig_pmi` | t1 | FALSE | nab | net balance, 0-centred |
| `aig_pci` | t1 | FALSE | nab | net balance |
| `aig_psi` | t1 | FALSE | nab | frozen 2022-11 |
| `wmi_sent` | t1 | FALSE | anz_sent | sentiment index level |

`wmi_sent` t2 (diff) is tested as a hyperparameter variant.

## Architecture (what changes, what doesn't)

The estimation math (`build_mai`, `nowcast_midas`, `transform_panel`, RBA methods)
is **unchanged**. Changes are: (a) data files in `data_raw/`, (b) rows in
`seed/panel_info.csv`, (c) two new entries in the backtest's `.lag_for_id`, and
(d) a **new sweep harness** that wraps the existing `backtest_v2()` to vary the
candidate set and hyperparameters without editing the estimation code.

### New unit: `R/sweep_v2.R` (harness glue only)

One purpose: run a parameterised backtest and collect comparable RMSE rows.
- Input: a variant spec = `{exclude_ids, model, sel_alpha, qa_lag, dfm_q, wmi_tcode, wmi_start}`.
- It re-derives the full-sample fixed selection **on that variant's candidate set**
  (so each variant's selection is honest), then runs the existing per-as-of loop.
- Output: one results CSV per variant under `cache/sweep_v2/<variant_id>.csv`,
  plus a master `cache/sweep_v2/summary.csv` with full-sample RMSE, post-COVID
  RMSE, held-out RMSE, direction-hit-rate, n_nowcasts per variant.
- Depends on: `backtest_v2.R` internals. To avoid copy-paste, `backtest_v2()` is
  lightly refactored to accept `exclude_ids`, `model`, `sel_alpha`, and a
  `qa_lag`/`dfm_q` pass-through (defaulting to current behaviour, so the existing
  call site is unchanged and the parity test still passes).

### Parameterisation needed in existing code (minimal, back-compatible)

- `build_mai(..., dfm_q = 1L, qa_unused)` — expose `q` (default 1 = current).
- `nowcast_midas(..., qa_lag = 0:1)` — expose the QA quarterly lag (default 0:1 = current).
- `backtest_v2(..., exclude_ids = character(0), sel_alpha = 0.10, dfm_q = 1L, qa_lag = 0:1)`.

All defaults reproduce today's numbers exactly (guarded by re-running the parity
check + confirming B0 reproduces the committed v2 backtest).

## Sweep design (staged, to control combinatorics and overfitting)

**Stage A — panel variants at default hyperparameters** (model=qa, α=0.10, q=1, qa_lag=0:1):
- B0: current v2 (no new data) — must reproduce the committed backtest.
- B1: extended NAB history only (1997+ nab_cond/conf; no AiG/Westpac).
- B2: B1 + AiG block (pmi/pci/psi).
- B3: B1 + Westpac sentiment (2008+).
- B4: B1 + AiG + Westpac (full new panel).
- B4a: B4 with wmi_sent from full history (1988+) instead of 2008+.

**Stage B — hyperparameter sweep on the best 1–2 Stage-A variants only:**
- model ∈ {qa, umidas}
- sel_alpha ∈ {0.05, 0.10, 0.20}
- dfm_q ∈ {1, 2}
- qa_lag ∈ {0:1, 0:2}
- wmi_tcode ∈ {t1, t2} (only if Westpac is in the winning variant)

Staging keeps the grid from exploding (Stage A = 6 runs; Stage B ≈ 2 × ≤24 runs)
and means hyperparameters are tuned only where panel choice already paid off.

**Scoring & overfitting guard.** Backtest window 2012→latest. Primary metric:
post-COVID RMSE (2022Q1+) and full-sample RMSE vs latest-vintage actual GDP
(same as the existing v1/v2 comparison). Held-out guard: the last 8 quarters are
reported as a separate OOS RMSE column; a Stage-B winner that only improves
in-sample but not OOS is flagged as likely overfit and not recommended.

## Testing

- **Reproduce-baseline gate:** B0 backtest RMSE must match the committed
  `v2_vs_v1_backtest*` numbers (post-COVID 0.52, v1 0.34) within rounding.
  If not, stop — the refactor changed behaviour; fix before sweeping.
- **Span/units assertions:** a small R/py check confirms each new CSV's span and
  scale before wiring (AiG min<0, wmi ~65–125, nab can be negative).
- **Existing tests:** `nowcasting_v2/tests/` and the scrape's `tests/` (33) re-run
  green.
- **Parity check:** `R/check_replication_parity.R` still passes (estimation math
  untouched).

## Deliverable (morning review)

Committed on `nowcast-v2`:
1. `cache/sweep_v2/summary.csv` — every variant's RMSEs side by side.
2. Comparison graphs (mirroring `v2_vs_v1_backtest*.png`): best-config vs current
   v2 vs v1 vs actual, full-sample and post-COVID.
3. `docs/.../2026-06-09-survey-integration-results.md` — the verdict: which data
   helped, by how much, in-sample vs OOS, and a clear v1→v2 cutover recommendation
   with the evidence and the residual risks.

## Out of scope (YAGNI)

- Vintage-correct release-date alignment (provenance retained for later).
- Backfilling the six short NAB sub-series.
- S&P/Judo PMI (never sourced).
- Westpac pre-2008 reconstruction quality work.
- Any website/JSON/front-end changes — this is a modelling experiment only.
</content>
</invoke>
