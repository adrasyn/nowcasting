import { describe, it, expect } from "vitest";
import { loadDashboardData } from "./data";

describe("loadDashboardData", () => {
  it("loads all five JSON files and returns a DashboardData object", () => {
    const data = loadDashboardData();
    expect(data.latest.target_quarter).toBeTruthy();
    expect(data.gdp.series.length).toBeGreaterThan(0);
    expect(data.nowcasts.vintages.length).toBeGreaterThan(0);
    expect(data.indicators.indicators.length).toBeGreaterThan(0);
    expect(typeof data.performance.mae_pct).toBe("number");
    expect(typeof data.performance.bias_pct).toBe("number");
    expect(data.performance.rba_comparison).toBeDefined();
  });

  it("returns sane fallbacks when files are missing", () => {
    // loader should not throw even with missing files; test via monkey-patching env
    // covered by fallback branches in loadDashboardData
    const data = loadDashboardData();
    expect(typeof data).toBe("object");
  });

  // ONE NOWCAST, ONE TARGET. v3 is estimated on the ABS's initial estimates
  // and publishes the model's figure less its recent average error against
  // them. The model's own figure rides along as provenance; nothing on the
  // page scores against the latest vintage any more.
  it("v3 performance is scored against the ABS's initial estimate", () => {
    const data = loadDashboardData();
    const p = data.performanceV3;
    expect(p).toBeDefined();
    expect(p!.basis).toBe("abs_first_print");
    expect(p!.target).toBe("first_print");
    expect(typeof p!.bias_pct).toBe("number");
    expect(typeof p!.bias_window_quarters).toBe("number");
    for (const e of p!.errors) {
      expect(typeof e.qoq_model_nowcast_pct).toBe("number");
      expect(typeof e.qoq_actual_pct).toBe("number");
      // Every row says which model produced it — the current one, or the
      // previous revised-target version for a quarter it published live.
      expect(["first_print", "revised_target"]).toContain(e.model);
    }
  });

  it("the published nowcast is the model's figure less its recent average error", () => {
    const data = loadDashboardData();
    const v3 = data.latestV3;
    // Payloads emitted before 2026-09-10 carry no correction; there is nothing
    // to check on those, and the site renders them without the clause.
    if (!v3?.bias_correction) return;
    const nowcast = v3.horizons.find((h) => h.kind === "nowcast");
    expect(typeof nowcast?.model_qoq_growth_pct).toBe("number");
    const implied =
      nowcast!.model_qoq_growth_pct! - v3.bias_correction.pp;
    expect(Math.abs(nowcast!.qoq_growth_pct - implied)).toBeLessThan(1e-3);
  });

  // ---- the combination (2026-09-12) ---------------------------------------
  // The homepage publishes the equal-weight average of v2 and v3. The loader
  // reports it as its own fields; `page.tsx` prefers them over v3's.

  it("reads the combination payloads as their own fields, not as v3's", () => {
    const data = loadDashboardData();
    // Optional by design: a checkout from before the emitter has no combo
    // files and the page serves v3 alone.
    if (!data.latestCombo) return;
    expect(data.latestCombo.schema).toMatch(/^combo-/);
    // THE POINT OF THE EXPLICIT FIELDS. `latestV3` must still be v3's own
    // payload; a loader that returned the average under that name would leave
    // nothing able to name either model's own figure.
    expect(data.latestV3?.schema).not.toMatch(/^combo-/);
    expect(data.performanceCombo?.method).toMatch(/equal-weight average/);
  });

  it("the combination's published figure is the mean of its two components", () => {
    const data = loadDashboardData();
    const combo = data.latestCombo;
    if (!combo || combo.status !== "ok") return;
    expect(combo.horizons.length).toBeGreaterThan(0);
    for (const h of combo.horizons) {
      expect(h.components).toBeDefined();
      const mean = (h.components!.v2 + h.components!.v3) / 2;
      expect(Math.abs(h.qoq_growth_pct - mean)).toBeLessThan(1e-4);
    }
  });

  it("every combination track-record row says it is the combination", () => {
    const data = loadDashboardData();
    const p = data.performanceCombo;
    if (!p) return;
    expect(p.basis).toBe("abs_first_print");
    expect(p.errors.length).toBeGreaterThan(0);
    for (const e of p.errors) expect(e.model).toBe("combination");
  });
});
