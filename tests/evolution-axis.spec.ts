import "./indicator-reveal.cases";
import { test, expect } from "@playwright/test";
import { buildMonitorView, bandFor } from "../src/lib/monitor";
import { loadDashboardData } from "../src/lib/data";
const view = buildMonitorView(loadDashboardData());

for (const width of [375, 390, 1440])
  test(`evolution y-axis has regular readable ticks and contains both quarters' bands at ${width}px`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 1000 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    const commit = process.env.NOWCAST_EXPECTED_COMMIT;
    await page.goto(`/?axis-check=${commit ?? "local"}-${Date.now()}`);
    if (commit)
      await expect(page.locator('meta[name="build-commit"]')).toHaveAttribute("content", commit);
    await page.evaluate(() => document.fonts.ready);
    const tabs = page.getByRole("tab", { name: /^Q[1-4] \d{4}$/ });
    const initial = page.locator("#path-chart svg");
    if (await initial.count())
      await expect.poll(() => initial.evaluate(svg => Math.abs(
        svg.getBoundingClientRect().width - (svg as SVGSVGElement).viewBox.baseVal.width,
      ))).toBeLessThan(0.75);
    for (const [j, horizon] of [view.current, view.next].entries()) {
      await tabs.nth(j).click();
      await expect(tabs.nth(j)).toHaveAttribute("aria-selected", "true");
      const svg = page.locator("#path-chart svg");
      if (!(await svg.count())) {
        await expect(page.getByText("Awaiting published estimates for this quarter.")).toBeVisible();
        continue;
      }
      await expect.poll(() => svg.evaluate(el => Math.abs(
        el.getBoundingClientRect().width - (el as SVGSVGElement).viewBox.baseVal.width,
      ))).toBeLessThan(0.75);
      const axis = await svg.evaluate(el => {
        const chart = el.getBoundingClientRect();
        const ticks = [...el.querySelectorAll<SVGGElement>("[data-evolution-tick]")].map(g => {
          const text = g.querySelector("text")!;
          const b = text.getBoundingClientRect();
          return { value: Number(g.dataset.evolutionTick), label: text.textContent,
            top: b.top, bottom: b.bottom, left: b.left - chart.left,
            font: parseFloat(getComputedStyle(text).fontSize) };
        });
        const h = (el as SVGSVGElement).viewBox.baseVal.height;
        return { ticks, bandsInside: [...el.querySelectorAll<SVGPathElement>(".band-fill")]
          .every(path => { const b = path.getBBox(); return b.y >= 14.5 && b.y + b.height <= h - 27.5; }) };
      });
      expect(axis.ticks.length).toBeGreaterThanOrEqual(3);
      expect(axis.ticks.length).toBeLessThanOrEqual(6);
      expect(axis.ticks.map(t => t.value)).toContain(0);
      expect(new Set(axis.ticks.map(t => t.label)).size).toBe(axis.ticks.length);
      const min = axis.ticks[0].value, max = axis.ticks.at(-1)!.value;
      const step = axis.ticks[1].value - min;
      for (let i = 1; i < axis.ticks.length; i++) {
        expect(axis.ticks[i].value - axis.ticks[i - 1].value).toBeCloseTo(step, 10);
        expect(axis.ticks[i - 1].top - axis.ticks[i].bottom).toBeGreaterThanOrEqual(8);
      }
      for (const tick of axis.ticks) {
        expect(tick.left).toBeGreaterThanOrEqual(-0.5);
        expect(tick.font).toBeGreaterThanOrEqual(11);
      }
      for (const value of horizon.runs.flatMap(r => [
        r.qoq_growth_pct, ...(bandFor(r, 68) ?? []), ...(bandFor(r, 95) ?? []),
      ])) {
        expect(value).toBeGreaterThanOrEqual(min);
        expect(value).toBeLessThanOrEqual(max);
      }
      expect(axis.bandsInside).toBe(true);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await page.locator(".evolution-block").screenshot({ path: info.outputPath(`${j}-regular-axis.png`) });
    }
  });
