# Nowcast v2 — RBA MAI + MIDAS — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the v1 nowcast engine with the RBA's Monthly Activity Indicator (MAI) + U-MIDAS methodology (RDP 2024-04), built parallel in `nowcasting_v2/`, validated against v1, and cut over only once it clears a "competitive-enough" bar — keeping the existing website working and adding the MAI as a new product.

**Architecture:** Three-layer hybrid (spec: `docs/superpowers/specs/2026-06-04-nowcast-v2-rba-mai-midas-design.md`). We OWN a data-ingestion layer (free fetchers + scrapers → a monthly panel with vintages) and an emit layer (the existing JSON contract + `mai.json`); we REUSE the RBA `methods/*.R` verbatim for the estimation math (Stage 1 MAI via single-factor DFM; Stage 2 U-MIDAS nowcast). Replicate-then-build: Phase 1 reproduces the RBA's published numbers on their frozen MAI to validate the engine before we rebuild Stage 1 on our own data.

**Tech Stack:** R (pinned via `renv`), `midasr`, the RBA package's `methods/` (`qmle_dfm_methods.R`, `mai_utils.R`, `ndfm_methods.R`, `var_methods.R`, `lm_hac_methods.R`, `misc_methods.R`), `readabs` (ABS), RBA free CSV downloads, `pdftools`/`rvest` (scrapers), `seasonal` (X-13 self-SA), `testthat`. Site: existing Next.js (`src/`).

**Execution environment:** Windows 11, R 4.5.1, `renv` active. Shell examples use git-bash idioms; if a `cd nowcasting_v2` fails with "No such file or directory" the shell is already there — run without `cd`. The repo carries Windows-runner fixes (FRED `httr::GET`/HTTP-1.1 — though note FRED data endpoints were unreachable from this host on 2026-06-03; prefer ABS/RBA sources).

---

## Karpathy guardrails (apply to every task)

- **No production touch until Phase 6 (cutover).** All new work lives under `nowcasting_v2/`. Do NOT edit `pipeline/*.R`, `seed/`, `data/`, or the GitHub Action until the Phase 6 cutover gate passes. v1 keeps running weekly untouched throughout.
- **Reuse, don't reinvent.** Source the RBA `methods/*.R` verbatim. Do NOT rewrite their estimation math. Our new code is data-in / results-out drivers + I/O.
- **Simplicity first.** Each fetcher/parser is the minimum to produce one tidy `date,value` (or wide) CSV. No config frameworks, no abstractions used once.
- **Fail loud on data.** A fetch/parse failure must `stop()` or be explicitly logged + skipped with a recorded gap — never silently drop a series or fabricate values (carry over the 2026-06 scraper discipline).
- **Goal-driven.** Every phase has a verifiable gate below; do not proceed past a gate that fails.

## Acceptance gates (hard stops)

1. **Phase 1 parity gate:** the reproduced MIDAS nowcast metrics match the RBA paper's Table 3/4 figures within a stated tolerance (≈±2% relative on RMSE; same sign on MSE-F decisions). If not, the engine isn't being driven correctly — STOP and resolve before building Phase 2+.
2. **Phase 3 MAI sanity gate:** our live MAI correlates strongly with quarterly GDP growth over the overlap sample (target corr ≥ 0.6 pre-COVID) and is not dominated by short-history series (compare MAI with/without Tier-2 scraped series). If the MAI is junk, fix the panel before MIDAS.
3. **Phase 6 cutover gate (competitive-enough):** real-time POOS backtest shows v2 within-noise of v1 on post-COVID QoQ RMSE (within ~10%) AND hit rate not materially worse, AND v2 delivers the MAI + no-worse downturn behaviour. Clear → cut over. Not clear → iterate or hold (recorded, v1 stays).

---

## File structure (all new files under `nowcasting_v2/`)

```
nowcasting_v2/
  rba_paper/                      # REFERENCE ONLY (already present) — paper + their code/data
  R/
    methods/                      # symlink-or-copy of rba_paper/content/Code/methods (sourced verbatim)
    fetch/                        # our data-ingestion layer
      fetch_abs_panel.R           # ABS series via readabs (labour, retail, trade, house prices)
      fetch_rba_panel.R           # RBA free CSVs (credit D2, yields F2, payments C1, equities F7)
      scrape_nab_full.R           # extend NAB scraper to all sub-indices (conditions/forward/trade/stocks/profit/emp)
      scrape_anz_ivi.R            # ANZ job ads + ANZ-Roy Morgan confidence + Jobs&Skills IVI
      fetch_substitutes.R         # Judo/S&P PMI (AiG replacement), WMI scrape-or-substitute
    build_panel.R                 # assemble all sources -> monthly wide panel + save vintage
    transform_panel.R            # adapt RBA Transform_MAI_Data.R: stationarity + standardise (uses panel_info.csv)
    build_mai.R                   # Stage 1 driver: targeted selection + single-factor DFM -> MAI
    nowcast_midas.R               # Stage 2 driver: U-MIDAS (QA spec) -> GDP nowcast
    emit_json_v2.R                # emit latest.json/gdp.json (same contract) + mai.json (adapts v1 04_emit_json + ci_bands.R)
    run_nowcast_v2.R             # top-level: fetch -> build_panel -> transform -> MAI -> MIDAS -> emit
    compute_ci_params_v2.R        # CI params from v2 backtest (reuses pipeline/compute_ci_params.R logic)
    backtest_v2.R                 # real-time POOS backtest of v2
    analyze_v2_vs_v1.R            # ladder + held-out comparison (reuses 2026-06 analyze_results pattern)
  data_raw/                       # one tidy CSV per source/series
  seed/
    panel_info.csv                # per-series: id, source, tcode, tlog, tgroup, longname (our analogue of mai_info.csv)
  data/                           # v2 outputs staged here pre-cutover: latest.json, gdp.json, mai.json
  cache/                          # gitignored: panel vintages, estimated MAI, backtest output
  tests/
    fixtures/                     # saved sample PDFs/HTML/CSVs for deterministic parser tests
    test_*.R
  NIGHT-LOG.md                    # running decision log (as in the 2026-06 work)
src/                              # MODIFIED only in Phase 5: +MAI chart, types.ts/data.ts +mai
```

---

## Phase 0 — Environment + obtain the replication baseline

### Task 0.1: Install v2 R dependencies

**Files:** none created.

- [ ] **Step 1:** Install `midasr` + confirm the RBA methods' deps load.
  Run: `cd pipeline && Rscript -e 'install.packages(c("midasr"), repos="https://cloud.r-project.org"); for (p in c("midasr","readabs","pdftools","rvest","seasonal","testthat","dplyr","readr","lubridate")) cat(p, requireNamespace(p, quietly=TRUE), "\n")'`
  Expected: every package prints `TRUE`.
- [ ] **Step 2:** No commit (environment only).

### Task 0.2: Wire the RBA methods into the v2 tree

**Files:** Create `nowcasting_v2/R/methods/` (copy of `nowcasting_v2/rba_paper/content/Code/methods/`).

- [ ] **Step 1:** Copy the methods so our drivers source a stable path:
  `mkdir -p nowcasting_v2/R/methods && cp nowcasting_v2/rba_paper/content/Code/methods/*.R nowcasting_v2/R/methods/`
- [ ] **Step 2: Verify they source without error**
  Run: `cd nowcasting_v2/R && Rscript -e 'for (f in list.files("methods", full.names=TRUE)) source(f); cat("methods sourced OK\n")'`
  Expected: prints `methods sourced OK` (resolve any missing-package errors against Task 0.1).
- [ ] **Step 3: Commit** `git add nowcasting_v2/R/methods && git commit -m "v2(setup): vendor RBA methods/ into nowcasting_v2/R"`

### Task 0.3: Create the v2 sandbox skeleton + night log

**Files:** Create `nowcasting_v2/{data_raw,data,cache,seed,tests/fixtures}/.gitkeep`, `nowcasting_v2/NIGHT-LOG.md`, `nowcasting_v2/cache/.gitignore` (`*`).

- [ ] **Step 1:** `mkdir -p nowcasting_v2/{data_raw,data,cache,seed,tests/fixtures}; printf '*\n!.gitignore\n' > nowcasting_v2/cache/.gitignore; printf '# Nowcast v2 build log\n' > nowcasting_v2/NIGHT-LOG.md`
- [ ] **Step 2: Commit** `git add nowcasting_v2/NIGHT-LOG.md nowcasting_v2/cache/.gitignore && git commit -m "v2(setup): sandbox skeleton + log"`

---

## Phase 1 — Replicate the RBA MIDAS layer (PARITY GATE)

> Validates we drive `methods/` + `midasr` correctly, using the RBA's frozen MAI. Run from `nowcasting_v2/rba_paper/content/` (their scripts use relative `Code/`/`Data/` paths). The Stage-1 scripts are commented out in `Run_MAI_NC_GDP_Replication.R` (censored data) — we run the downstream MIDAS scripts that DO work.

### Task 1.1: Run the reproducible replication scripts

**Files:** writes to `nowcasting_v2/rba_paper/content/Results/` (their output dir).

- [ ] **Step 1:** Run the working subset:
  `cd nowcasting_v2/rba_paper/content && Rscript -e 'source("Code/Modelling_GDP_MIDAS_TP.R"); source("Code/Recursive_Nowcast_GDP_UMIDAS_TP.R"); source("Code/Recursive_Nowcast_GDP_UMIDAS_TP_MSEF_BOOTSTRAP.R")'`
  Expected: completes; writes results (CSV/figures) to `Results/`. Capture stdout to `../../cache/phase1_replication.log` via `> ../../cache/phase1_replication.log 2>&1`.
- [ ] **Step 2:** If a script errors on a missing package or path, fix the env/path (NOT their logic) and re-run. Log any deviation in `NIGHT-LOG.md`.

### Task 1.2: Parity check vs the paper

**Files:** Create `nowcasting_v2/R/check_replication_parity.R`; Test: `nowcasting_v2/tests/test_parity.R`.

- [ ] **Step 1: Extract the paper's benchmark numbers** — from `rba_paper/rdp2024-04.pdf` Table 3 (RMSE/MAE by model) and Table 4 (MSE-F test stats + p-values; full-sample QA test stat 135.34, p 0.00; pre-COVID QA 11.47, p 0.00). Record them as constants in `check_replication_parity.R`.
- [ ] **Step 2: Write the failing test** comparing our `Results/` output to those constants within tolerance:
```r
# tests/test_parity.R
test_that("replicated MSE-F matches the paper within tolerance", {
  res <- read_replication_results("rba_paper/content/Results")  # defined in check_replication_parity.R
  expect_equal(res$msef_qa_full, 135.34, tolerance = 0.05)      # ~5% relative
  expect_lt(res$pval_qa_full, 0.05)
})
```
- [ ] **Step 3: Run → FAIL** (function/results not wired): `cd nowcasting_v2 && Rscript -e 'library(testthat); source("R/check_replication_parity.R"); test_file("tests/test_parity.R")'`
- [ ] **Step 4: Implement** `read_replication_results()` to parse the relevant `Results/` file(s) and the parity constants.
- [ ] **Step 5: Run → PASS.** If values are materially off (>5%), STOP — investigate how we're invoking their scripts (this is the parity GATE). Record resolution in `NIGHT-LOG.md`.
- [ ] **Step 6: Commit** `git add nowcasting_v2/R/check_replication_parity.R nowcasting_v2/tests/test_parity.R && git commit -m "v2(phase1): replicate RBA MIDAS layer + parity gate"`

---

## Phase 2 — Data acquisition (our panel; sandbox; external reads only)

> Goal: a monthly wide panel covering as many of the RBA's 30 targeted predictors as obtainable, each a tidy `date,value` CSV under `data_raw/`, plus `seed/panel_info.csv` (id, source, tcode, tlog, tgroup, longname). Tier 1 first (free, high-history — gets the MAI viable), then Tier 2 (scrape), then Tier 3 (substitute/drop). **Each fetcher follows the same TDD pattern; the worked example below is the template — apply it per series.** Sub-tracks 2A/2B/2C are independent and may be parallelised.

### Fetcher TDD pattern (apply to every series)

1. Save a fixture (download the source once into `tests/fixtures/`).
2. Write a failing `testthat` test asserting the parser yields `date,value`, sorted, plausible range, expected coverage.
3. Implement the parser + a live `fetch_*()` that writes `data_raw/<id>.csv` and prints a coverage line (`<id>: N obs, MIN → MAX`).
4. Run test → PASS; run live fetch → confirm coverage.
5. Add the series' row to `seed/panel_info.csv`.
6. Commit.

**Worked template (RBA credit, D2) — replicate this shape for each series:**
```r
# nowcasting_v2/R/fetch/fetch_rba_panel.R  (one function per series; shown: total credit)
suppressMessages({library(readr); library(dplyr); library(lubridate); library(tibble)})
parse_rba_csv <- function(path, series_id) {        # generic RBA-table parser (locate "Series ID" row, pick column)
  lines <- read_lines(path); sid <- grep("^Series ID,", lines)[1]
  fields <- strsplit(lines[sid], ",", fixed=TRUE)[[1]]; col <- which(fields == series_id)
  if (length(col) != 1) stop("series ", series_id, " not found in ", path)
  body <- lines[(sid+1):length(lines)]; recs <- lapply(body, function(l) strsplit(l, ",", fixed=TRUE)[[1]])
  d <- dmy(vapply(recs, `[`, "", 1)); v <- suppressWarnings(as.numeric(vapply(recs, function(r) r[col], "")))
  tibble(date = floor_date(d, "month"), value = v) |> filter(!is.na(date), !is.na(value)) |> arrange(date)
}
fetch_credit_total <- function(dest="data_raw/credit.csv") {
  url <- "https://www.rba.gov.au/statistics/tables/csv/d2-data.csv"; tmp <- tempfile(fileext=".csv")
  download.file(url, tmp, mode="wb", quiet=TRUE)
  out <- parse_rba_csv(tmp, "DLCACA")   # CONFIRM exact series_id from the fixture header (karpathy: don't guess)
  write_csv(out, dest); cat(sprintf("credit: %d obs, %s -> %s\n", nrow(out), min(out$date), max(out$date))); out
}
```
**Karpathy note:** RBA/ABS series IDs MUST be confirmed against the saved fixture header, not guessed (the 2026-06 work proved this — `search_abs_series` doesn't exist in `readabs 0.4.19`; discover IDs via `read_abs()`).

### Sub-track 2A — Tier 1 free series (`fetch_abs_panel.R`, `fetch_rba_panel.R`)

- [ ] **Task 2A.1 — ABS labour (readabs):** emp, ft_emp, pt_emp, unemployment, underemployment, hours. Discover the 6 series_ids via `read_abs("6202.0")`; one tidy CSV each; add panel_info rows. Apply the pattern; commit.
- [ ] **Task 2A.2 — ABS activity:** retail (8501.0 / household spending), goods exports (5368.0 — reuse v1's `A2718577A`), residential property prices (6432.0/6416.0). Discover ids from fixtures; commit.
- [ ] **Task 2A.3 — RBA free CSVs:** total/housing/business credit (D2), AGS 3/5/10y yields + BBSW for spreads (F2/F1), credit-card payments (C1), equity price index (F7). One function per series in `fetch_rba_panel.R` using `parse_rba_csv`; confirm each series_id from fixtures; commit.
- [ ] **Task 2A.4 — Tier-1 coverage report:** print first/last/n for every Tier-1 series; assert all have history ≥ 2005 and latest within ~2 months. Commit the report to `NIGHT-LOG.md`.

### Sub-track 2B — Tier 2 scraped series (`scrape_nab_full.R`, `scrape_anz_ivi.R`)

- [ ] **Task 2B.1 — NAB full suite:** extend the 2026-06 NAB PDF scraper (recover it from branch `panel-expansion-research:pipeline/experimental/fetch/scrape_nab_survey.R`) to also parse forward orders, trading, stocks, profitability, employment sub-indices from the monthly + quarterly PDFs. Reuse the 21 cached PDF fixtures. TDD per sub-index; log coverage + gaps (expect ~2023+, short — flag for the Phase 3 history-depth check). Commit.
- [ ] **Task 2B.2 — ANZ-Indeed job ads + ANZ-Roy Morgan confidence:** discover the release pages (do not template URLs); fixture + tolerant parser; monthly (job ads) / weekly→monthly (confidence). Log coverage; commit.
- [ ] **Task 2B.3 — Jobs & Skills Australia Internet Vacancy Index:** download the published IVI series (free gov data, often a direct XLSX/CSV); parse total vacancies; commit.

### Sub-track 2C — Tier 3 substitutes (`fetch_substitutes.R`)

- [ ] **Task 2C.1 — PMI substitute:** AiG PMI/PCI are discontinued. Source the **Judo Bank / S&P Global Australia Manufacturing + Services PMI** (the live successor) via its monthly release; if not freely obtainable, record as DROPPED in `panel_info.csv` + `NIGHT-LOG.md` (do not fabricate). Commit.
- [ ] **Task 2C.2 — Consumer sentiment:** attempt a Westpac-MI headline scrape; if licence-blocked, SUBSTITUTE with the already-sourced ANZ-Roy Morgan confidence (note the substitution). Commit.
- [ ] **Task 2C.3 — Final panel manifest:** finalise `seed/panel_info.csv` with every series actually obtained + its tcode/tlog/tgroup (copy codes from `rba_paper/content/Data/mai_info.csv` for shared series; assign for new). Print the obtained-vs-30 coverage summary to `NIGHT-LOG.md`. Commit.

---

## Phase 3 — Build the MAI (Stage 1)

### Task 3.1: Assemble the monthly panel + vintage

**Files:** Create `nowcasting_v2/R/build_panel.R`; Test: `tests/test_build_panel.R`.

- [ ] **Step 1: Write the failing test** — `build_panel()` returns a wide tibble keyed on monthly `date`, one column per `panel_info$id`, dates first-of-month, no all-NA columns.
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** — read every `data_raw/*.csv`, left-join on `date` onto a monthly spine (min→max across series), save `cache/panel_vintage_<YYYYMMDD>.rds` + return wide. Fail loud if a `panel_info` id has no CSV.
- [ ] **Step 4: Run → PASS;** print per-column coverage. **Commit.**

### Task 3.2: Transform to stationary + standardised

**Files:** Create `nowcasting_v2/R/transform_panel.R`; Test: `tests/test_transform.R`.

- [ ] **Step 1: Write the failing test** — for a known input column with `tcode`/`tlog`, `transform_panel()` returns the expected stationary, ~zero-mean/unit-variance output (assert mean≈0, sd≈1 over the non-NA sample; assert the differencing matches the tcode).
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** by adapting `rba_paper/content/Code/Transform_MAI_Data.R` — apply per-series `tcode` (level/diff/%); `tlog`; then standardise. Drive it from `seed/panel_info.csv`.
- [ ] **Step 4: Run → PASS. Commit.**

### Task 3.3: Targeted-predictor selection + MAI estimation

**Files:** Create `nowcasting_v2/R/build_mai.R`; Test: `tests/test_mai.R`.

- [ ] **Step 1: Implement** the driver: (a) re-run the RBA targeted-predictor selection (adapt `Targeted_Predictor_MAI_Dataset.R`, which needs the quarterly indicator set + first-release GDP — source GDP from ABS `A2304402X` real-time and the quarterly indicators analogous to `qtr_int.csv`) on OUR transformed panel; (b) estimate a **single-factor** DFM via `methods/qmle_dfm_methods.R` (confirm factor count with `methods/ndfm_methods.R`); (c) extract the monthly MAI; save `cache/mai.rds` + `data_raw/mai.csv`.
- [ ] **Step 2: Write the MAI sanity test (GATE 2)** — correlation of the MAI (quarterly-averaged) with quarterly GDP growth ≥ 0.6 over the pre-COVID overlap; and the MAI is not materially driven by short-history Tier-2 series (re-estimate without them; corr stays ≥ ~0.55).
- [ ] **Step 3: Run → PASS or STOP** (Gate 2). If it fails, revisit the panel (Phase 2) before MIDAS. Log the MAI diagnostics to `NIGHT-LOG.md`.
- [ ] **Step 4: Commit.**

---

## Phase 4 — MIDAS nowcast (Stage 2)

### Task 4.1: U-MIDAS nowcast driver

**Files:** Create `nowcasting_v2/R/nowcast_midas.R`; Test: `tests/test_nowcast_midas.R`.

- [ ] **Step 1: Implement** — feed the monthly MAI + first-release quarterly GDP into a U-MIDAS regression (`midasr` + the spec from `Modelling_GDP_MIDAS_TP.R`, including the **QA current-quarter** term). Return the current-quarter GDP-growth nowcast + implied level (prev released level × (1+growth)).
- [ ] **Step 2: Write the failing test** — on a fixed historical as-of date with a frozen MAI slice, the nowcast is finite, within a plausible band (e.g. |qoq| < 5% outside COVID), and reproduces a hand-checked value to tolerance.
- [ ] **Step 3: Run → FAIL → implement → PASS. Commit.**

### Task 4.2: End-to-end `run_nowcast_v2.R`

**Files:** Create `nowcasting_v2/R/run_nowcast_v2.R`.

- [ ] **Step 1: Implement** the top-level chain: fetch (optional `--no-fetch` to reuse cache) → `build_panel` → `transform_panel` → `build_mai` → `nowcast_midas` → return a `nowcast` list (target_quarter, nowcast_value, qoq_growth, yoy_growth, latest_actual_value, mai_series).
- [ ] **Step 2: Run it** end-to-end on cached data; confirm it prints a current-quarter nowcast + MAI tail. **Commit.**

---

## Phase 5 — Emit layer + `mai.json` + site

### Task 5.1: v2 emit (same contract + mai.json)

**Files:** Create `nowcasting_v2/R/emit_json_v2.R`; copy `pipeline/ci_bands.R` → `nowcasting_v2/R/ci_bands.R`; Test: `tests/test_emit_v2.R`.

- [ ] **Step 1: Implement** by adapting `pipeline/04_emit_json.R`: emit `latest.json` + `gdp.json` with the SAME schema (so the site is unchanged) from the v2 `nowcast`, using the bias-aware `ci_bands.R` + a v2 `seed/ci_params.json`; ADD `mai.json` = `{ generated_at, series: [{date, value}], latest }`.
- [ ] **Step 2: Write the failing test** — emitted `latest.json` validates against `src/lib/types.ts` field names (`gdp_chain_volume_millions`, `qoq_growth_pct`, `ci_68_low/high`, `ci_95_low/high`); `mai.json` has the expected shape.
- [ ] **Step 3: Run → FAIL → implement → PASS;** emit into `nowcasting_v2/data/` (NOT repo `data/`). **Commit.**

### Task 5.2: Site — MAI chart + types

**Files:** Modify `src/lib/types.ts`, `src/lib/data.ts`; Create `src/components/MaiChart.tsx`; Modify the page that renders the dashboard to include it.

- [ ] **Step 1:** Add a `Mai`/`MaiSeries` interface to `types.ts` + a default in `data.ts`; load `mai.json`.
- [ ] **Step 2:** Create `MaiChart.tsx` (a line chart of the monthly MAI, matching existing chart components' props/styling — follow `VintageChart.tsx`/`IndicatorDetailCard.tsx` patterns).
- [ ] **Step 3:** Render it in the dashboard page below the GDP nowcast. Run `npm run build` → passes.
- [ ] **Step 4: Commit** (frontend change is additive; GDP UI untouched).

---

## Phase 6 — Validation backtest + cutover (CUTOVER GATE)

### Task 6.1: Real-time POOS backtest of v2

**Files:** Create `nowcasting_v2/R/backtest_v2.R`.

- [ ] **Step 1: Implement** — for each quarter-end as-of date over 2015→latest, rebuild the panel vintage as-of that date (respecting each series' publication lag, like v1's release calendar), re-estimate MAI + MIDAS, record the nowcast vs the realised first-release GDP. Write `cache/backtest_v2/backtest_results.csv` (same columns as v1's backtest_results for reuse).
- [ ] **Step 2: Run** (long); confirm output covers post-COVID quarters incl. 2026 Q1.

### Task 6.2: v2-vs-v1 comparison

**Files:** Create `nowcasting_v2/R/analyze_v2_vs_v1.R` (reuse the `analyze_results.R` ladder/held-out logic from branch `panel-expansion-research`).

- [ ] **Step 1: Implement** — read v2 + v1 baseline backtest_results; compute post-COVID QoQ RMSE/hit + Q1-2026 held-out for both; print the gate readout (within ~10% RMSE? hit not worse? downturn behaviour?).
- [ ] **Step 2:** Generate `compute_ci_params_v2.R` → `nowcasting_v2/seed/ci_params.json` from the v2 backtest. **Commit** the analysis + params.

### Task 6.3: Decision + cutover

**Files (only if gate passes):** Modify `.github/workflows/*nowcast*`, move `nowcasting_v2/R/*` into the production path (or repoint the Action at `nowcasting_v2/R/run_nowcast_v2.R`), repoint emit `target_dir` to repo `data/`, retire `pipeline/*.R`.

- [ ] **Step 1: Write the decision doc** `docs/backtest-recommendation-v2-2026-<dd>.md` — the ladder + held-out tables, the competitive-enough verdict (GATE 3), and the go/no-go.
- [ ] **Step 2: If GO:** repoint the GitHub Action to run `run_nowcast_v2.R` emitting to `data/`; remove/retire `pipeline/*.R` (kept in git history); run the full chain once; confirm `data/latest.json` + `mai.json` + the site build. **Commit** as the cutover.
- [ ] **Step 3: If NO-GO:** record why; leave v1 running; list the smallest changes that might close the gap. **Commit** the decision only.
- [ ] **Step 4: Update memory** — record the v2 outcome (shipped or held) and supersede/annotate `project-panel-expansion-result`.

---

## Self-review notes

- **Spec coverage:** sequencing (Phases 1→2-5→6), maximize-coverage data (Phase 2 tiers 2A/2B/2C), competitive-enough cutover (Gate 3 / Task 6.3), engine-swap + mai.json + one chart (Phase 5), approach C hybrid (methods/ vendored in 0.2 + reused in Phases 3-4) — all covered. The three spec risks (history depth, AiG dead, methods/ as-is) appear as Gate 2 / Task 2C.1 / Phase 1 respectively.
- **Discovery-dependent code** (scraper regexes, exact series_ids) is intentionally given as a TDD *pattern + per-series targets* rather than fabricated parser code — the same approach that worked in the 2026-06 fetcher work; the worked RBA-CSV template is complete and copyable.
- **Reuse:** NAB scraper, `ci_bands.R`, `analyze_results.R`, and v1's `04_emit_json` structure are explicitly recovered/adapted rather than rewritten.
- **No production touch before Phase 6:** every write before cutover is under `nowcasting_v2/`; Phase 1 runs only in the reference dir's `Results/`.
