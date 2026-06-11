# Nowcast v2 — RBA MAI + MIDAS methodology — Design Spec

**Date:** 2026-06-04
**Status:** Design approved (brainstorming) — pending user review before plan.
**Goal:** Replace the v1 nowcast engine (13-series flat DFM straight to GDP) with the RBA's **Monthly Activity Indicator (MAI) + MIDAS** methodology (Hartigan & Rosewall, RDP 2024-04), as a full v2, while keeping the existing website working and adding the MAI as a new product.

**Reference materials:** `nowcasting_v2/rba_paper/` — the paper (`rdp2024-04.pdf`), read-me, full replication code (`content/Code/`, incl. `methods/`), and data (frozen MAI + real-time vintages).

---

## Why (context)

- v1 is a 13-series flat 3-factor DFM that nowcasts the GDP **level** directly. The 2026-06 panel-expansion study (`docs/backtest-recommendation-2026-06-04.md`, on branch `panel-expansion-research`) concluded **NO-GO**: adding variables didn't improve accuracy or fix the Q1-2026 miss.
- RDP 2024-04 explains why and offers a better-grounded approach. Its key empirical finding: **Australian quarterly GDP growth is serially uncorrelated**, so monthly-information models barely beat a sample-mean benchmark *in normal times*; their value concentrates in **downturns**, and the only variant that beats the mean in both regimes is the one using **current-quarter** information ("QA"). This reframes success: v2's edge is downturn robustness + the MAI as a product, not lower normal-times RMSE.

## Decisions locked in brainstorming

| Decision | Choice |
|---|---|
| **Sequencing** | **Replicate-then-build.** Phase 1: validate the RBA engine on their frozen MAI (reproduce their published numbers). Phase 2: rebuild a live MAI from our data + MIDAS nowcast. Then backtest vs v1 and cut over. |
| **Data policy** | **Maximize coverage** — chase as many of the 30 targeted predictors as obtainable (free + scrape + manual), documenting per-series feasibility + fallbacks. |
| **Cutover bar** | **Competitive-enough** — replace v1 if v2 is within-noise of v1 on normal-times accuracy AND adds clear value (MAI, COVID robustness, methodological credibility). |
| **Output scope** | **Engine swap + add MAI** — same JSON contract (`latest.json`, `gdp.json`) so the site keeps working; add `mai.json` + one new MAI chart. v1 `pipeline/*.R` retired (kept in history). |
| **Build approach** | **C — Hybrid.** Reuse the RBA `methods/*.R` verbatim for the estimation math; wrap with our own data-ingestion + emit layers. Build parallel in `nowcasting_v2/`; cut over only after the bar is cleared. |

## The RBA method (what we're adopting)

Two stages:
1. **MAI (Stage 1):** ~53 monthly series → keep the ~30 best predictors of GDP (targeted selection) → compress to a **single-factor** dynamic factor model → one monthly **Monthly Activity Indicator**. Published spec: `q=1, s=2, p=1`.
2. **Nowcast (Stage 2):** feed the monthly MAI into an **unrestricted MIDAS** regression (handles monthly→quarterly mixed frequency properly) → quarterly real GDP-growth nowcast. Adopt their best spec including the **current-quarter ("QA")** information.

**Replication constraint (verified):** the public package's MAI-estimation scripts fail because licensed series are stripped from `mai_panel.csv`; the RBA ships the **pre-computed (frozen) MAI** so only the downstream MIDAS layer self-replicates. We therefore reproduce the MIDAS layer (Phase 1) and rebuild Stage 1 ourselves on our own data (Phase 2).

---

## Architecture

Three layers, built parallel in `nowcasting_v2/`:

```
 OUR DATA LAYER (own)            RBA ESTIMATION CORE (their methods/, verbatim)     OUR EMIT LAYER (own)
 free fetchers (ABS/RBA) ─┐
 scrapers (NAB/ANZ/IVI)  ─┼─► monthly panel ─► transform ─► targeted select ─► MAI(DFM) ─► U-MIDAS ─► latest.json/gdp.json (same)
 manual CSVs ─────────────┘    (+ vintages,                                    (q=1)     (QA)      + NEW mai.json ─► Next.js (+1 chart)
                                ragged edge)
```

**The seam (approach C):** `methods/qmle_dfm_methods.R`, `mai_utils.R`, `ndfm_methods.R`, and the MIDAS scripts are sourced untouched for the math. Everything around them — fetching, ragged-edge/vintages, JSON emit, the site — is ours and matches the existing project. Phase 1 validates exactly the `methods/` code we reuse.

### Data layer

Candidate pool = the RBA's 30 targeted predictors, tiered by sourceability:

| Tier | ~Count | Series | Source / method |
|---|---|---|---|
| **1 — Free + automatable** | ~16 | emp, ft/pt emp, unemployment, underemployment, hours; retail; exports; house prices; total/housing/business credit; credit-card payments; AGS 3/5/10y yields + spreads; equity prices | ABS via `readabs`; RBA free CSVs (D2 credit, F2 yields, C1 payments, F7 equities). Long history. |
| **2 — Scrapable (free, fragile)** | ~9 | NAB suite (conditions, forward orders, trading, stocks, profitability, employment); ANZ-Indeed job ads; ANZ-Roy Morgan confidence; Jobs & Skills AU Internet Vacancy Index | Extend the existing NAB PDF scraper to all sub-indices; new scrapers for ANZ/IVI monthly releases. |
| **3 — Proprietary / dead** | ~4 | AiG PMI + PCI (discontinued ~2023); Westpac-MI consumer sentiment + family finances (proprietary) | AiG → substitute Judo Bank/S&P Global PMI (live successor) or drop; WMI → scrape headline or substitute ANZ-RM. Per-series decision documented. |

Realistic coverage **~25 of 30**.

Data-layer components:
1. **Panel assembly** — all sources → one tidy monthly wide panel; save a **vintage** each run (real-time-honest backtests).
2. **Transform** — adapt `Transform_MAI_Data.R`: per-series stationarity code + log flag + standardise, reusing `mai_info.csv` codes for shared series, assigning codes for new ones.
3. **Targeted-predictor selection** — re-run the RBA selection on *our* pool (needs the quarterly indicator set + GDP).
4. **Ragged edge / real-time** — the MAI DFM's EM/Kalman handles partially-reported latest months natively (as v1 does).

**Key risk — history depth.** The MAI DFM wants long history (theirs: 1979–2021). Tier-1 series have it; **Tier-2 scraped series are short** (NAB only ~2023 from prior work), so they barely inform the historical MAI. Mitigations: lean on long Tier-1 series for the MAI core; seek deeper historical backfills for scraped series; let selection/EM down-weight short series; measure the MAI with/without them.

### Estimation core

- **Stage 1:** targeted selection → single-factor DFM (`qmle_dfm_methods.R`; `ndfm_methods.R` to confirm factor count) → monthly MAI.
- **Stage 2:** U-MIDAS via `midasr` + `Modelling_GDP_MIDAS_TP.R` spec, including the **QA current-quarter** term → quarterly GDP-growth nowcast + level.
- Thin drivers feed our panel in, pull MAI + nowcast out — the only new code here.

### Emit layer + site

- `latest.json`, `gdp.json` — **same contract** (site unchanged); reuse v1's `04_emit_json` structure.
- **NEW `mai.json`** — monthly MAI series + metadata.
- **CI bands carry over** — the bias-aware empirical bands (just shipped), regenerated from *v2's own* backtest errors via `compute_ci_params.R`.
- **Site:** one new MAI chart/section reading `mai.json`; `types.ts`/`data.ts` extended; existing GDP UI untouched.

---

## Validation, cutover, testing

- **Phase 1 parity gate:** reproduce the RBA's published nowcast figures (Tables 3/4) on their frozen MAI, within tolerance → proves we drive `methods/` correctly before reusing it.
- **Phase 2 backtest:** real-time POOS backtest of v2 (our MAI → MIDAS) **vs v1**, identical window + metrics (post-COVID QoQ RMSE/hit, Q1-2026 held-out), reusing the `analyze_results` harness pattern from the panel-expansion work.
- **Cutover gate (competitive-enough):** v2 within-noise of v1 on post-COVID accuracy AND delivers the MAI + better downturn behaviour. Clear → repoint GitHub Action + site at v2 outputs, retire `pipeline/*.R`. Not clear → iterate or hold, documented.
- **Testing:** fixture-based unit tests for every fetcher/scraper/transform/emit; the Phase 1 parity check; the backtest harness. Karpathy gates throughout — fail loud on data, sandbox in `nowcasting_v2/` until cutover.

## Risks & open items

- **History depth** for scraped Tier-2 series (above) — the biggest technical risk to MAI quality.
- **AiG PMI/PCI dead** — substitute (Judo/S&P PMI) or drop; confirm during Phase 2 data work.
- **RBA `methods/` is "as-is, unsupported"** and assumes static (non-live) samples — adapting to ragged-edge weekly updates may surface friction at the seam; Phase 1 de-risks by running it first.
- **Licensing** — we must source our own copies of any proprietary series (not reuse theirs); document attribution.
- **Normal-times accuracy** — by the paper's own finding, v2 may not beat v1 in calm quarters; the competitive-enough bar + the MAI/COVID value account for this.

## Out of scope

- Site redesign beyond one MAI chart.
- Block-structured / multi-factor extensions beyond the RBA's `q=1` MAI.
- Re-litigating the v1 panel-expansion variables (settled: NO-GO).
- Pushing to remote / deploying — cutover wiring is in scope, the deploy trigger is the user's call.
