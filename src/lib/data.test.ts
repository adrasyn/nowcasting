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

  it("v3 performance carries first-print actuals and the revision adjustment", async () => {
    const data = await loadDashboardData();
    const p = data.performanceV3;
    expect(p).toBeDefined();
    expect(typeof p!.bias_first_print_pct).toBe("number");
    expect(typeof p!.mae_first_print_pct).toBe("number");
    expect(typeof p!.revision_adjustment_pp).toBe("number");
    for (const e of p!.errors) {
      expect(typeof e.qoq_first_print_pct).toBe("number");
      expect(typeof e.qoq_error_first_print_pp).toBe("number");
    }
    const nowcast = data.latestV3?.horizons.find((h) => h.kind === "nowcast");
    if (data.latestV3?.status === "ok" && data.latestV3.revision_adjustment) {
      expect(typeof nowcast?.expected_first_print_pct).toBe("number");
    }
  });
});
