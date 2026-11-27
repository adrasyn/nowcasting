import { expect, test } from "@playwright/test";
import { dayLabel } from "../src/lib/monitor";

test("evolution hover reads the nearest date without clicking and restores the selected date", async ({page}) => {
  await page.setViewportSize({width: 1100, height: 900});
  await page.emulateMedia({reducedMotion: "reduce"});
  await page.goto("/");
  const plot = page.locator("#path-chart svg");
  await plot.scrollIntoViewIfNeeded();
  await expect.poll(() => plot.evaluate(s =>
    Math.abs(s.getBoundingClientRect().width - (s as SVGSVGElement).viewBox.baseVal.width)
  )).toBeLessThan(0.75);
  const points = plot.locator("[data-point]");
  expect(await points.count()).toBeGreaterThan(1);
  const first = points.first(), readout = page.locator(".path-readout p");
  const starting = await readout.innerText();
  const firstDate = (await first.getAttribute("data-run-date"))!;
  const position = (point: typeof first) => point.evaluate(el => {
    const svg = (el as SVGGElement).ownerSVGElement!;
    const b = svg.getBoundingClientRect(), v = svg.viewBox.baseVal;
    const cx = el.querySelector("circle")!.cx.baseVal.value;
    return {x: b.left + b.width * cx / v.width, y: b.top + b.height * 23 / v.height};
  });
  const aim = await position(first);
  await page.mouse.move(aim.x, aim.y);
  await expect(readout).toContainText(dayLabel(firstDate, true));
  await expect(first).toHaveAttribute("aria-pressed", "false");
  await page.mouse.move(2, 2);
  await expect(readout).toHaveText(starting);
  await first.focus();
  await expect(readout).toContainText(dayLabel(firstDate, true));
  await expect(first).toHaveAttribute("aria-pressed", "true");
  const last = points.last(), latest = await position(last);
  await page.mouse.move(latest.x, latest.y);
  await expect(readout).toHaveText(starting);
  await expect(last).toHaveAttribute("aria-pressed", "false");
  await page.mouse.move(2, 2);
  await expect(readout).toContainText(dayLabel(firstDate, true));
});
