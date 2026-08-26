# Nowcast v3 — Australian panel design (Plan B)

**Date:** 2026-08-26
**Status:** Approved in brainstorming; awaiting review before an implementation plan is written.
**Predecessor:** Plan A (the engine port) — complete, PR #19.
Plan: `docs/superpowers/plans/2026-08-24-nowcast-v3-nyfed-port.md`

## Why this exists

Plan A ported the NY Fed Staff Nowcast 2.0 to Python and reproduced the published US
nowcast for 2023-09-29. The engine works. It currently runs on the NY Fed's own panel of 31
US series. Plan B replaces that panel with Australian data.

This is the whole risk of the v3 program. The engine is verified against an external
reference; the Australian panel cannot be, because nobody publishes an Australian nowcast
from this model. Everything downstream — the backtest, the site, the CI split — assumes the
panel is right.

## The governing principle

**Mirror the NY Fed panel. For each of their series, find the Australian equivalent. Where
none exists, leave the gap rather than invent a substitute.**

This was chosen deliberately over building the best-available Australian panel from scratch.
The reasoning: the model's block structure, factor count and priors were designed around the
NY Fed's panel composition. Departing from it means departing from the evidence base that
justified those choices, and we have no oracle to catch the consequences.

Departures from the mirror are therefore explicit, few, and flagged in this document.

## Decisions

Four decisions were taken during brainstorming. Each is recorded with its reasoning so a
later reader can see what was chosen against.

### D1 — Mirror the NY Fed panel, series by series

Rejected: reusing v2's 39-series panel; building an automated-sources-only panel; adding
manual-source series for maximum coverage. All three optimise for Australian data
availability rather than for fidelity to a model whose behaviour we have verified.

### D2 — The manufacturing block stays thin

The NY Fed panel carries **seven** monthly manufacturing series: durable goods new orders,
manufacturers' shipments, unfilled orders, manufacturers' inventories, wholesale inventories,
total business inventories, and industrial production. **Australia publishes none of these
monthly.** ABS discontinued most; the survivors are quarterly.

Rejected: substituting mining and resources series (Australia's cyclical goods sector);
including the quarterly equivalents at quarterly frequency; both together. The block is left
empty rather than filled with something that plays a different role.

Also considered and rejected: using NAB sub-series as substitutes. Three map well
conceptually — Forward Orders for durable goods new orders, Stocks for inventories, Capacity
Utilisation for industrial production. But the NY Fed's manufacturing series load on
**Global + Nominal + COVID**, while its survey series load on **Global + Soft + COVID**. The
Soft block exists to absorb the shared "survey-ness" of diffusion indices — bounded,
sentiment-driven, not denominated in dollars. Placing a survey in the hard-data block would
prevent the Soft factor from doing its job and would attribute survey noise to the nominal
factor. The model would run and look healthy while doing it.

### D3 — Keep the COVID factor, re-dated to Australia

The fifth factor is retained, active **March 2020 to December 2021** — the Victorian and NSW
lockdowns and the closed international border, rather than the US timeline.

Rejected: dropping it and relying on stochastic volatility and outlier states; fitting
several candidate windows and letting a backtest choose. The first departs from the mirror;
the second is defensible but costs an estimation sweep per window at ~1.5 h each, and can be
revisited in Plan C if the fixed window proves unsatisfactory.

**Useful consequence.** In the NY Fed panel the COVID factor is factor five, which is why
`Gibbs_update.m:156-158` pins factor five's stochastic volatility at one by hard-coded index.
Keeping COVID in slot five means the literal port does the intended thing. Plan A recorded
this as a landmine on the assumption the Australian block order might differ; this decision
defuses it, and §Validation pins it with a test.

### D4 — The model stays annualised; conversion happens on emit

Australian headline GDP is quarter-on-quarter. The NY Fed model works in annualised quarterly
growth, using the Mariano–Murasawa aggregation weights `[1,2,3,2,1]/9`.

The model keeps those weights unchanged. The annualised figure is converted to QoQ when
writing `data/*_v3.json`.

Rejected: re-deriving the aggregation filter for QoQ natively. That changes the length-5
weight vector which `construct_SSM.m:131` silently assumes (see §Landmines), requires
regenerating fixtures, and puts a hand-derived filter at the centre of a model we would then
have no way to check. Keeping the internal quantity annualised also leaves it directly
comparable to the NY Fed's own published figures.

## The panel — 17 series

Ten are already members of v2's panel; seven are new to this project. Quarterly series marked *(q)*.

| NY Fed category | n | Australian series | Source |
|---|---|---|---|
| Labour | 5 | Employment; Unemployment rate; ANZ-Indeed Job Ads; Internet Vacancy Index; Unit labour cost *(q)* | ABS 6202; ABS 6202; ANZ-Indeed; Jobs and Skills Australia; ABS 5206 |
| Surveys | 2 | AiG Manufacturing PMI; NAB Business Conditions | AiG; NAB |
| Manufacturing | 0 | *(none — see D2)* | — |
| Housing and construction | 1 | Building Approvals | ABS 8731 |
| Retail and consumption | 2 | Retail Sales; Household Spending (real) | ABS 8501; ABS 5682 |
| International trade | 3 | Exports; Imports; RBA Index of Commodity Prices | ABS 5368; ABS 5368; RBA I2 |
| Prices | 2 | Monthly CPI; Monthly CPI trimmed mean | ABS 6484 |
| Income | 2 | Real GDI *(q)*; **Real GDP *(q)* — the target** | ABS 5206 |

### Departures from a strict mirror, stated explicitly

1. **The RBA Commodity Price Index substitutes for the export price index.** Australia's
   export price index (ABS 6457) is quarterly. The RBA index is monthly and measures prices
   received by Australian commodity exporters, so it occupies the same role in the same
   block — but it is a different statistic, not a like-for-like match. It was independently
   approved on 2026-06-03 as the direct fix for the Q1 2026 miss, which was a commodity and
   export shock the v2 panel could not see.

2. **Seven further series have no Australian counterpart and are simply absent:** the two PCE
   price indices (no monthly Australian analogue), the import price index, housing starts,
   new houses sold, construction work done, and real disposable income (all quarterly in
   Australia). Combined with the seven manufacturing series, fourteen of the NY Fed's 31 have
   no Australian equivalent, giving a panel of 17.

3. **Seven of v2's eight NAB sub-series are excluded.** The NY Fed survey block has exactly two
   members. NAB Business Conditions is the closest match to their Philadelphia Fed series;
   AiG Manufacturing PMI matches Empire State.

## Factor structure

Five factors, mirroring the NY Fed's:

| Factor | Loads on |
|---|---|
| 0 — Global | every series |
| 1 — Soft | the two survey series |
| 2 — Nominal | prices, trade, commodity |
| 3 — Labour | the five labour series |
| 4 — COVID | every series except prices, active 2020-03 to 2021-12 |

**COVID must remain the fifth factor.** See D3 and §Validation.

## Data sources and freshness

Split by what can run unattended.

**Fetched by v3 in Python (13 series).** All twelve ABS series, plus the RBA commodity index. Stable
machine-readable endpoints; run in CI with no human involved. New fetchers, modelled on v2's
logic but not importing from it — v3 and v2 stay independent.

**Read from v2's committed CSVs (4 series).** ANZ-Indeed Job Ads, Internet Vacancy Index, AiG
Manufacturing PMI, NAB Business Conditions. These originate in media releases and PDFs. v2
already fetches them weekly and commits the result to `nowcasting_v2/data_raw/` (56 files
tracked, verified). Rebuilding that plumbing in Python would duplicate a working thing.

### Freshness guards are mandatory, not optional

Every series declares a maximum staleness — a monthly ABS series roughly six weeks, a weekly
survey roughly two. **If any input exceeds its limit, the run fails loudly and publishes
nothing.**

This is the single most important operational requirement in this document. The four
v2-sourced series depend on a weekly routine on one laptop. v1's NAB feed died in June 2026
and the failure surfaced only because a guard halted the job — by design in that instance,
but the same class of failure could as easily have published a stale number. A nowcast built
on three-month-old survey data is worse than no nowcast, because it looks current.

## Starting values

The NY Fed ships `initval.mat`, whose `param.Lambda` doubles as the prior mean for the
loadings. Australia needs its own. Generate it by principal components on the assembled
panel. It needs to be sane, not correct — the sampler re-estimates from there.

## Validation

**There is no oracle.** Plan A could check itself against a published NY Fed number. Nothing
publishes an Australian nowcast from this model. This is the defining difference between the
two plans, and no amount of green tests substitutes for it.

Checks, in order of what they actually buy:

1. **The US fixtures must keep passing.** Every Australian change touches shared code. If a
   fetcher or spec change breaks the US reproduction, it is caught immediately. This is the
   strongest guard available and it already exists.

2. **The four Plan A landmines get live tests, not comments.** See §Landmines.

3. **Panel assembly is tested like data.** Ragged edges where series end on different dates;
   series whose histories start decades apart; and a leakage check of the kind that cleared
   v2 — blank the current quarter's months and confirm the nowcast moves by essentially
   nothing.

4. **A sanity pass on estimation.** The sampler completes at production settings, the factors
   are not degenerate, and the loadings have the signs a reader would expect.

Backtest performance and band coverage are **Plan C**, not Plan B. Plan B's gate is that the
panel is right and the model estimates sanely on it.

### The gate, revised

The plan document currently states Plan B's gate as *"Panel builds to a complete monthly
matrix back to at least 1990."* **That is not achievable with this panel and should not be.**
Household spending starts in 2012, building approvals in 2000, the job-ads and survey series
later still. Demanding a complete matrix would mean discarding the best consumption series
available.

The model handles missing data natively — that is what the Kalman filter is for. The gate is
therefore:

- **GDP and the core labour series extend back to at least 1990.**
- **Every other series starts when it genuinely starts**, with ragged edges tested rather
  than filled.
- The assembled panel builds without gaps *within* a series' own history.

## Landmines carried from Plan A

Each becomes an executable test, not a comment.

| # | Landmine | Treatment in Plan B |
|---|---|---|
| 1 | `load_spec` permutes monthly-before-quarterly while the panel is built in raw CSV order; correct only if the spec CSV is already frequency-sorted | Guard added in Plan A, fires on load, mutation-tested. The Australian spec CSV must be frequency-sorted; the guard enforces it. |
| 2 | `Gibbs_update.m:156-158` pins factor five's stochastic volatility at one by hard-coded index | D3 puts COVID in slot five, which is what the code assumes. Add a test asserting the COVID factor is factor five, so a block reordering fails loudly instead of silently losing that factor's volatility. |
| 3 | `construct_SSM.m:131` pads the quarterly `H` branch with the wrong length variable; harmless only while `vec_m` and `vec_q` are both length 5 | D4 keeps the aggregation weights unchanged, so this never fires. If Plan C revisits QoQ natively, it fires immediately. |
| 4 | `np.minimum` propagates NaN where MATLAB's `min` omits it, at the `bd = 15` volatility cap | Unreachable with US missingness. Australian missingness differs — ragged starts, quarterly-only series. **This is the one landmine that cannot be ruled out by inspection**; it needs a test against the real assembled panel. |

## Non-goals

- **No backtest.** Plan C.
- **No site work.** Plan D. The site contract stays JSON-only.
- **No CI changes.** Plan E.
- **v2 is not touched.** v3 reads four of its committed CSVs and changes nothing in it. v3
  supersedes v1; it does not replace v2.
- **No panel expansion beyond the mirror.** Candidates deferred to Plan C's evidence gate:
  the Brent oil price (approved 2026-06-03 *only if the backtest likes it*), and adding NAB
  Forward Orders and Stocks to the Soft block as additional soft series.

## Open questions

1. **Internet Vacancy Index as the ADP analogue.** ADP is a private payroll measure; IVI is a
   vacancy count. The mapping is weaker than the others and IVI may prove collinear with ANZ
   job ads. Flagged for Plan C's evidence gate rather than resolved now.
2. **Trimmed-mean CPI monthly history.** ABS 6484's monthly series is comparatively short.
   Its start date needs confirming during implementation; if too short to be useful it drops
   and the Prices block carries one series.
3. **Household spending versus retail sales.** v2's own notes record retail sales as a
   genuinely weak GDP proxy (pre-COVID correlation +0.06) and household spending as the
   stronger series. Both are included here because the NY Fed carries both retail sales and
   real PCE. If they prove redundant, Plan C decides.
