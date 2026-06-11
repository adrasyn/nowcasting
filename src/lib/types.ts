export interface NowcastEstimate {
  gdp_chain_volume_millions: number;
  qoq_growth_pct: number;
  yoy_growth_pct: number;
  ci_68_low: number;
  ci_68_high: number;
  ci_95_low: number;
  ci_95_high: number;
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
// A single v2 model estimate (headline = qa_a05 precision, stress = umidas_a20).
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
  ci_basis: string;
  ci_n: number;
  ci_sd_pp: number;
  ci_bias_pp: number;
}

export interface LatestV2 {
  generated_at: string;
  schema: string;
  target_quarter: string;
  data_through: string;
  prev_level: { value: number; date: string | null; source: string };
  models: { headline: V2Model; stress: V2Model };
  v1_comparison: {
    model_name: string;
    target_quarter: string;
    qoq_growth_pct: number;
    yoy_growth_pct: number;
    gdp_chain_volume_millions: number;
    source: string;
  } | null;
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
}
