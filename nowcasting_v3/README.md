# nowcasting-v3 — NY Fed Staff Nowcast 2.0, ported to Python

A Python port of the New York Fed Staff Nowcast 2.0 (Almuzara, Baker, O'Keeffe &
Sbordone, 2023): a Bayesian dynamic factor model with stochastic volatility and
outlier states, to be refitted to Australian data.

The port is a translation, not a reimplementation. Where the published MATLAB
does something surprising — and it does, in several places — the Python does the
same surprising thing, and says so in a comment. Deviating would break the one
thing that makes the port checkable: that every function can be compared against
the original, running, on the same inputs.

**Status: Plan A complete.** Both published US headline nowcasts reproduce end
to end, and every per-series release impact of the week the drop is configured
for. The other week's per-series table cannot be reproduced from this drop, for
a reason that is measured rather than assumed. See
[The end-to-end gate](#the-end-to-end-gate).

## Layout

| Path | Purpose |
| --- | --- |
| `nyfed/` | The Python port (the deliverable). |
| `nyfed/run_us_reference.py` | `example_nowcast.m` end to end; the gate's runner. |
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
.venv/bin/pytest -m "not slow"      # ~25 s, 137 tests: the iteration loop
.venv/bin/pytest                    # ~30 min, 151 tests, incl. the end-to-end gate
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
