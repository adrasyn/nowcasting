import { test, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";
import type { Page } from "@playwright/test";
import { loadDashboardData } from "../src/lib/data";
import { buildMonitorView, percentage } from "../src/lib/monitor";

const data = loadDashboardData(), view = buildMonitorView(data);
const commit = process.env.NOWCAST_EXPECTED_COMMIT ??
  execFileSync("git", ["rev-parse", "HEAD"], { encoding: "utf8" }).trim();
const inputs = view.indicators.indicators;

async function identity(page: Page) {
  await expect(page.locator('meta[name="build-commit"]')).toHaveAttribute("content", commit);
}
async function estimates(page: Page) {
  for (const h of [view.current, view.next]) {
    const card = page.locator(`.estimate.${h.role}`);
    await expect(card.locator("[data-value=qoq]")).toHaveText(percentage(h.qoq));
    await expect(card.locator("[data-value=yoy]")).toHaveText(percentage(h.yoy));
    await expect(card).toHaveAttribute("data-state", h.state);
  }
}
test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
});

test("publish: exact candidate, current estimates and complete history", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  expect((await page.goto("/"))?.status()).toBe(200);
  await identity(page);
  await estimates(page);
  await expect(page.locator(".series-row")).toHaveCount(inputs.length);
  await expect(page.locator("#weekly-tables tbody tr")).toHaveCount(view.history.length);
  await expect(page.locator("#record-table tbody tr")).toHaveCount(view.performance?.errors.length ?? 0);
});

test("publish: phone navigation, quarter views and indicator disclosure", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.evaluate(() => document.fonts.ready);
  const initial = page.locator("#path-chart svg");
  if (await initial.count())
    await expect.poll(() => initial.evaluate(svg => Math.abs(
      svg.getBoundingClientRect().width - (svg as SVGSVGElement).viewBox.baseVal.width,
    ))).toBeLessThan(0.75);
  const tabs = page.getByRole("tab");
  for (let j = 0; j < await tabs.count(); j++) {
    await tabs.nth(j).click();
    await expect(tabs.nth(j)).toHaveAttribute("aria-selected", "true");
    const svg = page.locator("#path-chart svg");
    if (await svg.count()) {
      await expect(svg.locator(".chart-line")).toHaveCount(1);
      expect(await svg.locator("[data-evolution-tick]").count()).toBeGreaterThanOrEqual(3);
    } else await expect(page.getByText("Awaiting published estimates for this quarter.")).toBeVisible();
  }
  const input = inputs.find(i => i.series.some(p => p.value !== null));
  if (input) {
    const row = page.locator(`#series-${input.id}`);
    await row.locator("summary").click();
    await expect(row.locator(".series-detail")).toBeVisible();
    await expect(row.locator(".observation-list [role=listitem]")).toHaveCount(input.series.length);
  }
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(errors).toEqual([]);
});

test("publish: simple page stays static and serves its two GIFs", async ({ page }) => {
  const requests: string[] = [];
  page.on("request", r => requests.push(new URL(r.url()).pathname));
  const response = await page.goto("/simple/");
  await page.waitForLoadState("networkidle");
  expect(response?.status()).toBe(200);
  await identity(page);
  expect(await response!.text()).not.toMatch(/<script|<style|<svg|_next\//);
  expect(requests.sort()).toEqual(["/simple/", "/simple/nowcast.gif", "/simple/record.gif"]);
  await expect(page.getByRole("heading", { name: "Australian GDP nowcast", exact: true })).toBeVisible();
  await expect(page.locator("pre")).toHaveCount(
    (data.indicatorsCombo ?? data.indicatorsV3)?.indicators.length ?? 0,
  );
});

test("publish: v3 remains the current homepage alias", async ({ page }) => {
  expect((await page.goto("/v3"))?.status()).toBe(200);
  await estimates(page);
  await expect(page.locator(".series-row")).toHaveCount(inputs.length);
});

test("publish: the standalone v2 route remains available", async ({ page }) => {
  expect((await page.goto("/v2"))?.status()).toBe(200);
  await expect(page.getByRole("heading", { name: "Australia GDP nowcast", exact: true })).toBeVisible();
  await expect(page.locator("main")).toBeVisible();
});

test("publish: no-JavaScript estimates and history remain complete", async ({ browser }) => {
  const page = await browser.newPage({ javaScriptEnabled: false });
  await page.goto("/");
  await identity(page);
  await estimates(page);
  await expect(page.locator(".series-row")).toHaveCount(inputs.length);
  await expect(page.locator("#weekly-tables tbody tr")).toHaveCount(view.history.length);
  await page.close();
});
