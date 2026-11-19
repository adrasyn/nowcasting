// Display-only growth rates. Frequencies verified against the source registry.
// Every selected stored series is a level, not a rate or model transformation.
export const CHANGE_CHARTS = Object.freeze({
  credit_business: "m",
  credit_card: "m",
  credit_housing: "m",
  credit: "m",
  cpi: "m",
  employment: "m",
  ft_emp: "m",
  hours: "m",
  pt_emp: "m",
  gdi: "q",
  gdp: "q",
  unit_labour_cost: "q",
});
export function changeChartConfig(indicator) {
  const frequency = CHANGE_CHARTS[indicator.id];
  // Never take percentage changes of a rate if a payload's units change.
  if (
    !frequency ||
    ["%", "percent", "net balance"].includes(
      String(indicator.unit).trim().toLowerCase(),
    )
  )
    return null;
  return {
    frequency,
    step: frequency === "q" ? 3 : 1,
    label: frequency === "q" ? "q/q %" : "m/m %",
    words: frequency === "q" ? "quarter-on-quarter" : "month-on-month",
  };
}
function monthIndex(date) {
  const match = /^(\d{4})-(\d{2})$/.exec(date || "");
  if (!match) return null;
  const month = Number(match[2]);
  return month >= 1 && month <= 12 ? Number(match[1]) * 12 + month - 1 : null;
}
const monthDate = (index) =>
  `${Math.floor(index / 12)}-${String((index % 12) + 1).padStart(2, "0")}`;
function periodChanges(indicator, config, calculate) {
  const levels = new Map();
  for (const row of indicator.series) {
    const index = monthIndex(row.date);
    if (
      index === null ||
      (config.frequency === "q" && ((index % 12) + 1) % 3 !== 0)
    )
      continue;
    // Duplicate dates are ambiguous. Do not choose one or interpolate.
    levels.set(index, levels.has(index) ? null : row);
  }
  if (!levels.size) return { config, points: [] };
  const first = Math.min(...levels.keys()),
    last = Math.max(...levels.keys()),
    points = [];
  for (let index = first; index <= last; index += config.step) {
    const current = levels.get(index),
      previous = levels.get(index - config.step);
    const valid =
      current &&
      previous &&
      Number.isFinite(current.value) &&
      Number.isFinite(previous.value) &&
      current.value >= 0 &&
      previous.value > 0;
    const growth = valid ? calculate(current.value, previous.value) : null;
    // Missing periods stay null, so lines break and no zero baseline is invented.
    points.push({
      date: monthDate(index),
      value: Number.isFinite(growth) ? growth : null,
    });
  }
  return { config, points };
}

export function changeChartData(indicator) {
  const config = changeChartConfig(indicator);
  return config
    ? periodChanges(
        indicator,
        config,
        (current, previous) => ((current - previous) / previous) * 100,
      )
    : null;
}
const EMPLOYMENT_BARS = new Set(["employment", "ft_emp", "pt_emp"]);
export function employmentBarConfig(indicator) {
  if (!EMPLOYMENT_BARS.has(indicator.id)) return null;
  const unit = String(indicator.unit).trim().toLowerCase().replace(/^'/, "");
  return {
    kind: "people",
    frequency: "m",
    step: 1,
    label: "thousand people",
    words: "month-on-month change in people employed",
    unitsVerified: ["thousands", "000s persons"].includes(unit),
  };
}
export function employmentChangeData(indicator) {
  const config = employmentBarConfig(indicator);
  if (!config) return null;
  if (!config.unitsVerified) return { config, points: [] };
  // The saved employment observations are ALREADY in thousands of people.
  // Their difference has the same units: never divide these values by 1000.
  return periodChanges(
    indicator,
    config,
    (current, previous) => current - previous,
  );
}
