# First-print target A/B, 9 September 2026

Same 40 vintages (2023-01 to 2026-05, one unbuildable month as in the baseline), same three
seeds (4, 13, 19), same recording. Only the GDP series the model is trained on changes:
`--target first_print` replaces `gdp` with a chain index of first-release growth
(`nyfed/au/first_release.first_release_index`). Scored against the ABS first print of each
quarter; per-vintage medians over seeds, 40 paired vintages. Decision rule fixed before the
run in `docs/superpowers/plans/2026-09-09-first-print-target-ab-test.md`.

| | bias vs first print | MAE vs first print | RMSE | bias vs latest | MAE vs latest | chains at or below the 1.0 floor |
|---|---|---|---|---|---|---|
| baseline (latest-vintage target) | +0.193 | 0.234 | 0.274 | +0.120 | 0.242 | 0 of 120 |
| baseline less 0.0989pp adjustment | +0.094 | 0.181 | 0.216 | +0.021 | 0.189 | n/a |
| treatment (first-print target) | +0.130 | 0.188 | 0.218 | +0.057 | 0.206 | 99 of 120 (none below 0.5) |

Paired absolute error, treatment minus baseline: -0.046pp
(t = -3.45, better in 68% of vintages).
Treatment minus adjusted baseline: +0.007pp
(t = 0.62, better in 50%).
Correlation with the first print: baseline 0.238, treatment 0.387.

Decision rule: (a) bias falls by >= 0.05pp: PASS (-0.063). (b) MAE does not rise by
more than 0.02pp: PASS (-0.046). (c) no collapses: FAIL on its letter (83% of chains
sit at or below the shipping floor of 1.0; median loading 0.884 against
1.473 for the baseline) but not on its intent (no chain is in the collapsed
basin; the distribution is unimodal near 0.9). The run used `--collapse-floor -1` and recorded
every chain; cutting at the shipping floor keeps 18 vintages and gives bias
+0.137 / MAE 0.204 against the baseline's
+0.193 / 0.246 on the same vintages.

Decision: KEEP the latest-vintage target for now. The first-print target is a real improvement
over the raw baseline, but the revision adjustment already on the branch beats it on both
headline numbers at no cost, and the target would need its own collapse floor and seed
constants before it could ship. The single published nowcast should be the baseline less the
rolling mean revision. Next experiment: first-print target plus a bias correction, one backtest.

GDP global loading, treatment: min 0.589, p25 0.828, median
0.884, p75 0.953, max 1.342. Baseline median 1.473.

Run log: scratchpad fp_run.log (not committed), 65 min. Data:
`docs/measurements/2026-09-09-plan-c-first-print-target.csv`. Write-up published as an artifact
the same day.


## Addendum, same day: a bias correction on either target

Recursive correction (the September report's section 4.1): mean of the model's final-nowcast misses against the first print over quarters printed by the vintage date, subtracted from the nowcast. Scored per vintage against the first print.

### Expanding window, minimum four printed quarters: 29 vintages from 2024-01-01, targets 2023Q4..2026Q1

| arm | bias | MAE | RMSE | paired dAE vs adjusted baseline | corr with print |
|---|---|---|---|---|---|
| existing model, raw | +0.148 | 0.205 | 0.247 | +0.037 | 0.35 |
| existing model less 0.0989pp | +0.049 | 0.167 | 0.204 | +0.000 | 0.35 |
| existing model less the adjustment as known at the time | +0.065 | 0.173 | 0.211 | +0.006 | 0.32 |
| existing model less its own rolling miss | -0.099 | 0.195 | 0.225 | +0.027 | 0.36 |
| retrained on first prints, raw | +0.109 | 0.188 | 0.220 | +0.020 | 0.39 |
| retrained less its own rolling miss | -0.062 | 0.171 | 0.205 | +0.003 | 0.38 |

Mean correction applied: existing +0.247, retrained +0.171; recursive revision adjustment +0.083.

### Rolling eight quarters: 17 vintages from 2025-01-01, targets 2024Q4..2026Q1

| arm | bias | MAE | RMSE | paired dAE vs adjusted baseline | corr with print |
|---|---|---|---|---|---|
| existing model, raw | +0.106 | 0.201 | 0.233 | +0.013 | 0.07 |
| existing model less 0.0989pp | +0.008 | 0.188 | 0.208 | +0.000 | 0.07 |
| existing model less the adjustment as known at the time | +0.019 | 0.188 | 0.210 | -0.000 | 0.05 |
| existing model less its own rolling miss | -0.111 | 0.206 | 0.240 | +0.018 | 0.08 |
| retrained on first prints, raw | +0.071 | 0.201 | 0.231 | +0.013 | -0.04 |
| retrained less its own rolling miss | -0.080 | 0.213 | 0.243 | +0.025 | -0.08 |

Mean correction applied: existing +0.218, retrained +0.151; recursive revision adjustment +0.088.

### Rolling four quarters: 29 vintages from 2024-01-01, targets 2023Q4..2026Q1

| arm | bias | MAE | RMSE | paired dAE vs adjusted baseline | corr with print |
|---|---|---|---|---|---|
| existing model, raw | +0.148 | 0.205 | 0.247 | +0.037 | 0.35 |
| existing model less 0.0989pp | +0.049 | 0.167 | 0.204 | +0.000 | 0.35 |
| existing model less the adjustment as known at the time | +0.065 | 0.173 | 0.211 | +0.006 | 0.32 |
| existing model less its own rolling miss | -0.069 | 0.193 | 0.209 | +0.026 | 0.46 |
| retrained on first prints, raw | +0.109 | 0.188 | 0.220 | +0.020 | 0.39 |
| retrained less its own rolling miss | -0.041 | 0.179 | 0.205 | +0.011 | 0.40 |

Mean correction applied: existing +0.217, retrained +0.149; recursive revision adjustment +0.083.

Finding: the correction over-corrects on both targets (misses were largest in 2023 and early 2024 and have shrunk since, so a mean of past misses lags the drift); the corrected arms sit 0.04 to 0.11pp below the print with worse error than the adjusted baseline. The existing model's raw bias is falling (+0.19 whole window, +0.15 from 2024, +0.11 from 2025); the adjusted baseline is +0.01 on the six most recent quarters. Recommendation unchanged. Script: scratchpad four_arms.py (not committed); inputs are the two committed backtest CSVs.
