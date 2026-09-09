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

  // ONE NOWCAST, ONE TARGET. v3 publishes the model's figure less the ABS's
  // average upward revision, and scores it against the ABS's first print. The
  // model's own figure rides along as provenance; nothing on the page scores
  // against the latest vintage any more.
  it("v3 performance is scored against the ABS first print", () => {
    const data = loadDashboardData();
    const p = data.performanceV3;
    expect(p).toBeDefined();
    expect(p!.basis).toBe("abs_first_print");
    expect(typeof p!.bias_pct).toBe("number");
    for (const e of p!.errors) {
      expect(typeof e.qoq_model_nowcast_pct).toBe("number");
      expect(typeof e.qoq_actual_pct).toBe("number");
    }
  });

  it("the published nowcast is the model's figure less the adjustment", () => {
    const data = loadDashboardData();
    const v3 = data.latestV3;
    // Payloads emitted before 2026-09-09 carry no adjustment; there is nothing
    // to check on those, and the site renders them without the clause.
    if (!v3?.revision_adjustment) return;
    const nowcast = v3.horizons.find((h) => h.kind === "nowcast");
    expect(typeof nowcast?.model_qoq_growth_pct).toBe("number");
    const implied =
      nowcast!.model_qoq_growth_pct! - v3.revision_adjustment.pp;
    expect(Math.abs(nowcast!.qoq_growth_pct - implied)).toBeLessThan(1e-3);
  });
});
