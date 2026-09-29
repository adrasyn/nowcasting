# Historical TODO / backlog

Point-in-time investigation notes from April–August 2026, retained for context. This is **not a current priority list**: several proposals below were later implemented or superseded. Check the current code, [root README](../README.md), and dated measurements before acting on an item.

## April 2026 stationarity investigation (historical)

**Context.** We discovered two coupled bugs on 2026-04-17:
1. `generate_nowcast` was pulling `yfcst[, "in"]` (retrospective Kalman-smoothed fit for the latest OBSERVED quarter) and labelling it as the nowcast for the next quarter. Per the `nowcasting` package's R Journal paper (RJ-2019-020), the correct column is `yfcst[, "out"]` — the proper mixed-frequency nowcast. **Fix landed** in `pipeline/06_generate_nowcast.R`: now matches target_quarter against the ts time index and pulls `out` (falling back to `in` only if the target is already observed — useful for historical backtests).
2. With the fix, today's "correct" Q1 2026 nowcast comes out at **+3.02% QoQ / +5.66% YoY** — implausibly high vs RBA projections (~0.5% QoQ) and Australian recent actuals (~2% YoY). A controlled diagnostic (`pipeline/test_out_mixed_freq.R`, deleted after running; results in `.cache/mixfreq_test.txt`) showed that even stripping ALL Q1 2026 monthly data, the model still predicts +1.61% QoQ for Q1 — a pure factor-state projection that's already 2–3× too high.

**Root cause.** Model uses `trans = rep(0, ncol(ts_data))` in `Bpanel()` — i.e. *no stationarity transformation*, fit on raw levels. The DFM extracts the level trend as a common factor, then AR-projects it forward, producing persistent over-extrapolation. The earlier team decision to use `trans=0` was validated by a backtest showing "MAE ~$1–2K vs ~$100K with transforms" — **but that backtest was measuring `in`-column backcast residuals, not real nowcast errors**. The comparison was against the wrong quantity. With the corrected extraction, `trans=0` likely produces terrible POOS forecast errors.

**Plan for next session.**

1. **Audit each series' stationarity.** For every column in master_wide: run an Augmented Dickey-Fuller (ADF) test on the raw series, then on candidate transformations (1st difference, 2nd difference, log, log 1st diff, log 2nd diff, YoY diff) — pick the simplest transformation that passes ADF at the 5% level.
2. **Map those choices to `nowcasting`'s `trans` codes** in `Bpanel`. Confirm the exact semantics of each trans value from the package docs (the commented-out map we inherited — `gdp=7, household_spending=1, cons_conf=2, …` — is a candidate but needs verifying). Use `Rscript -e '?nowcasting::Bpanel'` as the source of truth.
3. **Refit with the stationarity-corrected panel.** Inspect today's Q1 2026 nowcast — it should land in a plausible range (roughly 0–1% QoQ for a healthy economy).
4. **Re-run the backtest sweep (r=2, r=3) with the corrected extraction + stationarity transforms.** The real POOS MAE will finally be measured. Replace `docs/backtest-recommendation-2026-04-17.md` with corrected numbers.
5. **Only after this** do we resume the Q1 2026 weekly reconstruction and push to the site (site has been pulled via DNS CNAME removal while we sort this).

**Helpful pointers.**
- `nowcasting::Bpanel` is where trans codes apply (currently in `pipeline/05_estimate_model.R:257`).
- Existing commented map (line 253): `gdp=7, household_spending=1, cons_conf=2, building_app=1, bus_conf=2, exports_goods=1, exports_servs=7, imports_goods=1, imports_servs=7, employment=1, unemp_rate=2, participation=2, hours_worked=1`.
- The diagnostic log from today is at `pipeline/.cache/mixfreq_test.txt` (kept — useful reference).
- Full master dataset post-SA-swap is at `pipeline/.cache/processed/master_dataset_complete.rds`.

**Where we stopped.** Was about to inspect `Bpanel()` source and documentation to confirm trans code semantics. Did not yet run any ADF tests or trial transformations.

---

## Post-hoc Q1 2026 weekly nowcast reconstruction

**Goal.** Rebuild a complete weekly nowcast track record for Q1 2026 as if the pipeline had been running on its current weekly schedule from the start of the quarter — producing one vintage per calendar week, using only the data that was actually available at that week's release dates.

**Motivation.** The existing `vintage_tracking.csv` for Q1 2026 is sparse and includes the stale-retail era. To have a clean, dense track record for the first full quarter under the MHSI model, we want to simulate what the weekly pipeline *would have* produced each week.

**Approach.**

1. Generate a list of target weekly nowcast dates covering Q1 2026 (e.g. every Monday from ~2026-01-05 through 2026-04-27, bounded by the next scheduled release date).
2. For each date:
   - Take a snapshot of indicator data available as of that date, using the release calendar in `pipeline/04_release_calendar.R` (`get_available_data()`).
   - Re-estimate the DFM on that snapshot (same n_factors the model ships with — informed by the factor-count backtest).
   - Generate a nowcast for 2026 Q1.
   - Write a vintage row into `vintage_tracking.csv` with the simulated run timestamp.
3. Save the RDS per vintage under `.cache/model_output/vintages/2026Q1/` matching the existing naming convention.
4. Re-emit `data/nowcasts.json` via the normal emit step so the Nowcast Evolution chart on the site reflects the dense track record.

**Note.** This overlaps structurally with `pipeline/09_backtest_model.R` (POOS re-estimation) but at weekly rather than quarterly cadence, and targeting a single quarter. Consider extracting a shared helper `run_nowcast_at_asof_date(master, config, as_of_date, target_quarter)` once this lands.

**Watch-outs.**

- The simulated vintages must be clearly distinguishable from real weekly runs — suggest either a prefix (`vintage_sim_…`) or a boolean `simulated` column added to the CSV.
- Running this once and committing vintages as real-weekly artifacts could be misleading; label clearly in the commit message and consider a flag the frontend could use to denote "reconstructed" vs "live" vintages.
- Respect the ragged edge: `get_available_data()` already handles it — don't shortcut.

---

## Evolution chart: add a dimmed next-quarter line

**Motivation (user, 2026-08-02).** While we're still inside the current quarter waiting for its GDP to be released, the *next* quarter's nowcast has already begun to evolve. Show it on the Nowcast Evolution chart as a second, less bright line — visible, but not competing with the current-quarter series for attention.

**Context worth knowing before starting.** We already saw an accidental version of this. Before the 2026-08-02 target-quarter fix, `nowcast_midas()` took the *last* MAI quarter rather than the first unreleased one, so the stress model drifted onto 2026 Q3 while the headline sat on Q2 — and `latest_v2.json` presented the two side by side under a single top-level `target_quarter`, inviting readers to compare them as if they described the same quarter. That was a bug and is fixed. This TODO is the *deliberate* version of the same idea, and it needs to be built so a reader can never confuse the two lines.

**Approach.**

1. Emit a second nowcast per run targeting `target_q + 1`. `nowcast_midas()` now always targets the first quarter without released GDP, so this needs an explicit second call (or a `target_offset` argument) rather than falling out of the ragged edge by accident.
2. `data/vintages_v2.json` already carries `target_quarter` on every row, so the data model needs no schema change — append the next-quarter vintages alongside the current-quarter ones and let the frontend group by `target_quarter`.
3. Frontend: render the current-quarter series at full weight and the next-quarter series dimmed (lower opacity, and consider dashed). Legend must name both quarters explicitly — not "current"/"next", which goes stale the moment GDP releases.
4. Handle the promotion. When the current quarter's GDP is released, the next-quarter line becomes the current-quarter line. `vintages_v2.json` is deliberately append-only (see `emit_v2_json.R` — a from-scratch reconstruction lets revisions silently rewrite history), so the promotion must be purely a rendering decision driven by `target_quarter` vs released GDP, never a rewrite of past rows.

**Watch-outs.**

- The next-quarter nowcast will sit at `jt = 0` or `1` for most of its visible life — i.e. little or no target-quarter data. Since `840e636` those stages get the paper's own FC and M1 models rather than the old random-walk fallback, so the estimator is legitimate, but it is running on the thinnest information the paper contemplates and its bands are correspondingly wide. The dimmer line is therefore statistically honest as well as visually sensible; consider a tooltip saying so.
- **`jt = 0` and `jt = 1` have never been calibrated.** Every CI parameter is estimated from backtest as-ofs, and production only ever reaches `jt = 2` or `3`, so `ci_params_for_stage()` has no bucket for the stages a next-quarter line would spend most of its life in and will fall back to the pooled band. Before shipping that line, either calibrate those stages explicitly (the backtest can be driven to them by targeting the *following* quarter) or state on the chart that the early band is pooled, not stage-specific.
- It must draw its confidence band from its own information stage, not the current quarter's. The per-stage CI work (`compute_ci_params_v2.R`, `ci_params_for_stage()`) already supports this — pass the next-quarter nowcast's own `n_months_in_quarter`.
- Don't let the two lines share a `prev_level`. That was exactly the `emit_v2_json.R:123` bug: the stress model's level and YoY were computed off the quarter before the *headline's* target, understating its level by a whole quarter of growth. A next-quarter nowcast needs the current quarter's (still unreleased, hence nowcast) level as its anchor — which means its level is a compounding of two estimates and should be presented with that uncertainty, or presented as growth only.

---

## Over-optimism: the model forecasts the long-run mean, not the current regime

**Finding (2026-08-08).** The +0.34pp bias is almost entirely a level offset, and
its cause is identifiable. Mean QoQ GDP growth by era:

| era | mean QoQ growth |
|---|---:|
| 1978–2019 | +0.775% |
| 2000–2019 | +0.700% |
| 2010–2019 | +0.642% |
| 2022–now | +0.503% |
| full sample | +0.819% |
| **model's mean forecast, 2022–now** | **+0.843%** |

The model's average forecast is the full-sample mean. The gap between that mean
and the current regime is +0.316pp; the measured bias is +0.340pp. That is the
whole of it, to within two hundredths.

**Mechanism.** The MAI is standardised, so it is mean-zero by construction, and
the U-MIDAS intercept is fitted over 1978–2026. "Activity around its historical
normal" therefore maps to "growth around its historical normal", where normal is
an average dominated by a much higher-growth era. A permanent downshift in trend
growth is invisible to a mean-zero factor. Note the era column is monotonic —
this is not a 2022 shock but a decades-long drift, so it will keep widening.

**The signal itself is fine; only the level is wrong.** Over the 17 calibration
quarters: correlation between forecast and actual +0.66, and 58% of the mean
squared error is pure level offset. Residual sd after removing the offset is
0.298 against RMSE 0.447 — so correcting the level alone would take RMSE from
0.45 to about 0.30 without touching the forecasting. For scale, a constant
"always predict +0.50" scores 0.293, currently better than the model; that is a
hindsight benchmark, not a real-time one, but it is not a flattering comparison.

**Second contributor, suspected but NOT measured.** The current selection is 12
series: four yield/spread measures, four labour (`emp`, `ft_emp`, `ue`, `ud`),
two credit, plus `household_spending` and `wmi_sent`. The four labour series are
highly correlated, so they push one strongly-weighted signal into the factor.
Australia post-2022 is exactly the environment where that misleads — record
immigration drove employment and hours up while output per hour fell, so labour
indicators read "strong" while GDP did not follow. Treat as a plausible
amplifier, not an established cause. (Do NOT re-run the old "share of |loading|"
diagnostic to test this: that statistic is a DFM2 normalisation artefact, since
the first column's loading is pinned to exactly 1.0.)

**What RDP 2024-04 says about this (checked 2026-08-08).**

- It *does* address structural drift — but only in the PREDICTORS. §3: rather
  than a full-sample mean it uses "dynamic demeaning" on each series, a rolling
  20-year backward-looking mean, following Kamber, Morley and Wong (2018),
  explicitly "as a way of controlling for potential structural breaks in the
  central tendency of each series". We already implement this
  (`transform_panel.R`, `.RBA_ROLL_MONTHS <- 240L`).
- It does NOT apply that device to the TARGET. GDP growth enters the U-MIDAS
  with a plain intercept (their Equation 10). So the predictor side is protected
  against drift in central tendency and the target side is not — in the paper
  and in ours identically. That gap is exactly the mechanism above.
- The word "bias" does not appear in the paper at all. Systematic over- or
  under-prediction is never discussed.
- **Their evaluation sample ends 2022:Q2.** The paper stops right at the start of
  the low-growth regime that produces our bias, so this is not a defect they
  could have seen.
- **Their benchmark is a sample mean model**, and their own result is more
  sobering than the headline: the 2x win is "primarily because of how well model
  M1 predicted the significant decline in quarterly GDP growth that occurred in
  2020:Q2". Excluding COVID, "the three 'M' models are outperformed by the sample
  mean model in both the shorter three-year and longer full sample horizons",
  with only QA narrowly ahead. Our ~1.04 relative RMSE against a full-sample-mean
  benchmark over 2022-2026 is therefore disappointing but not far outside what
  the paper itself reports once 2020 is removed.
- Unrelated but settled while looking: the 1978 start is data availability, not a
  modelling choice — footnote 17, the Labour Force Survey began February 1978.

**Preferred fix, and it is arguably NOT a deviation.** Apply the paper's own
dynamic-demeaning device to the target: subtract a rolling 20-year backward-
looking mean from GDP growth before the U-MIDAS regression, and add it back to
the prediction. This uses the paper's tool, its window length and its stated
rationale ("structural breaks in the central tendency"), just applied to the one
series they left out. It needs no ad hoc bias correction, no sample truncation,
and it adapts automatically as trend growth moves rather than being re-tuned. It
is also strictly real-time — a backward-looking window uses no future data.
Test this BEFORE the sample-start option below.

**The fallback test.** One backtest with a later estimation start — 2000,
say — and check whether the bias collapses while the +0.66 correlation survives.
About 30 minutes. It directly tests the diagnosis: if the cause is the sample
anchoring the intercept on a higher-growth era, a shorter sample fixes most of
it. If the bias survives a 2000 start, the trend story is wrong and the panel
composition becomes the prime suspect instead.

**Fidelity tension to settle before acting.** `sample_start = "1978-04-01"` in
`build_mai.R` is the paper's value, hard-coded there, and we deliberately moved
*to* it on 2026-08-02 for fidelity. Shortening it is a real deviation. The
argument for doing it anyway: the paper evaluates an average over 1988–2023,
where a slow level drift washes out, whereas we publish a live number in a
low-growth regime where it does not. It is also a sample-window choice rather
than a method change, which sits on the "our own panel" side of the line. If we
do it, document it beside the other accepted deviations in the review report.

**Do not patch this with a bias correction.** That was considered and rejected on
2026-08-02 (the paper does not bias-correct, and its MIDAS regression already
fits an intercept). Now that the bias has an identifiable cause, fixing the cause
is strictly better than subtracting the symptom. The site currently discloses the
tendency instead — see the accuracy line under the headline.

**External corroboration (2026-08-08).** The Melbourne Institute's nowcast for
the same quarter, 2026 Q2, is **+0.2% QoQ / 1.7% year-ended**, published 30 July.
Ours is +0.47% / +2.01%. A third party running a different method on the same
economy sits ~0.27pp below us — close to the measured bias, and consistent with
the diagnosis rather than with our being unluckily wrong in one quarter.

They also state, unprompted: "Our output growth nowcast, taken together with
hours worked in the June quarter, imply a further fall in labour productivity
occurred." That is direct support for the labour-composition hypothesis above —
the wedge between labour inputs and output is exactly what makes a panel with
four correlated labour series overshoot. It moves that hypothesis from
speculation to worth testing, though still not measured.

Their method differs from ours in kind, which is why the comparison is
informative rather than circular: they build a MONTHLY GDP series by temporal
disaggregation — constructed so that at quarterly frequency it coincides with
log real quarterly GDP, interpolating the historic ABS quarterly values together
with the nowcast, guided by monthly indicators. No factor model, no MIDAS
regression. Inputs: labour market, housing and business lending, household
spending, housing approvals, consumer expectations, trade conditions, commodity
prices. They publish no uncertainty band either. Contact is A/Prof Tim Robinson.
Caveat: this is from their site blurb and search-indexed excerpts — the report
PDFs sit behind Cloudflare and could not be read in full, so if a methodology
box exists in them it has not been checked.

**Reproducing the numbers.** Era means from `nowcasting_v2/data_raw/rt_dgdp_qtr.csv`;
forecast/actual pairs from `data/backcasts.json` (17 quarters, 2022 Q1–2026 Q1);
bias and sd from `pipeline/seed/ci_params_v2.json`.
