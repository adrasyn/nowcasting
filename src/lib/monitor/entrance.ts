import { finite, percentage } from "../monitor";
import type { MonitorHorizon } from "../monitor";
export const MAX_VALUE_RUNTIME = 3600;
export const BASE_INCREMENT_MS = 16;
export const easeInOut = (t: number) => {
  const p = Math.max(0, Math.min(1, t));
  return p * p * (3 - 2 * p);
};
// Count the increments actually displayed, including decimal rounding. All four
// values share one base interval. Very large releases compress that shared
// interval together, preserving their relative finish times within 3.6 seconds.
export const displayedSteps = (v: number | null) =>
  finite(v) ? Math.round(Number(Math.abs(v).toFixed(2)) * 100) : 0;
export interface EntranceGroup {
  start: number | null;
  baseMs: number;
}
export function entranceGroup(values: (number | null)[]): EntranceGroup {
  const largest = Math.max(0, ...values.map(displayedSteps));
  return {
    start: null,
    baseMs: largest
      ? Math.min(BASE_INCREMENT_MS, MAX_VALUE_RUNTIME / largest)
      : BASE_INCREMENT_MS,
  };
}
export const valueDuration = (value: number | null, group: EntranceGroup) =>
  Math.min(MAX_VALUE_RUNTIME, displayedSteps(value) * group.baseMs);
export function valueFrame(
  value: number | null,
  elapsed: number,
  group: EntranceGroup,
): string {
  const duration = valueDuration(value, group);
  if (!finite(value) || duration === 0 || elapsed >= duration)
    return percentage(value);
  const steps = Math.floor(
    displayedSteps(value) * easeInOut(elapsed / duration),
  );
  return percentage((Math.sign(value) * steps) / 100);
}
export const rangeDurations = (role: MonitorHorizon["role"]) => {
  const marker = role === "current" ? 1460 : 1580;
  return { marker, band68: marker + 80, band95: marker + 160 };
};
export function rangeFrame(h: MonitorHorizon, elapsed: number) {
  if (!finite(h.qoq)) return { marker: null, band68: null, band95: null };
  const d = rangeDurations(h.role),
    marker =
      elapsed <= 0
        ? 0
        : elapsed >= d.marker
          ? h.qoq
          : h.qoq * easeInOut(elapsed / d.marker);
  const grow = (
    band: [number, number] | null,
    duration: number,
  ): [number, number] | null =>
    !band
      ? null
      : elapsed >= duration
        ? band
        : [
            marker + (band[0] - h.qoq!) * easeInOut(elapsed / duration),
            marker + (band[1] - h.qoq!) * easeInOut(elapsed / duration),
          ];
  return {
    marker,
    band68: grow(h.band68, d.band68),
    band95: grow(h.band95, d.band95),
  };
}
