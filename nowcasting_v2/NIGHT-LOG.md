# Nowcast v2 (RBA MAI+MIDAS) — build log

**Branch:** nowcast-v2 (NOT pushed). **Plan:** docs/superpowers/plans/2026-06-04-nowcast-v2-rba-mai-midas.md
**Rule:** sandbox under nowcasting_v2/ only; NO production touch; NO autonomous Phase-6 cutover.

## Phase 0 — env + setup
- Branch nowcast-v2 off main (4d0f5f3).
- Vendored rba_paper methods/ -> nowcasting_v2/R/methods/.
- Skeleton + cache/.gitignore created.
- midasr install running.

## Phase 1 — replicate RBA MIDAS layer — PARITY GATE: PASS ✅
- Ran the 3 reproducible MIDAS scripts (Modelling_GDP_MIDAS_TP, Recursive_Nowcast_GDP_UMIDAS_TP, ..._MSEF_BOOTSTRAP) on the RBA frozen MAI, renv lib on .libPaths, cwd=rba_paper/content.
- **Parity: 22/22 metrics match the paper.** QA MSE-F full 135.337 vs 135.34 (0.00%); pre-COVID 11.468 vs 11.47; all 14 Table-3 RMSE match to 2dp. test_parity.R 6/6 PASS (re-verified independently).
- Deviations: libPaths set; bootstrap run at 200 reps for canonical CSVs (MSE-F stats are deterministic; p-values approx; a 1000-rep run was left finishing in background to refine p-values only). No statistical logic changed.
- **Engine validated** — we drive their U-MIDAS correctly on R 4.5.1 + this renv lib.
- Phase-2 data contract (from their code): MIDAS needs monthly MAI + quarterly GDP **growth**, ts freq 12/4, `length(monthly)==3*length(qtr)` aligned to quarter starts; QA (quarter-average) model is the headline winner; recursive eval from obs 40 (1988:Q2).

## Phase 2 — data acquisition (in progress)
- Dispatched 2 parallel background subagents (no-commit; each writes own panel_info_tierN.csv to avoid conflicts):
  - 2A Tier-1 free: ABS labour/retail/exports/house-prices + RBA credit/yields/payments/equities (~16 series).
  - 2B Tier-2 scrape: NAB full suite (recovering + extending the panel-expansion NAB scraper), ANZ job ads + ANZ-RM confidence, Jobs&Skills IVI.
- Next: 2C Tier-3 substitutes (Judo/S&P PMI for dead AiG; WMI scrape-or-substitute) + merge panel_info after 2A/2B land.

### Phase 3 prep (Stage-1 understanding, from reading their Code/)
- Transform_MAI_Data.R: tcode(t1=level,t2=diff)+tlog → rolling-center + unit-scale. Reuse via panel_info.csv.
- Targeted_Predictor_MAI_Dataset.R: per-series OLS+HAC regress GDP growth → Wald stat → keep > chi-sq threshold. Inputs: transformed panel + rt GDP growth (rt_dgdp_qtr) + quarterly dummies (qtr_int).
- Estimate_and_Analyse_TP_MAI.R: pc_factor init → qmle_dfm(q=1,s=2,p=1) → single factor = MAI. Reuses qmle_dfm_methods/ndfm_methods/mai_utils.
- => Phase 3 = wire our data into their functions (approach C). Need: our rt quarterly GDP growth + reuse qtr_int.csv (deterministic quarter dummies).

### Phase 2 results — 29 series obtained (~25 of RBA's 30)
- Tier 1 (19): emp,ft_emp,pt_emp,ue(rate),ud,hours,rt,export,credit,credit_housing,credit_business,fcmygbag3/5/10,scrigbag3/5/10(derived),firmmbab90,credit_card. (126 tests pass.) D2 credit spliced at 2019-07 break; AGS yields monthly from 2013 only (pre-2013 = RBA XLS, Tier-3 splice need).
- Tier 2 (10): nab_conf/cond/trade/profit/emp/forward (clean, 2023+), nab_stocks/cu (partial), anz_ads (2021+), anz_sent (1973+, also WMI substitute). 56 tests pass.
- MISSING/BLOCKED: house_prices (RPPI discontinued 2021), asx200 (no free RBA CSV; stooq needs key), ivi/doe_ads (jobsandskills.gov.au firewalls host), aig_pmi/pci (discontinued — Tier-3 Judo substitute pending).
- KEY RISK confirmed: NAB suite is short (2023+); long-history series (labour/credit/anz_sent/export) carry the MAI.
