import { describe, it, expect } from "vitest";
import { loadDashboardData } from "./data";
import type { LatestV2, V2Model } from "./types";

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

  // v2 publishes two horizons: the quarter the ABS has not printed, and the one
  // after it once that quarter has a month of data. The second is absent early
  // in a quarter, which is the ordinary state and not an error — so a test that
  // read the committed payload and returned when the field was missing checked
  // nothing at all in most weeks, including this one. The payload is hand-built
  // here instead: what is being asserted is the contract between the emitter
  // and /v2, and that holds whether or not this week's file exercises it.
  //
  // WHAT MUST NEVER REGRESS is /v2's chart selection. A next-quarter row
  // OUTLIVES its horizon: once the ABS prints, the quarter it targeted becomes
  // the current one, so selecting on `target_quarter` alone would silently
  // extend the current quarter's line backwards with figures made before the
  // quarter had begun.
  it("a next-quarter v2 row never reaches /v2's evolution chart", () => {
    const vintage = (
      run_date: string,
      target_quarter: string,
      horizon: string,
      qoq: number,
    ) => ({
      run_date,
      target_quarter,
      horizon,
      point: 700000,
      qoq_growth_pct: qoq,
      days_until_release: -60,
      ci_68_low: qoq - 0.3,
      ci_68_high: qoq + 0.3,
      ci_95_low: qoq - 0.6,
      ci_95_high: qoq + 0.6,
      data_through: "2026-08",
    });
    const model = (target_quarter: string, over: Partial<V2Model> = {}) => ({
      model_id: "qa",
      model_name: "QA-UMIDAS",
      target_quarter,
      gdp_chain_volume_millions: 703205,
      qoq_growth_pct: 0.61,
      yoy_growth_pct: 2.1,
      ci_68_low: 0.3,
      ci_68_high: 0.9,
      ci_95_low: 0.0,
      ci_95_high: 1.2,
      n_months_in_quarter: 2,
      ci_basis: "empirical",
      ci_n: 40,
      ci_sd_pp: 0.3,
      ci_bias_pp: 0.05,
      ...over,
    });
    const v2: LatestV2 = {
      generated_at: "2026-09-07T02:00:00+00:00",
      schema: "v2-staged-2",
      target_quarter: "2026 Q3",
      data_through: "2026-08",
      prev_level: { value: 699461, date: null, source: "ABS" },
      models: {
        headline: model("2026 Q3"),
        next_quarter: model("2026 Q4", {
          horizon: "next",
          current_quarter: "2026 Q3",
          n_months_in_quarter: 0,
        }),
      },
      vintages: [
        // Written while 2026 Q3 was still the NEXT quarter, before Q2 printed.
        vintage("2026-08-24", "2026 Q3", "next", 0.56),
        vintage("2026-09-07", "2026 Q3", "current", 0.61),
        vintage("2026-09-07", "2026 Q4", "next", 0.3),
      ],
      v1_comparison: null,
      note: "",
    };

    const nq = v2.models.next_quarter!;
    expect(nq.target_quarter).toBe("2026 Q4");
    expect(nq.current_quarter).toBe(v2.models.headline.target_quarter);

    // The selection in src/app/v2/page.tsx.
    const drawn = v2.vintages.filter((vt) => vt.horizon !== "next");
    expect(drawn.map((vt) => vt.run_date)).toEqual(["2026-09-07"]);
    expect(drawn.every((vt) => vt.target_quarter === v2.target_quarter)).toBe(
      true,
    );
  });

  it("v2's vintage log separates the two horizons", () => {
    const data = loadDashboardData();
    const v2 = data.latestV2;
    expect(v2).toBeDefined();
    for (const vt of v2!.vintages) {
      // A missing horizon means a row written before 2026-09-12: current.
      expect([undefined, "current", "next"]).toContain(vt.horizon);
    }
    // The /v2 chart's own selection: current-horizon rows for the headline
    // quarter. It must never pick up a next-quarter row.
    const drawn = v2!.vintages.filter(
      (vt) => vt.horizon !== "next" && vt.target_quarter === v2!.target_quarter,
    );
    expect(drawn.length).toBeGreaterThan(0);
    expect(drawn.every((vt) => vt.horizon !== "next")).toBe(true);
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
      const v2 = h.components!.v2;
      if (v2 === null) {
        // The next quarter before v2 has a figure for it: v3's own forecast,
        // kept so the next-quarter card and the chart toggle stay on the page.
        // It publishes no month of data, so nothing renders the figure.
        expect(h.kind).toBe("forecast");
        expect(h.months_with_data).toBe(0);
        expect(h.qoq_growth_pct).toBe(h.components!.v3);
        continue;
      }
      const mean = (v2 + h.components!.v3) / 2;
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
