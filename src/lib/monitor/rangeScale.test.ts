import { describe, it, expect } from "vitest";
import { sharedQuarterRangeBound, rangeTick } from "./rangeScale";
const h = (
  qoq: number | null,
  band95: [number, number] | null = null,
  band68: [number, number] | null = null,
) => ({ qoq, band95, band68 });
describe("shared quarter-card uncertainty axis", () => {
  it("defaults both cards to symmetric −1% to +1% for ordinary data", () => {
    expect(
      sharedQuarterRangeBound([
        h(0.4377, [0.0864, 0.789]),
        h(0.2525, [-0.15, 0.65]),
      ]),
    ).toBe(1);
    expect([-1, 0, 1].map(rangeTick)).toEqual(["−1%", "0", "+1%"]);
  });
  it("widens the pair together to a clean symmetric bound for any plotted point or band", () => {
    for (const [rows, bound] of [
      [[h(0.44, [-1.27, 1.41]), h(0.25, [-0.15, 0.65])], 1.5],
      [[h(2.01), h(0.3)], 2.5],
      [[h(-0.1, [-4.01, 0.5]), h(0.2)], 5],
      [[h(0.1, [-0.2, 0.3], [-0.4, 1.6]), h(0.2)], 2],
    ] as const) {
      const value = sharedQuarterRangeBound([...rows]);
      expect(value).toBe(bound);
      for (const row of rows)
        for (const n of [row.qoq, ...(row.band68 ?? []), ...(row.band95 ?? [])])
          if (n !== null) expect(Math.abs(n)).toBeLessThanOrEqual(value);
    }
    expect([-1.5, 0, 1.5].map(rangeTick)).toEqual(["−1.5%", "0", "+1.5%"]);
  });
  it("keeps missing, refused and non-finite observations from inventing a range", () => {
    expect(sharedQuarterRangeBound([])).toBe(1);
    expect(sharedQuarterRangeBound([h(null, [-9, 9]), h(0.3)])).toBe(1);
    expect(sharedQuarterRangeBound([h(NaN, [NaN, Infinity]), h(-1.1)])).toBe(
      1.5,
    );
    expect(sharedQuarterRangeBound([h(0, [0, 0]), h(null)])).toBe(1);
  });
});
