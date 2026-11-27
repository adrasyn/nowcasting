import { describe, expect, it } from "vitest";
import { buildMonitorView } from "../monitor";
import { finalBuiltAt, finalFixtureData, fixtureData } from "../../../tests/fixtures/monitor";
import type { DashboardData } from "../types";

describe("final estimate publication", () => {
  it("never uses 3/3 months by itself", () => {
    const h = buildMonitorView(fixtureData()).current;
    expect(h.source?.months_with_data).toBe(3);
    expect(h.months).toBeNull();
    expect(h.finalEstimate).toBeUndefined();
  });
  it("uses the exact certified current published row", () => {
    const d = finalFixtureData();
    const view = buildMonitorView(d, finalBuiltAt);
    expect(view.current.finalEstimate).toEqual(d.latestCombo!.final_estimate);
    expect(view.next.finalEstimate).toBeUndefined();
  });
  it("can update a complete estimate without changing the earlier chart dot", () => {
    const d = finalFixtureData(), latest = d.latestCombo!, h = latest.horizons[0];
    const first = buildMonitorView(d, finalBuiltAt).current;
    const original = {...first.runs.at(-1)!};
    // Use two ordinary weeks, both before the actual; the later one updates
    // the complete estimate, rather than being suppressed by a freeze.
    const oldRun = "2026-11-23", nextRun = "2026-11-30";
    const old = {...original, run_date: oldRun, v2_run_date: oldRun};
    const qoq = original.qoq_growth_pct + 0.05;
    const next = {...original, qoq_growth_pct: qoq, run_date: nextRun, v2_run_date: nextRun};
    latest.vintages!.splice(-1, 1, old, next);
    latest.as_of = nextRun;
    latest.generated_at = "2026-11-30T00:45:00Z";
    latest.final_estimate = {...latest.final_estimate!, run_date: nextRun, generated_at: latest.generated_at};
    latest.components = {v2: {as_of: nextRun, run_date: nextRun}, v3: {as_of: nextRun}};
    h.qoq_growth_pct = qoq;
    const current = buildMonitorView(d, finalBuiltAt).current;
    expect(current.months).toBe(3);
    expect(current.finalEstimate?.run_date).toBe(nextRun);
    expect(current.qoq).toBe(qoq);
    expect(current.runs.slice(-2).map(r => r.qoq_growth_pct)).toEqual([original.qoq_growth_pct, qoq]);
  });
  const changes: Record<string, (d: DashboardData) => void> = {
    "an incomplete month": d => { d.latestCombo!.horizons[0].complete_months!.pop(); },
    "a stale component": d => { d.latestCombo!.components!.v2!.stale_days = 1; },
    "a certification for the wrong quarter": d => { d.latestCombo!.final_estimate!.quarter = "2026 Q4"; },
    "a superseded stamp": d => { d.latestCombo!.generated_at = "2026-12-01T07:35:00Z"; },
    "a model refusal": d => { d.latestCombo!.status = "refused"; },
    "a mismatched chart point": d => { d.latestCombo!.vintages!.at(-1)!.qoq_growth_pct += 0.1; },
    "a different release date": d => { d.latestCombo!.horizons[0].release_date = "2026-12-03"; },
    "an already printed quarter": d => { d.gdp.series.push({quarter: "2026 Q3", value: 704000, qoq_pct: 0.5, yoy_pct: 2}); },
    "a carried forecast": d => { d.latestCombo!.horizons[0].kind = "forecast"; },
  };
  for (const [name, change] of Object.entries(changes)) {
    it(`does not badge ${name}`, () => {
      const d = finalFixtureData();
      change(d);
      const view = buildMonitorView(d, finalBuiltAt);
      expect(view.current.finalEstimate).toBeUndefined();
      expect(view.next.finalEstimate).toBeUndefined();
    });
  }
});
