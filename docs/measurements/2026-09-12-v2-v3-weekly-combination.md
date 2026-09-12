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

## Two horizons (2026-09-12, added)

**Question:** the same combination now also has a NEXT-quarter figure from both models (v2 gained the horizon; the v3 weekly backtest was re-run with the panel padded so it records one every week). How does the average score there, and how wide should its band be?

**Answer:** it still beats both models, by about the same margin, and its band is about a third wider. Over the 51 Mondays where both models had a month of data in the next quarter, the average has MAE 0.160pp against 0.237 for v2 and 0.193 for v3. Its 68% band is ±0.19pp against ±0.14pp at the current horizon.

Produced by `nowcasting_v3/tools/combination_backtest.py`, which writes the joined rows to `2026-09-12-v2-v3-weekly-combination-two-horizons.csv` and the band parameters to `pipeline/seed/ci_params_combo.json`.

### Inputs

- **v2:** `2026-09-12-v2-backtest-initial-estimate-target-two-horizons.csv`, the shipping-configuration backtest re-run with the next-quarter horizon recorded beside the current one.
- **v3:** `2026-09-12-v3-weekly-two-horizons-seed{4,13,19}.csv`, weekly Mondays 2023-01-02 to 2026-08-24, the panel padded so the second horizon exists every week. Median across the three seeds; two collapsed chains (seed 19, June 2023) dropped, leaving a two-seed median on those two Mondays. Less the live rolling-miss correction, the same correction at both horizons, zero on the 47 Mondays before four quarters had printed.
- **Score:** against the ABS's initial estimate, as above.
- **The pairing rule:** a row exists where both models nowcast the same quarter at the same Monday. At the next horizon it is scored only where BOTH had at least one month of data in that quarter, which is the live publication rule: v3 does not record a forecast built on no data and v2 cannot make one. That rule drops 37 of the 88 paired next-quarter Mondays.

### Current quarter (regression check)

| Arm | Bias (pp) | MAE | RMSE | n |
|---|---|---|---|---|
| v2 | +0.102 | 0.185 | 0.245 | 181 |
| v3 raw | +0.133 | 0.186 | 0.219 | 181 |
| v3 (less its rolling miss) | +0.017 | 0.174 | 0.205 | 181 |
| **Combination** | +0.059 | 0.129 | 0.166 | 181 |

Identical to the table at the top of this note, to three decimals, on the same 181 Mondays and with error correlation +0.049. The v2 backtest was re-run and the v3 backtest now pads the panel, and neither changed the current-quarter figures: padding moves a current-quarter nowcast by well under a basis point, and v2's headline path was not touched.

### Next quarter

| Arm | Bias (pp) | MAE | RMSE | n |
|---|---|---|---|---|
| v2 | +0.151 | 0.237 | 0.302 | 51 |
| v3 raw | +0.162 | 0.209 | 0.242 | 51 |
| v3 (less its rolling miss) | +0.044 | 0.193 | 0.224 | 51 |
| **Combination** | +0.098 | 0.160 | 0.205 | 51 |

Error correlation between the two models at this horizon: +0.117. Per quarter (the mean of the quarter's Mondays, 14 quarters): v2 MAE 0.205, v3 0.197, combination 0.158.

### Bands

The published band is the quantile of the combination's own absolute error at that horizon, applied symmetrically around the point.

| Horizon | n | 68% | 95% | MAE | Bias |
|---|---|---|---|---|---|
| Current quarter | 181 | ±0.144 | ±0.351 | 0.129 | +0.059 |
| Next quarter | 51 | ±0.194 | ±0.400 | 0.160 | +0.098 |

By months of data in the target quarter (MAE, and the combination's band):

| Horizon | Months | n | v2 | v3 | Combination | 68% | 95% |
|---|---|---|---|---|---|---|---|
| Current | v2 has 2 | 20 | 0.165 | 0.173 | 0.111 | ±0.12 | ±0.35 |
| Current | v2 has 3 | 161 | 0.187 | 0.174 | 0.131 | ±0.15 | ±0.35 |
| Next | v2 has 1 | 23 | 0.246 | 0.183 | 0.169 | ±0.21 | ±0.34 |
| Next | v2 has 2 | 28 | 0.229 | 0.201 | 0.152 | ±0.18 | ±0.41 |
| Next | v3 has 1 | 51 | 0.237 | 0.193 | 0.160 | ±0.19 | ±0.40 |

v3's backtest records no month count for the current quarter (only the months from the vintage to the quarter's end, which is a different thing), so the current-quarter split is on v2's count alone. At the next horizon v3 always has exactly one month: the second month of the next quarter is published only after the previous quarter has printed, by which time the next quarter has become the current one.

### Reading it

- The combination's advantage is not a current-quarter artefact. At the next horizon it beats the better of the two models by 0.033pp of MAE, against 0.045pp at the current horizon, on a quarter of the sample.
- The next-quarter error is about a quarter larger than the current-quarter error, not twice as large. A forecast with one month of data is worse than a nowcast with three, but not by as much as the calendar gap suggests.
- Both models over-predict more at the next horizon (+0.151 and +0.162 raw) than at the current one, and v3's rolling miss, which is estimated on current-quarter figures, removes most of it anyway (+0.044 residual).
- The two models' errors are more correlated at the next horizon (+0.12 against +0.05). Averaging helps less when the two are looking at the same single month, which is the mechanism the wider band is pricing.
- Every scored next-quarter row sits 100 to 121 days before its release, three or four Mondays per quarter: the weeks after a quarter's first month is published and before its predecessor prints.

### Caveats

- 15 quarters at the current horizon and 14 at the next, which is what 51 next-quarter Mondays are really made of; three or four Mondays inside one quarter are not three or four independent observations, so the per-quarter figures are the conservative reading and the bands are calibrated on a sample whose effective size is nearer 14 than 51.
- Every scored next-quarter row is a ONE-MONTH-OF-DATA forecast. The bands say nothing about a next-quarter figure built on two or three months, and the live rule means the site never publishes one: by the second month the quarter has become current.
- Neither backtest is a true real-time archive. v2's weekly vintages replay the 23 August 2026 panel with release-date cuts; v3's replay its vintage store with per-series publication lags. v3's run used the 200-sweep warm start of the backtest protocol, not the production sampler.
- v2's backtest uses a flat 60-day GDP lag and v3's uses the ABS's real release dates, so in the days around a print the two models name different current quarters. Those Mondays pair with nothing and are dropped rather than forced together; it is why the current horizon has 181 rows and not 189.
