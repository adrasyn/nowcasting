import { test, expect } from "@playwright/test";
import combo from "../data/latest_combo.json";
import comboIndicators from "../data/indicators_combo.json";
import v2Indicators from "../data/indicators_v2.json";
import history from "../data/nowcast_history_combo.json";
import performance from "../data/performance_combo.json";
import { loadDashboardData } from "../src/lib/data";
import { buildMonitorView, percentage, monthLabel } from "../src/lib/monitor";
import {
  indicatorChart,
  latestValue,
  rawChange,
  relativeChange,
} from "../src/lib/monitor/indicators";
import { compareDisplayedUpdates } from "../src/lib/monitor/indicatorDates.mjs";
import type { Indicator } from "../src/lib/types";
const view = buildMonitorView(loadDashboardData());
test("homepage publishes current real data, complete history, inline methodology and exact values", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Australia GDP nowcast", exact: true }),
  ).toBeVisible();
  for (const h of [view.current, view.next]) {
    const c = page.locator(`.estimate[data-quarter="${h.quarter}"]`);
    await expect(c.locator("[data-value=qoq]")).toHaveText(percentage(h.qoq));
    await expect(c.locator("[data-value=yoy]")).toHaveText(percentage(h.yoy));
  }
  await expect(page.locator(".series-row")).toHaveCount(
    comboIndicators.indicators.length,
  );
  await expect(page.locator("#weekly-tables tbody tr")).toHaveCount(
    history.runs.length,
  );
  await expect(page.locator("#record-table tbody tr")).toHaveCount(
    performance.errors.length,
  );
  await expect(page.locator("#methodology")).toContainText(
    "New York Fed Staff Nowcast 2.0",
  );
  await expect(page.locator("#methodology")).toContainText(
    "Research Discussion Paper 2024-04",
  );
  await expect(page.locator("#methodology")).toContainText("average error");
  await expect(page.getByRole("slider")).toHaveCount(0);
  await expect(page.locator("input[type=search],select")).toHaveCount(0);
  expect(await page.locator("dialog").count()).toBe(0);
});
test("all indicators retain corrected values, raw histories, survey points and rate semantics", async ({
  page,
}) => {
  await page.goto("/");
  for (const source of comboIndicators.indicators) {
    const i = source as Indicator,
      row = page.locator(`#series-${i.id}`),
      rel = relativeChange(i);
    await expect(row.locator(".series-latest")).toContainText(
      latestValue(i, i.series.at(-1)!.value),
    );
    await expect(row.locator(".series-delta")).toContainText(rawChange(i));
    await expect(row.locator(".series-relative")).toHaveText(
      rel === null ? "—" : percentage(rel),
    );
    expect(await row.locator(".observation-list [role=listitem]").count()).toBe(
      i.series.length,
    );
  }
  for (const id of ["employment", "credit", "cpi", "nab_cu", "hours", "gdp"]) {
    const row = page.locator(`#series-${id}`);
    await row.locator("summary").click();
    await expect(row.locator(".series-chart svg")).toBeVisible();
    await expect(row.locator(".observation-list")).toBeVisible();
  }
  await expect(page.locator("#series-nab_cu .detail-heading")).toContainText(
    "percent",
  );
});
test("ANZ check remains a retrieval date with provisional period and source; job ads unaffected", async ({
  page,
}) => {
  await page.goto("/");
  const i = comboIndicators.indicators.find(
      (r) => r.id === "anz_sent",
    )! as Indicator,
    row = page.locator("#series-anz_sent");
  await expect(row.locator("summary")).toContainText(
    monthLabel(i.series.at(-1)!.date),
  );
  if (i.series.at(-1)!.provisional)
    await expect(row.locator("summary .provisional")).toHaveAttribute(
      "aria-label",
      "Provisional",
    );
  await expect(row.locator(".series-release")).toHaveAttribute(
    "data-update-kind",
    "checked",
  );
  await expect(row.locator(".series-release time")).toHaveAttribute(
    "datetime",
    i.source_checked_at!.slice(0, 10),
  );
  await expect(row.locator(".series-release .visually-hidden")).toHaveText(
    "Checked",
  );
  await row.locator("summary").click();
  await expect(row.locator(".detail-meta")).toContainText("Last released—");
  await expect(row).toContainText(
    "Monthly average; provisional observations are labelled",
  );
  await expect(
    row.getByRole("link", { name: "Official monthly source" }),
  ).toHaveAttribute("href", i.source_url!);
  await expect(page.locator("#series-job_ads .series-release")).toHaveAttribute(
    "data-update-kind",
    "updated",
  );
});
test("dates are globally sorted and mini/detail chart types, units and values match", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  const ids = await page
    .locator(".series-row")
    .evaluateAll((rows) => rows.map((r) => r.id));
  expect(ids).toEqual(
    [...comboIndicators.indicators]
      .sort(compareDisplayedUpdates)
      .map((i) => "series-" + i.id),
  );
  for (const id of [
    "employment",
    "ft_emp",
    "pt_emp",
    "hours",
    "credit",
    "cpi",
    "gdi",
    "gdp",
    "unit_labour_cost",
    "nab_conditions",
  ]) {
    const row = page.locator("#series-" + id);
    await row.locator("summary").click();
    const mini = row.locator(".spark svg"),
      detail = row.locator(".series-chart svg"),
      source = indicatorChart(
        comboIndicators.indicators.find((i) => i.id === id)! as Indicator,
      );
    await expect(mini).toBeVisible();
    for (const attr of [
      "data-chart-type",
      "data-chart-unit",
      "data-last-date",
      "data-last-value",
    ])
      expect(await mini.getAttribute(attr)).toEqual(
        await detail.getAttribute(attr),
      );
    await expect(mini).toHaveAttribute("data-chart-type", source.kind);
    expect(await mini.locator("text,.zero-guide").count()).toBe(0);
    if (source.transformed)
      await expect(row.locator(".observations h4")).toContainText("levels");
    await row.locator("summary").click();
  }
});
test("phone, tablet, landscape and desktop widths, resizing, touch and keyboard charts", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  for (const width of [320, 375, 390, 667, 844, 1024, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(page.locator(".estimate")).toHaveCount(2);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    expect(await page.locator(".spark").first().isVisible()).toBe(
      width >= 1024,
    );
    expect(
      await page
        .locator(".page-header p")
        .evaluateAll((p) => p.map((n) => getComputedStyle(n).fontSize)),
    ).toEqual(["12px", "12px"]);
    await expect.poll(()=>page.locator('#path-chart svg').evaluate(svg=>Math.abs(svg.getBoundingClientRect().width-(svg as SVGSVGElement).viewBox.baseVal.width))).toBeLessThan(1);
    const row = page.locator("#series-employment");
    await row.locator("summary").click();
    await expect(row.locator(".series-chart svg")).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await row.locator("summary").click();
  }
  await page.setViewportSize({ width: 390, height: 844 });
  const row = page.locator("#series-employment");
  await row.locator("summary").click();
  const points = row.locator(".series-chart [data-point]");
  await points.last().focus();
  await page.keyboard.press("Home");
  await expect(points.first()).toBeFocused();
  await expect(points.first()).toHaveAttribute("aria-pressed", "true");
  await page.keyboard.press("End");
  await expect(points.last()).toBeFocused();
  await points.nth(4).dispatchEvent("click");
  await expect(points.nth(4)).toHaveAttribute("aria-pressed", "true");
  const tabs = page.getByRole("tab");
  await tabs.first().focus();
  await page.keyboard.press("ArrowRight");
  await expect(tabs.last()).toHaveAttribute("aria-selected", "true");
  await expect(tabs.last()).toBeFocused();
  await page.keyboard.press("Home");
  await expect(tabs.first()).toHaveAttribute("aria-selected", "true");
  expect(errors).toEqual([]);
});
test("reduced motion is final immediately, fonts load locally, and sheen follows current role", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await page.evaluate(() => document.fonts.ready);
  expect(
    await page
      .locator(".estimate.current")
      .evaluate((el) => getComputedStyle(el, "::after").animationName),
  ).toBe("none");
  expect(
    await page.evaluate(
      () =>
        document.getAnimations().filter((a) => a.playState === "running")
          .length,
    ),
  ).toBe(0);
  expect(
    await page
      .locator("main")
      .evaluate((el) => getComputedStyle(el).fontFamily),
  ).toContain("Monitor Inter");
  await expect(page.locator(".estimate.next")).toHaveCSS("box-shadow", "none");
});
test("/v3 remains a homepage alias", async ({ page }) => {
  await page.goto("/v3");
  await expect(page.locator(".series-row")).toHaveCount(
    comboIndicators.indicators.length,
  );
  await expect(page.locator(".estimate.current [data-value=qoq]")).toHaveText(
    percentage(view.current.qoq),
  );
});
// The standalone v2 route retains its own data and existing presentation.
test("/v2 serves v2 and keeps its corrected survey/rate and ANZ semantics", async ({
  page,
}) => {
  await page.goto("/v2");
  await expect(page.getByText(/growth this quarter/).first()).toBeVisible();
  await page
    .getByRole("button", { name: /Employment/ })
    .first()
    .click();
  await expect(page.getByText(/Jobs & labour · 000s persons/)).toBeVisible();
  await expect(page.getByText(/Labor · Thousands/)).toHaveCount(0);
  for (const id of ["nab_cond", "ue", "nab_cu", "nab_trade", "nab_emp"]) {
    const ind = v2Indicators.indicators.find((r) => r.id === id)!,
      latest = ind.series.at(-1)!.value,
      delta = latest - ind.series.at(-2)!.value,
      rate = ["ue", "nab_cu"].includes(id),
      dp = rate || ind.unit.toLowerCase() === "index" ? 1 : 0,
      sign = delta > 0 ? "+" : delta < 0 ? "−" : "";
    const row = page
      .getByRole("row")
      .filter({ has: page.getByRole("cell", { name: ind.name, exact: true }) });
    await expect(row.getByRole("cell").nth(1)).toHaveText(
      `${latest.toFixed(dp)}${rate ? "%" : ""}`,
    );
    await expect(row.getByRole("cell").nth(2)).toHaveText(
      `${sign}${Math.abs(delta).toFixed(dp)}${rate ? "pp" : " pts"}`,
    );
    await expect(row.getByRole("cell").nth(3)).toHaveText("—");
  }
  const row = page.getByRole("row").filter({
    has: page.getByRole("cell", {
      name: "Consumer confidence (ANZ)",
      exact: true,
    }),
  });
  await expect(row.getByRole("cell").nth(4)).toContainText("Checked");
  await expect(row.getByRole("cell").nth(5)).toHaveText("—");
  await page
    .getByRole("button", { name: /Consumer confidence \(ANZ\)/ })
    .click();
  await expect(
    page.getByRole("link", { name: "Official monthly source" }),
  ).toHaveAttribute("href", /monthly-ratings$/);
});
