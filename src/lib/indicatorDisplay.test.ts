import { describe, expect, it } from "vitest";
import { formatLatestValue, formatRawChange } from "./format";
import { hasPercentChange, indicatorDisplayUnit } from "./indicatorDisplay";

describe("indicator display semantics", () => {
  it.each(["index", "Index", "INDEX", " Index "])("shows survey changes in points for %s", (unit) => {
    for (const id of ["nab_conditions", "nab_cond", "aig_pmi", "wmi_sent", "bus_conf"]) {
      const indicator = { id, unit };
      const displayUnit = indicatorDisplayUnit(indicator);
      expect(hasPercentChange(indicator)).toBe(false);
      // Negative to negative, both directions across zero, and a zero base.
      for (const [previous, latest, change] of [
        [-1, -2, "−1.0 pts"], [-8.7, -20.1, "−11.4 pts"],
        [-1, 2, "+3.0 pts"], [2, -1, "−3.0 pts"], [0, -2, "−2.0 pts"],
      ] as const) {
        expect(formatRawChange(latest - previous, displayUnit)).toBe(change);
        expect(formatLatestValue(latest, displayUnit)).toBe(latest.toFixed(1));
      }
    }
  });

  it.each(["percent", "Percent", "PERCENT", " Percent ", "%"])("formats rates consistently for %s", (unit) => {
    const indicator = { id: "unemployment_rate", unit };
    expect(hasPercentChange(indicator)).toBe(false);
    expect(formatLatestValue(4.7, unit)).toBe("4.7%");
    expect(formatRawChange(0.1, unit)).toBe("+0.1pp");
    expect(formatRawChange(-0.2, unit)).toBe("−0.2pp");
    expect(formatRawChange(0, unit)).toBe("0.0pp");
  });

  it("corrects capacity use presentation without changing its metadata or values", () => {
    const indicator = { id: "nab_cu", unit: "net balance", series: [82.3, 82.1] };
    const before = structuredClone(indicator);
    const unit = indicatorDisplayUnit(indicator);
    expect(unit).toBe("percent");
    expect(hasPercentChange(indicator)).toBe(false);
    expect(formatLatestValue(indicator.series[1], unit)).toBe("82.1%");
    expect(formatRawChange(indicator.series[1] - indicator.series[0], unit)).toBe("−0.2pp");
    expect(indicator).toEqual(before);
  });

  it.each(["net balance", "Net Balance", " NET BALANCE "])("retains net-balance point formatting for %s", (unit) => {
    expect(hasPercentChange({ id: "nab_cond", unit })).toBe(false);
    expect(formatRawChange(-1, unit)).toBe("−1 pts");
  });

  it.each(["cpi", "commodity_prices", "unit_labour_cost", "job_ads", "anz_ads"])("preserves percentage growth for ratio-scale index %s", (id) => {
    for (const unit of ["Index", "index", "INDEX"]) {
      expect(hasPercentChange({ id, unit })).toBe(true);
      expect(formatLatestValue(108.53, unit)).toBe("108.5");
      expect(formatRawChange(108.53 - 107.87, unit)).toBe("+0.7 pts");
    }
  });

  it.each(["$m", "$bn", "$ millions", "persons", "count", "hours (thousands)"])("preserves growth for level series in %s", (unit) => {
    expect(hasPercentChange({ id: "level_series", unit })).toBe(true);
  });
});
