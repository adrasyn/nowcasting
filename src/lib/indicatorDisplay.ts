import type { Indicator } from "./types";

// Presentation semantics only. The model's units and observations stay intact.
// These indices measure levels with meaningful ratios, unlike confidence,
// diffusion and net-balance surveys. Keep aliases for the v2 and merged panels.
const RATIO_SCALE_INDICES = new Set([
  "cpi", "commodity_prices", "unit_labour_cost", "job_ads", "anz_ads",
]);

export function indicatorDisplayUnit(indicator: Pick<Indicator, "id" | "unit">): string {
  // The v2 payload labels all NAB rows as net balance, including this rate.
  return indicator.id === "nab_cu" ? "percent" : indicator.unit;
}

export function hasPercentChange(indicator: Pick<Indicator, "id" | "unit">): boolean {
  const unit = indicatorDisplayUnit(indicator).trim().toLowerCase();
  if (unit === "percent" || unit === "%" || unit === "net balance") return false;
  if (unit === "index") return RATIO_SCALE_INDICES.has(indicator.id);
  return true;
}
