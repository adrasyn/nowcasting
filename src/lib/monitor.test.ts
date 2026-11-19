import { describe, it, expect } from "vitest";
import { fixtureViews, fixtureData } from "../../tests/fixtures/monitor";
import { loadDashboardData } from "./data";
import {
  archiveRuns,
  buildMonitorView,
  releaseFor,
  shiftQuarter,
} from "./monitor";
import { indicatorChart, relativeChange } from "./monitor/indicators";
import {
  compareDisplayedUpdates,
  displayUpdateInfo,
} from "./monitor/indicatorDates.mjs";
import type { DashboardData } from "./types";
const fresh = fixtureData;
const now = "2026-11-19T10:00:00Z";
const view = (d: DashboardData) => buildMonitorView(d, now);
function addActual(d: DashboardData, q: string, value = 704000) {
  d.gdp.series.push({ quarter: q, value, qoq_pct: 0.5, yoy_pct: 2 });
}
describe("production monitor data contract", () => {
  it("uses the production bundle, accurate quarterly keyed y/y, all saved vintages and first-print scores", () => {
    const d = fresh(),
      v = view(d);
    expect(v.current.quarter).toBe("2026 Q3");
    expect(v.next.quarter).toBe("2026 Q4");
    expect(v.current.qoq).toBe(d.latestCombo!.horizons[0].qoq_growth_pct);
    expect(v.current.yoy).toBeCloseTo(
      (702523 / d.gdp.series.find((r) => r.quarter === "2025 Q3")!.value - 1) *
        100,
    );
    expect(v.next.yoy).toBeCloseTo(
      ((702523 * (1 + 0.2525 / 100)) /
        d.gdp.series.find((r) => r.quarter === "2025 Q4")!.value -
        1) *
        100,
    );
    expect(v.history).toHaveLength(d.historyCombo!.runs.length);
    expect(v.performance!.errors).toHaveLength(
      d.performanceCombo!.errors.length,
    );
    expect(v.indicators.indicators).toHaveLength(
      d.indicatorsCombo!.indicators.length,
    );
    expect(d).toEqual(fresh());
  });
  it("loads the complete current production bundle without fixed date or count assumptions", () => {
    const d = loadDashboardData(),
      v = view(d);
    const last = [...d.gdp.series]
      .sort((a, b) => a.quarter.localeCompare(b.quarter))
      .at(-1);
    expect(v.current.quarter).toBe(last ? shiftQuarter(last.quarter, 1) : null);
    expect(v.indicators).toBe(
      d.latestCombo ? d.indicatorsCombo : d.indicatorsV3,
    );
    expect(v.performance).toBe(
      d.latestCombo ? d.performanceCombo : d.performanceV3,
    );
    expect(v.history.length).toBeGreaterThanOrEqual(
      (d.latestCombo ? d.historyCombo : d.historyV3)?.runs.length ?? 0,
    );
  });
  it("does not roll on the calendar and rejects mismatched release dates", () => {
    const d = fresh();
    expect(buildMonitorView(d, "2027-01-12").current.quarter).toBe("2026 Q3");
    expect(
      releaseFor(
        "2026 Q4",
        { ...d.latestCombo!.horizons[1], release_date: "2026-12-02" },
        null,
      ),
    ).toBeNull();
  });
  it("rolls only after an official ABS actual and handles the year boundary", () => {
    const d = fresh();
    addActual(d, "2026 Q3");
    const v = view(d);
    expect(v.current.quarter).toBe("2026 Q4");
    expect(v.current.carriedForecast).toBe(true);
    expect(v.current.qoq).toBe(0.2525);
    expect(v.current.bandKind).toBe("error");
    expect(v.next.quarter).toBe("2027 Q1");
    expect(v.next.qoq).toBeNull();
    expect(v.warnings.join()).toMatch(/previous run/);
    const fixtures = fixtureViews();
    expect(fixtures.release.current.qoq).toBe(-0.12);
    expect(fixtures.release.next.qoq).toBe(0);
    expect(fixtures.year.current.quarter).toBe("2027 Q1");
    expect(fixtures.year.next.quarter).toBe("2027 Q2");
    expect(shiftQuarter("2026 Q4", 1)).toBe("2027 Q1");
  });
  it("does not publish a zero-month trend anchor, refusal or stale old target as a new point", () => {
    const f = fixtureViews();
    expect(f.stale.next.state).toBe("no-data");
    expect(f.stale.next.qoq).toBeNull();
    expect(f.refused.current.qoq).toBeNull();
    expect(f.refused.current.band68).toBeNull();
    expect(f.refused.model).toBe("combination");
    const d = fresh();
    addActual(d, "2026 Q4");
    expect(view(d).current.state).toBe("waiting");
    expect(view(d).current.qoq).toBeNull();
  });
  it("keeps model-specific panels, scores, history and band interpretation together", () => {
    const d = fresh();
    delete d.latestCombo;
    const v = view(d);
    expect(v.model).toBe("v3");
    expect(v.indicators).toBe(d.indicatorsV3);
    expect(v.performance).toBe(d.performanceV3);
    expect(v.current.bandKind).toBe("posterior");
    delete d.indicatorsV3;
    delete d.performanceV3;
    expect(view(d).indicators.indicators).toEqual([]);
    expect(view(d).performance).toBeNull();
  });
  it("handles missing and malformed optional data without fabricated figures", () => {
    const d = fresh();
    d.gdp.series = [];
    d.latestCombo!.horizons[0].ci_68_high = NaN;
    delete d.historyCombo;
    delete d.performanceCombo;
    delete d.indicatorsCombo;
    const v = view(d);
    expect(v.current.yoy).toBeNull();
    expect(v.current.band68).toBeNull();
    expect(v.performance).toBeNull();
    expect(v.indicators.indicators).toHaveLength(0);
    expect(fixtureViews().missing.current.qoq).toBeNull();
  });
  it("picks next week’s new point/date and retains rather than truncates the archive", () => {
    const v = fixtureViews().weekly;
    expect(v.asOf).toBe("2026-11-23");
    expect(v.current.qoq).toBe(0.53);
    expect(v.current.delta).toBeCloseTo(0.53 - 0.4377);
    expect(v.history).toHaveLength(7);
    expect(archiveRuns(v.history, [v.history[0]])).toHaveLength(7);
  });
  it("sorts the displayed date, keeping ANZ checked provenance and provisional observation intact", () => {
    const d = fresh(),
      rows = d.indicatorsCombo!.indicators.sort(compareDisplayedUpdates);
    const anz = rows.find((r) => r.id === "anz_sent")!;
    expect(displayUpdateInfo(anz)).toEqual({
      day: "2026-11-18",
      kind: "checked",
      label: "Checked",
    });
    expect(anz.last_release_date).toBeUndefined();
    expect(anz.series.at(-1)!.provisional).toBe(true);
    const no = {
      ...rows[0],
      id: "missing",
      source_checked_at: undefined,
      last_release_date: undefined,
    };
    expect([no, rows[0]].sort(compareDisplayedUpdates)[1].id).toBe("missing");
  });
  it("shares mini/detail calculations, correct employment scale, and gaps without bogus baselines", () => {
    const d = fresh();
    for (const id of ["employment", "ft_emp", "pt_emp"]) {
      const i = d.indicatorsCombo!.indicators.find((i) => i.id === id)!,
        c = indicatorChart(i);
      expect(c.kind).toBe("bars");
      expect(c.unit).toBe("thousand people");
      expect(c.points.at(-1)!.value).toBeCloseTo(
        i.series.at(-1)!.value - i.series.at(-2)!.value,
      );
    }
    for (const id of ["cpi", "credit", "gdp"]) {
      const i = d.indicatorsCombo!.indicators.find((i) => i.id === id)!,
        c = indicatorChart(i);
      expect(c.points.at(-1)!.value).toBeCloseTo(
        (i.series.at(-1)!.value / i.series.at(-2)!.value - 1) * 100,
      );
    }
    const i = d.indicatorsCombo!.indicators.find((i) => i.id === "employment")!;
    i.series = [
      { date: "2026-01", value: 100 },
      { date: "2026-03", value: 120 },
      { date: "2026-04", value: 130 },
    ];
    expect(indicatorChart(i).points.map((r) => r.value)).toEqual([
      null,
      null,
      null,
      10,
    ]);
    for (const id of ["nab_conditions", "nab_cu", "unemployment_rate"])
      expect(
        relativeChange(d.indicatorsCombo!.indicators.find((i) => i.id === id)!),
      ).toBeNull();
  });
});
