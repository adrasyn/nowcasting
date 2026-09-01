export function formatMillions(m: number): string {
  return `$${m.toLocaleString("en-AU")}M`;
}

export function formatPct(pct: number): string {
  if (pct === 0) return "0.00%";
  const sign = pct > 0 ? "+" : "−";
  return `${sign}${Math.abs(pct).toFixed(2)}%`;
}

export function formatQuarter(q: string): string {
  return q;
}

export function formatMonth(yyyyMm: string): string {
  const [y, m] = yyyyMm.split("-");
  const labels = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  return `${labels[parseInt(m, 10) - 1]} ${y.slice(2)}`;
}

export function formatDate(iso: string): string {
  const d = new Date(iso);
  const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  return `${d.getDate()} ${months[d.getMonth()]} ${d.getFullYear()}`;
}

/** "2026 Q2" -> "Q2 2026", the way the page's headings name a quarter. */
export function formatQuarterLabel(quarter: string): string {
  const m = quarter.match(/^(\d{4})\s*Q([1-4])$/);
  return m ? `Q${m[2]} ${m[1]}` : quarter;
}

export function formatDayMonth(iso: string): string {
  const d = new Date(iso);
  const months = ["January","February","March","April","May","June","July","August","September","October","November","December"];
  return `${d.getDate()} ${months[d.getMonth()]}`;
}

export function formatRawChange(delta: number, unit: string): string {
  const abs = Math.abs(delta);
  const sign = delta > 0 ? "+" : delta < 0 ? "−" : "";

  switch (unit) {
    case "$ millions":
    case "$m": {
      if (abs >= 1000) return `${sign}$${(abs / 1000).toFixed(1)}bn`;
      if (abs >= 100) return `${sign}$${abs.toFixed(0)}M`;
      return `${sign}$${abs.toFixed(1)}M`;
    }
    case "$bn":
      return `${sign}$${abs.toFixed(1)}bn`;
    case "persons":
    case "000s persons": {
      if (abs >= 1000) return `${sign}${(abs / 1000).toFixed(1)}m`;
      return `${sign}${abs.toFixed(1)}k`;
    }
    // ABS 6202.0 hours worked is reported in THOUSANDS of hours (~2,014,000 =
    // ~2.01bn hours a month nationally). indicators_v2.json used to label it
    // "mn hours" and fall through to the bare-number case below, so the page
    // rendered "2,014,342" against a millions-of-hours label — out by 1000x.
    // The unit string is now "hours (thousands)" everywhere; scale it for display.
    case "hours (thousands)": {
      if (abs >= 1_000_000) return `${sign}${(abs / 1_000_000).toFixed(2)}bn hrs`;
      if (abs >= 1000) return `${sign}${(abs / 1000).toFixed(1)}m hrs`;
      return `${sign}${abs.toFixed(0)}k hrs`;
    }
    case "dwellings":
    case "count":
      return `${sign}${Math.round(abs).toLocaleString("en-AU")}`;
    case "percent":
    case "%":
      return `${delta === 0 ? "" : sign}${abs.toFixed(1)}pp`;
    case "net balance":
      return `${delta === 0 ? "" : sign}${abs.toFixed(0)} pts`;
    case "index":
      return `${delta === 0 ? "" : sign}${abs.toFixed(1)} pts`;
    default:
      return `${sign}${abs.toFixed(1)}`;
  }
}
