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
