import { test, expect } from "@playwright/test";
const chart = "#path-chart svg";
async function progress(page: import("@playwright/test").Page) {
  return page.locator(chart).evaluate((svg) => {
    const p = svg.querySelector<SVGPathElement>(".chart-line")!,
      l = p.getTotalLength(),
      offset = parseFloat(getComputedStyle(p).strokeDashoffset) || 0;
    return {
      fraction: 1 - offset / l,
      state: svg.getAttribute("data-evolution-motion"),
      animations: svg
        .getAnimations({ subtree: true })
        .map((a) => ({ time: a.currentTime, state: a.playState })),
    };
  });
}
async function reveal(page: import("@playwright/test").Page) {
  await page.locator(chart).evaluate((el) => {
    const r = el.getBoundingClientRect();
    scrollTo(0, scrollY + r.top - 100);
  });
}
test("phone: an offscreen draw holds at zero until its first visible paint, then never replays on scroll", async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 390, height: 664 });
  await page.goto("/");
  await page.evaluate(() => scrollTo(0, 0));
  await page.waitForTimeout(800);
  // The actual plotted line is below an iPhone's visual viewport although the
  // chart header (and often the top of its SVG) is already visible.
  expect(
    await page
      .locator(chart + " .chart-line")
      .evaluate(
        (p) =>
          p.getBoundingClientRect().top >=
          (visualViewport?.offsetTop ?? 0) +
            (visualViewport?.height ?? innerHeight),
      ),
  ).toBe(true);
  const waiting = await progress(page);
  expect(waiting.fraction).toBeCloseTo(0, 3);
  await page.screenshot({ path: testInfo.outputPath("offscreen-zero.png") });
  await reveal(page);
  await expect
    .poll(async () => (await progress(page)).fraction)
    .toBeGreaterThan(0.05);
  const middle = await progress(page);
  expect(middle.fraction).toBeLessThan(0.95);
  await page.screenshot({
    path: testInfo.outputPath("first-visible-draw.png"),
  });
  await expect
    .poll(async () => (await progress(page)).fraction)
    .toBeCloseTo(1, 3);
  await page.evaluate(() => scrollTo(0, 0));
  await page.waitForTimeout(500);
  await reveal(page);
  expect((await progress(page)).fraction).toBeCloseTo(1, 3);
});
test("slow font/render readiness preserves frame zero, including quarter switching and reduced motion", async ({
  page,
}) => {
  let release!: () => void;
  const fontGate = new Promise<void>((resolve) => (release = resolve));
  await page.route("**/monitor/fonts/*.ttf", async (route) => {
    await fontGate;
    await route.continue();
  });
  await page.setViewportSize({ width: 390, height: 664 });
  await page.goto("/", { waitUntil: "domcontentloaded" });
  await reveal(page);
  await page.waitForTimeout(800);
  expect((await progress(page)).fraction).toBeCloseTo(0, 3);
  release();
  await page.evaluate(() => document.fonts.ready);
  await expect
    .poll(async () => (await progress(page)).fraction)
    .toBeGreaterThan(0.02);
  await expect
    .poll(async () => (await progress(page)).fraction)
    .toBeCloseTo(1, 3);
  await page.getByRole("tab").last().click();
  await reveal(page);
  await expect
    .poll(async () => (await progress(page)).fraction)
    .toBeGreaterThan(0.02);
  expect((await progress(page)).fraction).toBeLessThan(0.98);
  await page.emulateMedia({ reducedMotion: "reduce" });
  expect((await progress(page)).fraction).toBeCloseTo(1, 3);
  expect((await progress(page)).animations).toEqual([]);
});
test("desktop draw starts after layout and finishes with exact unmasked data", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await expect
    .poll(async () => (await progress(page)).fraction)
    .toBeGreaterThan(0.02);
  await expect
    .poll(async () => (await progress(page)).fraction)
    .toBeCloseTo(1, 3);
  await expect(page.locator(chart)).toHaveAttribute(
    "data-evolution-motion",
    "done",
  );
  await expect(page.locator(chart + " .chart-line")).not.toHaveAttribute(
    "style",
    /stroke-dash/,
  );
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
