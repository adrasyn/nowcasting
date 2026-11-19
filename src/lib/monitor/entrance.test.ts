import { describe, it, expect } from "vitest";
import {
  BASE_INCREMENT_MS,
  MAX_VALUE_RUNTIME,
  displayedSteps,
  easeInOut,
  entranceGroup,
  valueDuration,
  valueFrame,
  rangeFrame,
  rangeDurations,
} from "./entrance";
import { fixtureViews } from "../../../tests/fixtures/monitor";
import { percentage } from "../monitor";
describe("one-time nowcast entrance geometry and timing", () => {
  it("shares timing per visible increment, preserves relative finishes and bounds the whole group", () => {
    for (const values of [
      [0.44, 2.07, 0.25, 1.4],
      [-0.12, 0, 12.34, null],
      [20, -30, 0, 0.01],
    ]) {
      const g = entranceGroup(values);
      for (const value of values) {
        expect(valueDuration(value, g)).toBeLessThanOrEqual(MAX_VALUE_RUNTIME);
        if (displayedSteps(value))
          expect(valueDuration(value, g) / displayedSteps(value)).toBeCloseTo(
            g.baseMs,
          );
      }
      const distinct = [...new Set(values.map(displayedSteps))];
      expect(new Set(distinct.map((n) => n * g.baseMs)).size).toBe(
        distinct.length,
      );
    }
    expect(entranceGroup([0.44, 2.07, 0.25, 1.4]).baseMs).toBe(
      BASE_INCREMENT_MS,
    );
  });
  it("uses the same symmetric slow-fast-slow S-curve with exact signed endpoints and precision", () => {
    const g = entranceGroup([2, -0.44]);
    expect(easeInOut(0.25)).toBe(0.15625);
    expect(easeInOut(0.5)).toBe(0.5);
    expect(easeInOut(0.75)).toBe(0.84375);
    expect(valueFrame(2, 0, g)).toBe("0.00%");
    expect(valueFrame(2, 800, g)).toBe("+0.31%");
    expect(valueFrame(2, 1600, g)).toBe("+1.00%");
    expect(valueFrame(2, 2400, g)).toBe("+1.68%");
    expect(valueFrame(2, 3200, g)).toBe("+2.00%");
    expect(valueFrame(-0.44, 352, g)).toBe("−0.22%");
    for (const v of [0, -0.004, 0.004, 2.675, -2.675, null])
      expect(valueFrame(v, MAX_VALUE_RUNTIME, entranceGroup([v]))).toBe(
        percentage(v),
      );
    expect(valueFrame(null, 0, g)).toBe("—");
    expect(valueFrame(0, 0, g)).toBe("0.00%");
  });
  it("moves each estimate from zero while both bands grow from its moving marker and finish exactly", () => {
    for (const v of Object.values(fixtureViews()))
      for (const h of [v.current, v.next]) {
        const times = rangeDurations(h.role),
          g = entranceGroup([h.qoq, h.yoy]);
        expect(valueFrame(h.qoq, valueDuration(h.qoq, g), g)).toBe(
          percentage(h.qoq),
        );
        expect(valueFrame(h.yoy, valueDuration(h.yoy, g), g)).toBe(
          percentage(h.yoy),
        );
        const start = rangeFrame(h, 0),
          end = rangeFrame(h, times.band95);
        expect(end.marker).toBe(h.qoq);
        expect(end.band68).toEqual(h.band68);
        expect(end.band95).toEqual(h.band95);
        if (h.qoq !== null) {
          expect(start.marker).toBe(0);
          if (h.band68) expect(start.band68).toEqual([0, 0]);
          if (h.band95) expect(start.band95).toEqual([0, 0]);
          const middle = rangeFrame(h, times.marker / 2);
          expect(middle.marker).toBeCloseTo(h.qoq / 2);
          for (const n of [68, 95] as const) {
            const source = n === 68 ? h.band68 : h.band95,
              band = n === 68 ? middle.band68 : middle.band95;
            if (source && band)
              expect(band[1] - band[0]).toBeCloseTo(
                (source[1] - source[0]) *
                  easeInOut(times.marker / 2 / times[`band${n}`]),
              );
          }
        }
      }
  });
  it("gives the two rulers deterministic distinct endings and stays finished", () => {
    expect(rangeDurations("current").band95).toBeLessThan(
      rangeDurations("next").band95,
    );
    const h = fixtureViews().release.current;
    expect(rangeFrame(h, 10000)).toEqual(
      rangeFrame(h, rangeDurations(h.role).band95),
    );
  });
});
