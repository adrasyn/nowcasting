# Nowcast v3 — NY Fed Staff Nowcast 2.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the NY Fed Staff Nowcast 2.0 (Bayesian DFM with stochastic volatility and outlier states) from MATLAB to Python, refit it to Australian data, and publish it on nowcast.wlsn.me alongside v1 and v2.

**Architecture:** A new `nowcasting_v3/` Python package holds a faithful port of the NY Fed model engine, validated against the vendored MATLAB via Octave-generated fixtures. The engine is data-agnostic; an Australian panel spec and ABS/RBA fetchers feed it. Estimation runs quarterly and is expensive; the weekly job loads stored parameters and produces only the nowcast, density and news decomposition. Output reaches the site the same way v1 and v2 do — JSON files under `data/`, read at build time by Next.js.

**Tech Stack:** Python 3.11+, numpy, scipy, pandas, pytest. GNU Octave (fixture generation only, never production). Existing: Next.js 15, Tailwind v4, Recharts, GitHub Actions.

## Global Constraints

- **Python 3.11 or newer.** The system Python here is 3.9.6 — install a newer one. Do not target 3.9.
- **The vendored MATLAB is read-only.** `nowcasting_v3/nyfed_matlab/` is byte-identical to the NY Fed drop. Never edit it. Same rule as `nowcasting_v2/rba_paper/`.
- **Bit-exact RNG reproduction against MATLAB is impossible.** MATLAB's `rng(321)` plus `mvnrnd`/`gamrnd`/`betarnd`/`mnrnd` cannot be matched draw-for-draw by numpy. All testing follows the two-tier rule below. Any task that claims "matches MATLAB exactly" for a stochastic function is wrong.
- **Two-tier test rule.** Tier 1 (deterministic functions): must match Octave fixtures to `rtol=1e-10`. Tier 2 (stochastic functions): test the conditional distribution's moments against analytic values, plus an end-to-end posterior-mean check within Monte Carlo error. Never assert exact equality on a draw.
- **Never commit** `Estimates_*.mat` (21MB) or `.venv/`. Add to `.gitignore` in Task 0. **Test fixtures are the exception and MUST be committed** (Task 3, Step 2b): CI has no Octave and cannot regenerate them, so gitignoring them would silently skip every Tier 1 test in Actions. They are test inputs, not build output. Keep the directory under 5MB.
- **Unwrapping fixture scalars: use `.item()`, never bare `float()`/`int()`.** The fixtures store most scalars as `(1,1)` arrays, and NumPy 2 raises `TypeError` when converting any array with `ndim > 0` to a Python scalar. `published__*` and `horizon` are 0-d and convert fine, but do not rely on knowing which is which — `.item()` handles both, and unlike `.ravel()[0]` it raises on a multi-element array instead of silently taking the first entry.
- **Model dimensions for the US reference panel:** `n=31`, `n_f=5`, `p_f=4`, `p_e=1`, 3 quarterly series, `n_state=73`, `n_param=390`. These are assertable constants in tests.
- **The site contract is JSON only.** Pipelines and site communicate through `data/*.json`. No Python imports from the site, no site imports from Python.
- **Follow v2 conventions:** package at `nowcasting_v3/`, outputs named `data/latest_v3.json` etc., a `/v3` preview page before any main-page design work.

## Model ownership

Each task is tagged with the model that should execute it. The rule behind the tags:

- **Fable 5** — where a wrong answer looks right and the test is weak. Stochastic samplers, priors, the maths derivation, and any failed-reproduction debugging.
- **Opus 5** — exacting translation where the MATLAB is the spec and a Tier 1 fixture will catch an error. Also orchestration and review.
- **Sonnet 5** — mechanical work with a clear spec and a strong test, plus all site and pipeline glue.

Run the numerical port at `xhigh` effort regardless of model. Drop to `high` for glue and `low` for docs.

---

## Program map — five plans

This document fully specifies **Plan A** only. Plans B–E are scoped here but not yet written to task level, because Plan A's output determines their shape (the engine's Python interfaces determine the data contract; the panel design determines the fetchers). Write each one when its predecessor's gate passes.

| Plan | Deliverable | Gate to pass | Lead model |
|---|---|---|---|
| **A. Engine port** | `nowcasting_v3/nyfed/` reproduces the NY Fed model on US data | Tier 1 fixtures pass; published 2023-09-29 and 2023-10-06 nowcasts reproduced to ±0.01pp | Opus 5, Fable 5 on Tasks 6–7 |
| **B. Australian panel** | `model_spec_AU.csv` + ABS/RBA fetchers + `initval` seed | Panel builds to a complete monthly matrix back to at least 1990 | Fable 5 designs, Sonnet 5 builds |
| **C. Backtest** | Real-time vintage backtest, coverage check on the posterior bands | Bands achieve stated coverage, or the failure is documented as v2's was | Opus 5 |
| **D. Emit + site** | `data/*_v3.json`, types, `/v3` page, release-impact table | Page renders live numbers; `npm run build` and e2e pass | Sonnet 5 |
| **E. CI split** | Quarterly estimate job + weekly nowcast job | A full weekly cycle runs green in Actions | Opus 5 |

**Plan A is the whole risk.** Everything downstream assumes the engine is correct. Do not start Plan B before Plan A's gate passes.

### Why Plan A comes with a fixture generator

The four `.mat` files in the drop give an end-to-end target, but nothing intermediate. If the port's nowcast is wrong by 0.4pp, an end-to-end test tells you *that* but not *where* — and finding it by inspection across 2,400 lines is the most expensive failure mode in this project.

Octave fixes this. Octave cannot run the model in production (it lacks `datetime`, which `example_*.m`, `load_spec.m` and `summarize_data.m` all use, and it is not available in CI). But the **numerical core uses no `datetime` at all** — `Kalman_filter.m`, `fast_smoother.m`, `simulate_SSM.m`, `simulation_smoother.m`, `construct_SSM.m`, `construct_prior.m`, `map_parameter.m`, `vec_parameter.m` and the four `update_*.m` files are plain matrix code. Octave runs those, and its `statistics` package supplies `mvnrnd`, `gamrnd`, `betarnd` and `mnrnd`.

So: **Octave is a test oracle, not a runtime.** It turns a weak end-to-end check into per-function exact checks, which is what lets Sonnet safely own the mechanical half of the port. Task 0 verifies this claim before anything depends on it.

---

## File structure

```
nowcasting_v3/
  pyproject.toml              # package metadata, deps, pytest config
  README.md                   # what this is, how to run it, the Octave oracle
  nyfed/
    __init__.py
    linalg.py                 # symmetrize, spd_solve, spd_inv, spd_logdet
    rng.py                    # mvnrnd, gamrnd, betarnd, mnrnd_rows on a numpy Generator
    spec.py                   # ModelSpec dataclass, load_spec
    settings.py               # GibbsSettings dataclass
    parameters.py             # Params dataclass, vec_parameter, map_parameter
    ssm.py                    # StateSpace dataclass, kalman_filter, fast_smoother,
                              #   simulate_ssm, simulation_smoother, compute_lrv
    model.py                  # construct_ssm, construct_prior
    updates.py                # update_vol, update_scl, update_gam, update_ps
    gibbs.py                  # gibbs_update, s_update, gibbs_sampler
    nowcast.py                # point_nowcast, density_nowcast
  tools/
    gen_fixtures.m            # Octave: writes per-function fixtures
    matload.py                # .mat -> slim .npz for tests
  tests/
    conftest.py
    fixtures/                 # GITIGNORED - regenerate with tools/gen_fixtures.m
    test_linalg.py
    test_parameters.py
    test_spec.py
    test_ssm.py
    test_model.py
    test_updates.py
    test_gibbs.py
    test_nowcast.py
  nyfed_matlab/               # VENDORED, READ-ONLY (moved from nowcasting-v3/)
```

Module boundaries follow the MATLAB directory split, so any reviewer can hold one Python file and one MATLAB file side by side. That correspondence is the single most useful property of this layout — do not "improve" it by regrouping.

---

## Task 0: Scaffold, vendor the MATLAB, prove the Octave oracle

**Model: Opus 5.** The Octave feasibility check is the plan's load-bearing assumption; verify it before anything depends on it.

**Files:**
- Create: `nowcasting_v3/pyproject.toml`, `nowcasting_v3/README.md`, `nowcasting_v3/nyfed/__init__.py`, `nowcasting_v3/tools/gen_fixtures.m`, `nowcasting_v3/tools/matload.py`, `nowcasting_v3/tests/conftest.py`
- Move: `nowcasting-v3/nyfed-original-code/` -> `nowcasting_v3/nyfed_matlab/`
- Modify: `.gitignore`

- [ ] **Step 1: Rename the folder and vendor the MATLAB**

```bash
cd /Users/James/Documents/Claude/Projects/nowcasting
mkdir -p nowcasting_v3
git mv nowcasting-v3/nyfed-original-code nowcasting_v3/nyfed_matlab 2>/dev/null \
  || mv nowcasting-v3/nyfed-original-code nowcasting_v3/nyfed_matlab
mv nowcasting-v3/NYFed-Staff-Nowcast_technical-paper.pdf nowcasting_v3/
find nowcasting_v3 -name .DS_Store -delete
rmdir nowcasting-v3
```

- [ ] **Step 2: Add gitignore entries**

Append to `.gitignore`:

```
# v3 (NY Fed port): the 21MB estimates blob, venv, caches.
# NOTE: tests/fixtures/ is ignored only until Task 3, which commits the
# fixtures and removes the line below. CI has no Octave and cannot
# regenerate them, so they are test inputs, not build output.
/nowcasting_v3/nyfed_matlab/Estimates_*.mat
/nowcasting_v3/tests/fixtures/
/nowcasting_v3/.venv/
/nowcasting_v3/**/__pycache__/
```

- [ ] **Step 3: Install Octave and confirm the numerical core loads**

```bash
brew install octave
octave --eval "pkg load statistics; disp('statistics ok')"
```

Expected: prints `statistics ok`. If the `statistics` package is missing, run `octave --eval "pkg install -forge statistics"` first.

- [ ] **Step 4: Prove the oracle — run one core function in Octave**

Write `nowcasting_v3/tools/probe.m`:

```matlab
% Probe: can Octave run the numerical core? No datetime anywhere below.
addpath('../nyfed_matlab/functions/general')
addpath('../nyfed_matlab/functions/model')
pkg load statistics
rand('state', 321); randn('state', 321);

% Minimal well-posed SSM: 2 series, 3 states, 20 periods
N = 2; M = 3; K = 3; T = 20;
SSM = struct();
SSM.D = zeros(N,1);
SSM.H = [1 0 0; 0 1 0];
SSM.Sigma_eps = 1e-4*eye(N);
SSM.C = zeros(M,1);
SSM.F = 0.5*eye(M);
SSM.G = eye(M);
SSM.Sigma_eta = eye(K);
SSM.mu_1 = zeros(M,1);
SSM.Sigma_1 = eye(M);
Y = randn(N, T);
Y(1, 5) = NaN;   % exercise the missing-data branch

[ll, pred, filt] = Kalman_filter(Y, SSM);
printf('loglik = %.12f\n', ll);
save('-v7', 'probe_out.mat', 'Y', 'SSM', 'll', 'pred', 'filt');
```

Run:

```bash
cd nowcasting_v3/tools && octave probe.m
```

Expected: prints a finite `loglik` and writes `probe_out.mat`.

**If this fails**, stop and report before continuing. The likely culprit is `linsolve(S, eye(k), option)` with the `SYM`/`POSDEF` options struct. If Octave rejects it, patch **a copy** of `Kalman_filter.m` under `tools/octave_shims/` that substitutes `S \ eye(k)` — never edit the vendored original — and note in the README that the shim exists and why. If Octave cannot be made to work at all, escalate: the fallback is end-to-end-only testing, which shifts Tasks 3–5 from Sonnet 5 to Opus 5 and Tasks 6–7 to Fable 5 at `max` effort.

- [ ] **Step 5: Create the Python package**

`nowcasting_v3/pyproject.toml`:

```toml
[project]
name = "nowcasting-v3"
version = "0.1.0"
description = "NY Fed Staff Nowcast 2.0, ported to Python and refitted to Australian data"
requires-python = ">=3.11"
dependencies = ["numpy>=2.0", "scipy>=1.14", "pandas>=2.2"]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-xdist>=3.6"]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = [
  "fixtures: requires Octave-generated fixtures (skipped if absent)",
  "slow: multi-minute Gibbs runs",
]

[tool.setuptools.packages.find]
include = ["nyfed*"]
```

`nowcasting_v3/nyfed/__init__.py`:

```python
"""Python port of the New York Fed Staff Nowcast 2.0.

Reference implementation: ``nyfed_matlab/`` (vendored, read-only).
Almuzara, Baker, O'Keeffe & Sbordone (2023).
"""

__all__ = []
```

- [ ] **Step 6: Set up the environment and confirm it is clean**

```bash
cd nowcasting_v3
python3.11 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest --collect-only
```

Expected: pytest runs and collects 0 tests without error.

- [ ] **Step 7: Write the fixture loader**

`nowcasting_v3/tests/conftest.py`:

```python
from pathlib import Path

import numpy as np
import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    """Load an Octave-generated fixture as a dict of arrays.

    Fixtures are gitignored. Regenerate with:
        cd nowcasting_v3/tools && octave gen_fixtures.m
    """
    path = FIXTURE_DIR / f"{name}.npz"
    if not path.exists():
        pytest.skip(f"fixture {name} absent - run tools/gen_fixtures.m")
    return dict(np.load(path, allow_pickle=False))


@pytest.fixture
def fixture():
    return load_fixture
```

- [ ] **Step 8: Commit**

```bash
git add -A nowcasting_v3 .gitignore
git rm -r --cached nowcasting-v3 2>/dev/null || true
git commit -m "feat(v3): scaffold Python package, vendor NY Fed MATLAB, prove Octave oracle"
```

---

## Task 1: Linear algebra primitives

**Model: Sonnet 5.** Small, exactly specified, exactly testable.

**Files:**
- Create: `nowcasting_v3/nyfed/linalg.py`
- Test: `nowcasting_v3/tests/test_linalg.py`

**Interfaces:**
- Consumes: nothing
- Produces: `symmetrize(A) -> np.ndarray`, `spd_solve(A, B) -> np.ndarray`, `spd_inv(A) -> np.ndarray`, `spd_logdet(A) -> float`

These replace MATLAB's `linsolve(A, eye(k), struct('SYM',true,'POSDEF',true))` and `log(det(A))`.

- [ ] **Step 1: Write the failing test**

`nowcasting_v3/tests/test_linalg.py`:

```python
import numpy as np
import pytest

from nyfed.linalg import spd_inv, spd_logdet, spd_solve, symmetrize


def test_symmetrize_averages_with_transpose():
    a = np.array([[1.0, 2.0], [4.0, 3.0]])
    assert np.allclose(symmetrize(a), [[1.0, 3.0], [3.0, 3.0]])


def test_spd_inv_matches_dense_inverse():
    rng = np.random.default_rng(0)
    x = rng.standard_normal((6, 6))
    a = x @ x.T + 6 * np.eye(6)
    assert np.allclose(spd_inv(a), np.linalg.inv(a), rtol=1e-12)


def test_spd_inv_returns_exactly_symmetric():
    rng = np.random.default_rng(1)
    x = rng.standard_normal((5, 5))
    a = x @ x.T + 5 * np.eye(5)
    out = spd_inv(a)
    assert np.array_equal(out, out.T)


def test_spd_solve_matches_dense_solve():
    rng = np.random.default_rng(2)
    x = rng.standard_normal((4, 4))
    a = x @ x.T + 4 * np.eye(4)
    b = rng.standard_normal((4, 3))
    assert np.allclose(spd_solve(a, b), np.linalg.solve(a, b), rtol=1e-12)


def test_spd_logdet_matches_slogdet():
    rng = np.random.default_rng(3)
    x = rng.standard_normal((7, 7))
    a = x @ x.T + 7 * np.eye(7)
    assert spd_logdet(a) == pytest.approx(np.linalg.slogdet(a)[1], rel=1e-12)


def test_spd_logdet_survives_tiny_determinant():
    """log(det(A)) underflows here; the Cholesky form must not."""
    a = 1e-40 * np.eye(30)
    assert np.isfinite(spd_logdet(a))
    assert spd_logdet(a) == pytest.approx(30 * np.log(1e-40), rel=1e-12)


def test_spd_inv_handles_zero_dimension():
    """All-missing periods give a 0x0 system; it must not raise."""
    out = spd_inv(np.zeros((0, 0)))
    assert out.shape == (0, 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd nowcasting_v3 && .venv/bin/pytest tests/test_linalg.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'nyfed.linalg'`

- [ ] **Step 3: Write the implementation**

`nowcasting_v3/nyfed/linalg.py`:

```python
"""Symmetric positive-definite linear algebra.

Ports MATLAB's ``linsolve(A, B, struct('SYM',true,'POSDEF',true))`` and
replaces ``log(det(A))`` with a Cholesky log-determinant, which does not
underflow for the ill-conditioned prediction MSEs this model produces.
"""

from __future__ import annotations

import numpy as np
from scipy.linalg import cho_factor, cho_solve


def symmetrize(a: np.ndarray) -> np.ndarray:
    """Return (A + A') / 2. MATLAB: the ``symmetrize`` inline handle."""
    return (a + a.T) / 2.0


def spd_solve(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Solve A X = B for symmetric positive-definite A."""
    if a.shape[0] == 0:
        return np.zeros((0, b.shape[1] if b.ndim > 1 else 0))
    return cho_solve(cho_factor(symmetrize(a), lower=True), b)


def spd_inv(a: np.ndarray) -> np.ndarray:
    """Invert a symmetric positive-definite matrix, returning an exactly
    symmetric result. MATLAB: ``linsolve(A, eye(k), option)``."""
    k = a.shape[0]
    if k == 0:
        return np.zeros((0, 0))
    out = cho_solve(cho_factor(symmetrize(a), lower=True), np.eye(k))
    return symmetrize(out)


def spd_logdet(a: np.ndarray) -> float:
    """log|A| for symmetric positive-definite A, via Cholesky."""
    if a.shape[0] == 0:
        return 0.0
    chol = np.linalg.cholesky(symmetrize(a))
    return float(2.0 * np.sum(np.log(np.diag(chol))))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd nowcasting_v3 && .venv/bin/pytest tests/test_linalg.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add nowcasting_v3/nyfed/linalg.py nowcasting_v3/tests/test_linalg.py
git commit -m "feat(v3): SPD linear algebra primitives with Cholesky logdet"
```

---

## Task 2: Parameter vector mapping and the model spec

**Model: Sonnet 5.** Pure index arithmetic with an exact fixture, plus CSV parsing that mirrors `load_spec.m`.

**Files:**
- Create: `nowcasting_v3/nyfed/parameters.py`, `nowcasting_v3/nyfed/spec.py`, `nowcasting_v3/nyfed/settings.py`
- Test: `nowcasting_v3/tests/test_parameters.py`, `nowcasting_v3/tests/test_spec.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `Params` dataclass with fields `mu (n,)`, `gamma_g (float)`, `Lambda (n,n_f)`, `Phi (n_f,n_f,p_f)`, `gamma_f (n_f,)`, `pi_f (n_f,)`, `phi (n,p_e)`, `gamma_e (n,)`, `pi_e (n,)`
  - `vec_parameter(params) -> np.ndarray` shape `(n_param,)`
  - `map_parameter(vec, dims) -> Params` where `dims = (n, n_f, p_f, p_e)`
  - `ModelSpec` dataclass with `series_id, series_name, frequency, units, transformation, category, units_transformed` (lists), `trend (n,)`, `blocks (n,n_f)`, `prior (n,)`, `block_names`, `category_names`
  - `load_spec(path) -> ModelSpec`
  - `GibbsSettings` dataclass: `n_gs=10000, n_burn=8000, n_init=50, n_thin=2, n_each=8, state_each=1`

**Two details that will bite if missed.** Both are ported behaviour, not improvements:

1. `map_parameter` reshapes `Phi` as `(n_f, n_f, p_f)` from a flat slice. MATLAB is column-major; numpy defaults to row-major. Every `reshape` in this module must pass `order="F"`.
2. `load_spec` **sorts all fields by frequency**, monthly before quarterly (`{'d','w','m','q','sa','a'}` order). Every downstream index — `isquart`, `i_now`, `Y_location` — assumes that order. Skipping the sort produces a model that runs and is wrong.

- [ ] **Step 1: Write the failing tests**

`nowcasting_v3/tests/test_parameters.py`:

```python
import numpy as np
import pytest

from nyfed.parameters import Params, map_parameter, vec_parameter

DIMS = (31, 5, 4, 1)  # the US reference panel


def _params(dims=DIMS):
    n, n_f, p_f, p_e = dims
    rng = np.random.default_rng(7)
    return Params(
        mu=rng.standard_normal(n),
        gamma_g=float(rng.standard_normal()),
        Lambda=rng.standard_normal((n, n_f)),
        Phi=rng.standard_normal((n_f, n_f, p_f)),
        gamma_f=rng.standard_normal(n_f),
        pi_f=rng.standard_normal(n_f),
        phi=rng.standard_normal((n, p_e)),
        gamma_e=rng.standard_normal(n),
        pi_e=rng.standard_normal(n),
    )


def test_n_param_matches_formula():
    n, n_f, p_f, p_e = DIMS
    expected = 1 + n * (1 + n_f + p_e + 2) + n_f * (n_f * p_f + 2)
    assert expected == 390
    assert vec_parameter(_params()).shape == (390,)


def test_roundtrip_is_lossless():
    original = _params()
    restored = map_parameter(vec_parameter(original), DIMS)
    for field in ("mu", "Lambda", "Phi", "gamma_f", "pi_f", "phi", "gamma_e", "pi_e"):
        assert np.array_equal(getattr(original, field), getattr(restored, field))
    assert original.gamma_g == restored.gamma_g


def test_phi_uses_fortran_order():
    """MATLAB is column-major. A C-order reshape transposes Phi's lag slices
    and the model still runs, silently wrong."""
    n, n_f, p_f, p_e = DIMS
    vec = np.arange(390, dtype=float)
    phi_block_start = n + 1 + n * n_f
    block = vec[phi_block_start : phi_block_start + n_f * n_f * p_f]
    got = map_parameter(vec, DIMS).Phi
    assert np.array_equal(got, block.reshape((n_f, n_f, p_f), order="F"))
    assert got[0, 1, 0] != got[1, 0, 0]


def test_field_order_is_mu_gamma_lambda_phi():
    n, n_f, p_f, p_e = DIMS
    p = _params()
    vec = vec_parameter(p)
    assert np.array_equal(vec[:n], p.mu)
    assert vec[n] == p.gamma_g
    assert np.array_equal(vec[n + 1 : n + 1 + n * n_f], p.Lambda.reshape(-1, order="F"))
```

`nowcasting_v3/tests/test_spec.py`:

```python
from pathlib import Path

import numpy as np

from nyfed.spec import load_spec

SPEC_PATH = Path(__file__).parents[1] / "nyfed_matlab" / "model_spec_FRED.csv"


def test_loads_the_us_reference_panel():
    spec = load_spec(SPEC_PATH)
    assert len(spec.series_id) == 31
    assert spec.blocks.shape == (31, 5)
    assert spec.block_names == ["Global", "Soft", "Nominal", "Labor", "COVID"]


def test_series_are_sorted_monthly_before_quarterly():
    """load_spec.m permutes by frequency. Every downstream index depends on it."""
    spec = load_spec(SPEC_PATH)
    freq = np.array(spec.frequency)
    quarterly = freq == "q"
    assert quarterly.sum() == 3
    assert not quarterly[:28].any()
    assert quarterly[28:].all()
    assert set(np.array(spec.series_id)[quarterly]) == {
        "PRS85006112", "A261RX1Q020SBEA", "GDPC1",
    }


def test_gdp_is_locatable_after_sorting():
    spec = load_spec(SPEC_PATH)
    i_now = spec.series_id.index("GDPC1")
    assert spec.frequency[i_now] == "q"
    assert spec.trend[i_now] == 1.0


def test_blocks_encode_all_three_loading_states():
    """load_spec.m recodes in this order: `==1 -> NaN` (free), then `>1 -> 1`
    (normalising). A 0 is left as 0 (excluded from the block).

    INDPRO's CSV row is Global=100, Soft=0, Nominal=0, Labor=0, COVID=1,
    so it exhibits all three states at once."""
    spec = load_spec(SPEC_PATH)
    i = spec.series_id.index("INDPRO")
    assert spec.blocks[i, 0] == 1.0          # 100 -> normalising loading
    assert spec.blocks[i, 1] == 0.0          # 0   -> excluded, stays 0
    assert np.isnan(spec.blocks[i, 4])       # 1   -> free loading


def test_block_recoding_order_does_not_double_convert():
    """`==1 -> NaN` runs before `>1 -> 1`. Reversing the two would turn every
    free loading into a normalising one and silently over-identify the model."""
    spec = load_spec(SPEC_PATH)
    free = np.isnan(spec.blocks)
    assert free.any()
    assert ((spec.blocks == 1.0) | (spec.blocks == 0.0) | free).all()


def test_monthly_percent_change_trend_is_scaled_down_by_twelve():
    spec = load_spec(SPEC_PATH)
    i = spec.series_id.index("GDPC1")        # quarterly pca, not rescaled
    assert spec.trend[i] == 1.0
    monthly_pch = [
        j for j, (f, t) in enumerate(zip(spec.frequency, spec.transformation))
        if f == "m" and t == "pch"
    ]
    assert all(spec.trend[j] == 0.0 for j in monthly_pch)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd nowcasting_v3 && .venv/bin/pytest tests/test_parameters.py tests/test_spec.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'nyfed.parameters'`

- [ ] **Step 3: Write the implementations**

Port `map_parameter.m`, `vec_parameter.m`, `load_spec.m` and `load_settings.m` into `parameters.py`, `spec.py` and `settings.py`. The MATLAB is the specification — read each file and translate it line by line. Every `reshape` takes `order="F"`. `load_spec` must reproduce, in this order: the six text field extractions, the `UnitsTransformed` string substitutions, the `Trend` division by 12 for `pch` rows, the `Blocks` recoding (`==1 -> NaN`, `>1 -> 1`), the `Prior` column, then the frequency permutation applied to **every** field.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd nowcasting_v3 && .venv/bin/pytest tests/test_parameters.py tests/test_spec.py -v`
Expected: 10 passed (4 in `test_parameters.py`, 6 in `test_spec.py`)

- [ ] **Step 5: Commit**

```bash
git add nowcasting_v3/nyfed/parameters.py nowcasting_v3/nyfed/spec.py \
        nowcasting_v3/nyfed/settings.py nowcasting_v3/tests/test_parameters.py \
        nowcasting_v3/tests/test_spec.py
git commit -m "feat(v3): parameter vectorisation, model spec loader, Gibbs settings"
```

---

## Task 3: The fixture generator

**Model: Opus 5.** Chooses what to capture. Getting this wrong makes every later task's tests hollow.

**Files:**
- Create: `nowcasting_v3/tools/gen_fixtures.m`, `nowcasting_v3/tools/matload.py`
- Test: `nowcasting_v3/tests/test_fixtures_present.py`

**Interfaces:**
- Consumes: `nyfed_matlab/` (read-only), `Estimates_2023_09_20.mat`, `data/Data_2023_09_*.mat`
- Produces: `tests/fixtures/{kalman_small,kalman_us,fast_smoother_us,construct_ssm_us,construct_prior_us,update_scl,update_vol_cond,nowcast_us}.npz`

Each fixture stores **inputs and outputs together**, so a Python test loads the input, runs the port, and compares to the stored output. Fixtures for stochastic functions store the *inputs and the posterior parameters*, never a draw.

- [ ] **Step 1: Write the fixture generator**

`nowcasting_v3/tools/gen_fixtures.m` — for each captured function, save every input argument and every output. Cover, at minimum:

- `kalman_small`: the Task 0 probe SSM. Exercises the missing-data branch on a system small enough to debug by hand.
- `kalman_us`: real `SSM` built from `Estimates_2023_09_20.mat`'s median parameters and mean latents, real `Y_new`. Exercises `n_state=73`, time-varying `H` and `Sigma_eta`, and the ragged edge.
- `fast_smoother_us`: same inputs, all three outputs (`disturbances`, `states`, `MSEs`).
- `construct_ssm_us`: `param`, `latent`, `restrict` in; `D, H, Sigma_eps, F, G, Sigma_eta, mu_1, Sigma_1` out. **This is the highest-value fixture in the set** — `construct_SSM.m` is where the block structure, the quarterly aggregation weights `[1 2 3 2 1]/9`, the `f_active` COVID masking and the state ordering all live, and an error in any of them is invisible end-to-end.
- `construct_prior_us`: `dims`, `m_Lambda` in; the full prior struct out.
- `update_scl`: `x`, `vals`, `probs` in; the **posterior weight matrix** out (add a line to a shimmed copy that returns `posteriors` before the `mnrnd` draw). Never store `s`.
- `update_vol_cond`: `x`, `sigma`, `gamma` in; the mixture `posteriors` out, same shim approach.
- `published_nowcasts`: the NY Fed's own published output, read from `nyfed_matlab/output/Update_2023_09_29.mat` and `Update_2023_10_06.mat`. Carries `published__2023_09_29 = 2.0241866715115893` and `published__2023_10_06 = 2.3834662755905036` (2023 Q4, annualised QoQ), plus the per-series news table if it can be decoded. **Task 9's gate has no target without this fixture.** Note `output.news_table` is a MATLAB `table` object and `output.date` a `datetime`; scipy cannot decode either, so the per-series impacts may not be extractable — if so, the gate runs on the headline alone and that limitation is recorded.
- `nowcast_us`: the full `point_nowcast` call from `example_nowcast.m` — `Y_old`, `Y_new`, `SSM_old`, `SSM_new`, `i_now`, `t_now` in; `nowcast`, `forecasts`, `news`, `weights` out. This is deterministic given the SSMs, so it is a Tier 1 fixture despite sitting at the end of the pipeline.

Save with `save('-v7', ...)` so `scipy.io.loadmat` can read it. Put any shimmed MATLAB under `tools/octave_shims/`; never modify `nyfed_matlab/`.

- [ ] **Step 2: Write the .mat -> .npz converter**

`nowcasting_v3/tools/matload.py` reads each generated `.mat` with `scipy.io.loadmat(..., squeeze_me=False, struct_as_record=False)`, flattens MATLAB structs to `name__field` keys, and writes `tests/fixtures/<name>.npz`. Keep it slim — extract only the arrays the tests name. The 21MB estimates blob must not become a 21MB fixture.

**Two size rules, both load-bearing (see Step 2b).**

1. **Use `np.savez_compressed`, never `np.savez`.** These arrays are highly structured — `H` is mostly zeros, `F` and `G` are block-diagonal — and compress by roughly an order of magnitude.
2. **Cap the time dimension of the US fixtures at the last 60 periods.** Uncompressed, `H` alone is `31 x 73 x T x 8` bytes, which at the full sample is over 7MB for one array in one fixture. A 60-period window still exercises time-varying `H` and `Sigma_eta`, the quarterly aggregation, the `f_active` COVID mask and the ragged edge — everything the tests actually assert. Slice `Y`, `H`, `Sigma_eta` and the latents to the same window and store the window's start index in the fixture so tests can align.

The `kalman_small` fixture stays at full length: it is small by construction and is the one you debug by hand.

- [ ] **Step 2b: Commit the fixtures — do not gitignore them**

This reverses the `.gitignore` line Task 0 added. That line was wrong, and the reason matters:

**CI has no Octave and never will.** If `tests/fixtures/` is gitignored, every `@pytest.mark.fixtures` test skips in GitHub Actions — which is every Tier 1 exactness check in the project. CI would run only the Tier 2 statistical tests and report green, and the entire safety net for the port would exist on one laptop. That is the opposite of what the fixtures are for.

Unlike `pipeline/tests/fixtures/` (gitignored, and regenerable by any CI run of the R pipeline), these fixtures are **not regenerable in CI** — reproducing them requires MATLAB or Octave plus the vendored code. They are test inputs, not derived build output.

```bash
cd /Users/James/Documents/Claude/Projects/nowcasting
# Remove the Task 0 line that ignores fixtures.
python3 - <<'EOF'
import pathlib
p = pathlib.Path(".gitignore")
s = p.read_text().replace("/nowcasting_v3/tests/fixtures/\n", "")
p.write_text(s)
EOF
du -sh nowcasting_v3/tests/fixtures/
```

The fixture directory must total **under 5MB** after compression and windowing. If it does not, shrink the window further before committing — do not commit a large binary blob and do not silently gitignore it again. Report the actual size in the commit message.

- [ ] **Step 3: Generate and verify**

```bash
cd nowcasting_v3/tools && octave gen_fixtures.m && python ../.venv/bin/../../.venv/bin/python matload.py
cd .. && ls -la tests/fixtures/
```

Expected: eight `.npz` files, total well under 5MB.

- [ ] **Step 4: Write the guard test**

`nowcasting_v3/tests/test_fixtures_present.py`:

```python
import pytest

EXPECTED = [
    "kalman_small", "kalman_us", "fast_smoother_us", "construct_ssm_us",
    "construct_prior_us", "update_scl", "update_vol_cond", "nowcast_us",
]


@pytest.mark.parametrize("name", EXPECTED)
def test_fixture_loads_and_is_non_empty(fixture, name):
    data = fixture(name)
    assert data, f"fixture {name} is empty"
```

- [ ] **Step 5: Run it**

Run: `cd nowcasting_v3 && .venv/bin/pytest tests/test_fixtures_present.py -v`
Expected: 8 passed (or 8 skipped on a machine without Octave — that is the intended behaviour)

- [ ] **Step 6: Commit**

```bash
git add nowcasting_v3/tools nowcasting_v3/tests/test_fixtures_present.py
git commit -m "feat(v3): Octave fixture generator and .mat to .npz converter"
```

---

## Task 4: Kalman filter and smoothers

**Model: Opus 5.** Exacting translation, but every line is pinned by a Tier 1 fixture.

**Files:**
- Create: `nowcasting_v3/nyfed/ssm.py`
- Test: `nowcasting_v3/tests/test_ssm.py`

**Interfaces:**
- Consumes: `nyfed.linalg.{symmetrize, spd_inv, spd_logdet}`
- Produces:
  - `StateSpace` dataclass: `D (N,) | (N,T)`, `H (N,M) | (N,M,T)`, `Sigma_eps (N,N) | (N,N,T)`, `C (M,) | (M,T-1)`, `F (M,M) | (M,M,T-1)`, `G (M,K) | (M,K,T-1)`, `Sigma_eta (K,K) | (K,K,T-1)`, `mu_1 (M,)`, `Sigma_1 (M,M)`
  - `kalman_filter(Y, ssm, *, need_loglik=False) -> KalmanResult` with `.loglik`, `.error (N,T)`, `.inv_mse (N,N,T)`, `.gain (M,N,T)`, `.filter_mu (M,T)`, `.filter_sigma (M,M,T)`
  - `fast_smoother(Y, ssm) -> SmootherResult` with `.m_errors (N,T)`, `.shocks (K,T-1)`, `.states (M,T)`, `.mses`
  - `simulate_ssm(ssm, T, rng) -> (Y_sim, states_sim, disturbances_sim)`
  - `simulation_smoother(Y, ssm, rng) -> (states, disturbances)`
  - `compute_lrv(Y, n_lag=None) -> np.ndarray`

**Three notes for the implementer.**

1. **`need_loglik` defaults to `False`, unlike the MATLAB.** `fast_smoother.m` calls `Kalman_filter` and discards the log-likelihood, but MATLAB computes it anyway — an `O(N^3)` determinant per period, 28,000 times over. Nothing in the Gibbs or nowcast path reads it. Skip it by default and keep the flag for testing.
2. **Time-varying dispatch is by array ndim, exactly as MATLAB dispatches on `size(...,3) > 1`.** Do not "simplify" by broadcasting everything to 3-D: the memory cost at `n_state=73` and `T~400` is real, and the `Sigma_eta` array is `(1+n_f+n)` square per period.
3. **The transition matrices are indexed at `t-1`, the measurement matrices at `t`.** MATLAB's loop updates `C, F, G, Sigma_eta` from index `t-1` and `H, Sigma_eps` from index `t`. An off-by-one here shifts the whole model by one month and still produces plausible output.

- [ ] **Step 1: Write the failing tests**

`nowcasting_v3/tests/test_ssm.py`:

```python
import numpy as np
import pytest

from nyfed.ssm import (
    StateSpace, compute_lrv, fast_smoother, kalman_filter, simulation_smoother,
)


def _ssm(d, prefix="SSM"):
    """Rebuild a StateSpace from a Task 3 fixture.

    Fixtures flatten MATLAB structs to `prefix__field`. `C` and `D` are absent
    from some fixtures because the MATLAB defaults them; pass None so the port
    applies the same default.
    """
    return StateSpace(
        D=d.get(f"{prefix}__D"), H=d[f"{prefix}__H"],
        Sigma_eps=d.get(f"{prefix}__Sigma_eps"), C=d.get(f"{prefix}__C"),
        F=d[f"{prefix}__F"], G=d[f"{prefix}__G"],
        Sigma_eta=d.get(f"{prefix}__Sigma_eta"), mu_1=d[f"{prefix}__mu_1"].ravel(),
        Sigma_1=d[f"{prefix}__Sigma_1"],
    )


def _idx(d, key):
    """Zero-based index array from a fixture's `*_py` companion key."""
    return d[key].ravel().astype(int)


@pytest.mark.fixtures
def test_kalman_matches_octave_on_small_system(fixture):
    """2 series, 3 states, 20 periods, one NaN cell. Small enough to debug by
    hand, and the same system Task 0 used to prove the Octave oracle."""
    d = fixture("kalman_small")
    got = kalman_filter(d["Y"], _ssm(d), need_loglik=True)
    assert got.loglik == pytest.approx(float(d["loglik"].item()), rel=1e-10)
    assert np.allclose(got.error, d["prediction__error"], rtol=1e-10, equal_nan=True)
    assert np.allclose(got.gain, d["prediction__gain"], rtol=1e-10, equal_nan=True)
    assert np.allclose(got.filter_mu, d["filter__mu"], rtol=1e-10)
    assert np.allclose(got.filter_sigma, d["filter__Sigma"], rtol=1e-10)


@pytest.mark.fixtures
def test_kalman_matches_octave_with_an_entirely_missing_period(fixture):
    """A period where every series is NaN. The filter must propagate the state
    through it without updating, and not produce NaNs downstream."""
    d = fixture("kalman_small")
    got = kalman_filter(d["Y_allmiss"], _ssm(d), need_loglik=True)
    assert got.loglik == pytest.approx(float(d["loglik_allmiss"].item()), rel=1e-10)
    assert np.allclose(got.error, d["prediction_allmiss__error"],
                       rtol=1e-10, equal_nan=True)
    assert np.allclose(got.filter_mu, d["filter_allmiss__mu"], rtol=1e-10)
    assert np.isfinite(got.filter_mu).all()


@pytest.mark.fixtures
def test_kalman_matches_octave_on_the_us_panel(fixture):
    """73 states, time-varying H and Sigma_eta, ragged edge, 60-period window."""
    d = fixture("kalman_us")
    got = kalman_filter(d["Y"], _ssm(d))
    assert np.allclose(got.error, d["prediction__error"], rtol=1e-10, equal_nan=True)
    assert np.allclose(got.inv_mse, d["prediction__invMSE"], rtol=1e-10, equal_nan=True)
    assert np.allclose(got.gain, d["prediction__gain"], rtol=1e-10, equal_nan=True)


@pytest.mark.fixtures
def test_transition_matrices_are_indexed_one_period_back(fixture):
    """Guards the t vs t-1 off-by-one: MATLAB indexes C/F/G/Sigma_eta at t-1 and
    H/Sigma_eps at t. Shifting either produces a plausible filtered path that is
    wrong by one month. filter_sub__mu is stored at full length."""
    d = fixture("kalman_us")
    got = kalman_filter(d["Y"], _ssm(d))
    assert np.allclose(got.filter_mu, d["filter_sub__mu"], rtol=1e-10)


@pytest.mark.fixtures
def test_filter_covariance_matches_at_the_subsampled_periods(fixture):
    """filter.Sigma is 73x73x60 and was stored at 10 periods to hold the fixture
    size cap. sub_t_py brackets both f_active transitions and the ragged edge."""
    d = fixture("kalman_us")
    got = kalman_filter(d["Y"], _ssm(d))
    assert np.allclose(got.filter_sigma[:, :, _idx(d, "sub_t_py")],
                       d["filter_sub__Sigma"], rtol=1e-10)


@pytest.mark.fixtures
def test_fast_smoother_matches_octave(fixture):
    d = fixture("fast_smoother_us")
    got = fast_smoother(d["Y"], _ssm(d))
    assert np.allclose(got.states, d["states"], rtol=1e-10)
    assert np.allclose(got.m_errors, d["disturbances__m_errors"], rtol=1e-10)
    assert np.allclose(got.shocks, d["disturbances__shocks"], rtol=1e-10)


@pytest.mark.fixtures
def test_smoother_mses_match_at_the_subsampled_periods(fixture):
    d = fixture("fast_smoother_us")
    got = fast_smoother(d["Y"], _ssm(d))
    t = _idx(d, "sub_t_py")
    ts = _idx(d, "sub_t_shocks_py")
    assert np.allclose(got.mses.states[:, :, t], d["MSEs_sub__states"], rtol=1e-10)
    assert np.allclose(got.mses.m_errors[:, :, t], d["MSEs_sub__m_errors"], rtol=1e-10)
    assert np.allclose(got.mses.shocks[:, :, ts], d["MSEs_sub__shocks"], rtol=1e-10)


def test_simulation_smoother_mean_converges_to_the_smoothed_state():
    """Tier 2. Durbin-Koopman draws are centred on the smoothed state, so the
    average of many draws must converge to fast_smoother's output."""
    rng = np.random.default_rng(11)
    n, m, t = 2, 2, 40
    ssm = StateSpace(
        D=np.zeros(n), H=np.eye(n), Sigma_eps=1e-2 * np.eye(n),
        C=np.zeros(m), F=0.7 * np.eye(m), G=np.eye(m), Sigma_eta=np.eye(m),
        mu_1=np.zeros(m), Sigma_1=np.eye(m),
    )
    y = rng.standard_normal((n, t))
    smoothed = fast_smoother(y, ssm).states
    draws = np.array([simulation_smoother(y, ssm, rng)[0] for _ in range(400)])
    assert np.abs(draws.mean(axis=0) - smoothed).max() < 0.15


def test_compute_lrv_recovers_a_known_long_run_variance():
    """AR(1) with rho=0.5, unit shocks: LRV = 1/(1-0.5)^2 = 4."""
    rng = np.random.default_rng(13)
    t = 20000
    y = np.zeros((1, t))
    eps = rng.standard_normal(t)
    for i in range(1, t):
        y[0, i] = 0.5 * y[0, i - 1] + eps[i]
    assert compute_lrv(y, n_lag=4)[0, 0] == pytest.approx(4.0, rel=0.15)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd nowcasting_v3 && .venv/bin/pytest tests/test_ssm.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'nyfed.ssm'`

- [ ] **Step 3: Write the implementation**

Port `Kalman_filter.m`, `fast_smoother.m`, `simulate_SSM.m`, `simulation_smoother.m` and `compute_LRV.m`. Translate line by line against the MATLAB; the fixtures will find any divergence. Use `spd_inv` where MATLAB uses `linsolve(S, eye(k), option)` and `spd_logdet` where it uses `log(det(S))`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd nowcasting_v3 && .venv/bin/pytest tests/test_ssm.py -v`
Expected: 9 passed

- [ ] **Step 5: Benchmark one filter+smoother pass**

```bash
cd nowcasting_v3 && .venv/bin/python -c "
import time, numpy as np
from tests.conftest import load_fixture
from nyfed.ssm import fast_smoother
d = load_fixture('fast_smoother_us')
# rebuild ssm as in the tests, then:
t0 = time.perf_counter()
for _ in range(10): fast_smoother(d['Y'], ssm)
print('per pass:', (time.perf_counter()-t0)/10, 's')
"
```

Record the number in the commit message. At 28,000 Gibbs iterations, a pass over 0.5s means an estimation run over four hours — that is the input to the Task 9 performance decision. Do not optimise yet.

- [ ] **Step 6: Commit**

```bash
git add nowcasting_v3/nyfed/ssm.py nowcasting_v3/tests/test_ssm.py
git commit -m "feat(v3): Kalman filter, fast smoother, simulation smoother, LRV"
```

---

## Task 5: State-space construction and the prior

**Model: Opus 5 for both.** *(Revised after Task 3. The original assignment sent `construct_prior` to Fable 5, on the reasoning that a wrong hyperparameter samples happily and is invisible. That was written before the fixtures existed. `construct_prior_us` turned out to pin all eighteen prior fields exactly at `rtol=1e-10`, so for the US dimensions this is now Tier 1 work with a complete oracle — Opus territory. The Fable case does not disappear, it moves: it belongs to Plan B, where the Australian panel changes `n` and `n_f` and the fixture stops protecting anything. Fable stays assigned to Tasks 6 and 7, where draws cannot be pinned at all.)*

**Files:**
- Create: `nowcasting_v3/nyfed/model.py`
- Test: `nowcasting_v3/tests/test_model.py`

**Interfaces:**
- Consumes: `nyfed.parameters.Params`, `nyfed.ssm.StateSpace`
- Produces:
  - `Restrict` dataclass: `Lambda (n,n_f)`, `Phi (n_f,n_f,p_f)`, `iota (n,)`, `f_active (n_f,T)`, `isquart (n,) bool`
  - `Latent` dataclass: `sigma (n_f+n, T)`, `s (n_f+n, T)`, `state (1+n_f+n, T) | None`
  - `InitVal` dataclass: `param: Params`, `latent: Latent` — the starting point for the sampler, ported from `initval.mat`
  - `construct_ssm(params, latent, restrict, var_init=None) -> StateSpace`
  - `construct_prior(dims, m_Lambda) -> Prior` dataclass

**The state ordering, written out.** Everything downstream indexes into it, so it belongs in a docstring and a test, not in the reader's head. With `n_quart > 0`:

| Block | Size | Contents |
|---|---|---|
| trend | `n_g_state = 5` | `g_t` and 4 lags |
| factors | `n_f_state = max(5, p_f) * n_f` | `f_t` and lags, stacked lag-major |
| monthly errors | `n_e_state = max(1, p_e) * (n - n_quart)` | `e_t` for monthly series |
| quarterly errors | `n_q_state = max(5, p_e) * n_quart` | `e_t` for quarterly series and 4 lags |

For the US panel: `5 + 25 + 28 + 15 = 73`.

Quarterly rows of `H` use the Mariano-Murasawa weights `[1, 2, 3, 2, 1] / 9`; monthly rows use `[1, 0, 0, 0, 0]`. **Those weights encode annualised quarterly growth.** They are correct for the US panel and must not be changed in this task. Re-deriving them for Australian QoQ is Plan B, Task B3 — see the note at the end of this document.

- [ ] **Step 1: Write the failing tests**

`nowcasting_v3/tests/test_model.py`:

```python
import numpy as np
import pytest

from nyfed.model import Latent, Restrict, construct_prior, construct_ssm
from nyfed.parameters import map_parameter

DIMS = (31, 5, 4, 1)


def _params(d):
    """Rebuild Params from the fixture's stored parameter vector.

    Using `param_vec` rather than the individual `param__*` arrays makes this
    a cross-check of Task 2's map_parameter as well: if the Fortran-order
    unpacking were wrong, every construct_ssm assertion below would fail.
    """
    return map_parameter(d["param_vec"].ravel(), DIMS)


def _latent(d, prefix="latent"):
    return Latent(sigma=d[f"{prefix}__sigma"], s=d[f"{prefix}__s"])


def _restrict(d):
    """f_active and isquart are stored as uint8; the port wants bool."""
    return Restrict(
        Lambda=d["restrict__Lambda"],
        Phi=d["restrict__Phi"],
        iota=d["restrict__iota"].ravel(),
        f_active=d["restrict__f_active"].astype(bool),
        isquart=d["restrict__isquart"].ravel().astype(bool),
    )


@pytest.mark.fixtures
def test_construct_ssm_matches_octave_on_every_matrix(fixture):
    d = fixture("construct_ssm_us")
    got = construct_ssm(_params(d), _latent(d), _restrict(d))
    for name in ("D", "H", "Sigma_eps", "F", "G", "Sigma_eta", "mu_1", "Sigma_1"):
        want = d[f"SSM__{name}"]
        assert np.allclose(np.reshape(getattr(got, name), want.shape), want,
                           rtol=1e-10), name


@pytest.mark.fixtures
def test_state_dimension_is_seventy_three_for_the_us_panel(fixture):
    """5 trend + max(5,p_f)*n_f=25 factor + (n-n_quart)=28 monthly error
    + max(5,p_e)*n_quart=15 quarterly error."""
    d = fixture("construct_ssm_us")
    got = construct_ssm(_params(d), _latent(d), _restrict(d))
    assert got.F.shape[0] == 73
    assert got.H.shape == (31, 73, 60)


@pytest.mark.fixtures
def test_quarterly_rows_carry_the_mariano_murasawa_weights(fixture):
    """Quarterly series load on 5 trend lags as [1,2,3,2,1]/9; monthly rows load
    on the current period only. These weights encode ANNUALISED quarterly growth
    and must not be changed here - see Plan B, task B3."""
    d = fixture("construct_ssm_us")
    restrict = _restrict(d)
    got = construct_ssm(_params(d), _latent(d), restrict)
    h0 = got.H[:, :, 0]
    isq = restrict.isquart
    expected_q = np.outer(restrict.iota[isq], np.array([1.0, 2, 3, 2, 1]) / 9)
    assert np.allclose(h0[isq, :5], expected_q, rtol=1e-10)
    assert np.allclose(h0[~isq, 1:5], 0.0)


@pytest.mark.fixtures
def test_covid_factor_is_masked_outside_the_pandemic_window(fixture):
    """f_active zeroes the COVID factor's column of H outside the window. The
    factor block starts at state index 5 (after the 5 trend states)."""
    d = fixture("construct_ssm_us")
    restrict = _restrict(d)
    got = construct_ssm(_params(d), _latent(d), restrict)
    i_cov = 4
    col = 5 + i_cov
    off = np.flatnonzero(~restrict.f_active[i_cov, :])
    on = np.flatnonzero(restrict.f_active[i_cov, :])
    assert off.size and on.size, "fixture window must contain both states"
    assert np.allclose(got.H[:, col, off[0]], 0.0)
    assert not np.allclose(got.H[:, col, on[0]], 0.0)


@pytest.mark.fixtures
def test_construct_prior_matches_octave(fixture):
    d = fixture("construct_prior_us")
    got = construct_prior(DIMS, d["m_Lambda"])
    for name in ("m_mu", "P_mu", "m_Lambda", "P_Lambda", "m_Phi", "P_Phi",
                 "m_phi", "P_phi"):
        want = d[f"prior__{name}"]
        assert np.allclose(np.reshape(getattr(got, name), want.shape), want,
                           rtol=1e-10), name
    for name in ("nu_g", "s2_g", "nu_f", "s2_f", "nu_e", "s2_e",
                 "a_f", "b_f", "a_e", "b_e"):
        assert float(np.ravel(getattr(got, name))[0]) == pytest.approx(
            float(d[f"prior__{name}"].item()), rel=1e-12), name


def test_prior_outlier_probability_encodes_one_outlier_per_two_years():
    """pi_mean = 1 - 1/(2*12), 20 pseudo-observations. If the Australian panel
    changes this it must be a deliberate, documented choice."""
    prior = construct_prior(DIMS, np.zeros((31, 5)))
    a_f, b_f = float(np.ravel(prior.a_f)[0]), float(np.ravel(prior.b_f)[0])
    assert a_f / (a_f + b_f) == pytest.approx(1 - 1 / 24)
    assert a_f + b_f == pytest.approx(20)
    assert (a_f, b_f) == (float(np.ravel(prior.a_e)[0]),
                          float(np.ravel(prior.b_e)[0]))


def test_prior_phi_shrinks_towards_a_random_walk_in_the_first_lag():
    prior = construct_prior(DIMS, np.zeros((31, 5)))
    assert np.allclose(prior.m_Phi[:, :, 0], np.eye(5))
    assert np.allclose(prior.m_Phi[:, :, 1:], 0.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd nowcasting_v3 && .venv/bin/pytest tests/test_model.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'nyfed.model'`

- [ ] **Step 3: Write the implementation**

Port `construct_SSM.m` and `construct_prior.m`. Note that `example_estimate.m` applies `prior.P_Phi = prior.P_Phi / 5` *after* calling `construct_prior` — keep that outside the function, as the MATLAB does, and record it in the estimation entry point in Task 7.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd nowcasting_v3 && .venv/bin/pytest tests/test_model.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add nowcasting_v3/nyfed/model.py nowcasting_v3/tests/test_model.py
git commit -m "feat(v3): state-space construction and prior, pinned to Octave fixtures"
```

---

## Task 6: The four conditional updaters

**Model: Opus 5.** *(Revised after inspecting Task 3's shims. The original assignment was Fable 5, because these functions are sampled from and no fixture can pin a draw. That turned out to be wrong: `tools/octave_shims/update_vol_cond.m` injects **both** random statements as arguments — `weights` replaces `mnrnd(1, posteriors)` and `utmp` replaces `randn(T+1,1)` — and returns every intermediate. Conditional on those two inputs the whole routine is deterministic, so `update_vol` is pinnable bit-exactly end to end, stage by stage. The genuinely unpinnable surface that remains is small: `update_gam` and `update_ps`, which are 26 and 23 lines of conjugate draws. Fable stays on Task 7, where `Gibbs_update.m` really cannot be pinned.)*

The original concern still describes the risk correctly, and is worth keeping in mind even with the oracle available. `update_vol` is a 10-component mixture approximation to a log chi-square; `update_scl` is a 100-point discrete posterior; both are drawn from, so no fixture can pin the output. The fixtures pin the *posterior weights*, which is the strongest available check and still leaves the draw mechanics unguarded.

**Files:**
- Create: `nowcasting_v3/nyfed/updates.py`, `nowcasting_v3/nyfed/rng.py`
- Test: `nowcasting_v3/tests/test_updates.py`

**Interfaces:**
- Consumes: `nyfed.linalg`, `nyfed.ssm`
- Produces:
  - `rng.py`: `mvnrnd(mean, cov, rng)`, `gamrnd(shape, scale, rng)`, `betarnd(a, b, rng)`, `mnrnd_rows(probs, rng) -> (T,) int` — vectorised inverse-CDF row sampling, replacing MATLAB's `mnrnd(1, posteriors)`
  - `updates.py`:
    - `update_vol(x, sigma, gamma, mean_prior=0.0, var_prior=1e6, rng=None, *, weights=None, innovations=None, return_stages=False)` -> `(T,)` updated volatility path.

      **`weights` and `innovations` are the injection seam that makes this function Tier 1.** They correspond exactly to the two statements `tools/octave_shims/update_vol_cond.m` replaced with arguments: `weights` is the `(T, 10)` one-hot mixture draw that MATLAB takes with `mnrnd(1, posteriors)`, and `innovations` is the `(T+1,)` sequence MATLAB draws with `randn(T+1, 1)`. When either is `None` the function draws it from `rng`, which is the production path. When both are supplied the routine is fully deterministic and must reproduce Octave bit-for-bit.

      `return_stages=True` returns a `VolStages` dataclass carrying every intermediate the shim returns, in its order: `posteriors`, `mean_t`, `vars_t`, `y_t`, `x1_KF`, `p1_KF`, `x2_KF`, `p2_KF`, `ln_sigmasq`, `sigma`. Stage-by-stage comparison is what localises a mismatch to one line instead of one function.
    - `update_scl(x, vals, probs, rng=None, *, return_posteriors=False)` -> `(T,)` draw, or the `(T, n_s)` posterior when `return_posteriors=True`
    - `update_gam(x, nu_prior, s2_prior, rng) -> (N,)`
    - `update_ps(x, a_prior, b_prior, rng) -> (N,)`

    `return_posteriors` is part of the interface, not a debugging hook: it is the only exact check available on this module, because everything else here is a draw.

**Watch these four.**

1. **MATLAB's `gamrnd(a, b)` takes shape and *scale*.** numpy's `Generator.gamma(shape, scale)` matches. `update_gam` returns `1/sqrt(gamrnd(nu/2, 2/(nu*s2)))` — an inverse-gamma draw expressed through a gamma. Do not "simplify" it into `scipy.stats.invgamma`; the parameterisations differ and the error is silent.
2. **`update_scl` sets the posterior to the prior wherever the data is missing** (`posteriors(isnan(posteriors)) = probs_rep(...)`). NaN inputs are normal here — the series is missing that month. Drop this branch and every ragged-edge month gets a garbage outlier draw.
3. **`update_vol` adds a floor: `log(x.^2 + 1e-4)`.** Not cosmetic — without it, an exact zero residual sends the log to `-inf`.
4. **The mixture constants are 10 hard-coded triples** (Omori, Chib, Shephard & Nakajima 2007). Transcribe them from the MATLAB and assert their sum-to-one in a test; do not retype them from the paper.

- [ ] **Step 1: Write the failing tests**

`nowcasting_v3/tests/test_updates.py`:

```python
import numpy as np
import pytest

from nyfed.rng import mnrnd_rows
from nyfed.updates import (
    KSC_MEANS, KSC_PROBS, KSC_STDVS, update_gam, update_ps, update_scl, update_vol,
)

STAGES = ("posteriors", "mean_t", "vars_t", "y_t",
          "x1_KF", "p1_KF", "x2_KF", "p2_KF", "ln_sigmasq")


def test_ksc_mixture_probabilities_sum_to_one():
    """Omori, Chib, Shephard & Nakajima (2007), 10-component approximation to
    log chi-square with 1 df. Transcribe from update_vol.m, not the paper."""
    assert len(KSC_PROBS) == len(KSC_MEANS) == len(KSC_STDVS) == 10
    assert KSC_PROBS.sum() == pytest.approx(1.0, abs=1e-12)


@pytest.mark.fixtures
@pytest.mark.parametrize("suffix", ["", "_miss"])
def test_update_vol_reproduces_octave_stage_by_stage(fixture, suffix):
    """Tier 1. With the mixture draw and the innovations injected, update_vol is
    fully deterministic, so every intermediate must match - not just the final
    path. A stage-level assert says WHICH line diverged."""
    d = fixture("update_vol_cond")
    got = update_vol(
        d[f"x{suffix}"].ravel(), d["sigma_in"].ravel(),
        float(d["gamma"].item()),
        mean_prior=float(d["mean_prior"].item()),
        var_prior=float(d["var_prior"].item()),
        weights=d[f"weights{suffix}"], innovations=d["utmp"].ravel(),
        return_stages=True,
    )
    for name in STAGES:
        want = d[f"{name}{suffix}"] if f"{name}{suffix}" in d else d[name]
        assert np.allclose(np.reshape(getattr(got, name), want.shape), want,
                           rtol=1e-10), f"{name}{suffix}"
    assert np.allclose(got.sigma, d[f"sigma_out{suffix}"].ravel(), rtol=1e-10)


@pytest.mark.fixtures
@pytest.mark.parametrize("suffix", ["", "_miss"])
def test_update_scl_posterior_weights_match_octave(fixture, suffix):
    d = fixture("update_scl")
    got = update_scl(d[f"x{suffix}"].ravel(), d["vals"].ravel(), d["probs"].ravel(),
                     return_posteriors=True)
    assert np.allclose(got, d[f"posteriors{suffix}"], rtol=1e-10)


def test_update_scl_falls_back_to_the_prior_where_data_is_missing():
    """Missing months are normal on the ragged edge. update_scl.m sets the
    posterior to the prior there; without that branch every missing month draws
    from a garbage posterior."""
    rng = np.random.default_rng(21)
    vals = np.concatenate([[1.0], np.linspace(2, 5, 99)])
    probs = np.concatenate([[0.9], np.full(99, 0.1 / 99)])
    drawn = update_scl(np.full(5000, np.nan), vals, probs, rng)
    assert np.mean(drawn == 1.0) == pytest.approx(0.9, abs=0.02)


def test_update_scl_detects_a_large_outlier():
    rng = np.random.default_rng(22)
    vals = np.concatenate([[1.0], np.linspace(2, 5, 99)])
    probs = np.concatenate([[0.95], np.full(99, 0.05 / 99)])
    x = np.concatenate([np.zeros(99), [8.0]])
    drawn = np.array([update_scl(x, vals, probs, rng)[-1] for _ in range(200)])
    assert drawn.mean() > 2.0
    assert update_scl(x, vals, probs, rng)[0] == 1.0


def test_update_vol_survives_an_exact_zero_residual():
    """The 1e-4 floor inside log(x^2 + barr) is load-bearing: without it an exact
    zero residual sends the log to -inf."""
    rng = np.random.default_rng(24)
    out = update_vol(np.zeros(50), np.ones(50), 0.2, rng=rng)
    assert np.isfinite(out).all()


def test_update_vol_tracks_a_known_volatility_break():
    """Tier 2, production path. sigma is flat then 5x; the smoothed path must
    rise across the break."""
    rng = np.random.default_rng(23)
    t = 400
    truth = np.concatenate([np.full(t // 2, 1.0), np.full(t // 2, 5.0)])
    x = truth * rng.standard_normal(t)
    sigma = np.ones(t)
    for _ in range(40):
        sigma = update_vol(x, sigma, 0.2, rng=rng)
    assert sigma[:t // 2].mean() < 2.0
    assert sigma[t // 2:].mean() > 3.0


def test_update_gam_recovers_a_known_scale():
    """x_t = gamma * eps_t with gamma = 0.3, diffuse prior. Note update_gam
    returns 1/sqrt(gamrnd(...)) - an inverse-gamma expressed through a gamma.
    Do not substitute scipy.stats.invgamma; the parameterisations differ."""
    rng = np.random.default_rng(25)
    x = 0.3 * rng.standard_normal((20000, 1))
    draws = [update_gam(x, np.array([2.0]), np.array([0.001]), rng)[0]
             for _ in range(50)]
    assert np.mean(draws) == pytest.approx(0.3, rel=0.05)


def test_update_ps_recovers_a_known_probability():
    rng = np.random.default_rng(26)
    x = (rng.random((10000, 1)) < 0.8).astype(float)
    draws = [update_ps(x, np.array([1.0]), np.array([1.0]), rng)[0]
             for _ in range(50)]
    assert np.mean(draws) == pytest.approx(0.8, abs=0.02)


def test_mnrnd_rows_respects_the_row_probabilities():
    rng = np.random.default_rng(27)
    idx = mnrnd_rows(np.tile([0.1, 0.3, 0.6], (30000, 1)), rng)
    counts = np.bincount(idx, minlength=3) / len(idx)
    assert np.allclose(counts, [0.1, 0.3, 0.6], atol=0.01)


def test_mnrnd_rows_handles_differing_rows():
    rng = np.random.default_rng(28)
    probs = np.vstack([np.tile([1.0, 0.0], (500, 1)), np.tile([0.0, 1.0], (500, 1))])
    idx = mnrnd_rows(probs, rng)
    assert (idx[:500] == 0).all()
    assert (idx[500:] == 1).all()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd nowcasting_v3 && .venv/bin/pytest tests/test_updates.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'nyfed.rng'`

- [ ] **Step 3: Write the implementation**

Port `update_vol.m`, `update_scl.m`, `update_gam.m`, `update_ps.m` and the RNG shims. Give `update_vol` and `update_scl` a `return_posteriors` flag so the Tier 1 fixtures can check the conditional before the draw — that flag is the only exact check available on this module, so it is part of the interface, not a debugging aid.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd nowcasting_v3 && .venv/bin/pytest tests/test_updates.py -v`
Expected: 13 passed (the two fixture tests are parametrized over the clean and missing-data cases)

- [ ] **Step 5: Commit**

```bash
git add nowcasting_v3/nyfed/updates.py nowcasting_v3/nyfed/rng.py \
        nowcasting_v3/tests/test_updates.py
git commit -m "feat(v3): stochastic volatility, outlier, scale and probability updaters"
```

---

## Task 7: The Gibbs sampler

**Model: Fable 5.** `Gibbs_update.m` is 316 lines of conditional posteriors — `mu`, `gamma_g`, `Phi`, `phi`, `Lambda`, plus the volatility and outlier blocks — with restriction handling threaded through each. No fixture pins a draw. A transposed design matrix or a dropped prior-precision term gives a sampler that converges to the wrong posterior and looks entirely healthy while doing it. This is the single highest-risk file in the project.

**Files:**
- Create: `nowcasting_v3/nyfed/gibbs.py`
- Test: `nowcasting_v3/tests/test_gibbs.py`

**Interfaces:**
- Consumes: everything above
- Produces:
  - `gibbs_update(params, latent, Y, prior, restrict, rng) -> (Params, Latent)`
  - `s_update(params, latent, Y, restrict, rng) -> Latent`
  - `gibbs_sampler(Y, prior, restrict, initval, settings, rng, *, need_latents=False) -> GibbsResult` with `.params (n_param, n_gs)`, `.states`, `.sigmas`, `.ss`

**The single best test available here is conditional-posterior recovery on synthetic data.** Simulate from the model with known parameters, run the sampler, and check the posterior covers the truth. That catches a mis-specified conditional in a way no fixture can. Budget for it.

**Also note `t_skip` and `t_est`.** `Gibbs_update.m` computes `t_skip = p_e + 5*(n_quart>0)` and estimates only over `t_est`, which extends to the last period with any observation. Getting this window wrong silently changes the sample.

- [ ] **Step 1: Write the failing tests**

`nowcasting_v3/tests/test_gibbs.py`:

```python
import numpy as np
import pytest

from nyfed.gibbs import gibbs_sampler, gibbs_update, s_update
from nyfed.parameters import vec_parameter


@pytest.fixture
def synthetic():
    """A small DFM simulated from known parameters: n=6, n_f=1, p_f=1, p_e=1,
    T=600, no quarterly series, no SV (gamma fixed near zero)."""
    ...  # build and return (Y, true_params, restrict, initval, prior)


@pytest.mark.slow
def test_posterior_covers_the_true_loadings(synthetic):
    Y, truth, restrict, initval, prior = synthetic
    rng = np.random.default_rng(31)
    res = gibbs_sampler(Y, prior, restrict, initval,
                        _settings(n_gs=2000, n_burn=2000, n_thin=1), rng)
    lam = _extract(res.params, "Lambda")           # (n, n_f, n_gs)
    lo, hi = np.percentile(lam, [2.5, 97.5], axis=2)
    covered = ((truth.Lambda >= lo) & (truth.Lambda <= hi)).mean()
    assert covered >= 0.8


@pytest.mark.slow
def test_posterior_covers_the_true_factor_var_coefficient(synthetic):
    Y, truth, restrict, initval, prior = synthetic
    rng = np.random.default_rng(32)
    res = gibbs_sampler(Y, prior, restrict, initval,
                        _settings(n_gs=2000, n_burn=2000, n_thin=1), rng)
    phi = _extract(res.params, "Phi")[0, 0, :]
    lo, hi = np.percentile(phi, [2.5, 97.5])
    assert lo <= truth.Phi[0, 0, 0] <= hi


@pytest.mark.slow
def test_posterior_covers_the_true_idiosyncratic_ar(synthetic):
    Y, truth, restrict, initval, prior = synthetic
    rng = np.random.default_rng(33)
    res = gibbs_sampler(Y, prior, restrict, initval,
                        _settings(n_gs=2000, n_burn=2000, n_thin=1), rng)
    ar = _extract(res.params, "phi")               # (n, p_e, n_gs)
    lo, hi = np.percentile(ar, [2.5, 97.5], axis=2)
    assert ((truth.phi >= lo) & (truth.phi <= hi)).mean() >= 0.8


def test_restricted_loadings_never_move(synthetic):
    """Blocks fixed to 0 or to the normalising 1 must be identical in every draw."""
    Y, truth, restrict, initval, prior = synthetic
    rng = np.random.default_rng(34)
    res = gibbs_sampler(Y, prior, restrict, initval,
                        _settings(n_gs=50, n_burn=10, n_thin=1), rng)
    lam = _extract(res.params, "Lambda")
    fixed = ~np.isnan(restrict.Lambda)
    assert np.allclose(lam[fixed, :].std(axis=-1), 0.0)
    assert np.allclose(lam[fixed, 0], restrict.Lambda[fixed])


def test_two_runs_with_the_same_seed_are_identical(synthetic):
    """Reproducibility within the port. Not a claim about matching MATLAB."""
    Y, _, restrict, initval, prior = synthetic
    s = _settings(n_gs=20, n_burn=5, n_thin=1)
    a = gibbs_sampler(Y, prior, restrict, initval, s, np.random.default_rng(99))
    b = gibbs_sampler(Y, prior, restrict, initval, s, np.random.default_rng(99))
    assert np.array_equal(a.params, b.params)


def test_gibbs_update_preserves_parameter_vector_length(synthetic):
    Y, _, restrict, initval, prior = synthetic
    rng = np.random.default_rng(35)
    params, latent = gibbs_update(initval.param, initval.latent, Y, prior,
                                  restrict, rng)
    assert np.isfinite(vec_parameter(params)).all()
    assert latent.sigma.shape == initval.latent.sigma.shape


def test_s_update_leaves_sigma_untouched(synthetic):
    """S_update draws outlier indicators only; sigma is an input, not an output."""
    Y, _, restrict, initval, prior = synthetic
    rng = np.random.default_rng(36)
    out = s_update(initval.param, initval.latent, Y, restrict, rng)
    assert np.array_equal(out.sigma, initval.latent.sigma)
    assert out.s.shape == initval.latent.s.shape
```

Fill in `synthetic`, `_settings` and `_extract` concretely — the simulation is the test's whole value, so it must be real code, not a sketch.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd nowcasting_v3 && .venv/bin/pytest tests/test_gibbs.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'nyfed.gibbs'`

- [ ] **Step 3: Write the implementation**

Port `Gibbs_update.m`, `S_update.m` and `Gibbs_sampler.m`. Work block by block — `mu`, `gamma_g`, volatilities, outliers, `Phi`, `phi`, `Lambda` — and after each block, re-read the corresponding MATLAB and confirm the design matrix orientation and the prior-precision term by hand. Note that `Lambda` has two code paths: a joint update, and a factor-by-factor loop. Both are in the MATLAB; port both.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd nowcasting_v3 && .venv/bin/pytest tests/test_gibbs.py -v`
Expected: 7 passed (the `slow` ones take minutes)

- [ ] **Step 5: Commit**

```bash
git add nowcasting_v3/nyfed/gibbs.py nowcasting_v3/tests/test_gibbs.py
git commit -m "feat(v3): Gibbs sampler with posterior-recovery tests on synthetic data"
```

---

## Task 8: Point nowcast, density nowcast, news decomposition

**Model: Opus 5.** Deterministic given the SSMs and fully pinned by the `nowcast_us` fixture.

**Files:**
- Create: `nowcasting_v3/nyfed/nowcast.py`
- Test: `nowcasting_v3/tests/test_nowcast.py`

**Interfaces:**
- Consumes: `nyfed.ssm`, `nyfed.model`
- Produces:
  - `point_nowcast(Y_old, Y_new, ssm_old, ssm_new, i_now, t_now) -> PointNowcast` with `.nowcast (4, len(t_now))`, `.forecasts (N,T)`, `.news (N,T)`, `.weights (N,T,len(t_now))`
  - `density_nowcast(Y_new, ssm_new, i_now, t_now, rng) -> (len(t_now),)`
  - `news_table(result, spec, y_location, y_scale) -> pandas.DataFrame` with columns `series_id, series_name, forecast, actual, weight, impact`

**The four rows of `nowcast` are a decomposition, not four estimates.** Row 1 is old data with the old SSM, row 2 old data with the new SSM (isolating parameter revision), row 3 adds data revisions, row 4 adds new releases. The published nowcast is row 4; `row2 - row1` is the parameter-revision contribution and `row3 - row2` the data-revision contribution. `impact = (actual - forecast) * weight` is the per-release contribution, and it is the number the site's release-impact table displays.

- [ ] **Step 1: Write the failing tests**

`nowcasting_v3/tests/test_nowcast.py`:

```python
import numpy as np
import pytest

from nyfed.nowcast import density_nowcast, news_table, point_nowcast


@pytest.mark.fixtures
def test_point_nowcast_matches_octave(fixture):
    d = fixture("nowcast_us")
    got = point_nowcast(d["Y_old"], d["Y_new"], _ssm(d, "SSM_old"),
                        _ssm(d, "SSM_new"), int(d["i_now"].item()) - 1,
                        d["t_now"].ravel().astype(int) - 1)
    assert np.allclose(got.nowcast, d["nowcast"], rtol=1e-10)
    assert np.allclose(got.forecasts, d["forecasts"], rtol=1e-10, equal_nan=True)
    assert np.allclose(got.news, d["news"], rtol=1e-10, equal_nan=True)
    assert np.allclose(got.weights, d["weights"], rtol=1e-10, equal_nan=True)


@pytest.mark.fixtures
def test_impacts_and_revisions_sum_to_the_nowcast_change(fixture):
    """The decomposition identity: last week's nowcast + parameter revision
    + data revision + sum of release impacts = this week's nowcast."""
    d = fixture("nowcast_us")
    got = point_nowcast(d["Y_old"], d["Y_new"], _ssm(d, "SSM_old"),
                        _ssm(d, "SSM_new"), int(d["i_now"].item()) - 1,
                        d["t_now"].ravel().astype(int) - 1)
    released = ~np.isnan(got.news)
    impacts = ((got.news + got.forecasts) - got.forecasts) * got.weights[:, :, 0]
    total = (got.nowcast[1, 0] - got.nowcast[0, 0]) \
        + (got.nowcast[2, 0] - got.nowcast[1, 0]) \
        + np.nansum(impacts[released])
    assert total == pytest.approx(got.nowcast[3, 0] - got.nowcast[0, 0], abs=1e-8)


@pytest.mark.fixtures
def test_series_with_no_release_has_no_impact(fixture):
    d = fixture("nowcast_us")
    got = point_nowcast(d["Y_old"], d["Y_new"], _ssm(d, "SSM_old"),
                        _ssm(d, "SSM_new"), int(d["i_now"].item()) - 1,
                        d["t_now"].ravel().astype(int) - 1)
    unchanged = np.isnan(d["Y_new"]) | (d["Y_new"] == d["Y_old"])
    assert np.isnan(got.news[unchanged]).all()


@pytest.mark.fixtures
def test_news_table_columns_and_ordering(fixture):
    d = fixture("nowcast_us")
    got = point_nowcast(d["Y_old"], d["Y_new"], _ssm(d, "SSM_old"),
                        _ssm(d, "SSM_new"), int(d["i_now"].item()) - 1,
                        d["t_now"].ravel().astype(int) - 1)
    table = news_table(got, _spec(), d["Y_location"], d["Y_scale"])
    assert list(table.columns) == ["series_id", "series_name", "forecast",
                                   "actual", "weight", "impact"]
    assert table["impact"].abs().is_monotonic_decreasing


@pytest.mark.fixtures
def test_density_nowcast_is_centred_on_the_point_nowcast(fixture):
    """Tier 2: many density draws must average to the point estimate."""
    d = fixture("nowcast_us")
    rng = np.random.default_rng(41)
    t_now = d["t_now"].ravel().astype(int) - 1
    point = point_nowcast(d["Y_old"], d["Y_new"], _ssm(d, "SSM_old"),
                          _ssm(d, "SSM_new"), int(d["i_now"].item()) - 1, t_now)
    draws = np.array([density_nowcast(d["Y_new"], _ssm(d, "SSM_new"),
                                      int(d["i_now"].item()) - 1, t_now, rng)
                      for _ in range(500)])
    assert draws[:, 0].mean() == pytest.approx(point.nowcast[3, 0], abs=0.05)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd nowcasting_v3 && .venv/bin/pytest tests/test_nowcast.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'nyfed.nowcast'`

- [ ] **Step 3: Write the implementation**

Port `point_nowcast.m` and `density_nowcast.m`, and write `news_table` to reproduce the table `example_nowcast.m` prints, sorted by absolute impact so the site can take the top rows directly.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd nowcasting_v3 && .venv/bin/pytest tests/test_nowcast.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add nowcasting_v3/nyfed/nowcast.py nowcasting_v3/tests/test_nowcast.py
git commit -m "feat(v3): point nowcast, density nowcast, news decomposition"
```

---

## Task 9: End-to-end gate — reproduce the published US nowcasts

**Model: Opus 5 to run it; Fable 5 if it fails.** A mismatch here after every unit test passes is the hardest debugging class in the project, and the point at which to escalate rather than grind.

**Files:**
- Create: `nowcasting_v3/nyfed/run_us_reference.py`, `nowcasting_v3/tests/test_end_to_end.py`
- Modify: `nowcasting_v3/README.md`

- [ ] **Step 1: Write the reference runner**

`run_us_reference.py` reproduces `example_nowcast.m` in Python end to end: load the spec, load `Data_2023_09_22.mat` and `Data_2023_09_29.mat`, load the stored estimates, rebuild `param_old`/`param_new` from the posterior medians and the mean latents, run 1,250 `s_update` draws for each vintage, average, build both SSMs, then run `point_nowcast` and 1,250 `density_nowcast` draws. Print the nowcast, the revision decomposition and the news table.

- [ ] **Step 2: Write the gate test**

`nowcasting_v3/tests/test_end_to_end.py`:

```python
import pytest

from nyfed.run_us_reference import run_reference_week

# Expected values come from the Update_*.mat fixtures, never from memory.


@pytest.mark.slow
@pytest.mark.fixtures
@pytest.mark.parametrize("week", ["2023-09-29", "2023-10-06"])
def test_reproduces_the_published_nowcast(week, fixture):
    expected = float(fixture("published_nowcasts")[f"published__{week.replace('-', '_')}"])
    got = run_reference_week(week)
    assert got.nowcast == pytest.approx(expected, abs=0.01)


@pytest.mark.slow
@pytest.mark.fixtures
def test_reproduces_the_release_impacts(fixture):
    """Every series' impact must match, not just the total - a compensating pair
    of errors can leave the headline right while both components are wrong.

    HORIZON 1 ONLY. example_nowcast.m:174 linear-indexes an (n, T, 2) weights
    array with an (n, T) mask, so the published Weight/Impact columns cover the
    first t_now and nothing else. Comparing horizon 2 against them would compare
    our real numbers to MATLAB's dropped ones and pass or fail for no reason.
    """
    d = fixture("published_nowcasts")
    assert int(d["news_0929__horizon"]) == 1
    got = run_reference_week("2023-09-29")
    for series_id, impact in zip(d["news_0929__series_id"], d["news_0929__impact"]):
        assert got.impact_for(str(series_id), horizon=0) == pytest.approx(
            float(impact), abs=0.01
        )
```

- [ ] **Step 3: Run the gate**

Run: `cd nowcasting_v3 && .venv/bin/pytest tests/test_end_to_end.py -v -m slow`
Expected: 3 passed

**If the nowcast is out by more than 0.01pp:** do not start guessing. The Tier 1 fixtures already pin every deterministic function, so the divergence is in a stochastic path or in how the reference runner assembles inputs. Check, in order: the posterior-median parameter reconstruction, the `s_update` draw count and averaging, the `Y_location`/`Y_scale` standardisation, then `t_now` and `i_now` indexing (MATLAB is 1-based). Escalate to Fable 5 if that pass does not find it.

**The targets.** 2023 Q4, annualised QoQ: **2.0242** for the 2023-09-29 vintage and **2.3835** for 2023-10-06, taken from the drop's own `Update_*.mat`. If the per-series news table proved undecodable in Task 3, `test_reproduces_the_release_impacts` cannot run — skip it explicitly with a reason rather than deleting it, so the gap stays visible.

**Set the tolerance from measurement, not from my guess — do this before running the gate.**

The published figures came out of MATLAB with `rng(321)` and 1,250 averaged `S_update` draws. Our numpy RNG cannot reproduce that draw sequence, so the port converges to the same limit by a different path, with Monte Carlo error around it. Whether that error fits inside ±0.01pp is an empirical question that nobody has answered, and asserting a tolerance we have not measured would make this gate either falsely reassuring or falsely alarming.

So Task 9 gets a Step 0:

- [ ] **Step 0: Measure the seed-to-seed spread**

Run `run_reference_week("2023-09-29")` five times with five different seeds. Record the five nowcasts, their mean, and their standard deviation. Write all of it into the README.

Then set the gate tolerance to `max(0.01, 3 * measured_sd)` and state the chosen number and its basis in the test file. If `3 * sd` exceeds 0.01pp, the wider tolerance is the honest one — and the spread itself is a finding worth recording, because it bounds how reproducible any weekly published figure can be.

If the spread is so wide that no useful tolerance exists (say, over 0.1pp), stop and report it. That would mean the averaging is not damping the draws the way the design assumes, which is a model-level finding, not a porting bug — and it would matter for the live site, since it bounds what a weekly nowcast can claim.

**Note on tolerance.** The ±0.01pp floor is not arbitrary slack — `example_nowcast.m` averages 1,250 stochastic `s_update` draws, so even MATLAB does not reproduce itself exactly across seeds. Do not tighten this to an exact match; it cannot be met.

- [ ] **Step 4: Record the timing**

Time a full `gibbs_sampler` run at production settings (`n_gs=10000, n_burn=8000, n_thin=2`) on the US panel. Write the wall-clock into the README. This number decides Plan E: under 5 hours and the quarterly re-estimation fits a GitHub Actions job; over it and a self-hosted runner is required.

If the run is too slow, profile before optimising. The expected hotspot is `update_vol`'s inner recursion — `n_f + n = 36` series, each a T-length loop, 28,000 times — not the Kalman filter. Reach for numba on the measured hotspot only.

- [ ] **Step 5: Write the README and commit**

Document: what this package is, the Octave oracle and why it exists, the two-tier test rule, how to regenerate fixtures, the measured timings, and the standing rule that `nyfed_matlab/` is never edited.

```bash
git add nowcasting_v3/nyfed/run_us_reference.py \
        nowcasting_v3/tests/test_end_to_end.py nowcasting_v3/README.md
git commit -m "feat(v3): US reference reproduction gate - Plan A complete"
```

---

## Plan A gate

Plan A is complete when all of these hold. Do not begin Plan B before then.

- [ ] `pytest` passes with fixtures present, including `-m slow`
- [ ] The 2023-09-29 and 2023-10-06 nowcasts reproduce to ±0.01pp
- [ ] Every per-series release impact reproduces to ±0.01pp
- [ ] A full production-settings estimation run has been timed and recorded
- [ ] `nyfed_matlab/` is unmodified: `git log --oneline -- nowcasting_v3/nyfed_matlab` shows only the vendoring commit

---

## Plans B–E — scope only

Written to task level once Plan A's gate passes.

### Plan B: Australian panel — **Fable 5 designs, Sonnet 5 builds**

- **B1** Series selection. ABS/RBA replacements for the 31 FRED series. Several have no monthly Australian equivalent — JOLTS, ADP payrolls, monthly PCE, monthly real GDI, Empire State and Philly Fed. Expect 15–25 series. The Soft block leans on NAB and Westpac-MI, both already fetched by v1/v2.
- **B2** Block design and normalising loadings.

  **Read this before designing the blocks.** `construct_SSM.m:166` builds the `var_init` factor
  blocks as `n_f` contiguous 5x5 blocks, but the factor states are **lag-major**. So
  `state_group{1+i_f}` spans a mix of lags across factors, *not* factor `i_f`. Verified under
  Octave in Task 5's review: with `n_f=2` and factor 2 inactive at `t=1`,
  `diag(Sigma_1)(6:15) = [12 12 12 12 12 2 2 2 2 2]` — the tight initial prior lands on the
  higher lags of *both* factors, not on the inactive factor. The Python port reproduces this
  faithfully. Anyone reasoning about "the initial prior on the COVID factor" is reasoning about
  something the code does not do. Which series fixes each factor's scale (`100` in the spec CSV) is a modelling decision, not a translation. Also: whether a COVID block is still warranted for Australia, and over what window.
- **B3** **The quarterly aggregation weights.** `construct_ssm` uses `[1,2,3,2,1]/9`, the Mariano-Murasawa filter for *annualised* quarterly growth. Australian headline GDP is QoQ. Either re-derive the filter for QoQ or keep the model annualised internally and convert on emit. This is a short derivation with total consequence — Fable, and write the derivation into the docs.

  **Landmine, found in Task 5 and confirmed in the source.** `construct_SSM.m:131` pads the *quarterly* branch of `H` using `length(vec_m)*n_f`, where `length(vec_q)*n_f` is meant — the surrounding terms on that same line all use `vec_q`. It is harmless in the US model only because `vec_m = [1,0,0,0,0]` and `vec_q = [1,2,3,2,1]/9` are both length 5.

  **If B3 changes `vec_q` to a different length, this line silently mis-sizes the zero padding and `H` comes out wrong — or the assembly raises a dimension error far from the cause.** The Python port reproduces the bug faithfully, as it must to keep the fixture green. Whoever does B3 must decide deliberately whether to keep or correct it, and if correcting, must regenerate the affected fixtures. Do not discover this by debugging.
- **B4** `initval` construction. The MATLAB ships a 128KB `initval.mat` whose `param.Lambda` is also the prior mean for the loadings. An Australian panel needs its own, most likely PCA-seeded.
- **B5** Fetchers and panel assembly to a monthly matrix back to at least 1990, reusing v1/v2 patterns.

### Plan C: Backtest and calibration — **Opus 5**

Real-time vintage backtest, then a coverage check on the posterior bands. v2's 68% band achieved 41% coverage; these bands are a genuine posterior rather than an error-dispersion proxy, but that must be demonstrated, not assumed. If coverage fails, publish the track record instead of the interval, as v2 does.

### Plan D: Emit and site — **Sonnet 5**

`data/latest_v3.json`, `vintages_v3.json`, `indicators_v3.json`, `performance_v3.json`; types in `src/lib/types.ts`; loaders in `src/lib/data.ts` following the existing `readJsonOptional` feature-detect pattern; a `/v3` preview page modelled on `src/app/v2/page.tsx`. `deploy.yml` already triggers on `data/**`, so it needs no change.

The one genuinely new component is the **release-impact table** — per-series contribution in pp to this week's move. Neither v1 nor v2 can produce it, and it is what the NY Fed's own page is known for. Worth designing properly rather than shipping as a raw table.

### Plan E: CI split — **Opus 5**

Quarterly estimation job (heavy; may exceed the 6-hour per-job Actions limit — the Task 9 timing decides) and a weekly nowcast job that loads stored parameters.

Four decisions to make here, recorded now so they are not rediscovered late:

- **Run v3 on `ubuntu-latest`, as its own job.** `nowcast-weekly.yml` uses `windows-latest` because of R. GitHub bills Windows minutes at 2x Linux, and v3 needs no Windows-specific anything. A separate job also means a v3 timeout cannot stale the v1 headline.
- **Ship the parameter file as a release asset, not an Actions artifact.** The weekly job reads it every week; artifacts expire (90 days by default), a release asset does not.
- **Confirm the weekly job fits `timeout-minutes: 60`.** The weekly path is 1,250 `s_update` draws plus 1,250 `density_nowcast` draws plus one `point_nowcast` — not the sampler. Time it at the end of Task 9 alongside the estimation run, and raise the timeout deliberately if needed rather than discovering it in a failed cron.
- **Pin Python and lock dependencies.** The R side is pinned via renv and has already lost a week to an unpinned external fetch (issue #12). Do the equivalent here: an exact `requirements.lock`, and `actions/setup-python` with an explicit version.
 The parameter artifact is 21MB for the US model: use an Actions artifact or a release asset, or thin the stored latents. Add the v3 step to `nowcast-weekly.yml` as `continue-on-error`, exactly as v2 is, so a v3 failure cannot stale the v1 headline.

---

## Attribution

`nyfed_matlab/` is the NY Fed's published replication code and carries no LICENSE file in the drop. Confirm the terms before the repo goes public with it, and credit the lineage on the methodology panel the way v2 credits RBA RDP 2024-04:

> Almuzara, Baker, O'Keeffe & Sbordone (2023), *The New York Fed Staff Nowcast 2.0*, Federal Reserve Bank of New York.
