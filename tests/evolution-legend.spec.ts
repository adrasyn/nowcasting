import { test, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";
import type { Locator } from "@playwright/test";

type RGB = [number, number, number];
type Raster = { centre: RGB; palette: [RGB, number][] };
// Pillow is already a required dependency of the simple-page build. Sample
// actual browser screenshots, including SVG/CSS opacity and parent layers.
async function pixels(el: Locator, path: string): Promise<Raster> {
  const png = await el.screenshot({ path });
  return JSON.parse(execFileSync("python3", ["-c", `
import sys,io,json,collections
from PIL import Image
im=Image.open(io.BytesIO(sys.stdin.buffer.read())).convert('RGB')
data=im.get_flattened_data() if hasattr(im,'get_flattened_data') else im.getdata()
print(json.dumps({'centre':im.getpixel((im.width//2,im.height//2)),
 'palette':list(collections.Counter(data).items())}))
`], { input: png }).toString());
}
const near = (a: RGB, b: RGB) => a.every((v, i) => Math.abs(v - b[i]) <= 1);
const over = (under: RGB, alpha: number): RGB =>
  under.map((v, i) =>
    Math.round(v * (1 - alpha) + [12, 242, 93][i] * alpha),
  ) as RGB;

for (const width of [375, 390, 1440])
  for (const colorScheme of ["light", "dark"] as const)
    test(`evolution legend matches rendered line and layered bands at ${width}px in ${colorScheme}`, async ({ page }, info) => {
      await page.setViewportSize({ width, height: 1000 });
      await page.emulateMedia({ reducedMotion: "reduce", colorScheme });
      const commit = process.env.NOWCAST_EXPECTED_COMMIT;
      await page.goto(`/?legend-check=${commit ?? "local"}-${Date.now()}`);
      if (commit)
        await expect(page.locator('meta[name="build-commit"]')).toHaveAttribute("content", commit);
      await page.evaluate(() => document.fonts.ready);
      const initialPlot = page.locator("#path-chart svg");
      if (await initialPlot.count())
        // Reduced motion deliberately adds no animation state. A measured
        // viewBox confirms hydration/layout before clicking the quarter tabs.
        await expect.poll(() => initialPlot.evaluate((svg) => Math.abs(
          svg.getBoundingClientRect().width - (svg as SVGSVGElement).viewBox.baseVal.width,
        ))).toBeLessThan(0.75);
      const tabs = page.getByRole("tab", { name: /^Q[1-4] \d{4}$/ });
      await expect(tabs).toHaveCount(2);
      const measurements = [];
      for (let quarter = 0; quarter < 2; quarter++) {
        await tabs.nth(quarter).click();
        await expect(tabs.nth(quarter)).toHaveAttribute("aria-selected", "true");
        const svg = page.locator("#path-chart svg");
        // After an ABS rollover the next quarter can legitimately have no
        // published history. Do not turn that supported state into a CI failure
        // or create test observations in the application data.
        if (!(await svg.count())) {
          await expect(page.getByText(
            "Awaiting published estimates for this quarter.",
          )).toBeVisible();
          await expect(page.locator(".evolution-block .legend")).toBeVisible();
          measurements.push({
            quarter: await tabs.nth(quarter).textContent(),
            state: "no published estimates",
          });
          continue;
        }
        await expect(svg).toHaveCount(1);
        await expect(svg.locator(".band-fill")).toHaveCount(2);
        const paint = await svg.evaluate((el) => ({
          line: getComputedStyle(el.querySelector(".chart-line")!).stroke,
          bands: [...el.querySelectorAll(".band-fill")].map(p => ({
            fill: getComputedStyle(p).fill,
            opacity: Number(getComputedStyle(p).opacity),
          })),
        }));
        // Preserve the deployed chart palette and its actual drawing order.
        expect(paint).toEqual({
          line: "rgb(3, 65, 89)",
          bands: [
            { fill: "rgb(12, 242, 93)", opacity: 0.15 },
            { fill: "rgb(12, 242, 93)", opacity: 0.35 },
          ],
        });
        const plot = await pixels(svg, info.outputPath(`${quarter}-plot.png`));
        const expected = {
          "line-key": [3, 65, 89] as RGB,
          "band95-key": over([255, 255, 255], paint.bands[0].opacity),
          "band68-key": over(
            over([255, 255, 255], paint.bands[0].opacity),
            paint.bands[1].opacity,
          ),
        };
        for (const key of ["line-key", "band68-key", "band95-key"] as const) {
          const swatch = page.locator(`.evolution-block .legend .${key}`);
          const sample = await pixels(swatch, info.outputPath(`${quarter}-${key}.png`));
          expect(
            near(sample.centre, expected[key]),
            `${key}: actual ${sample.centre}, expected rendered ${expected[key]}`,
          ).toBe(true);
          const plottedPixels = plot.palette
            .filter(([rgb]) => near(rgb, sample.centre))
            .reduce((n, [, count]) => n + count, 0);
          expect(plottedPixels,
            `${key} colour must occur inside the actual plotted chart`,
          ).toBeGreaterThan(5);
          measurements.push({
            quarter: await tabs.nth(quarter).textContent(),
            key, rgb: sample.centre, paint,
          });
        }
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      }
      await info.attach("rendered-legend-colours", {
        body: JSON.stringify(measurements, null, 2),
        contentType: "application/json",
      });
    });
