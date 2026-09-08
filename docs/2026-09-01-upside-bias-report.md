# Why all three nowcasting models run hot

**An investigation into systematic upside bias in v1, v2 and v3**

James Wilson / nowcasting project · written 1 September 2026, updated 2 September

> **Update, 2 September.** The ABS printed 2026 Q2 at **+0.4% q/q, 2.1% y/y**.
> All three models over-predicted again, and §5 — written the day before as a
> pre-registered test — has its answer. Figures throughout are current to that
> print. The one material change: **v3's bias is no longer arguable.**

---

## Summary

Your instinct is right, but the cause is not what "optimism bias" usually means.

**The finding.** All three models lean upward, and two of the three reject unbiasedness
formally. v2 is worst: **+0.33pp per quarter**, 15 of 18 quarters too high, p = 0.0002, with a
Mincer–Zarnowitz test rejecting unbiasedness outright (F = 25.3, p < 0.0001). **57% of v2's
total squared error is pure bias, not noise.** v1 is next: **+0.23pp**, 14 of 18 too high,
p = 0.002, MZ also rejects (p = 0.009). v3 is smallest at **+0.13pp** — 12 of 15 too high, a
sign test at p = 0.035 and a t-test at p = 0.059. Before the Q2 print I called v3's bias
suggestive rather than significant. One quarter later it clears one of the two tests, and the
direction is no longer arguable.

The ordering is itself informative: **v2 +0.33 > v1 +0.23 > v3 +0.13.** v3 is the only model
with a time-varying long-run growth component, and it is the least biased. That is not a
coincidence — see §4.2a and Mechanism 3. But §4.2a also shows that component is already working
as its designers intended, so it is not the lever it first appeared to be.

**The cause.** Not psychology, not a bug, and not a data-revision artefact. It is a **stale
anchor**. All three models map indicators to GDP using a historical relationship. That
relationship has broken, and it has broken in one specific place: **labour productivity.**

> Australia's GDP growth fell from **+0.70%/qtr** (1990–2019) to **+0.41%/qtr** (2023–2026),
> a drop of **−0.295pp**. Over the same period hours worked grew **faster**, not slower
> (+0.35 → +0.40%/qtr). Every bit of the slowdown — 115% of it — is the **output-per-hour**
> term, which fell from **+0.353** to **+0.013%/qtr**.

A model whose panel is built on labour input and activity volumes cannot see that. It sees
inputs running about normal and predicts output running about normal. Output is not normal.
**The change in the productivity term is −0.340pp/qtr. v2's measured bias is +0.328pp/qtr.**
Those were −0.340 and +0.340 when this was written, and the caveat below said the exactness was
partly luck. One quarter later the match has already loosened, which is the caveat being right
rather than the finding being wrong: the order of magnitude is what carries.

**The clinching evidence.** The bias **does not shrink as data arrives**: +0.144pp at three
months to go, +0.137pp at one month to go. If the models simply lacked information, the bias
would decay as the quarter filled in. It does not. The mapping itself is shifted up.

**What to do.** Ranked in the report below. The cheap win first: an explicit, published
**rolling bias correction** cuts v2's RMSE by 28% and its MAE from 0.332 to 0.242 in honest
out-of-sample testing, and cuts v1's MAE by 41%. **Do not apply it to v3** — its correction is
smaller than its own standard error and its error is a slope problem, not a level one (§4.1).
The real fix is to give the models something that carries the productivity signal, and to let
the long-run growth anchor move.

**The test, and its result.** The ABS printed 2026 Q2 at **+0.4%**. Raw calls were v1 +0.69%
(**+0.29** error), v3 +0.64% (**+0.24**), v2 +0.53% (**+0.13**). The bias-corrected calls were
closer on both models that had one: v2 +0.31% (**−0.09**, and the sign flipped, which is what a
working correction does) and v1 +0.51% (**+0.11**). One quarter is not proof, but it moved the
right way. See §5.

---

## 1. Is the bias real?

### 1.1 The headline numbers

Scored on final nowcast versus published actual, quarterly growth in percentage points, over
each model's comparable post-COVID window:

| | n | window | mean bias | MAE | RMSE | quarters too high | bias share of MSE |
|---|---:|---|---:|---:|---:|---:|---:|
| **v1** | 18 | 2022Q1–2026Q2 | **+0.225** | 0.317 | 0.342 | **14/18** | **43%** |
| **v2** | 18 | 2022Q1–2026Q2 | **+0.328** | 0.356 | 0.435 | **15/18** | **57%** |
| **v3** | 15 | 2022Q4–2026Q2 | **+0.128** | 0.253 | 0.265 | **12/15** | **23%** |

Significance:

| test | v1 | v2 | v3 |
|---|---|---|---|
| t-test, H₀: bias = 0 | t = +3.61, **p = 0.002** | t = +4.74, **p = 0.0002** | t = +2.06, p = 0.059 |
| sign test | 14/18, **p = 0.031** | 15/18, **p = 0.008** | 12/15, **p = 0.035** |
| Mincer–Zarnowitz joint (a=0, b=1) | F = 6.47, **p = 0.009 — reject** | F = 25.32, **p < 0.0001 — reject** | F = 1.93, p = 0.18 — cannot reject |

**Be precise about what this shows.** v1 and v2 are both statistically biased at conventional
levels, on all three tests. v3 now clears the sign test (12 of 15, p = 0.035) but not the t-test
(p = 0.059), and Mincer–Zarnowitz still cannot reject — its 15 quarters and small point estimate
leave the joint test underpowered. The honest statement is: *two models are decisively biased;
the third is biased in the same direction, on a test it now passes and a test it does not.*

The Q2 print is what moved v3 across. On 1 September its sign test was 11 of 14 at p = 0.057
and I called the bias suggestive rather than significant. Adding one quarter — another
over-prediction, +0.24pp — took it to p = 0.035. That is a thin margin resting on one
observation, and it would move back if Q3 comes in high. The point estimate and the sign pattern
remain the sounder evidence.

### 1.1a A note on where v1's numbers come from

`data/performance.json` scores v1 on **one** quarter, and an earlier draft of this report took
that at face value. That file is built from `data/nowcasts.json` — v1's **live vintage log**,
which only begins 2026-02-09 and covers 2026 Q1 and Q2. It is not the extent of v1's evidence.

v1's pseudo-out-of-sample backtest lives at
`pipeline/.cache/backtest_output/nab_fix_r3/backtest_results.csv`: 24 quarters from 2020 Q1,
run 2026-08-23 at the production config (r = 3, VAR(1)) by `pipeline/rerun_backtest_nab_fix.R`,
after the NAB history correction. It is the current, corrected v1 backtest.

Two framing choices matter for reading it:

- **The full 24 quarters are useless for bias.** COVID dominates: 2020 Q2 errors +7.50pp,
  2021 Q4 −3.00pp. Over all 24 the bias is +0.197 with RMSE 1.886 and p = 0.62 — the estimate is
  swamped, not absent.
- **The 2022-onward window is the comparable one**, and matches v2's window exactly. That is what
  the table above reports (16 backtest quarters plus the live 2026 Q1 result, +0.46).

For completeness: excluding only the five COVID shock quarters but keeping 2021, v1's bias is
−0.03 over 19 quarters. The bias is a **post-2022 phenomenon** in v1, which is consistent with
the productivity story in §2 — the break dates from 2022–23, not from COVID.

The v3 Plan C backtest gives an independent read on the same question, with 120 vintage-seed
rows across 14 targets: mean error **+0.123pp**, **81% of runs too high**. Treating each
vintage as independent gives t = 5.44, p < 10⁻⁵ — but vintages within a quarter are not
independent, so that overstates the case. Clustering properly by target quarter returns
+0.122pp, t = 1.87, p = 0.084. Same answer as the track record.

### 1.2 The bias does not decay with horizon

This is the single most diagnostic result in the investigation.

| horizon | n | mean error | % too high | mean nowcast | mean actual |
|---|---:|---:|---:|---:|---:|
| 3 months out | 36 | +0.137 | 83% | +0.558 | +0.421 |
| 2 months out | 42 | +0.089 | 79% | +0.528 | +0.439 |
| 1 month out | 42 | +0.144 | 81% | +0.583 | +0.439 |

Flat. With almost the whole quarter of monthly data in hand, v3 is as biased as it was at the
start. Within a quarter the error barely moves — 2025 Q2 ran −0.504, −0.514, −0.414 across the
three horizons.

This rules out the comfortable explanation. The models are not starting from a high prior and
being talked down by data. **They read the incoming data and conclude something too high.**

### 1.3 The models are close to reporting a constant

| | mean nowcast | mean actual | dispersion ratio | corr |
|---|---:|---:|---:|---:|
| v1 | +0.723 | +0.511 | 0.63 | — |
| v2 | +0.826 | +0.497 | 1.33 | +0.66 |
| v3 | +0.562 | +0.437 | **0.33** | +0.43 |

v3's quarter-to-quarter variation is **less than a third** of the variation it is trying to
predict. It is, to a first approximation, a constant at +0.557%/qtr with a small wobble. v2 has
the opposite problem — it is *over*-volatile (1.31) *and* biased.

This matters for how you read the bias. When a forecast is nearly constant, its errors are just
the actual series' deviations from that constant, sign-flipped. If the constant sits above the
recent mean, **most errors are positive by construction**. That is exactly what we see.

So the two failures are linked but distinct:
- **Level failure** (the bias): the constant is too high.
- **Signal failure** (the low R²): there is not much genuine news response to begin with.

Fixing the first is cheap and mechanical. Fixing the second is the real modelling problem.

### 1.4 What the constant actually is

Australian GDP growth, %/quarter:

| era | n | mean | annualised |
|---|---:|---:|---:|
| 2000–2007 | 31 | +0.820 | +3.28% |
| 2000–2019 | 79 | +0.704 | +2.82% |
| 2010–2019 | 40 | +0.642 | +2.57% |
| 2015–2019 | 20 | +0.615 | +2.46% |
| 2022Q1–2026Q1 (v2's window) | 17 | +0.503 | +2.01% |
| 2023–2026 (v3's window) | 14 | **+0.439** | **+1.76%** |

Now compare:

- **v2 averages +0.843%/qtr.** That is the **2000–2007** mean. v2 is nowcasting pre-GFC Australia.
- **v1 averages +0.724%/qtr.** That is roughly the **2000–2019** mean.
- **v3 averages +0.557%/qtr.** That sits between the 2015–2019 mean and today. Closer, still high.
- **Reality is +0.44%/qtr.**

Each model's constant is a different vintage of "normal", and each one is stale by a different
amount. The bias ranking follows the staleness ranking exactly.

Trend growth has fallen steadily for twenty-five years. The models' anchors have not kept up.

---

## 2. Why — five candidate mechanisms, ranked by evidence

### Mechanism 1 — The productivity break *(strong evidence; this is the main story)*

Decomposing GDP growth into hours worked and output per hour:

| | GDP | = | hours | + | productivity |
|---|---:|---|---:|---|---:|
| 1990–2019 | +0.704 | | +0.351 | | **+0.353** |
| 2023–2026 | +0.409 | | +0.396 | | **+0.013** |
| **change** | **−0.295** | | **+0.045** | | **−0.340** |

Hours worked did not slow. They *accelerated* slightly. Output per hour went to zero.

This is well documented outside the project. The Productivity Commission reports labour
productivity fell **3.7% in 2022–23**, against a long-term average of +1.3%, "as record high
increases in hours worked outpaced output growth". The capital-to-labour ratio fell **4.9%**,
the largest decline in Australia's recorded history, and employment shifted toward
lower-productivity sectors — hospitality and care services.

**Why this produces upside bias specifically.** Fit the pre-COVID labour→GDP relationship and
apply it to 2023–2026 labour data:

| rule fitted 2000–2019 | predicts for 2023–2026 | actual | over-prediction |
|---|---:|---:|---:|
| hours → GDP | +0.704%/qtr | +0.409 | **+0.295pp/qtr** |
| employment → GDP | +0.709%/qtr | +0.409 | **+0.300pp/qtr** |

That is v2's bias, reproduced from labour data alone.

A detail worth noticing: in every era the *slope* on labour is small and statistically
insignificant (2000–2019: 0.148, se 0.138, R² = 0.015). Almost all of the predictive content
sits in the **intercept**. So "the labour→GDP rule" is really "the historical average", and the
productivity collapse is the economic reason that average is now wrong.

Your own memory note already suspected the panel was labour-dominated. This quantifies the cost.

### Mechanism 2 — Panel-wide disconnect from the target *(strong evidence)*

Broader than labour. Take each indicator's 2023Q1–2026Q1 mean, z-score it against its own
1990–2019 distribution, and sign it toward GDP using v3's own priors:

| series | sign | signed z | reads as |
|---|---:|---:|---|
| employment | +1 | **+0.24** | above normal |
| NAB conditions | +1 | **+0.30** | above normal |
| building approvals | +1 | +0.04 | about normal |
| imports | +1 | −0.16 | below normal |
| household spending (real) | +1 | −0.19 | below normal |
| unemployment rate | −1 | −0.24 | below normal |
| exports | +1 | −0.51 | below normal |
| AiG PMI | +1 | −2.07 | far below normal |
| **GDP (the target)** | | **−0.68** | **well below normal** |

Equal-weighted, the panel says the economy is running **−0.32 sd** below normal. GDP is actually
running **−0.68 sd** below normal. The gap of **0.35 sd** is worth **+0.15pp/qtr** in GDP units
— which brackets v3's measured +0.12pp.

**GDP has slowed by more than its own indicators have.** Any model that maps indicators to GDP
with historical loadings must over-predict. Caveat: this is equal-weighted, not the model's
actual weighting, so treat it as indicative of direction and scale, not a decomposition.

Note also what is holding v3's bias down: the AiG PMI at −2.07 sd. v3 includes it; v2 does not.
That is likely a real part of why v3 is less biased — and it is a fragile reason, since a single
survey reading that far from its own history invites the question of whether the series itself
has shifted.

### Mechanism 3 — Standardisation against a long, stale sample *(strong mechanism, partly mitigated in v3)*

The NY Fed-style DFM standardises every series against its full-sample mean and standard
deviation, then de-standardises the nowcast by adding the mean back. When the factor carries
little news, **the nowcast converges to the full-sample mean**. v3's panel starts in 1980. The
1980–2019 mean is far above today's.

To v3's credit, it already implements the published fix: `model_spec_AU.csv` sets `Trend = 1`
on `gdp` and `gdi`, giving GDP a random-walk long-run growth component. **This is almost
certainly why v3's bias is a third of v2's.**

But the trend loads on the two quarterly series only. All twelve monthly indicators carry
`Trend = 0` and are standardised against their own long-run means. So the monthly block still
pushes the factor up whenever inputs run above their historical norms — which, per Mechanism 1,
is exactly what labour has been doing. The fix is applied to the target but not to the inputs.

### Mechanism 4 — Data revisions *(small, and runs the other way)*

Worth ruling out explicitly. Both backtests score against the **latest published** GDP, not the
first print (`pipeline/04_emit_json.R:544`). ABS revisions are typically small and modestly
upward — the 2024–25 annual figure was revised up 0.1pp.

If actuals drift up over time, then scoring against revised data makes errors *smaller*. So the
measured bias, if anything, **understates** what a live user saw on print day. This mechanism
does not explain the bias; it slightly deepens it.

### Mechanism 5 — Deflator error *(unresolved; flagged, not tested here)*

Your memory records that v2 deflates household spending with the **quarterly** CPI interpolated
to monthly, and that v3 inherits the issue. Under-deflating nominal spending overstates real
growth, and the error would be largest exactly when inflation is high and moving — 2022 to 2024,
where v2's bias is largest.

This is a plausible contributing channel with the right timing and the right sign. It is not
quantified here because it needs a proper re-run with the correct monthly deflator. It should
not be dismissed, and it is testable.

**One mechanism explicitly rejected: behavioural optimism.** These are mechanical models. No one
is talking them up. The word "optimism" imports an explanation that does not apply.

---

## 3. What the literature says

### 3.1 This exact pathology is documented, and the fix is known

The closest paper to your problem is **Antolín-Díaz, Drechsel and Petrella**. Two works matter.

**"Tracking the Slowdown in Long-Run GDP Growth"** (*Review of Economics and Statistics*, 2017,
99(2), 343–356) builds a DFM with a time-varying long-run growth rate. Their central finding on
causes reads as if written about Australia today: *a decline in the growth rate of labour
productivity appears to be behind the recent slowdown in GDP growth* for the US and other
advanced economies. They show the model detects shifts in long-run growth "in a timely and
reliable manner" in real time.

**"Advances in Nowcasting Economic Activity"** (*Journal of Econometrics*, 2024, 238(2), 105634;
working versions circulated as CEPR DP15926/DP17800) states your symptom directly:

> "A persistent upward bias is evident after around 2010, reflecting a failure to capture the
> decline in long-run growth which materialized in this decade."

and on the remedy:

> "Modeling long-run growth as time-varying eliminates a bias often present in long-horizon
> forecasts."

> "At longer horizons, both SPF surveys and FOMC projections display a noticeable upward bias in
> the last decade, which our model eliminates thanks to the addition of time-varying long-run
> growth."

Their 2010–2018 numbers: RMSE 0.62pp for their model, 0.66 for the SPF, 1.14 for the FOMC.
Average forecast error — bias — 0.37 for their model, **0.58 for the SPF, 1.04 for the FOMC**.

Two things follow. First, **professional and official US forecasters carried larger bias than
your v3 does**, for the same reason, over a comparable period. Second, the fix that worked is
the one v3 has half-implemented.

They also report a density-calibration result you should check on your own bands: their basic
model put only 21% of outcomes outside a 68% interval where 32% was expected — **over-confident**
— while the full model achieved 34%. Under-dispersed point forecasts usually travel with
over-confident intervals, and v3's dispersion ratio of 0.32 is a warning sign.

### 3.2 The broader forecasting literature: this is a location shift

Outside nowcasting, this is the **structural break** problem, and specifically the worst kind.
**Clements and Hendry**, "Intercept corrections and structural change" (*Journal of Applied
Econometrics*, 1996, 11, 475–494) and subsequent work establish that **location shifts — changes
in equilibrium means — are the most pernicious form of break**, because they induce systematic
forecast failure rather than merely noisier forecasts.

Their prescribed remedy is exactly the cheap fix in §4.1: **intercept correction**, adjusting the
forecast by recent average error. Their warning is equally important, and it showed up in this
project's numbers:

> reductions in forecast bias may only be achieved at the cost of inflated forecast error variances

That is precisely what happens to v3 below — MAE improves 27%, RMSE only 7%. The literature
predicted this. A separate strand notes that Mincer–Zarnowitz-based correction sometimes fails
to improve out-of-sample accuracy at all. Bias correction is not free, and it must be tested,
not assumed.

### 3.3 Is optimism a real phenomenon elsewhere? Yes — but it is not your mechanism

There is a large literature on genuine forecaster optimism. **IMF WEO** projections are
persistently too optimistic across horizons, country groups and decades. **Timmermann (2006)**
and the IMF's own Independent Evaluation Office (2014) independently find systematic
over-prediction of growth during recessions. **Loungani (2001)** and later work found the record
of failure to predict recessions "virtually unblemished". IMF WP/21/275 links over-optimism to
prior credit-to-GDP expansion; IMF WP/18/39 covers recession forecasting failure.

This is real, and it is worth knowing about. But it describes **judgemental** forecasts produced
inside institutions with incentives. Your models have no incentives. Citing this literature as
an explanation for v2 would be a category error. It belongs in the report as the thing your
problem is *not*.

### 3.4 Is your bias unique? No — and the sign is regime-dependent

The most useful comparison is with the two US nowcasts your v3 is ported from.

The NY Fed Staff Nowcast ran roughly **half a point above** actual GDP on average in pre-pandemic
years. Since 2022 it has run **about a point below**, with Atlanta Fed GDPNow also below. The
sign **flipped**.

That is the crux of the whole report. If nowcast bias were optimism, it would not flip. It flips
because it tracks whether realised growth is running above or below the model's embedded trend:

- **US, post-2022:** actual growth ran hot relative to trend → trend-anchored models
  **under**-predicted.
- **Australia, post-2022:** actual growth ran cold relative to trend → trend-anchored models
  **over**-predict.

Same pathology, opposite sign, because the two economies sit on opposite sides of their anchors.
Your models are not unusually optimistic. They have the standard stale-anchor problem, and
Australia's productivity slump makes it present as optimism.

*Source caution: the US bias magnitudes come from secondary commentary rather than an official
evaluation. Treat the direction and the sign-flip as the robust part; verify the magnitudes
against source data before quoting them.*

A closer-to-home note: Australian Treasury's own **"Nowcasting Australia's Gross Domestic
Product"** (Treasury Working Paper 2018-04, Grant et al.), which sits in this repository,
evaluates its model on RMSE against a simple average benchmark and **does not report bias at
all**. That is the norm, not an oversight. Most nowcasting write-ups report RMSE and MAE and
never test the first moment. **Your project would be unusual for measuring it, not for having it.**

### 3.5 Does the RBA share the bias?

Six paired observations from `pipeline/rba_somp_forecasts_v2.csv`, year-ended growth:

| target | RBA SoMP | actual | RBA error |
|---|---:|---:|---:|
| 2023 Q2 | 1.75 | 2.26 | −0.51 |
| 2023 Q4 | 1.50 | 1.33 | +0.17 |
| 2024 Q2 | 1.20 | 0.89 | +0.31 |
| 2024 Q4 | 1.50 | 1.24 | +0.26 |
| 2025 Q2 | 1.80 | 1.98 | −0.18 |
| 2025 Q4 | 2.00 | 2.51 | −0.51 |

Mean error **−0.08pp** — roughly unbiased, with large errors in both directions.

Read this carefully. Six observations of a year-ended number cannot establish that the RBA is
unbiased. But it does mean **you cannot claim the bias is an unavoidable feature of forecasting
Australia in this period**. A judgemental forecaster with the same data did not carry it. The
bias is a property of the models, not of the era.

---

## 4. What to do

### 4.1 Ship an explicit bias correction *(do this first — cheap, testable, honest)*

Subtract a rolling estimate of recent mean error. Tested properly out-of-sample — correction
estimated only on quarters strictly before the one being scored:

| | quarters | raw RMSE | corrected RMSE | raw MAE | corrected MAE | residual bias |
|---|---:|---:|---:|---:|---:|---:|
| **v1**, rolling 8q | 13 | 0.361 | **0.304** (−16%) | 0.348 | **0.207** (−41%) | −0.01 |
| **v2**, rolling 8q | 13 | 0.399 | **0.286** (−28%) | 0.332 | **0.242** (−27%) | −0.10 |
| **v2**, expanding | 13 | 0.399 | 0.301 (−25%) | 0.332 | 0.251 | −0.14 |
| **v3**, expanding | 10 | 0.290 | 0.270 (−7%) | 0.278 | **0.204** (−27%) | +0.00 |
| **v3**, rolling 8q | 10 | 0.290 | 0.286 (−1%) | 0.278 | 0.205 | −0.01 |

**For v1 and v2 this is a large, unambiguous win** — v1's MAE falls 41%, the biggest gain of
the three. **For v3 the answer is no, and the reason is structural, not a matter of degree.**

#### Ship it per model, not across the board

| | correction c (8q) | its own se | **c / se** | worst-case \|error\| | error-vs-actual slope | verdict |
|---|---:|---:|---:|---:|---:|---|
| **v2** | +0.217 | 0.109 | **+2.00** | **0.610 → 0.466 (−24%)** | −0.13 (R² 0.02) | **Ship** |
| **v1** | +0.179 | 0.118 | +1.52 | 0.531 → 0.697 (+31%) | — | Marginal — monitor |
| **v3** | +0.089 | 0.096 | **+0.92** | 0.420 → **0.654 (+56%)** | **−0.86 (R² 0.90)** | **Do not ship** |

Five reasons v3 is different:

1. **The correction is smaller than its own standard error.** +0.089 against se 0.096, a 95%
   interval of [−0.100, +0.278]. You cannot distinguish it from zero. Applying it injects noise
   of roughly its own size.
2. **The accuracy gain is not significant.** A Diebold–Mariano-style test on absolute errors
   gives p = 0.163; on squared errors, p = 0.956 — the RMSE benefit is *literally zero*
   (t = −0.06).
3. **Worst-case error rises 56%.** It helps 8 of 10 quarters by a little and hurts 2 by a lot:
   2025 Q2 goes 0.420 → 0.654, 2025 Q4 goes 0.260 → 0.430. For v2 the same correction *reduces*
   worst-case error 24%. Opposite outcomes from the same operation.
4. **v3's error is a slope problem, not a level problem.** Regress each model's error on actual
   growth: v2 gives slope −0.13, R² = 0.02 — its error is a genuine level offset, independent of
   what the economy did, which is exactly what a constant correction is for. v3 gives slope
   −0.86, R² = 0.90 — its error is almost entirely *"the economy moved and v3 didn't."*
   A constant cannot fix that. It shifts the line down, fixing weak quarters and breaking strong
   ones — precisely the pattern in point 3.
   *(This is partly mechanical: a near-constant forecast forces the slope toward −1. It restates
   the dispersion finding in sharper form rather than adding independent evidence — but it is
   still the right frame for the decision.)*
5. **The regime may already be turning.** Growth over the last four quarters averaged +0.62%/qtr
   against +0.32% across 2023–24. v3 over-predicts in weak quarters (+0.238) and *under*-predicts
   in strong ones (−0.313). If productivity recovers, a hard-coded downward correction compounds
   the error instead of removing it.

A sixth, non-statistical reason: **it would improve the metric you display while making the
model worse where it matters.** v3's MAE falls 27% on paper. Its RMSE does not move and its
worst quarters get worse. Shipping that onto the site — especially as v3 goes to the homepage
after the 2026-09-02 print — is metric-shopping, whatever the intent.

Shrinking the correction does not rescue it: a James–Stein weight (λ = c²/(c²+se²)) gives
RMSE 0.296 and MAE 0.227, *worse* than the plain rolling correction on both. The estimate is
noisy but not noisy enough for shrinkage to help; the problem is that it is the wrong
instrument, not that it is mis-sized.

**What to do for v3 instead.** Publish the bias — measured, signed, uncorrected — and fix the
dispersion. §4.2 step 1 (plot the estimated `g_t` against realised 20-quarter growth) is the
cheap first move, and it also tells you whether the trend component is already closing the gap,
in which case the residual +0.12 decays without intervention. Set an explicit trigger to revisit:
**if the rolling c/se exceeds 2.0 for two consecutive quarters, reopen the decision.**

This is also Clements and Hendry's variance warning, observed live in your own data — bias
reduction bought at the cost of inflated error variance. For v2 the trade is worth it. For v3
it is not.

Since your site headlines MAE, this improves the published metric. Be careful that this is a
real improvement and not metric-shopping — state both numbers.

Implementation notes:

- **Use a rolling window, not expanding.** The bias is itself drifting (v2: +0.449 over its first
  nine quarters, +0.217 over its last eight; v3: +0.160 then +0.080). An expanding mean will
  over-correct as the underlying problem improves.
- **Publish the correction as a separate line.** "Model +0.53, bias adjustment −0.22, published
  +0.31." Never fold it in silently. It is a confession of a known defect, and hiding it makes
  the track record uninterpretable.
- **Widen the intervals.** A correction estimated from 8–17 observations carries real
  uncertainty. Adding an estimated constant must widen the band, not leave it unchanged.
- **Set a retirement condition now.** If the rolling correction stays inside ±0.05pp for six
  consecutive quarters, drop it.

This is a patch. It buys time to do §4.2. It does not deserve to be permanent.

### 4.2 The time-varying trend *(not the fix I thought it was)*

v3 already has the mechanism — the random-walk trend `g_t` loading on `gdp` and `gdi`. I ranked
extending it as the top change to v3, on the reading that its narrow loading was a defect. §4.2a
shows it is not: the loading is the reference design, the trend moves *more* than the NY Fed's
does, and the prior and identification are both fine. What remains, in what is now a much more
tentative order:

1. **Diagnose first — done.** §4.2a. The answer changed the ranking below.
2. **Load the trend on consumption** — *tested, and it does nothing.* See §4.2b. Kept in the
   list because the reasoning was sound and the negative result is the useful part.
3. **Re-anchor the standardisation.** The monthly block is standardised against 1980-onward
   means, so the panel's own notion of "normal" is fixed at a stale value. Test a rolling or
   exponentially-weighted mean. This is where Mechanism 3 bites, and it is untouched by anything
   §4.2a rules out — the trend and the standardisation are separate machinery.
4. **Do not load the trend on the labour block.** I recommended this first. It is wrong twice
   over: ADP's selection vector covers output, income and consumption on a balanced-growth
   argument that does not extend to employment, and the productivity finding is precisely that
   labour and output *decoupled*. Loading the trend there asserts the thing this report
   disproves.

### 4.2a Diagnostic result — the trend works as designed, and that is the problem

Ran it. `state/au_estimate.npz` stores parameters and stochastic volatilities, not states
(`s` and `sigma` are `(19, 560)` = `1 + n_f + n` shock rows, not the state vector), so recovering
`g_t` needs a pass of `fast_smoother` over the rebuilt panel, then de-standardising into GDP's
own units via `iota = spec.trend / panel.y_scale`.

The NY Fed's technical paper plots exactly this in its Figure 1 — "GDP Growth (%YoY) and
Estimated Trend", the trend with a 90% probability interval — so the honest comparison is against
their chart, not against a standard of my own choosing. Reading their figure off the page:

| year | v3's trend (AU) | NY Fed's trend (US) |
|---|---:|---:|
| 1985 | 3.02% | 2.84% |
| 2000 | 2.95% | 2.80% |
| 2010 | 2.83% | 2.63% |
| 2024 | **2.67%** | **2.61%** |
| **decline, 1985–2024** | **0.36pp** | **0.23pp** |

**Australia's trend moves 1.6× as much as the reference model's over the same window**, in the
same shape — a smooth near-linear glide that flattens at the end. Their band is a comparable
±0.2–0.3pp. And US year-ended growth drops below their trend band in 2022–23, exactly as
Australia's does now.

**This overturns how I first read the result.** An earlier version of this section was titled
"the trend is frozen" and reported that `g_t` captured only 22% of the realised slowdown as
though that were a defect. It is not: a random-walk long-run growth component is built to track
*secular* drift across decades, the NY Fed calls its own the "subtle decline" because subtle is
the intent, and both models capture a similarly modest share of their own slowdown. **v3's trend
component is behaving like the reference implementation, only more responsively.**

Two things I checked along the way are still worth recording, because they rule out the obvious
repairs:

**The prior is not binding.** Posterior `gamma_g` is 0.01134 — an innovation sd of **0.1065**,
against a prior mean sd of 0.0106 from `nu_g = 18, s2_g = 0.0001` (`model.py:474`). The posterior
sits ten times above the prior mean, so loosening it does nothing.

**Nor is the trend unidentified.** With `need_mses=True` the smoother gives `g_t` a posterior sd
of **0.176 annualised pp** against total movement of 0.370 — a ratio of 2.10. It moved more than
its own uncertainty.

**What does survive is the gap.** `g_t` sits at **+0.658%/qtr** against realised 2023–26 growth
of **+0.409%** — **+0.249pp/qtr**, or 2.9 standard errors once the trend's own posterior sd
(0.044pp/qtr) and the realised mean's standard error (0.073pp/qtr) are both counted. v3's mean
nowcast is +0.562, *below* its own anchor, so the panel does pull it down about 0.10pp. It starts
from the wrong place rather than ignoring the data.

So the diagnosis is not "the trend is broken, repair it". It is:

> **A slow-moving random-walk trend is the wrong instrument for a fast regime shift.** That is
> true of the NY Fed's model too. Australia simply had the regime shift.

Three consequences, and the second is a reversal:

- **The residual bias will not decay on its own.** The trend is not slowly catching up.
- **"Widen the trend's loadings" is no longer the top-ranked change.** I ranked it first when I
  believed the narrow loading was a defect. It is the reference design, and ADP's published model
  is narrower than "real activity" too — see §4.3. It is still worth testing, but expect little:
  if the mechanism is the constraint, broadening its information set may move it barely at all.
- **It strengthens the case for correcting the level (§4.1), which I argued against for v3.**
  That argument rested partly on a structural fix being available. It is less available than I
  said. The objections in §4.1 still stand on their own terms — v3's error is a slope problem and
  its correction is smaller than its own standard error — but the alternative I was holding out
  for is weaker than advertised.

### 4.2b The consumption test, and its result

ADP's selection vector puts long-run growth on output, income **and consumption**, on a
balanced-growth argument. v3 had `household_spending` in the panel at `Trend = 0`, and it is
*monthly* — so loading the trend on it would roughly triple the observations identifying a trend
informed by two quarterly series, while moving v3 toward the published model rather than away.
The cheapest remaining structural test, and the last one §4.2a had not already ruled out.

Thresholds were set before running, so the result could not be read to taste. **Confirm:** the
end-point anchor falls more than 0.3pp annualised, closing about a third of the gap. **Kill:**
it moves less than 0.1pp. James added a third outcome I had not allowed for — that the anchor
moves *up*, because household spending held up through the inflation period and would hand the
trend a series saying the slowdown was milder than GDP says. The data backs that: household
spending slowed **−0.143pp/qtr** against GDP's **−0.295**, and **−0.19sd** against **−0.68sd**
measured against each series' own volatility.

One cell of `model_spec_AU.csv`, then a full re-estimation at production settings (10,000 draws
after 8,000 burn, seed 4, 74 minutes) so the comparison was like-for-like.

| | baseline | + consumption | change |
|---|---:|---:|---:|
| Anchor, 2026 (annualised) | 2.664% | 2.669% | **+0.005pp** |
| Anchor (%/qtr) | +0.659 | +0.661 | +0.001 |
| Total sample movement | 0.365pp | 0.342pp | −0.023 |
| `gamma_g` | 0.01134 | 0.01122 | — |
| Gap to realised | +0.250pp/qtr | +0.252pp/qtr | — |

**+0.005pp.** Two orders of magnitude below "helps", and far inside the trend's own posterior sd
of 0.176. Tripling the observations identifying the trend changed nothing. The factor structure
held — GDP's Global loading came out 1.228 against the 1.0 collapse floor.

The direction is the one James predicted and total movement fell slightly, but neither is worth
claiming: 0.005pp is noise, not a signal. The conclusion was right; the mechanism it was right
about is not demonstrated by a result where nothing moved.

**This closes the branch.** Four independent lines now say the same thing — the prior is not
binding, the trend is identified, it moves 1.6× the reference model's, and giving it three times
the information does nothing:

> **The trend's flatness is not an information problem or a tuning problem. A random-walk
> long-run growth component cannot track a fast regime shift, however it is informed.**

Which is worth more than a fix would have been, because it rules out a whole class of them. What
remains is a different mechanism — regime-switching, or an explicit productivity state with its
own dynamics — or correcting the level and saying so. §4.1's objections to correcting v3 still
stand on their own terms; the structural alternative I was holding out against them does not.

### 4.3 Put productivity in the panel

The models are blind to the exact variable driving the error. An earlier draft of this section
listed "GDP per hour, directly, as a quarterly series" as a candidate. **That was wrong, and the
reason it is wrong reorders the whole list.**

#### Do not add GDP per hour as a panel series

GDP per hour is *GDP divided by hours worked*, and the ABS publishes it **in the national
accounts — the same release as GDP itself**. For target quarter Q it does not exist until GDP(Q)
is already published. It carries **zero within-quarter news**. Adding it to the panel cannot help
you nowcast the quarter you are trying to nowcast.

There is a second, worse problem. GDP ≡ hours × productivity is an accounting identity. Put GDP,
hours and GDP-per-hour in one factor panel and you have three series with an exact linear
relationship in logs. That is degenerate — and v3 already has documented sensitivity here
(`gdp_global_loading` and the `collapsed` flag in the Plan C backtest exist because the factor
structure can fold into GDP's own trend).

#### The same objection partly applies to unit labour cost — which I told you to start with

`unit_labour_cost` (A2433074L) also comes from the national accounts. Its fixture is quarterly
and ends 2026Q1, the same vintage as GDP. It is **not a news source either**, and describing it
as carrying "the signal" was imprecise.

But this one is a reframe, not a retraction. **The diagnosed defect is a level problem — the bias
is flat across horizons.** A same-lag quarterly series still pins down the *regime* through its
history, which is exactly the input a stale anchor needs. So ULC is worth testing; it just fixes
the anchor, not the signal. Expect nothing from it on within-quarter responsiveness.

#### The thing I missed: v3 has no hours worked at all

`model_spec_AU.csv` carries `employment` — headcount — and no measure of hours. v3 does not even
fetch it. Yet hours is the labour input in the decomposition that drives this entire report, and:

- it is **monthly**, from the Labour Force Survey, at the same ~2–3 week lag as `employment`
  (both series in `nowcasting_v2/data_raw` run to 2026-07, so hours is available for all three
  months of 2026 Q2 right now);
- in the nowcast era it is the better of the two labour indicators —

| 2022Q3–2026Q1 (n=15) | slope | se | p | R² |
|---|---:|---:|---:|---:|
| GDP ~ employment | +0.050 | 0.264 | 0.852 | **0.003** |
| GDP ~ hours | +0.147 | 0.099 | 0.161 | **0.145** |

**Three honesty checks on that table.** n = 15 and neither slope is significant. In a joint
regression employment flips negative (−0.175) while hours enters +0.182 — that is
multicollinearity, not evidence that headcount is harmful. And R² is low everywhere: over
2000–2019 hours explains 1.4% of quarterly GDP. The claim is only that hours is *less
misleading* than headcount right now, not that it is a good predictor.

**And one check that matters more.** v2 *does* carry hours in its labour block. v2 is also the
**most** biased model. So adding hours will not fix v3's bias, and should not be sold that way.
Its value is against v3's *other* defect — the dispersion ratio of 0.32 and the −0.86 error slope
from §4.1. A better labour input is a candidate for making v3 respond to the economy at all,
which is the problem a bias correction cannot touch.

#### Revised ordering

1. **Add monthly hours worked.** Genuinely new information, timely, absent from the panel, and
   the right variable per the decomposition. Cheapest real change. Target: dispersion, not bias.
2. **Test `unit_labour_cost` with a non-zero prior** — as an anchor input, judged on bias and on
   the estimated `g_t` path, not on within-quarter responsiveness.
3. **Nowcast the identity instead of adding series to the factor block.** GDP growth ≈ hours
   growth + productivity growth. Hours you can see monthly; productivity is the slow-moving piece
   the trend component is *supposed* to be carrying — and §4.2b is the evidence that it cannot,
   which promotes this from an elegant alternative to the main structural candidate. A bridge
   structure rather than a panel edit, so it belongs with the §4.2 work rather than here.
4. **Compositional shift** — employment share in low-productivity sectors. Slow-moving and hard
   to get monthly, but it is the mechanism the Productivity Commission identifies.

Note the tension with your own evidence: your worksheet at `docs/candidate-variables-2026-06-03.md`
was pointed at commodity/terms-of-trade expansion. Commodity prices read **−0.42 sd**, so they
would have pulled the nowcast down and helped. But the *diagnosed* mechanism here is productivity,
and this analysis suggests re-ordering that worksheet accordingly.

### 4.4 Fix the deflator

Mechanism 5 is unresolved and has the right sign and timing. Your memory already records the
correct monthly CPI history exists, spliced across the live 6401.0 and the ceased 6484.0
catalogues, and that this was done for `cpi` but not carried through to deflation. Quantify it
before assuming it is small.

### 4.5 Report bias as a first-class metric

You already surface MAE on the site. Add bias next to it, with a sign. Two reasons: it is the
component of your error that is actually fixable, and the literature review above shows most
projects never look. Publishing it is a genuine differentiator.

Add the Mincer–Zarnowitz regression to the backtest output as a standing test, not a one-off.

### 4.6 What not to do

- **Do not tune the panel until the anchor is fixed.** With v3's dispersion ratio at 0.32, most of
  the nowcast is the constant. Adding series to a model that is mostly reporting its intercept
  will move the intercept unpredictably and teach you very little.
- **Do not treat v3's insignificant bias as absence of bias.** n = 14 has almost no power. The
  point estimate and the sign pattern are the information you have.
- **Do not apply a v2-sized correction to v3.** They are different sizes for good structural
  reasons — v3 has the trend component, v2 does not.

---

## 5. The test, and its result

The ABS published 2026 Q2 on 2 September at **+0.4% q/q, 2.1% y/y**. The calls below were
recorded here the day before, unchanged since.

| model | call | error | bias-corrected call | corrected error |
|---|---:|---:|---:|---:|
| v1 | +0.69% | **+0.29** | +0.51% | **+0.11** |
| v3 | +0.64% | **+0.24** | — (not defensible, §4.1) | — |
| v2 | +0.53% | **+0.13** | +0.31% | **−0.09** |

**All three over-predicted again**, which is the fourth consecutive quarter for v2 and keeps the
central claim intact.

**The correction earned its place on both models that had one.** v2 went from +0.13 to −0.09 —
closer, and the sign flipped, which is what a correction that is doing real work looks like
rather than one that is merely shrinking. v1 went +0.29 to +0.11. One quarter proves nothing on
its own; what it does is fail to falsify, in the direction the 17 prior quarters predicted.

Year-ended tells the same story: v2 2.07% against 2.10% actual, v3 2.18%, v1 2.24%.

Two things worth not glossing over.

**The least-biased model was not the most accurate.** v3 (+0.24) lost to v2 (+0.13) this
quarter and lost on year-ended too. Over the window v3 still has much the better MAE — 0.253
against 0.356 — but a single quarter is exactly where a low-dispersion model can be beaten by a
noisier one that happens to land. It is the same point §1.3 makes from the other side: low bias
and low error are different properties, and v3 buys the first partly by refusing to move.

**+0.4% is another weak print, and it did not disturb the diagnosis.** It sits almost exactly on
the 2023Q1–2026Q2 realised mean of **+0.409%/qtr**, and well below v3's trend anchor of
**+0.658%**. The anchor gap of §4.2a is unchanged by the new observation.

## 6. Caveats

State these plainly wherever this analysis is used.

1. **Small samples.** v1 n=18, v2 n=18, v3 n=15. v1 and v2 clear conventional significance;
   v3 clears the sign test only, and by a margin that rests on the single Q2 observation. **v1's window is also a choice** — its backtest runs from 2020 Q1, but COVID
   swamps the bias estimate there (RMSE 1.886, p = 0.62). The reported figures use 2022 onward,
   matching v2's window. Defensible and stated, but a choice: v1 shows no bias before 2022.
2. **Pseudo-real-time backtests.** All three models see revised data and are scored against revised
   outcomes. Your own `backtest_v3.json` notes flag this, and that v2's predictor selection is
   fixed to the full sample — a look-ahead with no counterpart in v3. Their *relative* comparison
   is therefore unreliable; each model's own bias against its own actuals is the sounder number.
   v1's 17 quarters also mix 16 backtest quarters with one genuinely live result (2026 Q1, +0.46),
   which is consistent with the backtest but is not the same kind of observation.
   v1's 17 quarters also mix 16 backtest quarters with one genuinely live result (2026 Q1, +0.46),
   which is consistent with the backtest but is not the same kind of observation.
3. **The z-score diagnostic is equal-weighted**, not the model's real weighting. Direction and
   scale, not decomposition.
4. **The productivity break and v2's bias are the same size, and that is all that should be
   claimed.** They read −0.340 and +0.340 on 1 September, which was closer than two independently
   estimated quantities have any right to be over samples this short. The Q2 print moved v2's to
   +0.328 within a day. The order of magnitude is the finding; the decimals never were.
5. **US comparison magnitudes come from secondary sources.** The sign-flip is the robust part.
6. **Mechanism 5 (deflator) is flagged, not tested.**
7. **Six RBA observations cannot establish RBA unbiasedness** — only that the bias is not forced
   by the period.

---

## Sources

**Nowcasting and long-run growth**
- Antolín-Díaz, J., Drechsel, T. and Petrella, I. (2017), "Tracking the Slowdown in Long-Run GDP Growth", *Review of Economics and Statistics* 99(2), 343–356. https://direct.mit.edu/rest/article/99/2/343/58399/Tracking-the-Slowdown-in-Long-Run-GDP-Growth
- Antolín-Díaz, J., Drechsel, T. and Petrella, I. (2024), "Advances in Nowcasting Economic Activity: The Role of Heterogeneous Dynamics and Fat Tails", *Journal of Econometrics* 238(2), 105634. https://www.sciencedirect.com/science/article/abs/pii/S0304407623003500
- Working-paper version (quoted above): https://www.ecb.europa.eu/press/conferences/shared/pdf/20210615_11th_cft/Petrella_paperT7.pdf · CEPR DP15926 https://cepr.org/publications/dp15926 · CEPR DP17800 https://cepr.org/publications/dp17800

**Structural breaks and intercept correction**
- Clements, M. P. and Hendry, D. F. (1996), "Intercept corrections and structural change", *Journal of Applied Econometrics* 11(5), 475–494. https://onlinelibrary.wiley.com/doi/abs/10.1002/(SICI)1099-1255(199609)11:5%3C475::AID-JAE409%3E3.0.CO;2-9
- Clements, M. P. and Hendry, D. F., "Forecasting in the Presence of Structural Breaks and Policy Regime Shifts". https://www.nuffield.ox.ac.uk/economics/papers/2002/w12/DFHGEMTom.pdf

**Forecaster optimism (the thing this is not)**
- IMF WP/21/275, "Macrofinancial Causes of Optimism in Growth Forecasts". https://www.imf.org/-/media/files/publications/wp/2021/english/wpiea2021275-print-pdf.pdf
- IMF WP/18/39, "How Well Do Economists Forecast Recessions?". https://www.imf.org/-/media/files/publications/wp/2018/wp1839.pdf
- IMF WP/16/228, "Forecast Errors and Uncertainty Shocks". https://www.imf.org/external/pubs/ft/wp/2016/wp16228.pdf

**Australian context**
- Productivity Commission, *Annual productivity bulletin 2024*. https://www.pc.gov.au/ongoing/productivity-insights/bulletins/bulletin-2024/
- Grant, A. L. et al. (2018), "Nowcasting Australia's Gross Domestic Product", Treasury Working Paper 2018-04. (In repository root.)
- Tulip, P. and Wallace, S. (2012), "Estimates of Uncertainty around the RBA's Forecasts", RBA RDP 2012-07. https://www.rba.gov.au/publications/rdp/2012/pdf/rdp2012-07.pdf
- RBA historical forecasts. https://www.rba.gov.au/statistics/historical-forecasts.html
- ABS, "Revisions", *Australian System of National Accounts: Concepts, Sources and Methods*. https://www.abs.gov.au/statistics/detailed-methodology-information/concepts-sources-methods/australian-system-national-accounts-concepts-sources-and-methods/edition-8/chapter-24-quality-national-accounts/revisions

**US nowcast comparison**
- Federal Reserve Bank of New York, Staff Nowcast FAQs. https://www.newyorkfed.org/research/policy/nowcast/faqs.html
- Federal Reserve Bank of Atlanta, GDPNow explainer. https://www.atlantafed.org/research-and-data/data/gdpnow/explainer

**Project data used**
`data/performance.json`, `data/performance_v2.json`, `data/performance_v3.json`,
`data/backtest_v3.json`, `data/gdp.json`, `data/latest*.json`,
`docs/measurements/2026-08-30-plan-c-backtest.csv`, `nowcasting_v2/data_raw/*.csv`,
`nowcasting_v3/model_spec_AU.csv`, `pipeline/rba_somp_forecasts_v2.csv`.

Analysis scripts: `bias1.py` … `bias8.py` in this session's scratchpad.
