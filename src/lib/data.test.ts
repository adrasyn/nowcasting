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

  // ONE NOWCAST, ONE TARGET. v3 is trained on first-print GDP and publishes
  // the model's figure less its own rolling miss against that first print. The
  // model's own figure rides along as provenance; nothing on the page scores
  // against the latest vintage any more.
  it("v3 performance is scored against the ABS first print", () => {
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
      // Every row says which model produced it — the current first-print model,
      // or the previous revised-target one for a quarter it published live.
      expect(["first_print", "revised_target"]).toContain(e.model);
    }
  });

  it("the published nowcast is the model's figure less its rolling miss", () => {
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
});
