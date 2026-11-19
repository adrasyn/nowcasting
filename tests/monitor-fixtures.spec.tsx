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
    for (const width of [375, 390, 1440]) {
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
