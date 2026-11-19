import { test, expect, Page } from "@playwright/test";
import { loadDashboardData } from "../src/lib/data";
import { buildMonitorView, percentage } from "../src/lib/monitor";
import { displayedSteps } from "../src/lib/monitor/entrance";
const view = buildMonitorView(loadDashboardData()),
  values = [view.current.qoq, view.current.yoy, view.next.qoq, view.next.yoy];
async function scene(page: Page) {
  return page.evaluate(() => ({
    values: [
      ...document.querySelectorAll<HTMLElement>(".value-counter-visual"),
    ].map((el) => el.dataset.display),
    final: [...document.querySelectorAll(".value-counter-final")].map(
      (el) => el.textContent,
    ),
    boxes: [...document.querySelectorAll(".estimate")].map((el) => {
      const b = el.getBoundingClientRect();
      return { x: b.x, y: b.y, width: b.width, height: b.height };
    }),
    ranges: [...document.querySelectorAll(".range-graphic svg")].map((svg) => ({
      width: svg.getBoundingClientRect().width,
      marker: Number(
        svg.querySelector("[data-estimate-marker]")?.getAttribute("x1"),
      ),
      bands: [...svg.querySelectorAll("[data-band]")].map((el) => ({
        n: Number(el.getAttribute("data-band")),
        x: Number(el.getAttribute("x")),
        width: Number(el.getAttribute("width")),
      })),
    })),
  }));
}
for (const width of [375, 390, 1440])
  test(`value and uncertainty entrances: exact start, mid, end and stable layout at ${width}px`, async ({
    page,
    browser,
  }, testInfo) => {
    const viewport = { width, height: width < 500 ? 844 : 1000 };
    await page.setViewportSize(viewport);
    const control = await browser.newPage({
      viewport,
      reducedMotion: "reduce",
    });
    await control.goto("/");
    await control.evaluate(() => document.fonts.ready);
    await expect
      .poll(() =>
        control
          .locator(".range-graphic svg")
          .first()
          .evaluate((svg) =>
            Math.abs(
              svg.getBoundingClientRect().width -
                (svg as SVGSVGElement).viewBox.baseVal.width,
            ),
          ),
      )
      .toBeLessThan(0.1);
    const final = await scene(control);
    await control.close();
    const time = new Date("2026-11-19T10:00:00Z");
    await page.clock.install({ time });
    await page.clock.pauseAt(new Date(time.getTime() + 1000));
    await page.goto("/", { waitUntil: "domcontentloaded" });
    await page.evaluate(() => document.fonts.ready);
    await expect(page.locator(".value-counter-visual").first()).toHaveAttribute(
      "data-display",
      displayedSteps(values[0]) ? "0.00%" : percentage(values[0]),
    );
    await expect
      .poll(() =>
        page
          .locator(".range-graphic svg")
          .first()
          .evaluate((svg) =>
            Math.abs(
              svg.getBoundingClientRect().width -
                (svg as SVGSVGElement).viewBox.baseVal.width,
            ),
          ),
      )
      .toBeLessThan(0.1);
    expect(
      await page
        .locator(".value-counter")
        .evaluateAll((els) =>
          els.every(
            (el) =>
              getComputedStyle(el).fontSize ===
              getComputedStyle(el.parentElement!).fontSize,
          ),
        ),
    ).toBe(true);
    const start = await scene(page);
    expect(start.values).toEqual(
      values.map((v) => (displayedSteps(v) ? "0.00%" : percentage(v))),
    );
    expect(start.final).toEqual(values.map(percentage));
    for (const [j, h] of [view.current, view.next].entries()) {
      if (h.qoq === null || !h.band95) continue;
      const ending = final.ranges[j],
        ninetyFive = ending.bands.find((b) => b.n === 95)!;
      const zero =
        ending.marker -
        (h.qoq * ninetyFive.width) / (h.band95[1] - h.band95[0]);
      expect(start.ranges[j].marker).toBeCloseTo(zero, 5);
      for (const b of start.ranges[j].bands) {
        expect(b.width).toBe(0);
        expect(b.x).toBeCloseTo(zero, 5);
      }
    }
    await page.screenshot({ path: testInfo.outputPath("entrance-start.png") });
    await page.clock.runFor(500);
    const mid = await scene(page);
    expect(mid.boxes).toEqual(start.boxes);
    expect(mid.final).toEqual(start.final);
    for (let j = 0; j < mid.ranges.length; j++) {
      for (const b of mid.ranges[j].bands) {
        expect(b.width).toBeGreaterThan(0);
        expect(b.width).toBeLessThan(
          final.ranges[j].bands.find((end) => end.n === b.n)!.width,
        );
      }
      if (values[j * 2] !== null && values[j * 2] !== 0)
        expect(
          Math.abs(mid.ranges[j].marker - final.ranges[j].marker),
        ).toBeLessThan(
          Math.abs(start.ranges[j].marker - final.ranges[j].marker),
        );
    }
    await expect(page.locator(".value-counter-visual").first()).toHaveAttribute(
      "aria-hidden",
      "true",
    );
    expect(await page.locator(".value-counter [aria-live]").count()).toBe(0);
    await page.screenshot({ path: testInfo.outputPath("entrance-mid.png") });
    await page.clock.runFor(3500);
    const end = await scene(page);
    expect(end.values).toEqual(values.map(percentage));
    expect(end.final).toEqual(start.final);
    expect(end.boxes).toEqual(start.boxes);
    expect(end.ranges).toEqual(final.ranges);
    await page.screenshot({ path: testInfo.outputPath("entrance-end.png") });
    await page.clock.runFor(10000);
    expect(await scene(page)).toEqual(end);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
  });
test("reduced motion starts at final values and changing preference completes in place", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await page.evaluate(() => document.fonts.ready);
  const final = await scene(page);
  expect(final.values).toEqual(values.map(percentage));
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.reload();
  await page.emulateMedia({ reducedMotion: "reduce" });
  const end = await scene(page);
  expect(end.values).toEqual(final.values);
  await expect
    .poll(async () => JSON.stringify((await scene(page)).ranges))
    .toBe(JSON.stringify(final.ranges));
  expect(
    await page.evaluate(
      () =>
        document.getAnimations().filter((a) => a.playState === "running")
          .length,
    ),
  ).toBe(0);
});
test("without JavaScript the server output still presents the exact final values", async ({
  browser,
}) => {
  const page = await browser.newPage({ javaScriptEnabled: false });
  await page.goto("/");
  await expect(page.locator("[data-value=qoq]").first()).toHaveText(
    percentage(values[0]),
  );
  expect(
    await page
      .locator(".value-counter-visual")
      .evaluateAll((els) => els.map((el) => el.getAttribute("data-display"))),
  ).toEqual(values.map(percentage));
  await page.close();
});
