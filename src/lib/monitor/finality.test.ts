import { describe, expect, it } from "vitest";
import { buildMonitorView } from "../monitor";
import { finalBuiltAt, finalFixtureData, fixtureData } from "../../../tests/fixtures/monitor";
import type { DashboardData } from "../types";

describe("final estimate publication", () => {
  it("never uses 3/3 months by itself", () => {
    const h = buildMonitorView(fixtureData()).current;
    expect(h.months).toBe(3);
    expect(h.finalEstimate).toBeUndefined();
  });
  it("uses the exact certified current published row", () => {
    const d = finalFixtureData();
    const view = buildMonitorView(d, finalBuiltAt);
    expect(view.current.finalEstimate).toEqual(d.latestCombo!.final_estimate);
    expect(view.next.finalEstimate).toBeUndefined();
  });
  const changes: Record<string, (d: DashboardData) => void> = {
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
