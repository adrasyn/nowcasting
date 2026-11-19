import { test, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";

// These cases stay in the existing shared Chromium/iPhone WebKit motion suite;
// they consume the same prebuilt export, without changing workflow coverage.
test.describe("indicator detail reveal", () => {
  async function frames(svg: import("@playwright/test").Locator, time: number) {
    return svg.evaluate(async (el, ms) => {
      const animations = el.getAnimations({ subtree: true });
      animations.forEach((a) => { a.pause(); a.currentTime = ms; });
      await new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
      return [...el.querySelectorAll<SVGGraphicsElement>(".chart-line,.employment-bar")].map((p) => {
        const a = animations.find((a) => (a.effect as KeyframeEffect).target === p)!;
        const progress = a.effect!.getComputedTiming().progress as number;
        const style = getComputedStyle(p);
        if (p instanceof SVGPathElement) {
          const length = p.getTotalLength();
          const scale = length / (p.pathLength.baseVal || length);
          return { kind: "line", progress, fraction: Math.min(1, Math.max(0,
            (parseFloat(style.strokeDasharray) - parseFloat(style.strokeDashoffset)) * scale / length)),
            y: 0, expectedY: 0, duration: a.effect!.getTiming().duration };
        }
        const zero = Number(p.getAttribute("data-zero"));
        const finalY = Number(p.getAttribute("y")), height = Number(p.getAttribute("height"));
        return { kind: "bar", progress, fraction: height ? p.getBBox().height / height : progress,
          y: p.getBBox().y, expectedY: zero + (finalY - zero) * progress,
          duration: a.effect!.getTiming().duration };
      });
    }, time);
  }

  async function freezeOnCreation(page: import("@playwright/test").Page) {
    await page.addInitScript(() => {
      const native = Element.prototype.animate;
      Element.prototype.animate = function (keyframes, options) {
        const animation = native.call(this, keyframes, options);
        if (this.closest(".series-chart")) animation.pause();
        return animation;
      };
    });
  }

  async function open(page: import("@playwright/test").Page, id: string) {
    const row = page.locator(`#series-${id}`);
    await row.locator("summary").click();
    const svg = row.locator(".series-chart svg");
    await expect(svg).toBeVisible();
    await expect.poll(() => svg.evaluate((el) => Math.abs(
      el.getBoundingClientRect().width - (el as SVGSVGElement).viewBox.baseVal.width,
    ))).toBeLessThan(0.1);
    return svg;
  }

  for (const [id, kind] of [["credit", "line"], ["employment", "bar"]] as const)
    test(`${kind} geometry follows the entire native easing and releases without an end jump`, async ({ page }, info) => {
      await freezeOnCreation(page);
      for (const width of [1440, 390]) {
        await page.setViewportSize({ width, height: 900 });
        await page.goto("/");
        const svg = await open(page, id);
        if (kind === "bar") expect(await svg.locator(".employment-bar").evaluateAll((bars) => {
          const values = bars.map((bar) => Number(bar.getAttribute("data-chart-value")));
          return [values.some((v) => v < 0), values.some((v) => v > 0)];
        })).toEqual([true, true]);
        let previous = -1;
        for (const time of [0, 375, 750, 1125, 1425, 1499]) {
          const state = await frames(svg, time);
          expect(state.length).toBeGreaterThan(0);
          for (const point of state) {
            expect(point.duration).toBe(1500);
            expect(point.fraction).toBeCloseTo(point.progress, 4);
            expect(point.y).toBeCloseTo(point.expectedY, 3);
            expect(point.fraction).toBeGreaterThanOrEqual(previous - 0.0001);
          }
          previous = state[0].fraction;
          if (time === 0 || time === 750) await svg.screenshot({ path: info.outputPath(`${kind}-${width}-${time === 0 ? "start" : "middle"}.png`), animations: "allow" });
        }
        const before = await svg.screenshot({ path: info.outputPath(`${kind}-${width}-before-release.png`), animations: "allow" });
        await svg.evaluate(async (el) => {
          const animations = el.getAnimations({ subtree: true });
          animations.forEach((a) => a.play());
          await Promise.all(animations.map((a) => a.finished));
          await new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
        });
        expect(await svg.evaluate((el) => el.getAnimations({ subtree: true }).length)).toBe(0);
        const after = await svg.screenshot({ path: info.outputPath(`${kind}-${width}-finished.png`), animations: "allow" });
        // Compare the actual raster immediately before effect removal with the
        // final unmasked plot, rather than merely asserting a finished timeline.
        const changed = Number(execFileSync("python3", ["-c", `
import sys,json,base64,io
from PIL import Image,ImageChops
a,b=[Image.open(io.BytesIO(base64.b64decode(s))).convert('RGB') for s in json.load(sys.stdin)]
assert a.size==b.size
diff=ImageChops.difference(a,b)
pixels=diff.get_flattened_data() if hasattr(diff,'get_flattened_data') else diff.getdata()
print(sum(max(pixel)>8 for pixel in pixels))
`], { input: JSON.stringify([before.toString("base64"), after.toString("base64")]) }).toString());
        expect(changed).toBeLessThanOrEqual(8);
      }
    });

  test("resize preserves progress; closing cancels and reopening starts a fresh reveal", async ({ page }) => {
    await freezeOnCreation(page);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/");
    let svg = await open(page, "credit");
    const middle = (await frames(svg, 750))[0];
    const old = await svg.evaluateHandle((el) => el.getAnimations({ subtree: true })[0]);
    await page.setViewportSize({ width: 375, height: 812 });
    await expect.poll(() => svg.evaluate((el) => Math.abs(el.getBoundingClientRect().width -
      (el as SVGSVGElement).viewBox.baseVal.width))).toBeLessThan(0.1);
    expect((await frames(svg, 750))[0].fraction).toBeCloseTo(middle.fraction, 4);
    await page.locator("#series-credit summary").click();
    await expect.poll(() => old.evaluate((a) => a.playState)).toBe("idle");
    svg = await open(page, "credit");
    expect((await frames(svg, 0))[0].fraction).toBe(0);
    expect((await frames(svg, 1499))[0].fraction).toBeGreaterThan(0.9999);
    await old.dispose();
  });

  test("reduced motion shows final line and bar geometry, including a mid-reveal preference change", async ({ page }) => {
    await freezeOnCreation(page);
    await page.goto("/");
    const line = await open(page, "credit");
    const bars = await open(page, "employment");
    expect((await frames(line, 750))[0].fraction).toBeLessThan(1);
    await frames(bars, 750);
    await page.emulateMedia({ reducedMotion: "reduce" });
    for (const svg of [line, bars]) {
      await expect.poll(() => svg.evaluate((el) => el.getAnimations({ subtree: true }).length)).toBe(0);
      expect(await svg.evaluate((el) => [...el.querySelectorAll<SVGGraphicsElement>(".chart-line,.employment-bar")].every((p) =>
        p instanceof SVGPathElement ? getComputedStyle(p).strokeDasharray === "none" :
          Math.abs(p.getBBox().height - Number(p.getAttribute("height"))) < 0.001))).toBe(true);
    }
    for (const id of ["credit", "employment"]) {
      await page.locator(`#series-${id} summary`).click();
      const svg = await open(page, id);
      expect(await svg.evaluate((el) => el.getAnimations({ subtree: true }).length)).toBe(0);
    }
  });
});
