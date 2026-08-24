# nowcasting-v3 — NY Fed Staff Nowcast 2.0, ported to Python

A Python port of the New York Fed Staff Nowcast 2.0 (Almuzara, Baker, O'Keeffe &
Sbordone, 2023): a Bayesian dynamic factor model with stochastic volatility and
outlier states, to be refitted to Australian data.

## Layout

| Path | Purpose |
| --- | --- |
| `nyfed/` | The Python port (the deliverable). |
| `nyfed_matlab/` | **Vendored MATLAB reference implementation. Read-only.** |
| `tools/` | Octave fixture generation and `.mat` -> `.npz` conversion. |
| `tests/` | Pytest suite; fixtures are generated, not committed. |
| `NYFed-Staff-Nowcast_technical-paper.pdf` | The reference paper. |

### `nyfed_matlab/` is read-only, permanently

Never edit a file under `nyfed_matlab/` — not to fix a bug, not to add a debug
print, not temporarily. It is the oracle the port is tested against, so it must
stay byte-identical to what the NY Fed published. If Octave ever needs a
modified version of one of those functions, put the modified copy in
`tools/octave_shims/` and `addpath` that directory ahead of the originals in
`tools/gen_fixtures.m`.

At present **no shim is needed** — see below.

## Testing strategy: Octave as a numerical oracle

The port is tested against the vendored MATLAB, executed under GNU Octave.
`tools/gen_fixtures.m` runs reference functions on small, fixed-seed inputs and
saves inputs and outputs; `tools/matload.py` flattens those into `.npz`; the
tests load them via `tests/conftest.py` and compare the Python port's output.

This was verified on 2026-08-24 with **Octave 11.3.0** on macOS (arm64).
`Kalman_filter.m` ran unmodified and returned a finite log-likelihood of
`-60.919914554813` on a 2-series / 3-state / 20-period model with one missing
observation. In particular Octave accepts `linsolve(S, eye(k), option)` with the
`SYM`/`POSDEF` options struct, which was the anticipated portability risk, so
**no shim was required and `tools/octave_shims/` does not exist**.

### Setup

```bash
brew install octave
octave --eval "pkg install -forge datatypes"    # statistics dependency
octave --eval "pkg install -forge statistics"
octave --eval "pkg load statistics; disp('statistics ok')"
```

### Regenerating fixtures

Fixtures are gitignored — regenerate them rather than committing them. Tests
that need an absent fixture skip rather than fail.

```bash
cd nowcasting_v3/tools
octave gen_fixtures.m
../.venv/bin/python matload.py fixtures_mat/kalman_basic.mat ../tests/fixtures/kalman_basic.npz
```

## Python environment

Requires Python >= 3.11 (developed against Homebrew Python 3.13).

```bash
cd nowcasting_v3
python3.13 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```
