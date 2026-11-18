import { test, expect } from "@playwright/test";
import fs from "node:fs";

const latest = JSON.parse(fs.readFileSync("data/latest_combo.json", "utf8"));
const indicators = JSON.parse(fs.readFileSync("data/indicators_combo.json", "utf8"));

test("/simple is current static HTML, with only its two GIF requests", async ({ page }) => {
  const requests: string[] = [];
  page.on("request", (request) => requests.push(new URL(request.url()).pathname));
  const response = await page.goto("/simple/");
  await page.waitForLoadState("networkidle");
  expect(response?.status()).toBe(200);
  const html = await response!.text();
  expect(html).not.toMatch(/<script|<style|<svg|_next\//);
  expect(requests.sort()).toEqual(["/simple/", "/simple/nowcast.gif", "/simple/record.gif"]);
  await expect(page.getByRole("heading", { name: "Australian GDP nowcast", exact: true })).toBeVisible();
  const nowcast = latest.horizons.find((h: { kind: string }) => h.kind === "nowcast");
  await expect(page.locator("#estimates")).toContainText(`${nowcast.qoq_growth_pct.toFixed(2)}%`);
  expect(await page.locator("pre").count()).toBe(indicators.indicators.length);
  expect(await page.locator("body > h2").last().textContent()).toBe("Methodology");
  await page.getByRole("link", { name: "Methodology", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Methodology", exact: true })).toBeVisible();
  await expect(page.getByText(/record above is scored/)).toBeVisible();
  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({ width, height: 900 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    expect(await page.locator("table").evaluateAll(tables => tables.every(t =>
      [...t.querySelectorAll("td,th")].every(c => c.firstElementChild?.tagName === "TT" &&
        getComputedStyle(c.firstElementChild).fontFamily === "monospace")))).toBe(true);
  }
});
