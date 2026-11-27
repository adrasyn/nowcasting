"use client";
import { useLayoutEffect } from "react";
import type { RefObject } from "react";
const DURATION = 1500;
function plotSpan(a: DOMRect, b: DOMRect) {
  return {
    left: Math.min(a.left, b.left), right: Math.max(a.right, b.right),
    top: Math.min(a.top, b.top), bottom: Math.max(a.bottom, b.bottom),
    width: Math.max(a.right, b.right) - Math.min(a.left, b.left),
  };
}
// Keep the native easing, but seek a paused timeline only on visible frames.
// An offscreen mount, Safari paint stall or late font must not consume the draw.
export function useEvolutionMotion(
  ref: RefObject<SVGSVGElement | null>,
  quarter: string | null | undefined,
  count: number,
) {
  useLayoutEffect(() => {
    const svg = ref.current,
      line = svg?.querySelector<SVGPathElement>(".chart-line");
    if (!svg || !line || !count) return;
    const media = matchMedia("(prefers-reduced-motion: reduce)");
    if (media.matches) return;
    let disposed = false,
      done = false,
      started = false,
      dirty = true,
      fontsReady = false,
      priming = 0,
      elapsed = 0,
      last: number | null = null,
      raf = 0;
    let animations: Animation[] = [];
    const seek = () => animations.forEach((a) => (a.currentTime = elapsed));
    const prepare = () => {
      animations.forEach((a) => a.cancel());
      animations = [];
      const timing: KeyframeAnimationOptions = {
        duration: DURATION,
        easing: "ease",
        fill: "both",
      };
      svg.querySelectorAll<SVGPathElement>(".chart-line").forEach((path) => {
        const length = path.getTotalLength();
        if (length)
          animations.push(
            path.animate(
              [
                {
                  strokeDasharray: `${length} ${length}`,
                  strokeDashoffset: length,
                },
                { strokeDasharray: `${length} ${length}`, strokeDashoffset: 0 },
              ],
              timing,
            ),
          );
      });
      svg
        .querySelectorAll<SVGRectElement>(".band-reveal")
        .forEach((rect) =>
          animations.push(
            rect.animate(
              [{ width: "0px" }, { width: rect.getAttribute("width") + "px" }],
              timing,
            ),
          ),
        );
      svg
        .querySelectorAll(".chart-point, .final-estimate-marker")
        .forEach((point) =>
          animations.push(
            point.animate([{ opacity: 0 }, { opacity: 1 }], {
              ...timing,
              easing: "steps(1, end)",
            }),
          ),
        );
      animations.forEach((a) => a.pause());
      seek();
      dirty = false;
    };
    const ready = () => {
      const box = svg.getBoundingClientRect(),
        view = svg.viewBox.baseVal;
      return (
        fontsReady &&
        box.width > 0 &&
        box.height > 0 &&
        Math.abs(box.width - view.width) < 0.75 &&
        Math.abs(box.height - view.height) < 0.75
      );
    };
    const visible = () => {
      if (document.visibilityState !== "visible") return false;
      const trail = svg.querySelector("[data-final-trail]"),
        solid = line.getBoundingClientRect(),
        dashed = trail?.getBoundingClientRect(),
        r = dashed ? (solid.width ? plotSpan(solid, dashed) : dashed) : solid,
        v = window.visualViewport,
        left = v?.offsetLeft ?? 0,
        top = v?.offsetTop ?? 0,
        right = left + (v?.width ?? innerWidth),
        bottom = top + (v?.height ?? innerHeight);
      return (
        r.width > 0 &&
        r.left >= left - 1 &&
        r.right <= right + 1 &&
        r.top >= top - 1 &&
        r.bottom <= bottom + 1
      );
    };
    let intersection: IntersectionObserver | null = null,
      resize: ResizeObserver | null = null,
      mutation: MutationObserver | null = null;
    const unlisten = () => {
      window.removeEventListener("scroll", wake);
      window.removeEventListener("resize", wake);
      window.visualViewport?.removeEventListener("scroll", wake);
      window.visualViewport?.removeEventListener("resize", wake);
      document.removeEventListener("visibilitychange", wake);
      media.removeEventListener("change", preference);
      intersection?.disconnect();
      resize?.disconnect();
      mutation?.disconnect();
    };
    const finish = () => {
      done = true;
      cancelAnimationFrame(raf);
      raf = 0;
      animations.forEach((a) => a.cancel());
      animations = [];
      svg.dataset.evolutionMotion = "done";
      unlisten();
    };
    const tick = (time: number) => {
      raf = 0;
      if (disposed || done) return;
      if (dirty) prepare();
      if (!ready() || !visible()) {
        last = null;
        if (!started) priming = 0;
        svg.dataset.evolutionMotion = started ? "paused" : "waiting";
        return;
      }
      if (!started) {
        // Two actual frame opportunities at zero after fonts and measured geometry.
        // The third frame is also zero; only the following frame can advance.
        if (priming < 2) {
          priming++;
          svg.dataset.evolutionMotion = "priming";
          seek();
          raf = requestAnimationFrame(tick);
          return;
        }
        started = true;
        last = time;
        svg.dataset.evolutionMotion = "playing";
        seek();
        raf = requestAnimationFrame(tick);
        return;
      }
      svg.dataset.evolutionMotion = "playing";
      // A long main-thread/paint gap slows the draw instead of skipping its start.
      if (last !== null)
        elapsed = Math.min(
          DURATION,
          elapsed + Math.max(0, Math.min(34, time - last)),
        );
      last = time;
      seek();
      if (elapsed >= DURATION) {
        finish();
        return;
      }
      raf = requestAnimationFrame(tick);
    };
    function wake() {
      if (!disposed && !done && !raf) raf = requestAnimationFrame(tick);
    }
    function preference() {
      if (media.matches) finish();
    }
    svg.dataset.evolutionMotion = "waiting";
    prepare();
    intersection = new IntersectionObserver(wake, {
      threshold: [0, 0.25, 0.5, 0.75, 1],
    });
    intersection.observe(line);
    resize = new ResizeObserver(() => {
      dirty = true;
      wake();
    });
    resize.observe(svg);
    mutation = new MutationObserver(() => {
      dirty = true;
      wake();
    });
    mutation.observe(svg, {
      attributes: true,
      subtree: true,
      attributeFilter: ["d", "viewBox", "width", "height"],
    });
    window.addEventListener("scroll", wake, { passive: true });
    window.addEventListener("resize", wake);
    window.visualViewport?.addEventListener("scroll", wake, { passive: true });
    window.visualViewport?.addEventListener("resize", wake);
    document.addEventListener("visibilitychange", wake);
    media.addEventListener("change", preference);
    Promise.resolve(document.fonts?.ready).then(() => {
      fontsReady = true;
      wake();
    });
    wake();
    return () => {
      disposed = true;
      cancelAnimationFrame(raf);
      animations.forEach((a) => a.cancel());
      unlisten();
      delete svg.dataset.evolutionMotion;
    };
  }, [ref, quarter, count]);
}
