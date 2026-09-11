# v2 + v3 weekly-vintage combination, scored against the ABS's initial estimates

**Date:** 2026-09-12. **Question:** does an equal-weight average of v2 (retargeted to the ABS's initial GDP estimates) and v3 (the live method: retrained on initial estimates, less its rolling miss) beat either model, when both are evaluated at the same Monday vintages?

**Answer:** yes, by about a quarter of the error. Over 181 Mondays (targets 2022Q4 to 2026Q2) the average has MAE 0.129pp against 0.185 for v2 and 0.174 for v3. The two models' weekly errors are essentially uncorrelated (r = +0.05), which is the condition under which equal weights come close to the optimal combination (Bates and Granger 1969; the "forecast combination puzzle" is that estimated weights rarely beat equal ones on samples this short).

## Inputs

- **v2:** the shipping-configuration backtest on the initial-estimate target, weekly Mondays from 2022 (`2026-09-11-v2-backtest-first-release-target-shipping.csv`, produced by `nowcasting_v2/R/recalib_ci_v2.R` on branch `feat/v2-first-release-target`). Identical on the overlap to the A/B run in `2026-09-11-v2-first-print-ab.md`.
- **v3:** `tools/plan_c_backtest.py` re-run at every Monday 2023-01-02 to 2026-08-31 instead of monthly (`2026-09-12-v3-weekly-vintage-first-print-seed{4,13,19}.csv`; 189 Mondays each, 2026-08-31 unbuildable because a panel series was stale at that as-of). Median across seeds per Monday. Two chains (seed 19, June 2023) collapsed and were dropped, leaving a two-seed median there. The rolling-miss correction is the live one: `rolling_miss` over the backtest misses in `data/first_print_misses.csv`, recursive, window 8, minimum 4, zero before four prints exist.
- **Score:** nowcast minus the ABS's initial estimate (`nowcasting_v3/data/gdp_first_release.csv`). Per Monday; per quarter (mean of the quarter's Mondays); final pre-print Monday.
- Joined data: `2026-09-12-v2-v3-weekly-combination.csv`.

## Results

| Arm | Bias (pp) | MAE | RMSE | Per-qtr bias | Per-qtr MAE | Final-vintage MAE |
|---|---|---|---|---|---|---|
| v2, initial-estimate target | +0.102 | 0.185 | 0.245 | +0.094 | 0.176 | 0.172 |
| v2 less its own rolling miss (8q) | -0.001 | 0.184 | 0.248 | -0.010 | 0.172 | 0.180 |
| v3 retrained, raw | +0.133 | 0.186 | 0.219 | +0.132 | 0.183 | 0.188 |
| v3 live method (retrained less rolling miss) | +0.017 | 0.174 | 0.205 | +0.018 | 0.173 | 0.166 |
| Equal-weight: v2 + v3 raw | +0.117 | 0.159 | 0.196 | +0.113 | 0.151 | 0.153 |
| **Equal-weight: v2 + v3 live** | +0.059 | 0.129 | 0.166 | +0.056 | 0.123 | 0.132 |
| Equal-weight: v2 corrected + v3 live | +0.008 | 0.133 | 0.177 | +0.004 | 0.125 | 0.136 |

Weekly n = 181; per-quarter and final-vintage n = 15.

By days to the ABS release (MAE, and the empirical band of the combination's absolute error):

| Horizon | n | v2 | v3 | Combination | 68% | 90% |
|---|---|---|---|---|---|---|
| <30d | 60 | 0.172 | 0.165 | 0.129 | ±0.16 | ±0.29 |
| 30-60d | 60 | 0.178 | 0.177 | 0.127 | ±0.14 | ±0.29 |
| 60-90d | 56 | 0.215 | 0.185 | 0.136 | ±0.13 | ±0.34 |
| >90d | 5 | 0.082 | 0.124 | 0.088 | ±0.09 | ±0.16 |

Per quarter (mean of the quarter's Mondays):

| Quarter | ABS initial | v2 | v3 | Combination |
|---|---|---|---|---|
| 2022Q4 | 0.48 | 0.32 | 0.65 | 0.49 |
| 2023Q1 | 0.23 | 0.19 | 0.51 | 0.35 |
| 2023Q2 | 0.36 | 0.44 | 0.42 | 0.43 |
| 2023Q3 | 0.21 | 0.24 | 0.45 | 0.34 |
| 2023Q4 | 0.24 | 0.34 | 0.19 | 0.26 |
| 2024Q1 | 0.13 | 0.58 | 0.29 | 0.44 |
| 2024Q2 | 0.23 | 0.49 | 0.18 | 0.34 |
| 2024Q3 | 0.33 | 0.67 | 0.19 | 0.43 |
| 2024Q4 | 0.58 | 0.68 | 0.40 | 0.54 |
| 2025Q1 | 0.21 | 0.22 | 0.40 | 0.31 |
| 2025Q2 | 0.60 | 0.83 | 0.23 | 0.53 |
| 2025Q3 | 0.39 | 0.50 | 0.45 | 0.47 |
| 2025Q4 | 0.79 | 0.64 | 0.48 | 0.56 |
| 2026Q1 | 0.27 | 0.59 | 0.54 | 0.56 |
| 2026Q2 | 0.42 | 0.16 | 0.37 | 0.26 |

## Reading it

- The gain is not a bias effect. v2 corrected by its own rolling miss (bias -0.001) has the same MAE as raw v2; the combination's gain comes from the two models missing different quarters (2024Q1 to 2024Q3 v2 was high and v3 low; 2025Q1 the reverse).
- The gain holds at every horizon inside 90 days, and is largest in the 60 to 90 day window where v2 is weakest.
- Correcting v2 as well (last row) removes the residual bias but adds nothing to MAE; the simpler combination (v2 raw, v3 as it ships) is the one to prefer.
- Bands: a 68% band of about ±0.15pp and a 90% band of about ±0.30pp would be honest for the combination; v3's own published bands are wider.
- Caveats: 15 quarters; v2's weekly vintages replay the 23 August 2026 panel with release-date cuts and v3's replay its vintage store with per-series publication lags, so neither is a true real-time archive; the v3 weekly run used the 200-sweep warm start of the backtest protocol, not the production sampler.

No presentation or shipping decision is taken here. See the interactive chart artifact of the per-quarter arms for the same series drawn.
