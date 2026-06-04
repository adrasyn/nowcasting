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
