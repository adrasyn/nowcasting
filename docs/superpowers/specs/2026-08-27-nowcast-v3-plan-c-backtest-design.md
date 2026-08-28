# Nowcast v3 Plan C — recursive backtest design

**Status:** design, not yet planned into tasks.
**Date:** 2026-08-27
**Depends on:** Plan A (PR #19), Plan B (PR #20). Both green; neither merged.

## Goal

Measure whether v3's nowcast is better than v2's, on the same target quarters,
under pseudo-real-time conditions.

## The question this exists to answer

v2 nowcast **+0.77** against a **+0.30** print for Q1 2026. The diagnosis on
record is a labour-dominated panel deaf to soft and commodity signals. v3's
panel adds commodity prices, exports/imports and a two-series Soft block, and
replaces U-MIDAS-on-a-single-factor with a five-block Bayesian DFM carrying
stochastic volatility and outlier states.

Plan C is the test of that diagnosis. If v3 does not beat v2 on the honest
windows, the diagnosis was wrong and the panel expansion was not the fix.

## Non-goals

- Not a live deployment. Plan D is the weekly path; Plan C only measures.
- Not a spec search. One panel, one spec, as Plan B left them. Comparing panel
  variants is a later exercise and would need its own look-ahead discipline —
  see "The trap v2 already fell into".
- Not a claim of true real-time. See "What a replayed vintage does and does not
  prove".

## Design

### 1. Recursive pseudo-real-time evaluation

For each target quarter `q` in the evaluation window, build panels at several
as-of dates spanning the quarter and produce a nowcast from each. `build_panel`
already cuts every series and every deflator tier by **release date**
(`observation date + publication_lag_days`), so an as-of panel contains only
what had actually been published.

Horizons per target quarter, named by what is known at each:

| Tag | As-of | What is in the panel |
|---|---|---|
| `h1` | end of month 1 of `q` | almost nothing about `q` |
| `h2` | end of month 2 of `q` | one month of monthly indicators |
| `h3` | end of month 3 of `q` | two months |
| `h4` | quarter end + 30d | three months, still pre-GDP-release |

`h4` is the one comparable to v2's published figure. `h1`–`h3` measure whether
the extra blocks buy early information, which is the whole claim.

### 2. Warm start — the compute lever, and its trap

Estimating each vintage cold is the binding constraint, and cold starts are
also where the bimodality bites: roughly half of seeds land in the collapsed
basin and `state_space` refuses.

Fit vintage `t` starting from vintage `t-1`'s posterior. Consecutive vintages
differ by one or two months of data, so the previous fit is a strong starting
point, it should land in the identified basin by construction, and it shortens
the chain needed.

**The seam is `build._initial_point`, which returns `(Prior, InitVal)`. Only
`InitVal` may be warmed.**

- `InitVal.param` — transfers directly. Every field is shaped by `(n, n_f, P_F,
  P_E)` and is independent of `T`.
- `InitVal.latent` — is `(n_f + n, T)` and `T` grows between vintages. Rebuild
  it cold rather than padding. It costs nothing: the sampler redraws latents on
  sweep one.
- `Prior` — **must stay cold.** `construct_prior` takes `Lambda0` as the prior
  *mean*. Warm-starting `Lambda0` would make the prior data-dependent and
  compound it across vintages: by the end of the backtest the prior would be an
  accumulation of every earlier fit, and the later vintages would be neither
  real-time nor independent. The prior is rebuilt from `seed_lambda` on the
  current panel at every vintage, exactly as today.

**Direction is strictly backward.** Vintage `t` may only be warmed from a
vintage strictly earlier than `t`. Warming from a later fit is look-ahead. This
must be enforced in code, not by convention — the runner walks vintages in
ascending as-of order and holds exactly one carried state.

### 3. The first vintage, and refusals

The first vintage has nothing to warm from. Cold-start it, and if
`CollapsedFactorError` is raised, retry with the next seed, recording how many
attempts it took. A vintage that cannot find the identified basin within a
bounded number of attempts fails the run loudly rather than being skipped.

Any refusal *after* the first vintage is a finding, not a nuisance: it means
the warm start did not hold, and it must be logged with the vintage that
produced it.

### 4. Record the loading, not just the verdict

`COLLAPSED_GLOBAL_LOADING = 0.75` is **a floor, not a convergence test**. At
500+500 sweeps one seed sat at 0.539 with a 0.48pp response — between the
basins, correctly refused, but the guard cannot tell "collapsed" from "had not
converged".

A warm start makes borderline chains *less* visible, because each one starts
where the last finished. So every vintage records the target's Global loading
as a number. A drift downward across the run is the signal that the warm chain
is decaying toward the collapsed basin, and nothing else would show it.

### 5. Anchor cold re-estimations

At a fixed interval through the window (proposed: every 8th vintage), also fit
**cold**, and compare the cold and warm nowcasts for that vintage.

This is the check that the warm chain has not drifted into a path-dependent
answer. Agreement within sampler noise is the pass condition; systematic
divergence invalidates the warm-start design and the run must be redone cold.
Cost is bounded and known in advance.

### 6. Evaluation

**Target:** first-print GDP, from v2's `data_raw/rt_dgdp_qtr.csv`, so v3 and v2
are scored against the same number. Latest-vintage GDP is a secondary cut, not
the headline — a nowcast is judged against what was published at the time.

**Units:** v3's target is annualised (`pca`); convert with
`nyfed.au.emit.annualised_to_qoq` before comparing to Australia's QoQ prints.

**Metrics:** RMSE, MAE and mean error (bias), per horizon, over:
- the full evaluation window;
- **post-COVID (2022+)**, the honest window;
- the last 8 quarters (`OOS8`).

**Baselines, in order of what they tell us:**
1. **v2**, on the same quarters and **the same as-of dates**. The comparison
   that matters. `backtest_v2.R:208` already takes an `as_of_freq` of
   `quarter_end` or a weekly Monday grid, and `.truncate_panel` applies its own
   per-series release lags, so v2 can be scored at whatever as-of dates v3 can
   afford. **v3's schedule is the binding one — run v2 on v3's dates, not the
   reverse.** v2 is cheap (MIDAS on a single factor); v3 is not.
2. **A no-change benchmark** (previous quarter's growth). If v3 does not beat
   this, nothing else about it is interesting.
3. RBA SoMP forecasts where the timing lines up — informative, not a target.

### 7. The trap v2 already fell into

v2's `SPEC-SWEEP-RESULTS.md` fixed the targeted-predictor selection **once on
the full sample** and then forced it at every historical as-of. That is
look-ahead, it flattered the stricter threshold, and the conclusion was
reversed on 2026-08-02 when the sweep was re-run without it.

Plan C inherits the lesson: **nothing chosen with knowledge of the whole sample
may be applied at a historical as-of.** The panel, the spec, the block
structure and the transformations are fixed by Plan B before the backtest runs,
and the backtest does not tune them. If a variant is tried later, its selection
must happen inside the recursion.

### 8. What a replayed vintage does and does not prove

Recorded as finding I3 in Plan B's review, and it must appear in the write-up
rather than in a footnote:

> The release-date cut reproduces **which observations existed** at the as-of.
> It does not reproduce **what they said**.

ABS series are revised. A replayed 2019 vintage carries today's revised values
for the months it admits, not the values a forecaster would have seen. So Plan
C is a **pseudo-real-time** backtest, and it will flatter v3 relative to a true
real-time record — as it equally flatters v2, which has the same limitation.

One exception worth noting: `aig_pmi.csv` was hand-entered at publication and
holds genuine first vintages, as now does the routine that maintains it.

## Compute budget and phasing

A full fit is ~1.5 h. The evaluation window that would match v2's backtest is
~49 quarters; at four horizons that is ~196 fits, which is not affordable cold
and is unmeasured warm.

So the work is phased, and **the window is sized after measurement, not
before**:

**Phase 0 — measure (small, cheap, decides everything after it). DONE
2026-08-28.** Ran as `nowcasting_v3/tools/plan_c_phase0.py`; 146 fits, 122
minutes, raw rows in `docs/measurements/2026-08-28-plan-c-phase0.csv`. Three
blocks of six consecutive vintages (2022, 2024, 2026) rather than one, because a
warm start that holds in 2026 says little about 2022 where `job_ads` is months
old.

**GO. The warm start held the identified basin 60 times out of 60** — every
block, every vintage, every chain length from 50 sweeps up. Cold held 28 of 75
(37%).

| Question | Answer |
|---|---|
| cold vs warm wall-clock per fit | **identical per sweep** (0.096 vs 0.097 s). The saving is fewer sweeps and no retry lottery, not faster sweeps. |
| does warm hold the basin every time | **yes, 60/60.** Cold: 28/75. |
| chain length a warm start needs | **200 sweeps** (`n_gs=200, n_burn=100`), 28 s/vintage. |
| warm vs cold nowcast agreement | **±0.03pp q/q at 200+ sweeps** in 2024 and 2026, against a fresh 3,000-sweep cold anchor. |

Warm minus the closing cold anchor, in pp quarter-on-quarter:

| `n_gs` | 2022 block | 2024 block | 2026 block |
|---|---|---|---|
| 50 | +0.004 | -0.068 | +0.001 |
| 100 | -0.467 | -0.147 | -0.031 |
| **200** | -0.442 | **-0.007** | **-0.030** |
| 500 | -0.165 | +0.010 | -0.039 |

200 is the floor: 100 undershoots by up to 0.15pp, which is the same order as
the error the backtest exists to measure. 500 buys nothing over 200.

**THE RETRY LOTTERY IS THE REAL COST, AND IT IS PER-VINTAGE.** Six cold anchors
took eleven attempts and 55 minutes between them. No seed travels: seed 4 was
identified at both 2022 anchors and collapsed at 2024-01, 2024-06 and 2025-12;
seed 13 was identified at 2024-01 and collapsed at 2024-06. A cold backtest
re-runs the lottery at every vintage with no seed it can trust in advance. That
is what the warm start removes, and it is a larger cost than the sweep count
suggests: 28 s warm against 21 minutes for the 2024-06 anchor, a factor of 45.

**2022 IS NOT A USABLE WINDOW, and this is the finding that changes the plan.**
Nowcast levels by block, identified warm fits, pp q/q:

| block | range | median |
|---|---|---|
| 2022 | 0.69 .. 4.12 | **2.24** |
| 2024 | 0.41 .. 0.73 | 0.57 |
| 2026 | 0.51 .. 0.65 | 0.59 |

Australia grew about 0.7% q/q in 2022Q1. The 2024 and 2026 blocks are
plausible; 2022 is not, and it is also the only block where warm and cold
disagree (0.44pp q/q at 200 sweeps, against 0.03pp elsewhere). The likely cause
is structural rather than a warm-start defect: `restrict.py` holds the COVID
factor active to December 2021, so a 2022 vintage sits on its edge, and
`job_ads` is barely a year old there.

**So the evaluation window starts 2023-01, not 2022-01.** That costs four target
quarters of twenty. Including 2022 would report v3 missing badly on the quarters
where the model is structurally weakest, which says nothing about the Q1 2026
question this plan exists to answer.

**Phase 1 — size and run.** Choose the window from the measured cost and a
stated wall-clock budget. Report the window that was affordable, and say
plainly what was left out. A backtest that quietly shrinks its window reads as
a full one.

**Phase 2 — evaluate and write up.** Metrics above, per horizon, against v2 and
the no-change benchmark, with the pseudo-real-time caveat stated in the result,
not the appendix.

## Risks

| Risk | Handling |
|---|---|
| Warm start hides a decaying chain | log the Global loading every vintage; anchor cold fits every 8th |
| Warm start is path-dependent | anchor comparison is the pass/fail |
| Bimodality returns mid-run | refusals after vintage 1 are findings, logged, not skipped |
| Compute overruns | Phase 0 sizes the window before Phase 1 commits |
| Pseudo-real-time flatters v3 | stated in the headline; v2 is scored identically so the comparison stays fair |
| Deflator tier silently skipped | `Panel.deflator_skipped` is now carried out; record it per vintage |

## The open question, and why Phase 0 closed it

**How long may Phase 1 run?** This was the whole decision when the spec was
written. **Phase 0's measurement removed it.**

At 28 seconds per warm vintage, the entire reachable window is affordable:

| | vintages | warm fits | anchors (every 8th) | total |
|---|---|---|---|---|
| 2023-01 .. 2026-05, monthly | 41 | 41 x 28 s = 19 min | 6 x ~9 min = 54 min | **~1.2 h** |

There is no budget trade-off left to make, because the thing that was expensive
turned out to be the cold-start retry lottery and the warm start does not pay
it. Phase 1 should run the whole window rather than sizing one. The remaining
cost is anchors, and how often to place them is a precision choice, not a reach
choice -- every 8th vintage costs under an hour and every 4th costs under two.

What follows is kept for the record of how the window was bounded.

Why it is the only one: inside a hard floor set by the data, how far back the
backtest reaches is a cost choice. The panel's series start at wildly different
dates (`gdp` 1959, `aig_pmi` 2001, `household_spending` 2012, `job_ads` 2021)
and the Kalman filter handles a late start natively -- an unobserved month is
simply unobserved. But a series that has not started at all is a different
thing: `check_freshness` refuses a vintage where a registered series has no
observation, and `standardise` refuses a row too thin to have a defined scale.

**THE FLOOR IS 2021-05, MEASURED.** ANZ-Indeed `job_ads` begins 2021-01, and
that single row sets it:

| asof | outcome |
|---|---|
| 2021-02 | `StaleSeriesError`: `job_ads` has nothing released yet |
| 2021-03 | one observation, which `chg` consumes -- an all-NaN row |
| 2021-04 | one finite observation; `ddof=1` sd undefined |
| **2021-05** | **two observations: the first vintage that builds** |

Two is the arithmetic floor, not an informativeness one. `job_ads`' own scale
reads 0.50 at n=2 and 2.31 at n=3, settling near 6.3 only from about n=7
(2021-10), so a window starting at 2021-05 spends its first months
standardising one row against a number that is still moving. **Recommended
start: 2021-10 or later**, which costs two quarters and buys a stable panel.
Either way, 2022+ is comfortably inside the floor.

This floor moved on 2026-08-28. `cpi_trimmed` began 2024-04 with no back series
to splice, so it, alone, put the floor at **2024-07** -- about seven target
quarters, which would not have covered the post-COVID window this plan is for.
Dropping it from the registry moved the floor to 2021-05 and the reachable
window from ~7 quarters to ~20.

SUPERSEDED BY MEASUREMENT, kept because the guess it contained was wrong in an
instructive direction. The draft assumed warm might be "~10x cold" and that an
overnight run would buy 17 quarters. Measured, warm at 200 sweeps is ~45x a cold
anchor, and the whole window costs about an hour. The trade-off table below no
longer describes a decision:

| Budget | Fits it buys (if warm is ~10x cold) | What that covers |
|---|---|---|
| One overnight run (~10 h) | ~65 | 17 quarters, 2022+ |
| A weekend (~48 h) | ~320 | more fits than the floor allows |

Two things about reach do still hold. 49 quarters would need data back to 2014
and the floor is 2021, so full like-for-like with v2's backtest is NOT available
to v3 while `job_ads` is in the panel. And beyond the reachable window the money
goes into more as-of dates per quarter, more seeds per fit, or more frequent
anchors -- not further back.
