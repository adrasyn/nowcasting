import { test, expect } from "@playwright/test";
import fs from "node:fs";
import { fixturePath } from "./fixtures/path";
import { loadDashboardData } from "../src/lib/data";
import { buildMonitorView } from "../src/lib/monitor";
import {
  sharedQuarterRangeBound,
  rangeTick,
} from "../src/lib/monitor/rangeScale";
const v = buildMonitorView(loadDashboardData()),
  bound = sharedQuarterRangeBound([v.current, v.next]);
for (const width of [375, 390, 1440])
  test(`quarter card charts share a symmetric legible scale and exact end data at ${width}px`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/");
    const svgs = page.locator(".range-graphic svg");
    await expect(svgs).toHaveCount(2);
    for (let j = 0; j < 2; j++) {
      const svg = svgs.nth(j),
        h = [v.current, v.next][j];
      await expect(svg).toHaveAttribute("data-range-bound", String(bound));
      if (h.qoq === null) continue;
      await expect(svg.locator("text")).toHaveText(
        [-bound, 0, bound].map(rangeTick),
      );
      const box = await svg.boundingBox();
      expect(box).not.toBeNull();
      await expect
        .poll(() =>
          svg.evaluate((el) =>
            Math.abs(
              el.getBoundingClientRect().width -
                (el as SVGSVGElement).viewBox.baseVal.width,
            ),
          ),
        )
        .toBeLessThan(0.1);
      const w = await svg.evaluate(
          (el) => (el as SVGSVGElement).viewBox.baseVal.width,
        ),
        x = (value: number) => 8 + ((value + bound) / (2 * bound)) * (w - 16);
      await expect
        .poll(async () =>
          Number(
            await svg.locator("[data-estimate-marker]").getAttribute("x1"),
          ),
        )
        .toBeCloseTo(x(h.qoq), 6);
      for (const n of [68, 95] as const) {
        const band = n === 68 ? h.band68 : h.band95;
        if (!band) continue;
        expect(
          Number(await svg.locator(`[data-band="${n}"]`).getAttribute("x")),
        ).toBeCloseTo(x(band[0]), 6);
        expect(
          Number(await svg.locator(`[data-band="${n}"]`).getAttribute("width")),
        ).toBeCloseTo(x(band[1]) - x(band[0]), 6);
      }
      expect(
        await svg
          .locator("text")
          .evaluateAll((els) =>
            els.every((el) => parseFloat(getComputedStyle(el).fontSize) >= 9),
          ),
      ).toBe(true);
    }
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
  });
test("widened and missing-quarter fixtures retain one common scale on phone and desktop", async ({
  page,
}) => {
  const html = JSON.parse(
      fs.readFileSync(fixturePath.replace(".json", "-ranges.json"), "utf8"),
    ),
    css = fs.readFileSync("src/app/monitor.css", "utf8");
  for (const [name, bound] of [
    ["typical", 1],
    ["widened", 2.5],
    ["missing", 1.5],
  ] as const) {
    await page.goto("/");
    await page.setContent(
      '<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{margin:0}' +
        css +
        "</style>" +
        html[name],
    );
    for (const width of [375, 390, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      for (const svg of await page.locator(".range-graphic svg").all())
        await expect(svg).toHaveAttribute("data-range-bound", String(bound));
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
    }
    if (name === "missing") {
      await expect(page.locator(".estimate.next [data-value=qoq]")).toHaveText(
        "—",
      );
      await expect(
        page.locator(".estimate.next [data-estimate-marker]"),
      ).toHaveCount(0);
    }
  }
});
