import { describe, it, expect } from "vitest";
import { firstDataMonth, formatDate, formatMillions, formatMonth, formatPct, formatQuarter, formatRawChange } from "./format";

describe("formatMillions", () => {
  it("formats with dollar prefix and comma thousands", () => {
    expect(formatMillions(694649)).toBe("$694,649M");
  });
});

describe("formatPct", () => {
  it("formats with sign and 2dp", () => {
    expect(formatPct(0.13)).toBe("+0.13%");
    expect(formatPct(-0.42)).toBe("−0.42%");
    expect(formatPct(0)).toBe("0.00%");
  });
});

describe("formatQuarter", () => {
  it("passes through canonical form", () => {
    expect(formatQuarter("2026 Q1")).toBe("2026 Q1");
  });
});

describe("formatMonth", () => {
  it("converts YYYY-MM to short label", () => {
    expect(formatMonth("2026-04")).toBe("Apr 26");
  });
});

describe("formatDate", () => {
  it("formats ISO date to human-readable", () => {
    expect(formatDate("2026-04-15")).toBe("15 Apr 2026");
  });
});

describe("formatRawChange", () => {
  it("formats $ millions under 100 with 1 dp", () => {
    expect(formatRawChange(-8.5, "$ millions")).toBe("−$8.5M");
  });

  it("formats $ millions 100+ with no decimals", () => {
    expect(formatRawChange(150, "$ millions")).toBe("+$150M");
  });

  it("formats $ millions ≥1000 as $Nbn with 1 dp", () => {
    expect(formatRawChange(1234, "$ millions")).toBe("+$1.2bn");
  });

  it("formats persons (series is thousands) under 1000 as k", () => {
    expect(formatRawChange(12.3, "persons")).toBe("+12.3k");
  });

  it("formats persons 1000+ as m", () => {
    expect(formatRawChange(1234, "persons")).toBe("+1.2m");
  });

  it("formats hours (thousands) with hrs suffix", () => {
    expect(formatRawChange(210, "hours (thousands)")).toBe("+210k hrs");
  });

  it("formats count with thousands separator", () => {
    expect(formatRawChange(1204, "count")).toBe("+1,204");
  });

  it("formats percent deltas as percentage points", () => {
    expect(formatRawChange(0.1, "percent")).toBe("+0.1pp");
  });

  it("formats index deltas as points", () => {
    expect(formatRawChange(-2.3, "index")).toBe("−2.3 pts");
  });

  it("uses unicode minus for negatives", () => {
    expect(formatRawChange(-150, "$ millions")).toBe("−$150M");
  });

  it("renders zero without a sign", () => {
    expect(formatRawChange(0, "percent")).toBe("0.0pp");
  });

  it("falls back gracefully for an unknown unit", () => {
    expect(formatRawChange(5.5, "whatever")).toBe("+5.5");
  });
});

describe("firstDataMonth", () => {
  // A quarter's opening month is measured through the month after it: 2026 Q3
  // began in July and its first indicator landed on 10 August.
  it("names the month after the quarter's first", () => {
    expect(firstDataMonth("2026 Q1")).toBe("February");
    expect(firstDataMonth("2026 Q2")).toBe("May");
    expect(firstDataMonth("2026 Q3")).toBe("August");
    expect(firstDataMonth("2026 Q4")).toBe("November");
  });

  it("accepts the unspaced form too", () => {
    // The Plan C backtest CSV writes quarters as "2026Q1", and
    // `formatQuarterLabel` accepts both, so this must not be stricter.
    expect(firstDataMonth("2026Q4")).toBe("November");
  });

  it("returns undefined for a label it cannot parse", () => {
    // The caller falls back to prose without a month rather than printing
    // "undefined" at a reader.
    for (const junk of ["", "2026 Q5", "not a quarter", "Q4"]) {
      expect(firstDataMonth(junk)).toBeUndefined();
    }
  });
});
