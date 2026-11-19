import type { Indicator } from "../types";
import { formatLatestValue, formatRawChange } from "../format";
import { hasPercentChange, indicatorDisplayUnit } from "../indicatorDisplay";
import { changeChartData, employmentChangeData } from "./chartChanges.mjs";
import { finite } from "../monitor";
export interface ChartPoint {
  date: string;
  value: number | null;
}
export interface IndicatorChart {
  points: ChartPoint[];
  kind: "line" | "bars";
  unit: string;
  description: string;
  transformed: boolean;
}
export const canonicalUnit = (i: Indicator) =>
  ({
    "millions of dollars": "$ millions",
    thousands: "000s persons",
    number: "count",
  })[indicatorDisplayUnit(i).trim().toLowerCase()] || indicatorDisplayUnit(i);
export const latestValue = (i: Indicator, v: number | null | undefined) =>
  finite(v)
    ? formatLatestValue(v, canonicalUnit(i)).replace(/^\$-/, "−$")
    : "—";
export function indicatorChange(i: Indicator) {
  const a = i.series.at(-1),
    b = i.series.at(-2);
  return a && b && finite(a.value) && finite(b.value)
    ? a.value - b.value
    : null;
}
export const rawChange = (i: Indicator) => {
  const d = indicatorChange(i);
  return d === null ? "—" : formatRawChange(d, canonicalUnit(i));
};
export const relativeChange = (i: Indicator) => {
  const d = indicatorChange(i),
    b = i.series.at(-2)?.value;
  return hasPercentChange(i) && d !== null && finite(b) && b !== 0
    ? (d / b) * 100
    : null;
};
// Both sizes use this one transformation and the same final 36 calendar slots.
export function indicatorChart(i: Indicator): IndicatorChart {
  const employment = employmentChangeData(i),
    growth = changeChartData(i);
  if (employment)
    return {
      points: employment.points,
      kind: "bars",
      unit: "thousand people",
      description: "Month-on-month change in people employed",
      transformed: true,
    };
  if (growth)
    return {
      points: growth.points,
      kind: "line",
      unit: growth.config.label,
      description: `${growth.config.words} percentage change, not annualised`,
      transformed: true,
    };
  return {
    points: i.series.map((r) => ({
      date: r.date,
      value: finite(r.value) ? r.value : null,
    })),
    kind: "line",
    unit: indicatorDisplayUnit(i),
    description: "Observed level",
    transformed: false,
  };
}
