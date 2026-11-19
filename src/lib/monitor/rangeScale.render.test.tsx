import * as React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { it, expect } from "vitest";
import fs from "node:fs";
import Monitor from "../../components/monitor/Monitor";
import { fixtureViews } from "../../../tests/fixtures/monitor";
import { fixturePath } from "../../../tests/fixtures/path";
import { sharedQuarterRangeBound } from "./rangeScale";
import { rangeFrame } from "./entrance";
it("renders typical, widened, and missing-quarter shared ranges without clipping or changing values", () => {
  const typical = fixtureViews().weekly,
    widened = structuredClone(typical),
    missing = structuredClone(typical);
  widened.current.qoq = 1.2;
  widened.current.band95 = [-0.2, 1.65];
  widened.next.qoq = -1.3;
  widened.next.band95 = [-2.05, -0.55];
  missing.current.band95 = [-1.27, 1.41];
  missing.next = {
    ...missing.next,
    state: "waiting",
    qoq: null,
    yoy: null,
    band68: null,
    band95: null,
  };
  const fixtures = { typical, widened, missing };
  for (const [name, v] of Object.entries(fixtures)) {
    const bound = sharedQuarterRangeBound([v.current, v.next]);
    expect(bound).toBe(name === "typical" ? 1 : name === "widened" ? 2.5 : 1.5);
    for (const h of [v.current, v.next])
      for (const time of [0, 100, 500, 900, 1500, 1740, 4000]) {
        const frame = rangeFrame(h, time);
        for (const value of [
          frame.marker,
          ...(frame.band68 ?? []),
          ...(frame.band95 ?? []),
        ])
          if (value !== null)
            expect(Math.abs(value)).toBeLessThanOrEqual(bound);
      }
  }
  fs.writeFileSync(
    fixturePath.replace(".json", "-ranges.json"),
    JSON.stringify(
      Object.fromEntries(
        Object.entries(fixtures).map(([name, v]) => [
          name,
          renderToStaticMarkup(<Monitor view={v} />),
        ]),
      ),
    ),
  );
});
