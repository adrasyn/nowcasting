import { test, expect } from "@playwright/test";

// `/` serves v3 and `/v2` serves v2. Both are published weekly by separate
// pipelines, so both need covering: the point of keeping v2 running is that it
// is a live comparison, and a comparison nothing tests is one nobody notices
// breaking.
//
// WHICH MODEL A PAGE SERVES IS PROVEN FROM ITS INDICATOR DATA, NOT ITS PROSE.
// The obvious check — look for the model's name in the methodology panel —
// does not work: `ModelSwitch` describes the OTHER model on every page, so
// "New York Fed Staff Nowcast 2.0" appears on /v2 and "Monthly Activity
// Indicator" appears on /. An assertion on either passes on both pages and
// proves nothing. The indicator detail card reads its group and unit straight
// out of `indicators_v3.json` or `indicators_v2.json`, so "Labor · Thousands"
// and "Jobs & labour · 000s persons" cannot appear on the wrong page.
//
// This matters more than it looks. On 2026-09-01 a branch cut from the wrong
// base carried the homepage swap into an unrelated CI fix, and this suite is
// the only thing that stopped the deploy.

const V3_INDICATOR = /Labor · Thousands/;
const V2_INDICATOR = /Jobs & labour · 000s persons/;

/** Open the first Employment indicator and read its metadata line. */
async function indicatorMeta(page: import("@playwright/test").Page) {
  await page.getByRole("button", { name: /Employment/ }).first().click();
}

test.describe("homepage", () => {
  test("renders the headline nowcast", async ({ page }) => {
    await page.goto("/");
    await expect(
      page.getByRole("heading", { name: "Australia GDP nowcast" })
    ).toBeVisible();
    await expect(page.getByText(/growth this quarter/).first()).toBeVisible();
    await expect(page.locator("svg").first()).toBeVisible();
    // The page names the quarter it publishes in both places it matters: the
    // headline eyebrow, and the column the track record scores against. Both
    // the headline and the next-quarter card carry the same eyebrow form, so
    // `.first()` keeps the locator out of strict mode.
    await expect(
      page.getByText(/Q\d 20\d\d: GDP nowcast$/).first()
    ).toBeVisible();
    await expect(page.getByText("Actual", { exact: true }).first()).toBeVisible();
  });

  test("serves v3, not v2", async ({ page }) => {
    await page.goto("/");
    await indicatorMeta(page);
    await expect(page.getByText(V3_INDICATOR)).toBeVisible();
    await expect(page.getByText(V2_INDICATOR)).toHaveCount(0);
  });

  test("the methodology panel opens", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: /^Methodology/ }).click();
    await expect(
      page.getByText(/New York Fed Staff Nowcast 2\.0/).first()
    ).toBeVisible();
    // The panel is the one place that explains what the published number is:
    // the average of two models, each a nowcast of the ABS's initial estimate.
    // The panel is closed by default, so this assertion lives here — and it is
    // SCOPED TO #methodology because the track-record notes above also say
    // "average error", so an unscoped match passes with the panel closed and
    // would survive the panel's copy being deleted.
    //
    // `/average error/` rather than `/most recent average error/`: the copy
    // now attaches the correction to the NY Fed model that owns it ("its own
    // average error over the last 8 quarters") instead of to the published
    // figure, which is an average of two already corrected models.
    await expect(
      page.locator("#methodology").getByText(/average error/).first()
    ).toBeVisible();
    // BOTH MODELS HAVE TO BE NAMED, because the published figure is their
    // average. The NY Fed assertion above is one half; this is the other, and
    // the paper number is the part a reader can look up. `ModelSwitch` is gone
    // from the foot of the page (commit 2cf1e6d), so neither string can now
    // reach this page from anywhere but the methodology copy.
    await expect(
      page.locator("#methodology").getByText(/Research Discussion Paper 2024-04/)
    ).toBeVisible();
  });
});

test.describe("v2 dashboard", () => {
  test("still renders at /v2", async ({ page }) => {
    await page.goto("/v2");
    await expect(page.getByText(/growth this quarter/).first()).toBeVisible();
    await expect(page.locator("svg").first()).toBeVisible();
  });

  test("serves v2, not v3", async ({ page }) => {
    await page.goto("/v2");
    await indicatorMeta(page);
    await expect(page.getByText(V2_INDICATOR)).toBeVisible();
    await expect(page.getByText(V3_INDICATOR)).toHaveCount(0);
  });
});

test("/v3 still resolves, for links made while it was the preview", async ({ page }) => {
  await page.goto("/v3");
  await expect(page.getByText(/growth this quarter/).first()).toBeVisible();
  // Same implementation as the homepage, so it must serve v3's data too.
  await indicatorMeta(page);
  await expect(page.getByText(V3_INDICATOR)).toBeVisible();
});
