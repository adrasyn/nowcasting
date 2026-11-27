import fs from "node:fs";
import { test, expect } from "@playwright/test";
import { fixturePath } from "./fixtures/path";
import { fixtureViews } from "./fixtures/monitor";
import { percentage } from "../src/lib/monitor";
// Real payload shape, changed only in isolated test memory. These fixtures are
// never put in data/ or exported by the application. SSR checks cover all text,
// tables and chart geometry; the live-data browser tests cover hydration/actions.
const fixtureHtml = JSON.parse(fs.readFileSync(fixturePath, "utf8"));
const css = fs.readFileSync("src/app/monitor.css", "utf8");
for (const [name, v] of Object.entries(fixtureViews()))
  test(`responsive fixture: ${name}`, async ({ page }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto("/");
    await page.setContent(
      '<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><style>body{margin:0}' +
        css +
        "</style>" +
        fixtureHtml[name],
    );
    for (const width of name === "final" ? [320, 390, 1440] : [375, 390, 1440]) {
      await page.setViewportSize({ width, height: 900 });
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      for (const h of [v.current, v.next]) {
        const card = page.locator(`.estimate.${h.role}`);
        await expect(card.locator("[data-value=qoq]")).toHaveText(
          percentage(h.qoq),
        );
        await expect(card.locator("[data-value=yoy]")).toHaveText(
          percentage(h.yoy),
        );
        await expect(card).toHaveAttribute("data-state", h.state);
      }
      expect(
        await page
          .locator("svg")
          .evaluateAll((svgs) =>
            svgs.every((svg) => !svg.outerHTML.match(/NaN|Infinity/)),
          ),
      ).toBe(true);
    }
    const strip = page.locator(".final-estimate-strip");
    const marker = page.locator("[data-final-marker]");
    const extension = page.locator("[data-final-extension]");
    if (name === "final") {
      await expect(page.locator(".estimate.current > .final-estimate-strip")).toHaveCount(1);
      await expect(page.getByText("Months of data", {exact: true}).first()).toBeVisible();
      for (const width of [320, 390, 1440]) {
        await page.setViewportSize({width, height: 900});
        for (const cardLabel of await page.getByText("Months of data", {exact: true}).all()) {
          const fits = await cardLabel.evaluate(el => {
            const range = document.createRange();
            range.selectNodeContents(el);
            const lines = range.getClientRects();
            const cell = el.parentElement!.getBoundingClientRect();
            return lines.length === 1 && lines[0].right <= cell.right + 0.5;
          });
          expect(fits, `Months of data fits at ${width}px`).toBe(true);
        }
        const visibleParts = await strip.locator("span:visible").allTextContents();
        expect(visibleParts).toHaveLength(1);
        expect(visibleParts[0]).toMatch(/\(excl\. (data )?revisions\)/);
        const widths = await strip.evaluate(e => [e.scrollWidth, e.clientWidth]);
        expect(widths[0], `Status strip at ${width}px (${visibleParts[0]})`).toBeLessThanOrEqual(widths[1]);
      }
      await expect(page.locator(".estimate.next .final-estimate-strip")).toHaveCount(0);
      await expect(page.locator("#path-chart").getByText("Final estimate", {exact: true})).toHaveCount(1);
      await expect(marker).toHaveAttribute("stroke-dasharray", "3 3");
      await expect(extension).toHaveAttribute("stroke-dasharray", "4 3");
      const start = Number(await extension.getAttribute("x1"));
      const end = Number(await extension.getAttribute("x2"));
      expect(end).toBeGreaterThan(start);
      await expect(marker).toHaveAttribute("data-final-marker", "2026-11-16");
      expect(Number(await marker.getAttribute("x1"))).toBeLessThan(start);
      const firstDot = page.locator('#path-chart [data-run-date="2026-11-16"] circle').first();
      expect(await marker.getAttribute("x1")).toBe(await firstDot.getAttribute("cx"));
      const latestDot = page.locator('#path-chart [data-run-date="2026-12-01"] circle').first();
      expect(await extension.getAttribute("x1")).toBe(await latestDot.getAttribute("cx"));
      expect(await extension.getAttribute("y1")).toEqual(await extension.getAttribute("y2"));
      await expect(page.locator("#path-chart .band-fill")).toHaveCount(2);
      for (const shape of await page.locator("#path-chart .band-fill").all())
        expect((await shape.getAttribute("d"))?.split(` L${end},`)).toHaveLength(3);
      await expect(page.locator("#path-chart [data-point]")).toHaveCount(v.current.runs.length);
    } else {
      await expect(strip).toHaveCount(0);
      await expect(marker).toHaveCount(0);
      await expect(extension).toHaveCount(0);
    }
    if (name === "rolled")
      await expect(page.locator(".estimate.current h2")).toHaveText("Q4 2026: GDP nowcast");
    if (name === "component") {
      await expect(page.locator(".estimate.next")).toContainText(
        "Awaiting both model estimates",
      );
      await expect(page.locator(".estimate.next [data-value=qoq]")).toHaveText(
        "—",
      );
    }
    if (name === "release") {
      await expect(page.locator(".estimate.current h2")).toHaveText(
        "Q4 2026: GDP nowcast",
      );
      await expect(page.locator(".estimate.next h2")).toHaveText(
        "Q1 2027: GDP nowcast",
      );
    }
    if (name === "year") {
      await expect(page.locator(".estimate.current h2")).toHaveText(
        "Q1 2027: GDP nowcast",
      );
      await expect(page.locator(".estimate.next")).toHaveAttribute(
        "data-state",
        "waiting",
      );
    }
    if (name === "refused") {
      await expect(page.locator(".data-warning")).toContainText("Test refusal");
      expect(await page.locator("#weekly-tables tbody tr").count()).toBe(
        v.history.length,
      );
    }
    expect(errors).toEqual([]);
  });
