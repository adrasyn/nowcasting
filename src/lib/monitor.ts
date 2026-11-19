import type {
  DashboardData,
  GdpQuarter,
  IndicatorData,
  LatestV3,
  Performance,
  V3Horizon,
  V3Vintage,
} from "./types";

export const finite = (v: unknown): v is number =>
  typeof v === "number" && Number.isFinite(v);
export function quarterIndex(value: string | undefined): number | null {
  const m = /^(\d{4}) Q([1-4])$/.exec(value ?? "");
  return m ? Number(m[1]) * 4 + Number(m[2]) - 1 : null;
}
export function shiftQuarter(value: string, amount: number): string | null {
  const n = quarterIndex(value);
  if (n === null) return null;
  const shifted = n + amount;
  return `${Math.floor(shifted / 4)} Q${(shifted % 4) + 1}`;
}
export const quarterLabel = (value: string | null) =>
  value ? value.split(" ").reverse().join(" ") : "Quarter unavailable";
export function quarterMonths(value: string | null): string {
  const n = quarterIndex(value ?? undefined);
  if (n === null) return "";
  return ["January–March", "April–June", "July–September", "October–December"][
    n % 4
  ];
}
export function isoDay(value: unknown): string | null {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}(?:$|T)/.test(value))
    return null;
  const day = value.slice(0, 10),
    d = new Date(day + "T00:00:00Z");
  return finite(d.getTime()) && d.toISOString().slice(0, 10) === day
    ? day
    : null;
}
export function dayLabel(value: unknown, year = false): string {
  const day = isoDay(value);
  return day
    ? new Date(day + "T00:00:00Z").toLocaleDateString("en-AU", {
        day: "numeric",
        month: "short",
        timeZone: "UTC",
        ...(year ? { year: "numeric" } : {}),
      })
    : "—";
}
export function monthLabel(value: unknown): string {
  if (typeof value !== "string" || !/^\d{4}-(0[1-9]|1[0-2])$/.test(value))
    return "—";
  return new Date(value + "-01T00:00:00Z").toLocaleDateString("en-AU", {
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  });
}
export const signed = (v: number | null | undefined, decimals = 2) =>
  finite(v)
    ? `${v < 0 ? "−" : v > 0 ? "+" : ""}${Math.abs(v).toFixed(decimals)}`
    : "—";
export const percentage = (v: number | null | undefined) =>
  finite(v) ? signed(v) + "%" : "—";
export type BandKind = "error" | "posterior";
export interface MonitorHorizon {
  quarter: string | null;
  role: "current" | "next";
  source: V3Horizon | null;
  state: "ready" | "waiting" | "no-data" | "refused";
  qoq: number | null;
  yoy: number | null;
  level: number | null;
  release: string | null;
  months: number | null;
  carriedForecast: boolean;
  bandKind: BandKind;
  band68: [number, number] | null;
  band95: [number, number] | null;
  runs: V3Vintage[];
  delta: number | null;
  previousRunDate: string | null;
}
export interface MonitorView {
  model: "combination" | "v3" | "unavailable";
  latest: LatestV3 | null;
  indicators: IndicatorData;
  performance: Performance | null;
  gdp: GdpQuarter[];
  history: V3Vintage[];
  current: MonitorHorizon;
  next: MonitorHorizon;
  actualQuarter: string | null;
  builtAt: string;
  asOf: string | null;
  warnings: string[];
}
export function bandFor(
  h: V3Horizon | V3Vintage | null,
  n: 68 | 95,
): [number, number] | null {
  const lo = h?.[`ci_${n}_low`],
    hi = h?.[`ci_${n}_high`];
  return finite(lo) && finite(hi) && lo <= hi ? [lo, hi] : null;
}
export function releaseFor(
  quarter: string | null,
  horizon: V3Horizon | null,
  latest: LatestV3 | null,
): string | null {
  if (!quarter) return null;
  const next = shiftQuarter(quarter, 1),
    n = quarterIndex(next ?? undefined);
  if (n === null) return null;
  const matches = (v: unknown) => {
    const day = isoDay(v);
    return day &&
      Number(day.slice(0, 4)) === Math.floor(n / 4) &&
      Number(day.slice(5, 7)) === ((n % 4) + 1) * 3
      ? day
      : null;
  };
  return (
    matches(horizon?.release_date) ||
    (latest?.target_quarter === quarter
      ? matches(latest.next_gdp_release_date)
      : null)
  );
}
export function archiveRuns(
  history: V3Vintage[],
  latest: V3Vintage[],
): V3Vintage[] {
  const merged = new Map<string, V3Vintage>();
  for (const r of [...history, ...latest]) {
    if (
      quarterIndex(r.target_quarter) === null ||
      !isoDay(r.run_date) ||
      !finite(r.qoq_growth_pct)
    )
      continue;
    // One published figure per target/run. A corrected current payload wins.
    merged.set(r.target_quarter + "|" + r.run_date, r);
  }
  return [...merged.values()].sort(
    (a, b) =>
      quarterIndex(b.target_quarter)! - quarterIndex(a.target_quarter)! ||
      b.run_date.localeCompare(a.run_date),
  );
}
export function horizonRuns(
  history: V3Vintage[],
  quarter: string | null,
): V3Vintage[] {
  return history
    .filter((r) => r.target_quarter === quarter)
    .sort((a, b) => a.run_date.localeCompare(b.run_date));
}
export function buildMonitorView(
  data: DashboardData,
  builtAt = new Date().toISOString(),
): MonitorView {
  // Keep the model and its panel, archive and score together. Never relabel v3
  // performance as the combination, and never bypass an explicit refusal.
  const model = data.latestCombo
    ? "combination"
    : data.latestV3
      ? "v3"
      : "unavailable";
  const latest =
    (model === "combination" ? data.latestCombo : data.latestV3) ?? null;
  const indicators = (model === "combination"
    ? data.indicatorsCombo
    : data.indicatorsV3) ?? { indicators: [] };
  const performance =
    (model === "combination" ? data.performanceCombo : data.performanceV3) ??
    null;
  const saved =
    (model === "combination" ? data.historyCombo : data.historyV3)?.runs ?? [];
  const history = archiveRuns(saved, latest?.vintages ?? []);
  // gdp.json contains verified, published ABS observations, not forecasts.
  // Calendar time deliberately plays no part in deciding the current target.
  const gdp = [...(data.gdp?.series ?? [])]
    .filter(
      (r) => quarterIndex(r.quarter) !== null && finite(r.value) && r.value > 0,
    )
    .sort((a, b) => quarterIndex(a.quarter)! - quarterIndex(b.quarter)!);
  const actualQuarter = gdp.at(-1)?.quarter ?? null;
  const horizons = Array.isArray(latest?.horizons) ? latest.horizons : [];
  const sourceCurrent = horizons.find(
    (h) => h.kind === "nowcast" && quarterIndex(h.quarter) !== null,
  );
  const currentQuarter = actualQuarter
    ? shiftQuarter(actualQuarter, 1)
    : (sourceCurrent?.quarter ??
      (quarterIndex(latest?.target_quarter) !== null
        ? (latest?.target_quarter ?? null)
        : null));
  const nextQuarter = currentQuarter ? shiftQuarter(currentQuarter, 1) : null;
  const ready = (h: V3Horizon | undefined) =>
    latest?.status === "ok" &&
    !!h &&
    finite(h.qoq_growth_pct) &&
    h.months_with_data !== 0;
  const levelFor = (
    quarter: string,
    seen = new Set<string>(),
  ): number | null => {
    if (seen.has(quarter)) return null;
    seen.add(quarter);
    const h = horizons.find((x) => x.quarter === quarter);
    if (ready(h)) {
      if (
        finite(h!.gdp_chain_volume_millions) &&
        h!.gdp_chain_volume_millions! > 0
      )
        return h!.gdp_chain_volume_millions!;
      const previous = shiftQuarter(quarter, -1)!;
      // Preserve the run's own conditioning levels when a forecast is carried
      // across a release. Do not silently recompute it as a new model run.
      const base = horizons.some((x) => x.quarter === previous)
        ? levelFor(previous, seen)
        : (gdp.find((r) => r.quarter === previous)?.value ?? null);
      return finite(base) ? base * (1 + h!.qoq_growth_pct / 100) : null;
    }
    return gdp.find((r) => r.quarter === quarter)?.value ?? null;
  };
  const make = (
    quarter: string | null,
    role: "current" | "next",
  ): MonitorHorizon => {
    const source = horizons.find((h) => h.quarter === quarter) ?? null;
    const isReady = ready(source ?? undefined),
      runs = horizonRuns(history, quarter);
    const usable = isReady ? source : null,
      level = usable && quarter ? levelFor(quarter) : null;
    const yearBase = quarter
      ? gdp.find((r) => r.quarter === shiftQuarter(quarter, -4))?.value
      : null;
    // Compare the two latest recorded estimates for the SAME target quarter.
    const last = runs.at(-1),
      previous = runs.at(-2);
    const kind: BandKind =
      model === "combination" &&
      (source?.kind === "nowcast" || finite(source?.components?.v2))
        ? "error"
        : "posterior";
    return {
      quarter,
      role,
      source,
      state:
        latest?.status === "refused"
          ? "refused"
          : isReady
            ? "ready"
            : source?.months_with_data === 0
              ? "no-data"
              : "waiting",
      qoq: usable?.qoq_growth_pct ?? null,
      yoy:
        finite(level) && finite(yearBase) && yearBase > 0
          ? (level / yearBase - 1) * 100
          : null,
      level,
      release: releaseFor(quarter, source, latest),
      months: finite(source?.months_with_data)
        ? source!.months_with_data!
        : null,
      carriedForecast:
        role === "current" && isReady && source?.kind === "forecast",
      bandKind: kind,
      band68: bandFor(usable, 68),
      band95: bandFor(usable, 95),
      runs,
      delta:
        last && previous ? last.qoq_growth_pct - previous.qoq_growth_pct : null,
      previousRunDate: previous?.run_date ?? null,
    };
  };
  const current = make(currentQuarter, "current"),
    next = make(nextQuarter, "next"),
    warnings: string[] = [];
  if (latest?.status === "refused")
    warnings.push(
      `No nowcast published: ${latest.refusal_reason ?? "model refusal"}. ${latest.refusal_detail ?? ""}`.trim(),
    );
  if (!latest)
    warnings.push(
      "No published nowcast payload is available. Historical observations remain below.",
    );
  if (!actualQuarter)
    warnings.push(
      "Published GDP observations are unavailable; year-on-year comparisons may be unavailable.",
    );
  if (current.carriedForecast)
    warnings.push(
      `${quarterLabel(current.quarter)} is the previous run’s forecast; awaiting a new nowcast after the ABS release.`,
    );
  else if (latest?.status === "ok" && current.state !== "ready")
    warnings.push(
      "Awaiting an estimate for the quarter after the latest published ABS GDP observation.",
    );
  if (model === "v3")
    warnings.push(
      "Combination unavailable; showing v3 and its own indicator panel and track record.",
    );
  const age = latest?.components?.v2?.stale_days;
  if (finite(age) && age > 0)
    warnings.push(
      `The combination uses the v2 component from ${dayLabel(latest?.components?.v2?.run_date, true)} (${age} days older).`,
    );
  if (!indicators.indicators.length)
    warnings.push("The selected model’s indicator panel is unavailable.");
  return {
    model,
    latest,
    indicators,
    performance,
    gdp,
    history,
    current,
    next,
    actualQuarter,
    builtAt,
    asOf: isoDay(latest?.as_of) || isoDay(latest?.generated_at),
    warnings,
  };
}
