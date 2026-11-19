import { finite } from "../monitor";
import type { MonitorHorizon } from "../monitor";
// One q/q percentage scale for both cards, including every plotted band.
// Waiting/refused quarters do not contribute their withheld source estimates.
export function sharedQuarterRangeBound(
  horizons: Pick<MonitorHorizon, "qoq" | "band68" | "band95">[],
): number {
  const maximum = Math.max(
    1,
    ...horizons
      .flatMap((h) =>
        finite(h.qoq) ? [h.qoq, ...(h.band68 ?? []), ...(h.band95 ?? [])] : [],
      )
      .filter(finite)
      .map(Math.abs),
  );
  if (maximum <= 1) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(maximum));
  return (
    [1, 1.5, 2, 2.5, 3, 4, 5, 7.5, 10]
      .map((n) => n * magnitude)
      .find((n) => finite(n) && n >= maximum) ?? maximum
  );
}
export const rangeTick = (v: number) =>
  v === 0
    ? "0"
    : `${v < 0 ? "−" : "+"}${Math.abs(v).toFixed(Number.isInteger(v) ? 0 : 1)}%`;
