import fs from "fs";
import path from "path";
import type {
  LatestNowcast,
  GdpSeries,
  VintageSeries,
  IndicatorData,
  Performance,
  DashboardData,
  LatestV2,
  BackcastData,
  LatestV3,
  V3Backtest,
} from "./types";

const DATA_DIR = path.join(process.cwd(), "data");

function readJson<T>(filename: string, fallback: T): T {
  const filePath = path.join(DATA_DIR, filename);
  try {
    const raw = fs.readFileSync(filePath, "utf-8");
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

// Optional artifacts: return undefined (not a fallback) when the file is absent,
// so consumers can feature-detect the staged v2 cutover.
function readJsonOptional<T>(filename: string): T | undefined {
  const filePath = path.join(DATA_DIR, filename);
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf-8")) as T;
  } catch {
    return undefined;
  }
}

const LATEST_FALLBACK: LatestNowcast = {
  generated_at: "1970-01-01T00:00:00Z",
  target_quarter: "—",
  data_through: "—",
  next_gdp_release_date: "1970-01-01",
  nowcast: {
    gdp_chain_volume_millions: 0,
    qoq_growth_pct: 0,
    yoy_growth_pct: 0,
    ci_68_low: 0,
    ci_68_high: 0,
    ci_95_low: 0,
    ci_95_high: 0,
  },
  latest_actual: {
    quarter: "—",
    gdp_chain_volume_millions: 0,
    qoq_growth_pct: 0,
    released_days_before_next: 0,
  },
};

export function loadDashboardData(): DashboardData {
  return {
    latest: readJson<LatestNowcast>("latest.json", LATEST_FALLBACK),
    gdp: readJson<GdpSeries>("gdp.json", { series: [] }),
    nowcasts: readJson<VintageSeries>("nowcasts.json", { vintages: [] }),
    indicators: readJson<IndicatorData>("indicators.json", { indicators: [] }),
    performance: readJson<Performance>("performance.json", {
      mae_millions: 0,
      mae_pct: 0,
      bias_millions: 0,
      bias_pct: 0,
      rba_comparison: { n: 0, avg_edge_pp: null },
      errors: [],
    }),
    latestV2: readJsonOptional<LatestV2>("latest_v2.json"),
    backcasts: readJsonOptional<BackcastData>("backcasts.json"),
    performanceV2: readJsonOptional<Performance>("performance_v2.json"),
    indicatorsV2: readJsonOptional<IndicatorData>("indicators_v2.json"),
    latestV3: readJsonOptional<LatestV3>("latest_v3.json"),
    backtestV3: readJsonOptional<V3Backtest>("backtest_v3.json"),
    indicatorsV3: readJsonOptional<IndicatorData>("indicators_v3.json"),
    performanceV3: readJsonOptional<Performance>("performance_v3.json"),
    // The equal-weight average of v2 and v3, written by
    // `nowcasting_v3/tools/emit_combination.py` at the end of the weekly v3
    // job. Optional because the emitter is newer than the job: a checkout from
    // before it, or a week it refused before writing, has v3's files and not
    // these.
    //
    // READ ALONGSIDE v3's, NOT IN PLACE OF THEM — see `DashboardData`. The
    // loader states what is on disk and `page.tsx` decides, so the choice is
    // one line in one component rather than a `??` buried in a file reader,
    // and `latestV3` still means v3's own payload wherever it is read.
    latestCombo: readJsonOptional<LatestV3>("latest_combo.json"),
    // The union of the two models' input panels, written by the same emitter.
    // The homepage's figure is half v2's, so its indicator panel must be too.
    indicatorsCombo: readJsonOptional<IndicatorData>("indicators_combo.json"),
    performanceCombo: readJsonOptional<Performance>("performance_combo.json"),
  };
}
