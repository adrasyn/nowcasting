# v2 on the first print, 11 September 2026

Two runs of `backtest_v2()` (nowcasting_v2/R/backtest_v2.R) on today's panel, weekly as-of grid 2022-01-03 to
2026-09-07 (245 as-ofs, 236 nowcasts each), the shipping configuration (`qa`, alpha 0.10, dfm_q 1, `.lag_acc`,
AiG and rt excluded, recursive selection). Only `gdp_csv` differs: the latest-vintage series
(`data_raw/rt_dgdp_qtr.csv`) vs the first-release series (nowcasting_v3/data/gdp_first_release.csv reshaped).
Scored against the ABS first print on targets 2022Q4..2026Q2, the v3 A/B's window. Data:
`docs/measurements/2026-09-11-v2-backtest-revised-target-2022on.csv` and
`docs/measurements/2026-09-11-v2-backtest-first-release-target-2022on.csv`.

## Per quarter (average of the quarter's weekly vintages), n=15 unless stated

| arm | bias | MAE | RMSE | corr with print |
|---|---|---|---|---|
| v2 as shipped (revised target) | +0.313 | 0.332 | 0.393 | 0.12 |
| v2 less 0.0989pp | +0.214 | 0.270 | 0.320 | 0.12 |
| v2 less the adjustment as known at the time | +0.235 | 0.284 | 0.339 | 0.10 |
| v2 less its rolling miss (expanding, min 4) | -0.182 | 0.262 | 0.294 | 0.20 | (n=11)
| v2 retrained on first-release GDP | +0.102 | 0.174 | 0.215 | 0.43 |
| v2 retrained + rolling miss | +0.037 | 0.196 | 0.234 | 0.24 | (n=11)

Mean series selected per vintage: 12.9 (revised target) vs 17.5 (first-release target).

## Per vintage, common window (from 2023-12-11, n=142)

| arm | bias | MAE | RMSE |
|---|---|---|---|
| v2 as shipped (revised target) | +0.250 | 0.295 | 0.386 |
| v2 less 0.0989pp | +0.152 | 0.253 | 0.331 |
| v2 less the adjustment as known at the time | +0.167 | 0.258 | 0.340 |
| v2 less its rolling miss (expanding, min 4) | -0.181 | 0.297 | 0.342 |
| v2 retrained on first-release GDP | +0.144 | 0.224 | 0.282 |
| v2 retrained + rolling miss | +0.037 | 0.210 | 0.269 |

Rolling-4 and rolling-8 windows give the same ordering (v2_arms.json in the session scratchpad).

## Against v3 on the same quarters (per quarter, vs first print)

| arm | v2 bias | v2 MAE | v3 bias | v3 MAE |
|---|---|---|---|---|
| base_raw | +0.313 | 0.332 | +0.190 | 0.225 |
| base_adj_const | +0.214 | 0.270 | +0.091 | 0.159 |
| base_bc | -0.182 | 0.262 | -0.092 | 0.182 |
| treat_raw | +0.102 | 0.174 | +0.128 | 0.177 |
| treat_bc | +0.037 | 0.196 | -0.059 | 0.162 |

Finding: for v2 the target is most of the bias. Retrained on first-release GDP (as RDP 2024-04 did), bias
+0.31 -> +0.10pp, MAE 0.33 -> 0.17pp, correlation with the print 0.12 -> 0.43; the Wald gate admits ~18
series instead of ~13. The rolling miss on the retrained model moves bias to ~0 at a small cost in error.
Retrained v2 lands within a few hundredths of v3's arms. Recommendation: point v2's weekly fetch at the
first-release series; no correction at launch. Write-up published as an artifact the same day.
