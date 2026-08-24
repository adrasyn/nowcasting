# Nowcast v3 — resume note

**Paused:** 2026-08-24. **Branch:** `feat/nowcast-v3-nyfed-port` (off `main`, **not pushed**).
**HEAD at pause:** `4aa6e8b`. Working tree clean. Suite **88 passing** under `-W error`.

## Restart in three commands

```bash
cd /Users/James/Documents/Claude/Projects/nowcasting
git checkout feat/nowcast-v3-nyfed-port
cd nowcasting_v3 && .venv/bin/pytest -q        # expect 88 passed
```

Plan: `docs/superpowers/plans/2026-08-24-nowcast-v3-nyfed-port.md`
Ledger (the recovery map, 336 lines, **gitignored — local to this machine**):
`.superpowers/sdd/2026-08-24-nowcast-v3-nyfed-port/progress.md`

Execution method: `superpowers:subagent-driven-development`. One implementer subagent per task,
a task review after each, a scoped re-review after each fix round. The ledger records every
task's commit range; a task with a `complete` line is done and must not be re-dispatched.

## Where we stopped

| Task | State |
|---|---|
| 0 Scaffold, vendor MATLAB, prove Octave oracle | complete |
| 1 Linear algebra primitives | complete |
| 2 Parameter mapping + spec loader | complete |
| 3 Fixture generator (10 fixtures, 2.35 MiB) | complete |
| 4 Kalman filter + smoothers | complete |
| 5 SSM construction + prior | complete |
| 6 SV + outlier updaters | complete |
| **7 Gibbs sampler + conditional-posterior oracle** | **NOT STARTED — 3 dispatches died on API 529** |
| 8 Point/density nowcast + news decomposition | not started |
| 9 End-to-end gate | not started |

## Next action, exactly

Three consecutive dispatches failed on `API Error: 529 Overloaded` — twice on Fable, once on
Opus, so it was platform-wide capacity, not a model or task problem. Each time the tree was
verified clean: no `gibbs.py`, no shim, 88 passing, 10 fixtures intact. **Nothing to unwind.**

```bash
SDD=~/.claude/plugins/cache/claude-plugins-official/superpowers/6.2.0/skills/subagent-driven-development
$SDD/scripts/task-brief docs/superpowers/plans/2026-08-24-nowcast-v3-nyfed-port.md 7
# then dispatch an implementer on opus with BASE=4aa6e8b
```

All Task 7 design work is already committed in `4aa6e8b` — nothing needs re-deriving.

## The two things worth knowing before touching Task 7

**1. Octave is a test oracle, not a runtime.** It cannot run the model in production (no
`datetime`, absent from CI) but it runs the numerical core unmodified, which is how every task
so far is pinned **bit-exactly** — `np.array_equal`, not `rtol`. Shims live in
`nowcasting_v3/tools/octave_shims/`; `nyfed_matlab/` is vendored and never edited (verified by
mtime: all 40 files still `2025-07-09 04:09`).

**2. Task 9 does NOT test the Gibbs sampler.** `example_nowcast.m` — and our reference runner —
nowcasts from the *stored* `Estimates_2023_09_20.mat` that MATLAB's own estimation run produced.
The end-to-end gate verifies the **nowcast** path, not the **estimation** path. A sampler with a
transposed design matrix would pass every downstream check.

That is why Task 7 gained Step 0: all randomness in `Gibbs_update.m` enters at six places, and
every `(m_X, Pinv_X)` pair is deterministic given the drawn state. Those pairs *are* the
conditional posteriors. Pin them at `rtol=1e-10` via a `gibbs_update_cond.m` shim and a
`gibbs_update_moments()` split in the port. Same seam that made Task 6 bit-exact.

## Measurements taken so far

- `simulation_smoother`, T=468: **0.0784 s/pass** → 0.61 h for 28,000 iterations (state block only).
- Whole-loop timing including the 36 SV updates per iteration is **still unmeasured** — Task 7
  produces it, and it decides whether quarterly re-estimation fits a hosted Actions runner.
- Task 9 gate targets, from the drop's own `Update_*.mat`: **2.0241866715115893** (2023-09-29)
  and **2.3834662755905036** (2023-10-06), 2023 Q4 annualised QoQ.

## Model assignments, as revised by evidence

Plan A now has **no Fable tasks**. Three assignments moved down a tier during execution, each
time because the fixtures turned out stronger than planned: `construct_prior` (Task 5),
the updaters (Task 6), and the Gibbs sampler (Task 7, once Step 0 existed). Fable's remaining
case is **Plan B**, where the Australian panel changes `n`/`n_f` and the fixtures stop
protecting anything.

## Nine plan defects found during execution

All nine were in **my test or interface code**, none in the porting guidance. The implementers
were reliable at translation; the verification written around them is where the errors lived.
Worth remembering for Tasks 8–9, where the tests carry most of the weight. Full list in the
ledger.

## Landmines recorded for Plan B

- **B3** — `construct_SSM.m:131` pads the quarterly `H` branch with `length(vec_m)` where
  `vec_q` is meant. Harmless only because both are length 5. B3 re-derives that filter for
  Australian QoQ; if `vec_q` changes length, `H` silently mis-sizes.
- **B2** — `construct_SSM.m:166` builds `var_init` factor blocks as contiguous 5x5 while the
  factor states are lag-major, so each block spans a mix of lags, not one factor. Anyone
  reasoning about "the initial prior on the COVID factor" is reasoning about something the code
  does not do.
- `np.minimum` propagates NaN where MATLAB's `min` omits it at the `bd = 15` volatility cap.
  Unreachable with US data; Australian missingness patterns differ.
