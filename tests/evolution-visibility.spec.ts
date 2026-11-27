import { test, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { loadDashboardData } from "../src/lib/data";
import { buildMonitorView, percentage } from "../src/lib/monitor";
const production = buildMonitorView(loadDashboardData());
test.beforeEach(() => {
  test.skip(
    !production.current.runs.length,
    "No published weekly points for the current target",
  );
});
const chart = "#path-chart svg";
async function progress(page: import("@playwright/test").Page) {
  return page.locator(chart).evaluate((svg) => {
    const p = svg.querySelector<SVGPathElement>(".chart-line")!,
      l = p.getTotalLength(),
      offset = parseFloat(getComputedStyle(p).strokeDashoffset) || 0;
    return {
      fraction:
        getComputedStyle(p).visibility === "hidden" ? 0 : 1 - offset / l,
      state: svg.getAttribute("data-evolution-motion"),
      visibility: getComputedStyle(p).visibility,
      animations: svg
        .getAnimations({ subtree: true })
        .map((a) => ({ time: a.currentTime, state: a.playState })),
    };
  });
}
async function initialized(page: import("@playwright/test").Page) {
  // A cold WebKit page can expose the intentionally complete SSR fallback
  // before hydration. Test the animation only after enhancement has initialized.
  await expect(page.locator(chart)).toHaveAttribute(
    "data-evolution-motion",
    /waiting|priming|playing|paused|done/,
  );
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
  await initialized(page);
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
  expect(
    waiting.fraction,
    JSON.stringify({
      state: waiting.state,
      visibility: waiting.visibility,
      time: waiting.animations[0]?.time,
    }),
  ).toBeCloseTo(0, 3);
  expect(waiting.animations.length).toBeGreaterThan(0);
  expect(
    waiting.animations.every((a) => a.time === 0 && a.state === "paused"),
  ).toBe(true);
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
  await page.evaluate(() => scrollTo(0, 0));
  await expect(page.locator(chart)).toHaveAttribute(
    "data-evolution-motion",
    "paused",
  );
  const paused = (await progress(page)).fraction;
  await page.waitForTimeout(400);
  expect((await progress(page)).fraction).toBeCloseTo(paused, 4);
  await reveal(page);
  await expect
    .poll(async () => (await progress(page)).fraction)
    .toBeGreaterThan(paused);
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
  await initialized(page);
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
  if (!production.next.runs.length) {
    await expect(
      page.getByText("Awaiting published estimates for this quarter."),
    ).toBeVisible();
    await page.getByRole("tab").first().click();
  }
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
}, info) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await initialized(page);
  if (production.current.finalEstimate) {
    const sequence = await page.locator(chart).evaluate((svg) => new Promise((resolve) => {
      const line = svg.querySelector<SVGPathElement>(".chart-line")!;
      const reveal = svg.querySelector<SVGRectElement>(".trail-reveal")!;
      const trail = svg.querySelector("[data-final-trail]")!;
      const deadline = performance.now() + 10000;
      let solidMoved = false, trailMoved = false, earlyTrail = false;
      function inspect() {
        const dash = parseFloat(getComputedStyle(line).strokeDashoffset) || 0;
        const width = reveal.getBBox().width, full = reveal.width.baseVal.value;
        if (dash > 0.01 && dash < line.getTotalLength() - 0.01) {
          solidMoved = true;
          earlyTrail ||= width > 0.01;
        }
        trailMoved ||= dash < 0.01 && width > 0.01 && width < full - 0.01;
        if (svg.getAttribute("data-evolution-motion") === "done" || performance.now() > deadline) {
          resolve({ solidMoved, trailMoved, earlyTrail, fullWidth: Math.abs(width - full) < 0.01,
            dashPattern: trail.getAttribute("stroke-dasharray") });
        } else requestAnimationFrame(inspect);
      }
      inspect();
    }));
    expect(sequence).toEqual({
      solidMoved: true, trailMoved: true, earlyTrail: false, fullWidth: true, dashPattern: "4 3",
    });
  } else {
    await expect
      .poll(async () => (await progress(page)).fraction)
      .toBeGreaterThan(0.02);
  }
  await expect
    // The visible-frame clock intentionally caps elapsed time after blocked
    // paints. Busy WebKit screenshot workers may need more wall time. Require
    // the exact completed/unmasked state, rather than weakening the endpoint.
    .poll(() => progress(page), { timeout: 10000, intervals: [100, 200, 300] })
    .toMatchObject({ fraction: 1, state: "done", animations: [] });
  await expect(page.locator(chart + " .chart-line")).not.toHaveAttribute(
    "style",
    /stroke-dash/,
  );
  const geometry = await page.locator(chart).evaluate((el) => {
    const svg = el as SVGSVGElement, view = svg.viewBox.baseVal;
    const mask = svg.querySelector<SVGRectElement>(".band-reveal")!.getBBox();
    const point = svg.querySelector('[data-point][aria-pressed="true"]')!;
    const marker = point.querySelector("circle")!;
    const ticks = [...svg.querySelectorAll<SVGGElement>("[data-evolution-tick]")]
      .map(g => Number(g.dataset.evolutionTick));
    return { width: view.width, height: view.height, maskWidth: mask.width,
      maskHeight: mask.height, hasDot: !!point.querySelector("[data-visible-point]"),
      x: Number(marker.getAttribute("cx")),
      y: Number(marker.getAttribute("cy")), label: point.getAttribute("aria-label"),
      min: Math.min(...ticks), max: Math.max(...ticks) };
  });
  expect(geometry.maskWidth).toBeCloseTo(geometry.width, 6);
  expect(geometry.maskHeight).toBeCloseTo(geometry.height, 6);
  const last = production.current.runs.at(-1)!;
  expect(geometry.label).toContain(percentage(last.qoq_growth_pct));
  expect(geometry.y).toBeCloseTo(15 +
    ((geometry.max - last.qoq_growth_pct) / (geometry.max - geometry.min)) *
    (geometry.height - 43), 6);
  const finalMarker = page.locator(chart + " [data-final-marker]");
  const completedOn = await finalMarker.count() ? await finalMarker.getAttribute("data-final-marker") : null;
  expect(geometry.hasDot).toBe(!completedOn || last.run_date <= completedOn);
  // The active dot, when present, has to be fully opaque after the draw.
  // Post-completion runs instead retain their hit target without a dot.
  // Sampling pixels ignores PNG compression/metadata differences between engines.
  const png = await page.locator(chart).screenshot({ path: info.outputPath("completed-unmasked.png") });
  const rgb = JSON.parse(execFileSync("python3", ["-c", `
import sys,io,json
from PIL import Image
p=json.loads(sys.argv[1]); im=Image.open(io.BytesIO(sys.stdin.buffer.read())).convert('RGB')
print(json.dumps(im.getpixel((round(p['x']/p['width']*im.width),round(p['y']/p['height']*im.height)))))
`, JSON.stringify(geometry)], { input: png }).toString());
  if (geometry.hasDot) expect(rgb).toEqual([12, 242, 93]);
  else expect(rgb).not.toEqual([12, 242, 93]);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

declare global {
  interface Window {
    __plotPaintProbe?: { before: number; after?: number; firstFrame?: number };
  }
}
test("a delayed phone paint cannot skip the beginning of the draw", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 664 });
  await page.addInitScript(() => {
    new MutationObserver((records) => {
      for (const record of records) {
        const svg = record.target;
        if (
          !(svg instanceof SVGSVGElement) ||
          svg.dataset.evolutionMotion !== "playing" ||
          window.__plotPaintProbe
        )
          continue;
        const path = svg.querySelector<SVGPathElement>(".chart-line")!;
        const fraction = () =>
          1 -
          (parseFloat(getComputedStyle(path).strokeDashoffset) || 0) /
            path.getTotalLength();
        const probe = (window.__plotPaintProbe = {
          before: fraction(),
          after: 0,
          firstFrame: 0,
        });
        const start = performance.now();
        while (performance.now() - start < 650) {
          /* Simulate a blocked phone paint. */
        }
        probe.after = fraction();
        requestAnimationFrame(() => (probe.firstFrame = fraction()));
      }
    }).observe(document, {
      subtree: true,
      attributes: true,
      attributeFilter: ["data-evolution-motion"],
    });
  });
  await page.goto("/");
  await reveal(page);
  await expect
    .poll(() => page.evaluate(() => window.__plotPaintProbe?.after))
    .toBeDefined();
  const probe = await page.evaluate(() => window.__plotPaintProbe!);
  expect(probe.before).toBeCloseTo(0, 3);
  expect(probe.after).toBeCloseTo(0, 3);
  expect(probe.firstFrame).toBeLessThan(0.12);
  await expect
    .poll(async () => (await progress(page)).fraction)
    .toBeCloseTo(1, 3);
});

test("no-JavaScript and reduced-motion evolution fallbacks remain complete", async ({
  browser,
}) => {
  for (const options of [
    { javaScriptEnabled: false },
    { reducedMotion: "reduce" as const },
  ]) {
    const page = await browser.newPage(options);
    await page.goto("/");
    const state = await progress(page);
    expect(state.fraction).toBeCloseTo(1, 3);
    expect(state.animations).toEqual([]);
    await expect(page.locator(chart + " .chart-line")).toBeVisible();
    await page.close();
  }
});

test("keyboard focus can enter an offscreen plot and keeps the selected point visible", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 664 });
  await page.goto("/");
  await initialized(page);
  await page.getByRole("tab").last().focus();
  await page.keyboard.press("Tab");
  const point = page.locator(chart + ' [data-point][tabindex="0"]');
  await expect(point).toBeFocused();
  await expect(point).toHaveCSS("opacity", "1");
  await page.keyboard.press("ArrowLeft");
  const previous = page.locator(chart + ' [data-point][tabindex="0"]');
  await expect(previous).toBeFocused();
  await expect(previous).toHaveCSS("opacity", "1");
});
