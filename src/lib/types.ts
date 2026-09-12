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
  // Which horizon produced the row: "current" (the earliest quarter the ABS has
  // not printed at that run date) or "next" (the one after it). Optional —
  // rows written before 2026-09-12 have no field and are all current-horizon.
  //
  // A row is keyed on (run_date, target_quarter), and a "next" row OUTLIVES its
  // horizon: once the ABS prints, the quarter it targets becomes the current
  // one, so the log then holds several rows for the current quarter that were
  // made at the next horizon. Anything selecting on target_quarter alone must
  // therefore say which horizons it wants.
  horizon?: string;
}

export interface VintageSeries {
  vintages: Vintage[];
}

// v1 used a fixed 4-group set; v2 adds its own (Financial & credit, etc.), so
// this is an open string. IndicatorGrid orders known groups first, then the rest.
//
// The homepage's merged panel (`data/indicators_combo.json`) speaks v3's
// vocabulary — "Labor", "Surveys", "Housing and Construction", "Retail and
// Consumption", "International Trade", "Prices", "Income" — plus one group v3
// has no series in at all: "Financial and credit", v2's credit aggregates,
// yields and spreads. It is not in GROUP_PREF, so it appends last, which is
// where it belongs.
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
  // Which model's input panel this series belongs to, on the merged file only
  // (`data/indicators_combo.json`): ["v3"], ["v2"], or both where the two
  // panels carry the same series under different ids. Provenance — nothing
  // renders it — so the grid shows one list and does not know there were two.
  models?: ("v2" | "v3")[];
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
  // v3 scores one number against one target: `qoq_nowcast_pct` is the published
  // nowcast and `qoq_actual_pct` is the ABS's first print of the quarter, the
  // number it is built to match. The fields below are provenance rather than
  // the score — the model's own figure before its rolling miss was taken off,
  // the correction that was taken off, and the same quarter as the ABS now
  // reports it after revisions. Absent on v1 and v2 payloads.
  qoq_model_nowcast_pct?: number | null;
  bias_correction_pp?: number | null;
  qoq_latest_vintage_pct?: number | null;
  // Which model produced this row: "first_print" is the current one, trained on
  // first-print GDP and corrected by its own rolling miss; "revised_target" is
  // the previous one, trained on the revised series, kept for quarters it
  // published live rather than restated by a model that did not publish them.
  // "combination" is the equal-weight average of v2 and v3 the homepage
  // publishes, and every row of `performance_combo.json` carries it.
  model?: "first_print" | "revised_target" | "combination";
  // The two component figures behind a "combination" row, so the table can be
  // read as arithmetic rather than as a third model. Absent on v1, v2 and v3.
  v2_qoq_nowcast_pct?: number | null;
  v3_qoq_nowcast_pct?: number | null;
  // The run date the scored figure comes from, live or backtested.
  // `live_run_date` names the same date only on rows that were published
  // before the ABS printed; this one is always present on a combination row.
  final_run_date?: string;
  // TRUE when this row was shifted by TODAY's correction rather than by the one
  // that stood on its own day, which was never computed. Honest approximation,
  // flagged rather than hidden.
  adjusted_retroactively?: boolean;
  yoy_nowcast: number | null;
  yoy_actual: number | null;
  yoy_rba: number | null;
  somp_release: string | null;
  edge_pp: number | null;
  // TRUE when this row is what the model actually published before the ABS
  // printed the quarter, rather than a backtest re-run over data that was
  // already known. The distinction is the whole credibility of a track record:
  // a backtest can be tuned to its own history, a live call cannot. Absent on
  // v2's payload and on every v3 row until the first quarter completes.
  is_live?: boolean;
  // The date the live figure was published, so a reader can check it against
  // `data/nowcast_history_v3.json`.
  live_run_date?: string;
}

export interface RbaComparison {
  n: number;
  avg_edge_pp: number | null;
  // The two error rates side by side, and who landed closer. A mean signed gap
  // hides how big either forecaster's misses were and cancels one large error
  // in each direction to nothing. Optional: v2's payload predates these.
  ours_mae?: number | null;
  rba_mae?: number | null;
  we_were_closer?: number | null;
}

export interface Performance {
  mae_millions: number;
  mae_pct: number;
  bias_millions: number;
  bias_pct: number;
  // What the errors above are measured against: "abs_first_print" on v3, where
  // the published nowcast and the target are both first-print figures. Absent
  // on v1, which scores against the latest vintage, and on v2, which scores
  // against the ABS's initial estimates but predates this field.
  basis?: string;
  n?: number;
  // What the model was trained on: "first_print" on v3. Absent on v1 and v2 --
  // v2 was retargeted to the ABS's initial estimates in 2026-09 but its payload
  // does not carry the field.
  target?: string;
  // How many printed quarters the rolling miss averages over, and how the
  // model's own uncorrected figure scores against the first print. Provenance
  // for the published number, not the number itself — the tiles and the table
  // above are the score.
  bias_window_quarters?: number;
  model_mae_vs_first_print_pct?: number | null;
  model_bias_vs_first_print_pct?: number | null;
  // How the scored figure was made: "equal-weight average of v2 and v3" on
  // `performance_combo.json`. Absent on the single-model payloads.
  method?: string;
  // The combination's own provenance: how many of the quarters below it called
  // live rather than in backtest, and how each component model scored over the
  // same quarters. The case for averaging is that these two are both worse
  // than `mae_pct`, so the numbers sit beside it rather than in a note.
  n_live?: number;
  v2_mae_pct?: number;
  v3_mae_pct?: number;
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
  // "current" or "next". The next-quarter model nowcasts the quarter AFTER the
  // one the ABS has not printed yet, off the same MAI, and `current_quarter`
  // names the quarter it lags into — which is also the quarter whose level its
  // own level chains off, so its level inherits the headline's error. Optional:
  // payloads emitted before 2026-09-12 carry neither.
  horizon?: string;
  current_quarter?: string;
}

export interface LatestV2 {
  generated_at: string;
  schema: string;
  target_quarter: string;
  data_through: string;
  prev_level: { value: number; date: string | null; source: string };
  // `next_quarter` is absent in the weeks when v2's index has no month past the
  // current quarter, which is the ordinary state early in a quarter.
  models: { headline: V2Model; next_quarter?: V2Model };
  // qa nowcast at each Monday — drives the evolution chart. Two rows per Monday
  // once the next quarter has data, told apart by `horizon`.
  vintages: Vintage[];
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
  // How many of this quarter's three months carry an observation. A forecast
  // quarter with zero is the model's unconditional anchor and nothing else,
  // which is why the page refuses to headline it.
  months_with_data?: number;
  // First Wednesday of the month three months after the quarter ends — the
  // ABS's scheduling rule. Emitted per horizon so each chart can plot its own
  // countdown without re-deriving the release calendar in the browser.
  release_date?: string;
  ci_68_low?: number;
  ci_68_high?: number;
  ci_95_low?: number;
  ci_95_high?: number;
  gdp_chain_volume_millions?: number;
  // The model's own estimate, before its rolling miss against the first print
  // is taken off. `qoq_growth_pct` above is the published figure — this less
  // the correction — and is what the whole page means by "the nowcast". This
  // one appears once, in the methodology panel, as provenance.
  model_qoq_growth_pct?: number;
  // On a combination payload, the two figures `qoq_growth_pct` is the mean of.
  // `check_payload.py` asserts that identity to four decimals on every horizon,
  // so these are the audit trail for the published figure and not a second
  // view of it. Absent on v3's own payload.
  //
  // `v2` IS NULL ON ONE HORIZON AND ONLY ONE. The combination keeps a forecast
  // horizon for the next quarter even in the weeks when v2 has no figure for
  // it, so this page's next-quarter card and the evolution chart's toggle do
  // not disappear for the two months in three when that quarter is empty. That
  // horizon is v3's figure alone, published with `months_with_data: 0` so the
  // card renders its waiting state and never shows the number.
  components?: { v2: number | null; v3: number };
  // The real month count behind a v3-only forecast, whose own
  // `months_with_data` is forced to 0. Nothing renders it.
  v3_months_with_data?: number;
  // Why this horizon is not an average, on the one horizon that is not.
  source?: string;
}

export interface LatestV3 {
  schema: string;
  // "abs_first_print": the horizons above are nowcasts of the ABS's first
  // print. Absent on payloads emitted before 2026-09-09.
  basis?: string;
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
  // What the model was trained on: "first_print". Absent on payloads emitted
  // before 2026-09-10.
  target?: string;
  // The model's own rolling miss against the first print, taken off its
  // estimate to produce the published figure. Re-estimated each week from
  // quarters that have already printed, so it carries no information about the
  // quarter being nowcast. Absent on payloads emitted before 2026-09-10.
  bias_correction?: {
    pp: number;
    n: number;
    window_quarters: number;
    min_quarters: number;
    first_quarter: string;
    last_quarter: string;
    basis: string;
  } | null;
  ci_basis?: string;
  // ---- combination payloads (`data/latest_combo.json`, schema "combo-1") ----
  // Same shape as v3's, so every component on the homepage renders it
  // unchanged. These four fields are the difference, and all four are absent
  // on v3's own payload.
  //
  // NOTE ON WHAT IS *NOT* THE COMBINATION'S. `bias_correction`, `panel`,
  // `diagnostics` and `estimate` are copied straight from v3 and describe the
  // v3 half only: the combination's own figure has no single correction behind
  // it and no single panel. The methodology panel says so.
  method?: string;
  // The empirical band parameters, per horizon. `provisional_next` is true
  // while the next-quarter band is the pooled current-quarter one, which
  // understates a forecast's uncertainty.
  band_pp?: {
    current?: { p68: number; p95: number; n: number; mae: number; bias: number };
    next?: { p68: number; p95: number; n: number; mae: number; bias: number };
    provisional_next?: boolean;
  };
  // Which run of each model this week's average is built from, and how stale
  // v2's was if it did not run.
  components?: {
    v2?: { as_of: string; run_date: string; schema?: string; stale_days?: number };
    v3?: { as_of: string; schema?: string };
  };
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
  kind?: "nowcast" | "forecast";
  months_with_data?: number;
  qoq_growth_pct: number;
  ci_68_low: number;
  ci_68_high: number;
  ci_95_low: number;
  ci_95_high: number;
  data_through: string;
  // On a combination vintage, the two figures this row averages and the v2 run
  // it took (v2 runs at 19:00 UTC Sunday and v3 at 20:30, both Monday morning
  // in Sydney, and a quiet v2 week is carried forward up to seven days, so the
  // two dates need not match).
  v2_qoq_growth_pct?: number;
  v2_run_date?: string;
  v3_qoq_growth_pct?: number;
  // "current" or "next" — which quarter this row was FOR at the time it was
  // written, decided by the run's own date against the ABS release calendar.
  // A 2026 Q3 row is "next" before Q2 printed and "current" after.
  horizon?: string;
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
  // Both models' panels as one list — what the homepage shows, because the
  // homepage publishes an average of the two. Optional for the same reason the
  // combination payloads are: a checkout from before the emitter has v3's file
  // and not this one, and the page falls back to v3's panel.
  indicatorsCombo?: IndicatorData;
  performanceV3?: Performance;  // v3's backtest track record
  // The equal-weight average of v2 and v3 — what the homepage publishes when
  // these are present. SEPARATE FIELDS RATHER THAN AN OVERRIDE OF latestV3,
  // deliberately. `latestV3` means v3's own payload everywhere it is read, so
  // a test or a future panel that wants the v3 half can still have it; a
  // loader that quietly returned an average under that name would leave
  // nothing on the site able to name either model's own figure. `page.tsx`
  // chooses which to publish; the loader only reports what is on disk.
  latestCombo?: LatestV3;
  performanceCombo?: Performance;
}
