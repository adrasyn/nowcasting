"use client";
import * as React from "react";
import { useLayoutEffect, useRef } from "react";
import { percentage } from "@/lib/monitor";
import { valueDuration, valueFrame } from "@/lib/monitor/entrance";
import type { EntranceGroup } from "@/lib/monitor/entrance";
export function startEntrance(group: EntranceGroup) {
  return group.start ?? (group.start = performance.now());
}
export function AnimatedValue({
  value,
  group,
}: {
  value: number | null;
  group: EntranceGroup;
}): React.JSX.Element {
  const ref = useRef<HTMLSpanElement>(null),
    final = percentage(value);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const media = matchMedia("(prefers-reduced-motion: reduce)");
    let raf = 0;
    const finish = () => {
      cancelAnimationFrame(raf);
      el.dataset.display = final;
    };
    if (media.matches || valueDuration(value, group) === 0) {
      finish();
      return;
    }
    const start = startEntrance(group);
    const paint = (now: number) => {
      const elapsed = Math.max(0, now - start);
      el.dataset.display = valueFrame(value, elapsed, group);
      if (elapsed < valueDuration(value, group))
        raf = requestAnimationFrame(paint);
    };
    paint(performance.now());
    const changed = () => {
      if (media.matches) finish();
    };
    media.addEventListener("change", changed);
    return () => {
      cancelAnimationFrame(raf);
      media.removeEventListener("change", changed);
    };
  }, [value, final, group]);
  // The final text reserves its exact size and remains available to screen
  // readers/copying. Only the aria-hidden generated text changes per frame.
  return (
    <span className="value-counter">
      <span className="value-counter-final">{final}</span>
      <span
        ref={ref}
        className="value-counter-visual"
        aria-hidden="true"
        data-display={final}
      />
    </span>
  );
}
