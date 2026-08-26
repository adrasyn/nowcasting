# nowcasting-v3 — NY Fed Staff Nowcast 2.0, ported to Python

A Python port of the New York Fed Staff Nowcast 2.0 (Almuzara, Baker, O'Keeffe &
Sbordone, 2023): a Bayesian dynamic factor model with stochastic volatility and
outlier states, to be refitted to Australian data.

The port is a translation, not a reimplementation. Where the published MATLAB
does something surprising — and it does, in several places — the Python does the
same surprising thing, and says so in a comment. Deviating would break the one
thing that makes the port checkable: that every function can be compared against
the original, running, on the same inputs.

**Status: Plans A and B complete.** Both published US headline nowcasts reproduce end
to end, and every per-series release impact of the week the drop is configured
for. The other week's per-series table cannot be reproduced from this drop, for
a reason that is measured rather than assumed. See
[The end-to-end gate](#the-end-to-end-gate). The engine now also estimates on
an Australian panel — see [The Australian panel](#the-australian-panel), which
has no oracle and says so.

## Layout

| Path | Purpose |
| --- | --- |
| `nyfed/` | The Python port (the deliverable). |
| `nyfed/run_us_reference.py` | `example_nowcast.m` end to end; the gate's runner. |
| `nyfed/au/` | The Australian panel: fetch, deflate, guard, assemble. Nothing in `nyfed/` outside it knows about Australia. |
| `model_spec_AU.csv` | The Australian model specification, 15 series over 5 blocks. |
| `nyfed_matlab/` | **Vendored MATLAB reference implementation. Read-only.** |
| `tools/` | Octave fixture generation, `.mat` → `.npz` conversion, timing. |
| `tests/` | Pytest suite. `tests/fixtures/*.npz` are committed. |
| `NYFed-Staff-Nowcast_technical-paper.pdf` | The reference paper. |

### `nyfed_matlab/` is read-only, permanently

Never edit a file under `nyfed_matlab/` — not to fix a bug, not to add a debug
print, not temporarily. It is the oracle the port is tested against, so it must
stay byte-identical to what the NY Fed published. The rule is enforceable and
checked as part of the plan gate:

```bash
git log --oneline -- nowcasting_v3/nyfed_matlab   # must show only the vendoring commit
```

If Octave ever needs a modified version of one of those functions, put the
modified copy in `tools/octave_shims/` and `addpath` that directory ahead of the
originals in `tools/gen_fixtures.m`.

One file inside it is not in git and never should be:
`Estimates_2023_09_20.mat`, 21 MB of stored Gibbs output that ships with the NY
Fed drop. `nyfed/run_us_reference.py` raises a clear error when it is absent,
and the tests that need it skip rather than fail.

## Testing strategy: Octave as a numerical oracle

The port is tested against the vendored MATLAB, executed under GNU Octave.
`tools/gen_fixtures.m` runs reference functions on small, fixed-seed inputs and
saves inputs and outputs; `tools/matload.py` flattens those into `.npz`; the
tests load them via `tests/conftest.py` and compare the Python port's output.

Why an oracle at all: a numerical port has no natural test. "The nowcast looks
about right" is not a test, and a hand-computed expectation for a 73-state
Kalman filter is not available. The MATLAB, running, is the only thing that
knows what the right answer is, so the fixtures are the specification.

This was verified on 2026-08-24 with **Octave 11.3.0** on macOS (arm64).
`Kalman_filter.m` ran unmodified and returned a finite log-likelihood of
`-60.919914554813` on a 2-series / 3-state / 20-period model with one missing
observation. In particular Octave accepts `linsolve(S, eye(k), option)` with the
`SYM`/`POSDEF` options struct, which was the anticipated portability risk, so
**no shim was required**.

### The two-tier test rule

*As amended on 2026-08-25 (commit `7a5c82c`). This is the form that binds; the
original omitted the `atol` clause and let 32 assertions run looser than they
claimed.*

**Tier 1 — deterministic results.** Match the Octave fixture to `rtol=1e-10`
**with an explicit `atol`**.

`np.allclose` defaults `atol` to `1e-8`. For any value smaller in magnitude than
100, that absolute floor dominates `rtol=1e-10` completely — so an assertion
written

```python
np.allclose(got, want, rtol=1e-10)          # WRONG: this is an atol=1e-8 check
```

is not the relative check it appears to be. It is three orders of magnitude
looser, and it will pass on a port that is wrong.

* **Default to `atol=0.0`.**
* Where an array holds entries near zero alongside entries of order 1, a hard
  zero is unachievable, so derive a floor **from the array itself**:
  `atol = 1e-12 * np.nanmax(np.abs(want))`. Never a hard-coded literal.
* State the measured deviation and the resulting margin in a comment, so the
  next reader can see the tolerance was earned rather than guessed.

**Tier 2 — stochastic results.** Never assert exact equality on a draw. Compare
moments, and express the tolerance as a multiple of a Monte Carlo standard error
computed from the draws themselves, not as a constant that happened to hold once.

**Unwrapping fixture scalars** uses `.item()` — never bare `float()` / `int()`,
never `.ravel()[0]`. The rule exists so nobody has to check whether a particular
value happens to be 0-d.

The suite runs under `filterwarnings = ["error"]` (set in `pyproject.toml`, not
at the command line, so the next new warning cannot pass CI in silence).

### Running the suite

```bash
cd nowcasting_v3
.venv/bin/pytest -m "not slow"      # ~25 s, 143 tests: the iteration loop
.venv/bin/pytest                    # ~30 min, 157 tests, incl. the end-to-end gate
```

A stale `nyfed/__pycache__` has faked a red suite twice in this project. Clear it
before investigating an inexplicable failure.

### Regenerating fixtures

Fixtures are **committed** — CI has no Octave and cannot rebuild them, so they
are test inputs rather than build output. `tests/test_fixtures_present.py` keeps
the directory under a 5 MiB budget and asserts that each fixture still carries
the keys its consumers depend on.

```bash
brew install octave
octave --eval "pkg install -forge datatypes"    # statistics dependency
octave --eval "pkg install -forge statistics"

cd nowcasting_v3/tools
octave gen_fixtures.m                            # -> tools/fixtures_mat/*.mat
../.venv/bin/python matload.py                   # -> tests/fixtures/*.npz
```

`tests/fixtures/published_nowcasts.npz` is different: it is not an Octave
fixture. It holds the NY Fed's own published nowcasts and news tables, recovered
from the undocumented MCOS subsystem of `nyfed_matlab/output/Update_*.mat` —
neither scipy nor Octave decodes a MATLAB `table`. Regenerate it with
`../.venv/bin/python extract_published.py`, and read that file's header before
touching it.

## The end-to-end gate

`nyfed/run_us_reference.py` is `example_nowcast.m` in Python, end to end: load
the spec, load two data vintages, rebuild the parameters from the posterior
medians of the stored Gibbs output, redraw the outlier states 1,250 times per
vintage, average, build both state spaces, then run the point nowcast, the news
decomposition and 1,250 density draws.

```bash
.venv/bin/python -m nyfed.run_us_reference 2023-09-29
.venv/bin/python -m nyfed.run_us_reference 2023-09-29 --seeds 321 1 2 3 4 --density-draws 20
.venv/bin/pytest tests/test_end_to_end.py -v
```

### Step 0: how reproducible is a weekly nowcast at all?

MATLAB's published figures average 1,250 stochastic `S_update` draws off
`rng(321)`. numpy cannot reproduce that stream, so this port converges to the
same limit along a different path, with Monte Carlo error around it. Before the
gate was ever run, that error was measured: five seeds per week, full
production-settings runs.

```bash
.venv/bin/python -m nyfed.run_us_reference 2023-09-29 --seeds 321 1 2 3 4 \
    --density-draws 20 --quiet          # 38 min
```

| Week | seed 321 | seed 1 | seed 2 | seed 3 | seed 4 | mean | **sd** | range |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2023-09-29 | 2.015771 | 2.030426 | 2.011280 | 2.010517 | 2.019899 | 2.017578 | **0.008112** | 0.019909 |
| 2023-10-06 | 2.399940 | 2.396070 | 2.388481 | 2.392394 | 2.400623 | 2.395502 | **0.005128** | 0.012142 |

#### Five seeds were not enough

Review asked for the two tightest per-series comparisons to be re-measured over
more seeds. Doing so showed the five-seed estimates were unreliable — the first
five seeds happened to be a tight cluster:

| quantity | sd (5 seeds) | **sd (15 seeds, 5-19)** | ratio |
| --- | --- | --- | --- |
| 2023-09-29 headline | 0.008112 | **0.017331** | 2.14 |
| 2023-10-06 headline | 0.005128 | **0.014124** | 2.75 |
| 2023-09-29 AMDMTI impact | 0.000019 | **0.000038** | 2.01 |
| 2023-09-29 AMDMUO impact | 0.000006 | **0.000014** | 2.30 |

An sd from `n` samples has a relative standard error of about `1/sqrt(2*(n-1))`
— 35% at n = 5, 19% at n = 15. **So every tolerance constant in
`tests/test_end_to_end.py` is measured over the fifteen seeds 5-19**, which are
disjoint from seed 321, the seed every assertion runs at. No tolerance is
estimated from the run it then judges.

All twenty 2023-09-29 headlines, sorted, run from 1.984494 to 2.035595, and the
published 2.024187 sits at the **74th percentile of this port's own
distribution** — an ordinary draw from it, mean gap −0.009370 = 0.61 sd.

**A weekly nowcast from this model is reproducible to about ±0.05pp, and no
further** (three sd, on the 15-seed estimate). That is a property of the model,
not of the port — MATLAB does not reproduce itself across seeds either. It bounds
what any weekly published figure can claim, and Plan D should not print more
precision than it.

Seed-to-seed sd of each series' first-horizon release impact, in pp, over the
fifteen seeds 5-19:

| 2023-09-29 | sd | | 2023-10-06 | sd |
| --- | --- | --- | --- | --- |
| DSPIC96 | 0.001282 | | PAYEMS | 0.004628 |
| DGORDER | 0.000919 | | BOPTIMP | 0.001185 |
| AMDMVS | 0.000502 | | BOPTEXP | 0.000632 |
| PCEC96 | 0.000475 | | JTSJOL | 0.000376 |
| HSN1F | 0.000392 | | UNRATE | 0.000354 |
| PCEPI | 0.000318 | | ADPMNUSNERSA | 0.000225 |
| PCEPILFE | 0.000263 | | TTLCONS | 0.000012 |
| AMDMTI | 0.000038 | | | |
| AMDMUO | 0.000014 | | | |

Every one of these is usable as a tolerance: none of the sixteen is so noisy
that no useful bound exists for it.

### The tolerance, and why it is `3 * sqrt(2) * sd`

The comparison is between **two** independent 1,250-draw averages — ours and
MATLAB's. The difference of two such averages has variance `2 * sd^2`, so a
three-sigma bound on it is `3 * sqrt(2) * sd = 4.243 * sd`. A bound of `3 * sd`
would be right only if the published figure were exact, and it is not.

**Two assumptions sit under that, and they are assumptions, not measurements.**

1. **MATLAB's per-run sd equals this port's.** Both average 1,250 draws of the
   same `S_update` from the same posterior, so it is reasonable — but only one
   MATLAB run was ever published, so its sd cannot be estimated from here, now
   or ever. If MATLAB's sd is larger than ours, `sqrt(2)` understates the right
   factor; if smaller, it overstates it.
2. **`sd` is known.** It is estimated from a handful of seeds, and an sd from `n`
   samples has a relative standard error of about `1/sqrt(2*(n-1))` — 35% at
   n = 5, 19% at n = 15, which is what the constants in force are measured over.
   A comparison landing near 1.0x of tolerance therefore is not meaningfully
   distinguishable from one landing just over it. Where one came close, the sd
   was re-measured over fifteen further seeds rather than left at five.

Neither point moves the substantive results. The 2023-09-29 headline passes
under `abs=0.01`, under `3*sd` and under `3*sqrt(2)*sd` alike; and the
2023-10-06 residual is a bias, which no choice of sigma multiple turns into a
meaningful pass.

**A Monte Carlo tolerance is only the right instrument for Monte Carlo error.**
Where a residual turns out to be a fixed offset, it is pinned as a two-sided
observation instead — see the 2023-10-06 section below.

The headline additionally keeps a `0.01`pp floor, the precision the figure is
published to. The per-series impacts get **no** floor: four of the nine
published impacts for 2023-09-29 are smaller in magnitude than 0.01, so a flat
`abs=0.01` would pass on those series even if the port returned exactly zero.

### Gate results

```
.venv/bin/pytest tests/test_end_to_end.py -v      # 13 passed in 13:10
```

**The gate is the 2023-09-29 week**, and what carries it is the literal floor:

| Week | published | this port (seed 321) | deviation | |
| --- | --- | --- | --- | --- |
| 2023-09-29 | 2.0241867 | **2.015771** | **0.008416** | **inside the plan's ±0.01pp floor** |

The deviation is 0.008416, and the plan asked for ±0.01pp. That is the result,
and it depends on no tolerance rule at all: it also clears the plan's original
`max(0.01, 3*sd)` and the `max(0.01, 3*sqrt(2)*sd)` used here.

`test_reproduces_the_published_nowcast` asserts **both**: the ±0.01pp floor,
which it meets at 0.84x, and the wider `3*sqrt(2)*sd` band, which it meets at
0.11x. The floor is the one doing the work — see
[Is the gate falsifiable?](#is-the-gate-falsifiable) for the mutation that slips
through the sigma band and is caught by the floor.

Do not read that 0.11x as an improvement on the 0.24x quoted before the sd
re-measurement: **the deviation never moved.** The tolerance widened, from
0.034416 to 0.073529, because the sd it is built from was re-measured larger.
That is a looser gate, not a tighter result.

One caveat on the floor, stated because the file's own rule is not to lean on a
ratio near 1.0x. Meeting ±0.01pp at 0.84x is a statement about **seed 321**, not
about every seed: this headline's seed-to-seed sd is 0.017331, so other seeds
miss ±0.01pp routinely. It does not flake — the seed is fixed and numpy's PCG64
stream is deterministic — but it is why the Monte Carlo band is kept alongside
the floor rather than replaced by it, and why the spread above is quoted next to
the point estimate.

2023-10-06 lands at **2.399940** against a published **2.3834663**, a residual of
**+0.016474** — which *passes* a Monte Carlo comparison, and is nonetheless not
asserted as a gate. The headline is a sum in which a **9.5-sigma** error in the
revisions term is masked by an ordinary noise excursion in another component, so
a headline assertion would report success over a decomposition that is wrong.
The components are pinned individually instead — see below.

All nine per-series release impacts for 2023-09-29, in pp of the nowcast:

| series | published | this port | deviation | tolerance | ratio |
| --- | --- | --- | --- | --- | --- |
| DGORDER | -0.052702 | -0.052058 | 0.000644 | 0.003899 | 0.17 |
| DSPIC96 | -0.040846 | -0.042265 | 0.001419 | 0.005440 | 0.26 |
| HSN1F | -0.030640 | -0.031053 | 0.000413 | 0.001663 | 0.25 |
| PCEPI | 0.021788 | 0.021942 | 0.000154 | 0.001350 | 0.11 |
| PCEC96 | -0.014736 | -0.014670 | 0.000066 | 0.002017 | 0.03 |
| AMDMVS | -0.008788 | -0.008640 | 0.000148 | 0.002129 | 0.07 |
| PCEPILFE | -0.005922 | -0.006285 | 0.000363 | 0.001118 | 0.33 |
| AMDMTI | -0.000928 | -0.000852 | 0.000076 | 0.000162 | 0.47 |
| AMDMUO | -0.000358 | -0.000339 | 0.000019 | 0.000059 | 0.33 |

All nine pass, the worst at 0.47x of tolerance. (On the original five-seed sds
the two smallest impacts read 0.94x and 0.76x; re-measuring their sds over
fifteen seeds moved them to 0.47x and 0.33x. The five-sample sds were
understated, not the deviations inflated.)

### Is the gate falsifiable?

A gate that cannot fail proves nothing, so the runner was mutated three ways and
the gate re-run against each. All three are the failure modes the plan names as
the first things to check after a miss. Re-run against the tolerances now in
force, after the sd re-measurement:

| Mutation | headline vs the ±0.01pp floor | headline vs `3*sqrt(2)*sd` = 0.073529 | per-series impacts |
| --- | --- | --- | --- |
| *(control — the real runner)* | pass, dev 0.008416 | pass | 9/9 pass |
| Compare horizon 2 against the published horizon-1 table | pass | pass | **6 of 9 fail**, worst 15.8x |
| Skip the 1,250 `S_update` draws; use the posterior-mean latents | **FAIL**, dev 0.040760 | *pass* | **1 of 9 fails**, 1.8x |
| Use the wrong "old" vintage for the week (09-20, not 09-22) | — | — | **caught**: 10 release rows, not 9 |

Two things fall out of that table, and both matter more than the pass itself.

**The `3*sqrt(2)*sd` tolerance is too loose to catch a real defect.** Deleting
the entire 1,250-draw `S_update` averaging — a gross error, the second thing the
plan says to check after a miss — moves the headline to 0.040760, which sits
comfortably *inside* the 0.073529 sigma band and would have gone green. **The
±0.01pp floor catches it.** That is the concrete reason the floor is the gate
criterion above and the sigma ratio is only supporting detail: on the one
mutation where the two disagree, the floor is right.

**The headline alone would miss the horizon mutation entirely** — it passes both
headline criteria while six of the nine per-series impacts fail, the worst by
15.8x. That is what the per-series test is for, and it is the same
compensating-errors argument that demotes the 2023-10-06 week below.

(Before the sd re-measurement this table read *7 of 9* and *3 of 9* for the first
two mutations, and the `S_update` mutation failed the sigma band as well as the
floor. The mutation deviations did not change; the tolerances they are judged
against did.)

### 2023-10-06 is not reproducible from this drop, and that is not a port bug

Its per-series table misses — four of seven impacts beyond the measured Monte
Carlo bound, the worst by 6.72x (TTLCONS), then ADPMNUSNERSA at 6.58x — and its
headline residual of +0.016474 hides a **fixed offset** in one component. (On
the superseded five-seed sds this read five of seven, worst 6.45x; BOPTEXP moved
under the line when its sd was re-measured 1.8x larger.)

**The published 2023-10-06 update was produced from an estimate file the drop
does not contain.** This is measured, not inferred, and pinned by
`test_the_1006_published_forecasts_need_parameters_this_drop_lacks`.

Each published `Forecast` is a sharp function of the parameter vector — across
four single draws from `param_Gibbs` every one of the sixteen forecasts moves by
at least 1.4% of its published value, and the median by 36.6%. So reproducing one
to a fraction of a percent pins the parameters. With
`median(param_Gibbs)` from `Estimates_2023_09_20.mat`, the worst relative error
over each week's published `Forecast` column is:

| Week | worst | median error as a fraction of the parameter-draw spread |
| --- | --- | --- |
| 2023-09-29 | **0.41%** | 0.004 |
| 2023-10-06 | **16.59%** | 0.064 |

Forty times worse, on the same code and the same estimate file. `example_nowcast.m`
labels `date_estimate_new` "estimate file for current week", so the estimate file
rolls forward weekly and only the 2023-09-29 week's was published.

Corroborating: the published `Actual` column reproduces to 1e-14 for **both**
weeks. `Actual` is `Y_location + Y_scale .* Y_new`, and `Y_location` / `Y_scale`
are pre-2020 statistics — identical whatever the estimate vintage. That is
exactly the signature of a re-estimated parameter file over unchanged
standardisation.

#### The bias is in the revisions term, and nowhere else

Split the headline residual across the decomposition `example_nowcast.m` itself
prints. Fifteen seeds (5-19), port minus published, each component scaled by its
own seed-to-seed sd:

| component | mean gap | sd | **in sigma** |
| --- | --- | --- | --- |
| 2023-09-29 level (row 1 of the 10-06 week) | −0.010291 | 0.017331 | 0.59 |
| release total | −0.000522 | 0.005401 | 0.10 |
| **revisions term** | **+0.019197** | **0.002028** | **9.46** |
| headline residual (the sum) | +0.008383 | 0.014124 | 0.59 |

Two of the three components are indistinguishable from the published values; the
third is off by nine and a half sigma. And the headline is back at 0.59 sigma,
because the level term is negative and cancels most of the revisions bias.

**That is the argument for not gating this week on its headline.** Not that the
headline fails — it passes. That it *cannot see* a 9.5-sigma error in one of its
own components, because another component's ordinary noise happens to offset it.
It is the compensating-errors failure the per-series test exists to catch,
arriving through the revision terms instead of the releases.

The published revisions term is derivable from the two committed fixtures with
no new computation, as `published_1006 − published_0929 − sum(published 10-06
impacts)` = **+0.161811**, which is exactly what `example_nowcast.m` prints as
"Impact from parameter and data revisions". This port gives **+0.181008** on the
same fifteen seeds, +0.183333 at seed 321.

Why that term. `rev_SSM` is by construction the effect of swapping `ssm_old` for
`ssm_new`, and in this drop `param_old == param_new`, so this port's `rev_SSM`
measures the **latent** revision and nothing else. MATLAB's 2023-10-06 run used
a later `param_new`, so its `rev_SSM` also contained a genuine **parameter**
revision — a quantity this port cannot compute at all, because the parameters
that would produce it are not in the drop.

**Measured, and sufficient.** Perturbing `param_new` away from
`median(param_Gibbs)` by exactly the size the forecast comparison measures
(median 6.4% of the parameter-draw spread) shifts the revisions term by, against
the +0.019197 that has to be explained:

| perturbation direction | induced shift in the revisions term | vs +0.019197 |
| --- | --- | --- |
| draw 0 | +0.010379 | 0.54x |
| draw 150 | −0.055074 | 2.87x |
| draw 300 | −0.022565 | **1.18x** |
| draw 450 | +0.011214 | 0.58x |

The offset that must be explained is squarely inside the range a
correctly-sized parameter perturbation produces, and one of four directions
reproduces it to 1.18x. (`rev_data` barely moves across all of these — 0.138 to
0.193 — while `rev_SSM` carries the shift, which is the mechanism above.)

**What that establishes, and what it does not.** It is a scale test, and it
passes as one: it kills the null that a parameter difference of the measured
size is too small to move the revisions term by 0.02, with a genuine control
(`rev_SSM` is exactly 0.000000 when both sides use the same parameters) and a
falsifier stated before the run. But 2 of the 4 directions carry the right sign,
which is a coin flip, and a range spanning ±0.055 would absorb any additive
defect smaller than that. So the missing estimate file is a **sufficient**
explanation, not a demonstrated exclusive one. **"No defect detected in the
revisions path" is what this earns; "a defect there is ruled out" is not** — and
the section below records that on the gate week those terms are pinned against
nothing at all.

The gap is pinned with two-sided bounds rather than skipped, so that the day
somebody obtains the real 2023-10-06 estimate file the tests fail and say to
promote the week into the gate.

#### What cannot be checked at all

The gate week's own revisions term has **no published counterpart**. Deriving it
needs the 2023-09-22 headline, and the drop ships no `Update_2023_09_22.mat`. So
for 2023-09-29 the release impacts are pinned against the published table and
the revision terms are pinned against nothing but the internal identity.

That is a live gap for Plan D, whose headline deliverable is a decomposition
panel built on exactly these terms. It is asserted rather than commented, in
`test_the_0929_revisions_term_has_no_published_counterpart`, so that if the
missing file ever turns up the test fails and says to add the check.

## The Australian panel

**Status: Plan B complete.** `nyfed/au/` builds an Australian panel and the
engine estimates on it. `nyfed/` itself is untouched — the engine reads a spec
CSV and a standardised `(n, T)` matrix and does not know which country it is
looking at.

```python
from nyfed.au.build import build_panel, estimate_short, quick_nowcast
panel = build_panel(asof="2026-06-01")          # fetches, guards, assembles
figure = quick_nowcast(panel)                   # estimates, guards, nowcasts
```

Both calls can **refuse**. `build_panel` raises `StaleSeriesError` if any input
has gone stale; `quick_nowcast` raises `CollapsedFactorError` if the fitted
chain left GDP disconnected from the panel. Neither has a bypass flag, and
neither refusal is a bug — see below.

### The 15 series

`model_spec_AU.csv` and `nyfed/au/sources.py` carry the same 15 rows in the same
order, and `assemble` refuses if they ever disagree — the panel is stacked from
the registry and labelled from the spec, so a mismatch would attach every label,
and `i_now`, to the wrong row.

| Series | Source | Locator | Block | Transform |
| --- | --- | --- | --- | --- |
| Employment | ABS 6202.0 | `A84423043C` | Labor* | `chg` |
| Unemployment rate | ABS 6202.0 | `A84423050A` | Labor | `chg` |
| ANZ-Indeed Job Ads | **v2 CSV** | `anz_ads` | Labor | `chg` |
| AiG Manufacturing PMI | **v2 CSV** | `aig_pmi` | Soft | `lin` |
| NAB Business Conditions | **v2 CSV** | `nab_cond` | Soft | `lin` |
| Building Approvals | ABS 8731.0 | `A422070J` | Global | `chg` |
| Household Spending (real) | ABS 5682.0, **deflated** | `A130200584T` | Global* | `pch` |
| Exports | ABS 5368.0 | `A2718577A` | Nominal | `pch` |
| Imports | ABS 5368.0 | `A2718603V` | Nominal | `pch` |
| RBA Commodity Prices (A$) | RBA table I2 | `GRCPAIAD` | Nominal | `pch` |
| Monthly CPI | ABS 6401.0 | `A130607789R` | Nominal* | `pch` |
| Monthly CPI trimmed mean | ABS 6401.0 | `A130400381L` | Nominal | `pch` |
| Unit labour cost | ABS 5206.0 | `A2433074L` | Labor | `pca` |
| Real gross domestic income | ABS 5206.0 | `A2304410X` | Global | `pca` |
| **Real GDP** (the target) | ABS 5206.0 | `A2304402X` | Global | `pca` |

`*` marks the series that normalises a block. Every series also loads the Global
factor, and all but the four price/commodity rows load the COVID factor, which
`nyfed/au/restrict.py` confines to March 2020 – December 2021.

Two series a reader may expect are absent, both deliberately and both documented
in `sources.py`: **retail sales** (ABS ceased Retail Trade after the June 2025
release; household spending covers the ground better) and the **Internet Vacancy
Index** (v2 has never once fetched it — the JSA host is firewalled from v2's
runner — and it duplicates job ads anyway).

### Household spending is deflated, and that is load-bearing

ABS publishes no monthly, real, seasonally adjusted household spending series.
The registry fetches the **nominal** Monthly Household Spending Indicator and
`build_panel` deflates it before anything else sees it, because the panel row
mirrors the NY Fed's real `PCEC96`, its transform is `pch`, and it **normalises
the Global factor** — so a nominal series would set the broadest factor's scale
from inflation. v2 measured the size of the error: 2024 mean 3-month nominal
growth 0.82% against real 0.19%, with real GDP around 0.4%.

The deflator (`nyfed/au/deflator.py`) is a three-tier ratio splice, because
Australia's monthly CPI history is split across a live publication (6401.0,
2024-04 onward), a ceased one (6484.0, 2017-09 to 2025-09) and a quarterly index
interpolated to monthly for the 2012–2017 tail. Each join is rebased by the
geometric mean of the overlap so that `pch` does not see a step change.

### Three series come from v2, and that is a real dependency

Job ads, the AiG PMI and NAB business conditions originate in media releases and
PDFs. v3 does not run v2's R code; it reads the CSVs v2's **weekly laptop
routine** commits to `nowcasting_v2/data_raw/`. If that routine stops, those
files go stale, and `nyfed/au/freshness.py` is what turns silent staleness into a
refusal. It has already happened: `aig_pmi.csv` was last committed on 2026-06-11
with its last observation at 2026-05-01, and from 2026-08-27 — 117 days later,
its widened budget — **a live build correctly refuses on that series and nothing
else**.

Ai Group has *not* stopped publishing — sourcing the publication lag turned up
releases for May, June and July 2026, the last still reporting a separate
manufacturing headline. What broke is v2's scraper, when the publication changed
shape. So the fix is a working fetcher, and there is a trap waiting in it: the
index is now a **net balance centred on zero** (−19.6 in July 2026), not the
50-centred diffusion index the committed history carries. Repairing the scraper
without handling that puts a level break into the Soft block.

### Freshness budgets are derived, not typed

`max_age_days` is not a field. It is

```
publication_lag_days + release_interval_days + SLACK_DAYS
```

where `publication_lag_days` is the only timing fact the registry stores: days
from an observation's **panel date** to the day it was actually released. The
panel date is the start of the reference month for a monthly series and the
**last** month of the quarter for the three quarterly ones, which is where
`fetch_abs` puts them and what `panel._align`'s `{3, 6, 9, 12}` mask requires;
every lag was measured against whichever convention applies to its series. Each
one was read off a release page or a publisher's release-date list on
2026-08-26, and `SeriesSource.lag_source` says which. An unsourced lag would be
the same failure mode one layer down: a number that looks measured and is not.

Typing the budget in directly got it wrong three times in this project, always in
the same direction, always because the panel date runs weeks ahead of the
release. 45–60 days for monthlies
halted healthy data; 75 still refused the four ABS monthlies that publish two
months in arrears; 120 for quarterlies refused `gdp` itself for two months out of
every three. The formula reproduces the numbers those guesses were reaching for
— `gdp` at 94 + 91 = 185 against an observed healthy 178–186, building approvals
at 62 + 31 = 93 against an observed 86 — and it is checkable against the ABS
calendar rather than against anyone's judgement.

`release_interval_days` defaults to the frequency — 31 days monthly, 91
quarterly — but **two publishers skip a month on their ordinary calendar**, and
the default would refuse them for behaving exactly as they always have. Ai Group
publishes no PMI for one December or January in most years (2020-12, 2022-01,
2022-12, 2023-01, 2024-01, 2025-01, 2025-12, plus 2017-06), so the routine case
is a 62-day gap and a worst age of 96 against an 86-day budget: once the AiG
fetcher is repaired the build would refuse **every February**. NAB skipped
September 2020 and would have refused then. Both now carry a per-series
`release_interval_override` of 62 with its own sourced note, measured on the
recorded vintage's own history since 2015. The price is disclosed: `aig_pmi`'s
budget goes 86 → 117, so a genuinely dead feed is caught 31 days later. That is
the right trade — an annual false refusal trains the operator to widen the
budget by hand, which is the one thing the guard forbids. The override widens
the *ordinary* calendar and nothing else: December 2022 and January 2023 were
both missed, a 92-day gap, and that is still refused.

One inequality has to hold: **`SLACK_DAYS` must stay below every release
interval, the overrides included.** At or above it, a series that skipped a
release outright still sits inside its budget and the guard stops guarding.
`SeriesSource.__post_init__` refuses an override that breaks it and
`test_the_slack_cannot_swallow_a_missed_release` pins it for every series.

### A vintage is cut by release date, not reference date

`build_panel(asof=...)` drops every observation whose **release** date —
`observation date + publication_lag_days` — falls after `asof`. Cutting on the
observation's own date instead, which this code did until the first review of
Task 10, admits data nobody had yet: up to nine weeks of it on `gdp`. At
`asof="2026-07-01"` seven of the fifteen series carried a 2026-07-01
observation, and this repo pins the release date of one of them — the 2026-07
commodity index came out on 4 August 2026.

`build_panel` is the primitive Plan C's backtest will call. A backtest whose
vintage at date *T* contains indicators published after *T* is the classic
forward-looking evaluation error: it does not fail loudly, it flatters every
result. `test_the_vintage_cut_is_by_release_date_not_by_reference_date` asserts
the invariant for every row, and pins the commodity instance.

**What the cut does not do is reproduce the values.** It reproduces *which
observations existed* at `asof`, not *what they said* on that day: ABS revises
seasonally adjusted series, so a recording made on 2026-08-26 and replayed at
2026-06-01 carries two months of revisions nobody had then. A backtest on this
primitive is revision-aware in its dating and revision-blind in its values. A
true real-time evaluation needs one recording per `asof`, not one recording
replayed at many.

An early `asof` also loses deflator tiers that had not started publishing yet:
the live 6401.0 monthly CPI does not exist before 2024-04, so at
`asof="2018-06-01"` that tier is legitimately empty and `build_deflator` skips
it, recording the skip in `Deflator.skipped`. A tier that is empty when the
recording says it should have data is still refused — the discriminator is the
uncut recording, so no date is typed in.

### The normalisation Australia had to choose for itself

`construct_prior` needs a prior mean for the loading matrix. The NY Fed ships a
fitted one in `initval.mat`; Australia has none, so `nyfed/au/initval.py` seeds
it by principal components on the assembled panel, and `nyfed/au/build.py` builds
the rest of the starting point — neutral volatilities, no outliers, mild factor
persistence — from the prior's own scales.

Two things about that seed are easy to get silently wrong, and both were:

1. **A principal component's sign is arbitrary; the spec's normalisation is
   not.** `model_spec_AU.csv` fixes household spending's Global loading at +1,
   which defines the factor to move with it. An unoriented seed contradicts that
   about half the time, and because the seed is the prior *mean* for every free
   loading in the column, the contradiction propagates: before this was fixed,
   real GDP loaded the Global factor at **−0.76 after 3,000 sweeps** while real
   consumption was pinned at +1, on a panel where the two correlate +0.12.
   `seed_lambda` now orients each column to its block's normalising series, and
   GDP's Global loading comes out at +1.33.
2. **Restricted loadings must start at their restriction value.** The sampler
   draws only the entries the restriction marks free and keeps the rest verbatim
   for the whole chain, so a normalising loading seeded from PCA would stay at an
   arbitrary number forever and quietly rescale its factor.

### Plan B has no oracle

Plan A could check itself against a published New York Fed figure. **Nobody
publishes an Australian nowcast from this model**, so nothing in
`tests/test_au_end_to_end.py` reproduces a reference number and nothing is tuned
toward one. What that gate does establish:

* the panel has the right shape, the right row order and honest ragged edges;
* the row that reaches the model is the **deflated** household spending series,
  checked by reconstruction to floating point;
* the engine accepts the panel and the sampler moves every free parameter and no
  restricted one;
* a chain that collapsed into the basin where GDP is disconnected from the panel
  is refused rather than turned into a number;
* the target quarter's own months drive the nowcast, and months after it move it
  ~160 times less;
* the vintage contains nothing that had not been released at `asof`.

That fourth point is a *consistency* check, not a leak detector, and the test
says so. Writing April's observation into March's column — an off-by-one in
`panel._align` — leaves the ratio above the asserted threshold at **all six
seeds measured**, and at two of them makes it look better. One post-target
month, published by eight of fifteen series, carries too little signal for the
statistic to separate the cases. The structural no-leak guarantee comes from the
Octave-pinned quarterly aggregation in `construct_ssm` plus the panel's
deterministic alignment and release-date tests. A vintage-pair leakage test
belongs to Plan C.

### GDP's posterior is bimodal, and the model refuses when it collapses

The clearest finding from running the model end to end, and the one that
produced the second guard.

**The premise, measured.** GDP loads only the Global factor and the COVID
factor. The COVID factor is active for 22 months (March 2020 – December 2021),
and those months hold **8 of GDP's 143 observations but 64.5% of its
standardised sum of squares**, including all five of its largest absolute
values. A factor confined to that window can fit the biggest moves in the target
series almost perfectly.

**The mechanism is a two-sided handover.** When GDP's Global loading collapses
(1.334 → 0.011 between two seeds) its COVID loading rises only 1.036 → 1.318 —
nowhere near enough, since the COVID factor is zero outside its 22 months and
the other 135 observations still need explaining. What takes them is GDP's own
idiosyncratic stochastic volatility, and it rises **outside** the window too:
0.875 → 1.107 between those seeds, 0.788 → 1.119 between the two basins' means
over ten seeds. COVID takes the in-window variance; GDP's own error takes the
out-of-window variance the Global loading used to carry. The result is a series
explained by itself.

A likely enabler: the Global factor is normalised by household spending, which
starts in 2012, so only **164 of the panel's 438 months** pin that factor's
scale.

**These are separate basins, not tails of one distribution.** A chain picks one
in its first sweeps and stays. Over 400 stored draws GDP's Global loading has a
5–95% range of −0.45…0.31 at seed 321 and 1.22…1.55 at seed 1, with each chain's
first and last fifty draws in the same place. Lengthening to 2,000 sweeps does
not resolve it. Five of ten seeds land in each basin.

**So the model refuses.** `state_space` — the one funnel from a sampler run to a
state space — raises `CollapsedFactorError` when the target's Global loading is
at or below **0.75**, a floor measured between the two basins: the five
collapsed chains gave 0.011…0.554 and the five identified ones 1.192…1.348.
Without it, a caller taking the library defaults got a plausible 2.83% number
from a model whose response to its *entire* monthly panel was 0.015pp. The
default seed was changed too, but a lucky default is not a guard — half the
seeds collapse, and the next caller passes their own.

Re-running with another seed gets a usable chain about half the time. That is a
workaround. The NY Fed does not face the coin flip at all because `initval.mat`
ships a *fitted* starting point that puts the chain in the right basin, and
Australia starts from a bland one. **Plan C needs a starting point with that
job, or a spec that does not make a 22-month factor compete with the Global
factor for the target series.**

### The gate replays a recorded vintage

`build_panel(asof=...)` fetches live. The gate does not: it replays
`tests/fixtures/au/vintage/`, a full-history recording of every series and every
deflator tier, because a live build takes ~2.5 minutes across four hosts, ABS
revises weekly, and `readabs` emits warnings that `filterwarnings = ["error"]`
would turn into unrelated failures. The recording is checked against the trimmed
payloads that were verified against published ABS and RBA releases, and
`load_vintage` refuses a recording whose locators no longer match the registry.

```bash
caffeinate -i .venv/bin/python tools/record_au_vintage.py    # needs network
```

## Measured timings

Measured on this project's development machine: Apple Silicon macOS (arm64),
Homebrew CPython 3.13.13, numpy 2.x, single process. Reproduce with:

```bash
cd nowcasting_v3/tools
../.venv/bin/python -u time_estimation.py weekly      # 6.4 min
../.venv/bin/python -u time_estimation.py estimate    # 1.50 h
```

| Path | What it runs | Wall clock |
| --- | --- | --- |
| **Weekly nowcast** | 2 x 1,250 `s_update`, 1 `point_nowcast`, 1,250 `density_nowcast` | **381.8 s = 6.4 min** |
| **Quarterly estimation** | `gibbs_sampler` at `n_gs=10000, n_burn=8000, n_thin=2` = **36,002** `gibbs_update` sweeps on the (31, 468) panel | **5388.4 s = 89.8 min = 1.50 h** (0.1497 s/sweep) |

Note the sweep count: `Gibbs_sampler.m` loops `-n_burn : n_gs` inclusive and does
`n_thin` updates per iteration, so production settings are 36,002 sweeps, not
the 28,000 a quick reading suggests.

**No drift over 36,002 sweeps.** Mean `|param|` over the first 100 stored draws
is 0.237802 and over the last 100 is 0.251759 — a 5.9% difference on a chain
that has already burned in 8,000 draws, which is MCMC noise, not degradation.
Every stored parameter is finite. Memory stayed flat; the only large allocation
is the 390 x 10,000 output array (31 MB), and `need_latents=False` keeps the
468-period latent arrays out of it.

### What this means for Plan E

* **The quarterly estimation job fits an Actions runner.** 1.5 h here. GitHub's
  hosted `ubuntu-latest` is materially slower than this machine for
  single-threaded numpy — budget 2-3x, so 3-4.5 h against the 6-hour per-job
  limit. That fits, but not by much: pin the Python version and the numpy
  version, and do not add series to the panel without re-timing. A self-hosted
  runner is not required.
* **The weekly job fits `timeout-minutes: 60` with room to spare.** 6.4 min here,
  so roughly 13-20 min on a hosted Linux runner. Keep the 60-minute timeout;
  there is no reason to raise it.
* Neither number includes fetching data or writing JSON.

## Attribution

`nyfed_matlab/` is the New York Fed's published replication code. Credit the
lineage wherever the model's output is published:

> Almuzara, Baker, O'Keeffe & Sbordone (2023), *The New York Fed Staff Nowcast
> 2.0*, Federal Reserve Bank of New York.

## Python environment

Requires Python >= 3.11 (developed against Homebrew Python 3.13).

```bash
cd nowcasting_v3
python3.13 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```
