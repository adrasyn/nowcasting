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

**Phase 0 — measure (small, cheap, decides everything after it).**
On ~6 consecutive vintages:
- cold vs warm wall-clock per fit;
- whether the warm start lands in the identified basin every time;
- the chain length a warm start actually needs, against the cold default;
- warm vs cold nowcast agreement on the same vintage.

Phase 0's output is a measured cost per vintage and a go/no-go on the warm
start. If warm starts do not reliably hold the basin, Plan C stops here and the
decision returns to the spec change (the COVID window carrying 64.5% of panel
variance) rather than routing around it.

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

## The one open question for James

**How long may Phase 1 run?** That is the whole decision. Everything else
follows from it.

Why it is the only one: how far back the backtest reaches is purely a cost
choice, not a data choice. The panel's series start at wildly different dates
(`gdp` 1959, `aig_pmi` 2001, `household_spending` 2012, `job_ads` 2021, both
CPI series 2024) and the Kalman filter handles a late start natively -- an
unobserved month is simply unobserved. So no window start "keeps every series
alive", nothing has to be trimmed to make one, and reach is bought with
wall-clock alone.

Illustrative arithmetic, at four as-of dates per target quarter. **The warm
speed-up is a guess until Phase 0 measures it** -- these are here to show the
shape of the trade, not to promise a number:

| Budget | Fits it buys (if warm is ~10x cold) | What that covers |
|---|---|---|
| One overnight run (~10 h) | ~65 | **17 quarters, 2022+** -- the honest post-COVID window |
| A weekend (~48 h) | ~320 | **49 quarters** -- full like-for-like with v2's backtest |

The recommendation is to start with the overnight budget. Post-COVID is the
window that decides the Q1 2026 question, it is the window v2's own sweep
treats as honest, and Phase 0 will have replaced the 10x guess with a measured
figure before anything is committed. Extending to the full 49 quarters is then
a second run, not a redesign.
