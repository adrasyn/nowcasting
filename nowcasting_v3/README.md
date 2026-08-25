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

**A weekly nowcast from this model is reproducible to about ±0.02pp, and no
further.** That is a property of the model, not of the port — MATLAB does not
reproduce itself across seeds either. It bounds what any weekly published figure
can claim, and Plan D should not print more precision than it.

Seed-to-seed sd of each series' first-horizon release impact, in pp:

| 2023-09-29 | sd | | 2023-10-06 | sd |
| --- | --- | --- | --- | --- |
| DGORDER | 0.001198 | | PAYEMS | 0.006218 |
| DSPIC96 | 0.001024 | | BOPTIMP | 0.001327 |
| HSN1F | 0.000457 | | UNRATE | 0.000781 |
| PCEC96 | 0.000432 | | JTSJOL | 0.000416 |
| AMDMVS | 0.000423 | | BOPTEXP | 0.000346 |
| PCEPI | 0.000236 | | ADPMNUSNERSA | 0.000288 |
| PCEPILFE | 0.000227 | | TTLCONS | 0.000013 |
| AMDMTI | 0.000019 | | | |
| AMDMUO | 0.000006 | | | |

Every one of these is usable as a tolerance: none of the sixteen is so noisy
that no useful bound exists for it.

### The tolerance, and why it is `3 * sqrt(2) * sd`

The comparison is between **two** independent 1,250-draw averages — ours and
MATLAB's. The difference of two such averages has variance `2 * sd^2`, so a
three-sigma bound on it is `3 * sqrt(2) * sd = 4.243 * sd`. A bound of `3 * sd`
would be right only if the published figure were exact, and it is not.

The headline additionally keeps a `0.01`pp floor, the precision the figure is
published to. The per-series impacts get **no** floor: four of the nine
published impacts for 2023-09-29 are smaller in magnitude than 0.01, so a flat
`abs=0.01` would pass on those series even if the port returned exactly zero.

### Gate results

```
.venv/bin/pytest tests/test_end_to_end.py -v      # 12 passed in 12:39
```

| Week | published | this port (seed 321) | deviation | tolerance | |
| --- | --- | --- | --- | --- | --- |
| 2023-09-29 | 2.0241867 | **2.015771** | 0.008416 | 0.034416 | PASS (0.24x) |
| 2023-10-06 | 2.3834663 | **2.399940** | 0.016474 | 0.021756 | PASS (0.76x) |

2023-09-29 also passes the plan's original `max(0.01, 3*sd)` rule and its flat
`abs=0.01` floor, so nothing about the headline rests on the `sqrt(2)`.

All nine per-series release impacts for 2023-09-29, in pp of the nowcast:

| series | published | this port | deviation | tolerance | ratio |
| --- | --- | --- | --- | --- | --- |
| DGORDER | -0.052702 | -0.052058 | 0.000644 | 0.005083 | 0.13 |
| DSPIC96 | -0.040846 | -0.042265 | 0.001419 | 0.004344 | 0.33 |
| HSN1F | -0.030640 | -0.031053 | 0.000413 | 0.001939 | 0.21 |
| PCEPI | 0.021788 | 0.021942 | 0.000154 | 0.001001 | 0.15 |
| PCEC96 | -0.014736 | -0.014670 | 0.000066 | 0.001833 | 0.04 |
| AMDMVS | -0.008788 | -0.008640 | 0.000148 | 0.001795 | 0.08 |
| PCEPILFE | -0.005922 | -0.006285 | 0.000363 | 0.000963 | 0.38 |
| AMDMTI | -0.000928 | -0.000852 | 0.000076 | 0.000081 | 0.94 |
| AMDMUO | -0.000358 | -0.000339 | 0.000019 | 0.000025 | 0.76 |

### Is the gate falsifiable?

A gate that cannot fail proves nothing, so the runner was mutated three ways and
the gate re-run against each. All three are the failure modes the plan names as
the first things to check after a miss.

| Mutation | headline | per-series impacts |
| --- | --- | --- |
| *(control — the real runner)* | pass, dev 0.008416 | 9/9 pass |
| Compare horizon 2 against the published horizon-1 table | pass | **7 of 9 fail** |
| Skip the 1,250 `S_update` draws; use the posterior-mean latents | **fail**, dev 0.040760 > 0.034416 | **3 of 9 fail** |
| Use the wrong "old" vintage for the week (09-20, not 09-22) | — | **caught**: 10 release rows, not 9 |

The headline alone would have missed the horizon mutation entirely. That is what
the per-series test is for.

### 2023-10-06 is not fully reproducible from this drop, and that is not a port bug

The 2023-10-06 headline reproduces. Its per-series table does not: five of the
seven impacts miss the measured Monte Carlo bound, the worst by 5.1x.

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

The gap is pinned with two-sided bounds rather than skipped, so that the day
somebody obtains the real 2023-10-06 estimate file the test fails and says to
promote the week into the gate.

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
