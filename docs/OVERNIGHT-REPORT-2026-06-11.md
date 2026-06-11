# Overnight report — 2026-06-10 → 06-11

Morning, James. Summary of the night's work. Two things went **live** (you authorised them); the **v2 cutover is built, tested, and staged for your approval** — it is *not* live and is *not* yet mergeable (the visual UI is specified but intentionally not hand-built; see §4).

---

## 1. Live site — RECOVERED ✅ (verified)

The site was stale because the **Mon 8 Jun cron crashed in R setup** — a transient HTTP 504 fetching Ghostscript inside `r-lib/actions/setup-r` (GitHub issue #12). It was the only run between the 3 Jun GDP release and last night, with no retry. Rollover logic was fine; it just never ran.

- Pushed the May NAB value (`2026-05-01,-14`, from the project's own investing.com batch) to `main` to clear the freshness guard, then triggered the pipeline.
- **Result (run 27311612887, success):** site rolled to **2026 Q2**, the Q1 actual (+0.27% QoQ, $695,945m) is ingested, the Q1 row is in the track record, and it redeployed. Live site is correct.

## 2. Weekly cron — HARDENED ✅ (live on `main`, test-run green)

Commit `5ea8293`. Tested via a green `workflow_dispatch` run (27312420072).
- **Retry** `setup-r` (the failure mode that staled the site) + **retry renv restore** 3× on transient CRAN/posit 5xx.
- **`actions/checkout` v4 → v5** ahead of the **16 Jun Node-24 forcing**.
- Failure alert now **assigns you** + **dedupes** (comments instead of stacking issues that go unactioned).
- ⚠️ Still worth doing later (not done): a post-GDP-release catch-up run so a release isn't only picked up the following Monday. Flagged, not built.

---

## 3. v2 cutover — BUILT, TESTED, STAGED (branch `nowcast-v2`, draft PR) 🔨

Your four decisions are baked in: **headline = `qa_a05` (precision)** + **`umidas_a20` "stress" toggle**, **seed track record with labelled backcasts**, **keep v1 as a comparison line**.

### The model emit (the hard core) — done + independently validated
`nowcasting_v2/R/emit_v2_json.R` produces a **non-destructive** `data/latest_v2.json` (parallel to the live file — running it does **not** touch the live site). Both configs are invoked exactly as the sweep scored them; CI params refit from the v2 backtests (`pipeline/seed/ci_params_v2*.json`).

> **A Fable review caught a real blocker before it reached you.** My first emit silently ran on a **stale baseline panel** (no Westpac, short NAB) and produced confident-but-wrong numbers (+0.78% / +0.54% — actually the *worst* sweep variant wearing the right bands). Fable re-derived the correct figures independently; I fixed the panel loader (`build_panel()` now always rebuilds from `data_raw` + a fail-loud guard that refuses to nowcast without the survey block) and re-ran. **The corrected output now matches Fable's independent numbers to the dollar.**

### The numbers (2026 Q2, corrected)

| | QoQ | Level ($m) | 68% band |
|---|---|---|---|
| **v2 headline** (qa_a05) | **+0.19%** | 697,287 | 693,433 – 698,360 |
| **v2 stress** (umidas_a20) | **−0.01%** | 695,904 | — |
| v1 (live, comparison) | +0.61% | 700,222 | — |

**This is a real signal divergence worth your attention:** v2 reads Q2 as **weak (~+0.2%, stress ~flat)** vs v1's +0.61%. Q1 actual was +0.27%.

### Honest accuracy picture (so you approve the precision/robustness trade with eyes open)
Fable rightly flagged this — the headline `qa_a05` is **not** uniformly better than the v1 you're retiring:

| Model | Post-COVID RMSE | OOS last-8q | Full-sample |
|---|---|---|---|
| v1 (13-series DFM) | **0.340** | 0.378 | 1.871 |
| v2 headline qa_a05 | 0.397 | **0.298** | 0.457 |
| v2 stress umidas_a20 | **0.325** | 0.317 | 0.875 |

v1 actually wins the *post-COVID* window; qa_a05 wins the *recent 8-quarter* window (the cleaner current-regime test — the basis you chose it on) and full-sample. This is the call you already made; just re-stating it so nothing's hidden. The site copy never claims v2 is "more accurate" — it says "tuned for precision in normal quarters."

### Also done + committed on the branch
- **Methodology copy** rewritten for MAI → U-MIDAS (RBA RDP 2024-04), with an honest "bands are approximate" caveat (`MethodologyPanel.tsx`, `layout.tsx`).
- **Backcasts:** `data/backcasts.json` — 12 quarters of the headline model's backtest (2023 Q2–2026 Q1, MAE 0.26pp, 92% hit), clearly labelled *hypothetical / not produced in real time*.
- **Frontend data contract:** additive, non-breaking `LatestV2` + `BackcastData` types and optional loaders (`types.ts`, `data.ts`). `tsc --noEmit` passes; the live v1 render is untouched.

---

## 4. NOT done — needs you ⛔

1. **The visual UI is specified, not built** — the CI-band shading, the headline/stress **toggle**, the v1 **comparison line**, and the **backcast table**. I deliberately stopped here: it's your design system (jw_pal), I can't visually verify a render overnight, and the cutover is gated on you anyway. **Consequence: the PR is NOT mergeable as-is** — the methodology copy already references a toggle that doesn't exist, so copy + UI must ship together. Draft PR is marked accordingly.
2. **Westpac (`wmi_sent`) live feed** — only needed for v2 to run *weekly* after cutover. Fable's recommended approach (parse the free official Westpac release in-cron; keep a local Cowork task as fallback) is scoped but not built. History is already banked, so this isn't urgent until you approve the cutover.
3. **Wiring v2 into the production cron** — deliberately not done; that's the live cutover, which is yours to approve.

## 5. What I'd suggest you do next
1. Eyeball `data/latest_v2.json` and the accuracy table above — confirm you're happy with **qa_a05 as headline** given it trails v1 post-COVID but leads on the recent window.
2. If yes: I build the four UI pieces (to your design), wire the Westpac feed + the production cron, and we do a final Fable pass before flipping live.
3. The recovery + hardening need nothing from you — they're already live and working.

Nothing was deployed to the public site except the authorised recovery. Full task list + commits are on `nowcast-v2`. — Big C 🌙
