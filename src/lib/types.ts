export interface NowcastEstimate {
  gdp_chain_volume_millions: number;
  qoq_growth_pct: number;
  yoy_growth_pct: number;
  ci_68_low: number;
  ci_68_high: number;
  ci_95_low: number;
  ci_95_high: number;
}

// The durable per-run record of *what data fed this week's run and how the
// number moved* — the causal audit trail the pipeline previously discarded.
// Lives quietly on latest.json / latest_v2.json (no visible panel); also powers
// the "updated this week" highlight in the indicator grid.
export interface DataUpdateSeries {
  id: string;
  name: string;
  prev_period: string;   // "YYYY-MM" the series carried last run
  latest_period: string; // "YYYY-MM" it advanced to this run
}

export interface DataUpdates {
  run_date: string;                  // "YYYY-MM-DD" of this run
  nowcast_delta_pp: number | null;   // qoq move vs the previous run (pp)
  series: DataUpdateSeries[];         // series that gained a fresh observation
}

export interface LatestNowcast {
  generated_at: string; // ISO 8601
  target_quarter: string; // e.g. "2026 Q1"
  data_through: string; // e.g. "2026-04"
  next_gdp_release_date: string; // ISO date, e.g. "2026-06-04"
  nowcast: NowcastEstimate;
  latest_actual: {
    quarter: string;
    gdp_chain_volume_millions: number;
    qoq_growth_pct: number;
    released_days_before_next: number; // e.g. -92
  };
  data_updates?: DataUpdates;
}

export interface GdpQuarter {
  quarter: string;
  value: number;
  qoq_pct: number;
  yoy_pct: number;
}

export interface GdpSeries {
  series: GdpQuarter[];
}

export interface Vintage {
  run_date: string; // "YYYY-MM-DD"
  target_quarter: string;
  point: number;
  qoq_growth_pct: number;
  days_until_release: number; // negative = before release
  ci_68_low: number;
  ci_68_high: number;
  ci_95_low: number;
  ci_95_high: number;
  data_through: string;
}

export interface VintageSeries {
  vintages: Vintage[];
}

// v1 used a fixed 4-group set; v2 adds its own (Financial & credit, etc.), so
// this is an open string. IndicatorGrid orders known groups first, then the rest.
export type IndicatorGroup = string;

export interface IndicatorPoint {
  date: string; // "YYYY-MM"
  value: number;
}

export interface Indicator {
  id: string;
  name: string;
  group: IndicatorGroup;
  unit: string;
  source: string;
  series: IndicatorPoint[];
  last_release_date?: string;       // ISO "YYYY-MM-DD" — when the latest point was released
  next_release_estimate?: string;   // ISO "YYYY-MM-DD" — when the next point is expected
  // Set by the weekly emit when this series gained a newer observation than it
  // carried in the previous run — i.e. it is one of the inputs that fed *this*
  // week's nowcast. prev_period/latest_period are "YYYY-MM" (e.g. "May → Jun").
  updated_this_run?: boolean;
  prev_period?: string;
  latest_period?: string;
}

export interface IndicatorData {
  indicators: Indicator[];
}

export interface AccuracyError {
  target_quarter: string;
  final_nowcast: number;
  actual: number;
  error_millions: number;
  error_pct: number;
  // QoQ growth per quarter — what the table displays. Optional: v1's
  // performance.json and pre-2026-08 v2 payloads carry levels only.
  qoq_nowcast_pct?: number;
  qoq_actual_pct?: number;
  qoq_error_pp?: number;
  yoy_nowcast: number | null;
  yoy_actual: number | null;
  yoy_rba: number | null;
  somp_release: string | null;
  edge_pp: number | null;
}

export interface RbaComparison {
  n: number;
  avg_edge_pp: number | null;
}

export interface Performance {
  mae_millions: number;
  mae_pct: number;
  bias_millions: number;
  bias_pct: number;
  rba_comparison: RbaComparison;
  errors: AccuracyError[];
}

// ---- v2 cutover (staged; gated on approval) ----------------------------------
// A single v2 model estimate (headline = qa_a10, the paper's selection threshold).
export interface V2Model {
  model_id: string;
  model_name: string;
  target_quarter: string;
  gdp_chain_volume_millions: number;
  qoq_growth_pct: number;
  yoy_growth_pct: number;
  ci_68_low: number;
  ci_68_high: number;
  ci_95_low: number;
  ci_95_high: number;
  n_months_in_quarter: number;
  // Which of the paper's per-stage models produced this figure: "QA-UMIDAS" on a
  // complete quarter, "UMIDAS-full" below it. Optional — vintages emitted before
  // per-stage dispatch (840e636) predate the field.
  estimator?: string;
  // Error-dispersion fields kept for the record. The site does NOT render these as
  // a confidence interval: centred on an uncorrected point estimate the 68% band
  // achieved 41% coverage. Re-measure before presenting them as a probability.
  ci_basis: string;
  ci_n: number;
  ci_sd_pp: number;
  ci_bias_pp: number;
  // Track record published in place of an interval, per the Atlanta Fed's GDPNow.
  // Optional: absent from payloads emitted before 2026-08-08.
  err_mae_pp?: number;
  err_bias_pp?: number;
  err_n?: number;
  // Which information stage's CI params were used ("pooled" if this stage was too
  // thin to calibrate). Optional for the same reason.
  ci_stage?: number | string;
}

export interface LatestV2 {
  generated_at: string;
  schema: string;
  target_quarter: string;
  data_through: string;
  prev_level: { value: number; date: string | null; source: string };
  models: { headline: V2Model };
  vintages: Vintage[]; // qa nowcast at each Monday — drives the evolution chart
  v1_comparison: {
    model_name: string;
    target_quarter: string;
    qoq_growth_pct: number;
    yoy_growth_pct: number;
    gdp_chain_volume_millions: number;
    source: string;
  } | null;
  data_updates?: DataUpdates;
  note: string;
}

export interface Backcast {
  target_quarter: string;
  qoq_forecast_pct: number;
  qoq_actual_pct: number;
  error_pp: number;
  direction_correct: boolean;
  is_backcast: true;
}

export interface BackcastData {
  model: string;
  basis: string;
  note: string;
  n: number;
  mae_pp: number;
  hit_rate_pct: number;
  backcasts: Backcast[];
}

// ---------------------------------------------------------------------------
// v3 (NY Fed Staff Nowcast 2.0 port, Australian panel)
// ---------------------------------------------------------------------------

// A REFUSAL IS A STATUS, NOT AN ABSENT FILE. v3 declines to publish rather than
// emit a figure it does not trust — a stale feed, or a chain that left GDP
// disconnected from the panel. The page must render that as a refusal; falling
// back to the previous file would show last week's number as if it were
// current, which is the failure the model's guards exist to prevent.
export interface V3Horizon {
  quarter: string;
  kind: "nowcast" | "forecast";
  qoq_growth_pct: number;
  annualised_growth_pct: number;
  ci_68_low?: number;
  ci_68_high?: number;
  ci_95_low?: number;
  ci_95_high?: number;
  gdp_chain_volume_millions?: number;
}

export interface LatestV3 {
  schema: string;
  status: "ok" | "refused";
  generated_at: string;
  as_of: string;
  // present when status === "refused"
  refusal_reason?: string;
  refusal_detail?: string;
  // present when status === "ok"
  target_quarter?: string;
  data_through?: string;
  prev_level?: { value: number; quarter: string } | null;
  horizons: V3Horizon[];
  vintages?: V3Vintage[];
  next_gdp_release_date?: string;
  ci_basis?: string;
  panel?: {
    n_series: number;
    n_months: number;
    first_month: string;
    series: string[];
    deflator_skipped: Record<string, string>;
  };
  diagnostics?: {
    gdp_global_loading: number;
    collapse_floor: number;
    n_gs: number;
    n_burn: number;
    seed: number;
  };
}

export interface V3Vintage {
  run_date: string;
  target_quarter: string;
  qoq_growth_pct: number;
  ci_68_low: number;
  ci_68_high: number;
  ci_95_low: number;
  ci_95_high: number;
  data_through: string;
}

export interface V3Score {
  mae: number;
  rmse: number;
  bias: number;
  r_squared: number;
  // An honest conditional mean varies at sqrt(R^2) of the outcome's spread.
  // Varying more than that is confidence the model has not earned.
  dispersion_ratio: number;
  calibrated_ratio: number;
}

export interface V3Backtest {
  schema: string;
  window: {
    first_target: string;
    last_target: string;
    n_vintages: number;
    n_quarters: number;
  };
  scores: { v3: V3Score; v2: V3Score };
  by_quarter: {
    target: string;
    actual: number;
    v3: number;
    v2: number;
    n_vintages: number;
  }[];
  notes: Record<string, string>;
}

export interface DashboardData {
  latest: LatestNowcast;
  gdp: GdpSeries;
  nowcasts: VintageSeries;
  indicators: IndicatorData;
  performance: Performance;
  // Staged v2 cutover artifacts (optional — present once the v2 pipeline emits them).
  latestV2?: LatestV2;
  backcasts?: BackcastData;
  performanceV2?: Performance; // backcast track record in the live $M schema
  indicatorsV2?: IndicatorData; // the v2 model's input panel
  // v3 preview artifacts (optional — present once the v3 runner has emitted them).
  latestV3?: LatestV3;
  backtestV3?: V3Backtest;
  indicatorsV3?: IndicatorData; // the v3 model's input panel
  performanceV3?: Performance;  // v3's backtest track record
}
