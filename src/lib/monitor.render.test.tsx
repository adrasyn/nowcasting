import * as React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { it, expect } from "vitest";
import fs from "node:fs";
import Monitor from "../components/monitor/Monitor";
import { fixtureViews } from "../../tests/fixtures/monitor";
import { fixturePath } from "../../tests/fixtures/path";
it("renders all rollover/refusal/missing fixtures with full historical tables and valid SVG geometry", () => {
  const html = Object.fromEntries(
    Object.entries(fixtureViews()).map(([name, view]) => [
      name,
      renderToStaticMarkup(<Monitor view={view} />),
    ]),
  );
  for (const body of Object.values(html)) {
    expect(body).toContain("Historical data");
    expect(body).not.toMatch(/NaN|Infinity/);
  }
  expect(html.release).toContain("Q4 2026: GDP nowcast");
  expect(html.release).toContain("Q1 2027: GDP nowcast");
  expect(html.year).toContain("Q1 2027: GDP nowcast");
  expect(html.refused).toContain("Test refusal");
  fs.writeFileSync(fixturePath, JSON.stringify(html));
});
