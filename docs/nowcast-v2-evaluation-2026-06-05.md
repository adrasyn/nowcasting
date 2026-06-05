# Nowcast v2 (RBA MAI + MIDAS) — evaluation & recommendation

**Date:** 2026-06-05 · **Branch:** `nowcast-v2` (not merged/pushed) · **Build log:** `nowcasting_v2/NIGHT-LOG.md`
**Spec:** `docs/superpowers/specs/2026-06-04-nowcast-v2-rba-mai-midas-design.md` · **Plan:** `docs/superpowers/plans/2026-06-04-nowcast-v2-rba-mai-midas.md`

## What was built
A full, working v2 nowcast engine adopting RBA RDP 2024-04: a **Monthly Activity Indicator (MAI)** — a single dynamic factor over ~31 monthly predictors — fed into a **QA U-MIDAS** regression to nowcast quarterly GDP growth. The RBA's estimation code is reused verbatim (approach C); our code is data ingestion + glue + emit. Phase 1 reproduced the RBA paper's published numbers **exactly (22/22 metrics)**, so the engine is validated.

## Head-to-head: v2 vs v1 (real-time POOS backtest)

| Metric | **v2** (MAI→QA-UMIDAS) | **v1** (13-series DFM r=3) | Winner |
|---|--:|--:|---|
| **post-COVID QoQ RMSE** | 0.51 pp | **0.34 pp** | v1 (1.5×) |
| post-COVID hit rate | 94% | 94% | tie |
| **full-sample RMSE** (incl. COVID) | **0.46 pp** | 1.87 pp | **v2 (4×)** |
| **2026 Q1 held-out** (actual +0.27%) | **+0.48%** | +0.80% | **v2** |
| Monthly Activity Indicator | ✅ produced | ✗ | **v2** |

**Reading it:** v1 is meaningfully **more precise in normal quarters**; v2 is **far more robust through downturns/COVID**, calls the **Q1-2026 miss much better**, and yields the **MAI** as a standalone product.

## Can the calm-quarter gap be closed? (Option 2 — three levers, all tested)

| Lever | What we tried | Result |
|---|---|---|
| **C — data/MAI quality** | Diagnosed the weak retail series (genuinely noisy, not a bug) → replaced with Monthly Household Spending (5× better, selected); added building approvals; vehicles honestly skipped (sources too sparse) | Gap unchanged (0.52→0.51). **Not data-bound** — our MAI is already 86% of the RBA's *own* MAI ceiling. |
| **A — calibration/model** | Real-time intercept/bias correction (the post-COVID error is a +0.33pp systematic over-prediction) + full U-MIDAS | No clean win. Bias is only **42% of the error** (variance floor 0.39pp **> v1's 0.34**); de-biasing also **costs ~18pp hit rate** and is **v2-specific** (it hurts v1). Full U-MIDAS helps post-COVID but wrecks full-sample/Q1 (RBA were right that QA is more robust). |
| **B — fair monthly cadence** | Re-measured v2 as it actually runs (0/1/2/3 within-quarter months), not just quarter-ends | RMSE flat (~0.41–0.50); even with the full quarter it's 0.46 **> v1's 0.34**. Timeliness doesn't rescue it. (Small window — caveat.) |

**Conclusion: the calm-quarter gap is intrinsic.** ~58% of v2's post-COVID error is irreducible variance — v1's *direct-to-GDP* DFM is simply tighter in normal quarters than a two-step MAI→MIDAS. No data, calibration, model, or cadence lever closes it without sacrificing the dimensions where v2 already wins. (And because AU quarterly GDP growth is serially uncorrelated, *nobody* — including the RBA's own MAI — predicts calm quarters much better than the mean; the value of this whole class of model is concentrated in downturns.)

## Recommendation

**This is a genuine product call, and the cleanest answer is a hybrid.**

1. **★ Recommended — ship the MAI alongside v1 (hybrid, low-risk).** Keep v1 as the headline GDP nowcast (it's more precise in the normal quarters that dominate), and publish the **MAI as a new monthly activity indicator** + a downturn signal. This captures v2's genuine value (the MAI is exactly what the RBA publishes it for; v2's COVID/Q1 robustness becomes an early-warning overlay) with **zero loss** of v1's calm-quarter precision. It's also the original scope ("add the MAI as a new product").
2. **Replace v1 with v2 outright** — only if downturn robustness + a single unified MAI-driven story matters more than ~0.17pp of calm-quarter precision. Defensible (v2 is more robust and called Q1 better) but trades away precision in the common case.
3. **Keep v1, shelve v2** — if calm-quarter precision is paramount; v2 stays as validated research on its branch.

**Next step if you pick (1) or (2):** Phase 5 (emit `mai.json` + same JSON contract + one MAI chart) is the remaining build, then the cutover/launch — both await your go. Nothing has been pushed; `main` and v1 are untouched.
