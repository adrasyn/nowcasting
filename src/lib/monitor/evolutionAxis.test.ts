import { it, expect } from "vitest";
import { evolutionAxis, evolutionTick } from "./evolutionAxis";

it("uses regular well-spaced ticks, includes zero and contains every finite value", () => {
  for (const values of [
    [0.12, 1.01], [-1.01, -0.12], [-0.34, 0.85], [0.001, 0.009],
    [-0.009, 0.001], [-12.8, 31.2], [0], [0.4], [], [NaN, Infinity],
  ]) for (const height of [80, 137, 237, 400]) {
    const axis = evolutionAxis(values, height);
    expect(axis.ticks).toContain(0);
    expect(axis.max).toBeGreaterThan(axis.min);
    expect(height / (axis.ticks.length - 1)).toBeGreaterThanOrEqual(26);
    expect(new Set(axis.ticks.map((v) => evolutionTick(v, axis.step))).size)
      .toBe(axis.ticks.length);
    for (const v of values.filter(Number.isFinite)) {
      expect(axis.min).toBeLessThanOrEqual(v);
      expect(axis.max).toBeGreaterThanOrEqual(v);
    }
    for (let j = 1; j < axis.ticks.length; j++)
      expect(axis.ticks[j] - axis.ticks[j - 1]).toBeCloseTo(axis.step, 10);
  }
});

it("does not bunch a padded negative bound next to zero for the reported positive range", () => {
  const axis = evolutionAxis([0.12, 1.01], 137);
  expect(axis.ticks).toEqual([0, 0.25, 0.5, 0.75, 1, 1.25]);
  expect(axis.ticks.map((v) => evolutionTick(v, axis.step)))
    .toEqual(["0.00", "0.25", "0.50", "0.75", "1.00", "1.25"]);
});
