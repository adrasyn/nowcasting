import { loadDashboardData } from "../../src/lib/data";
import { buildMonitorView } from "../../src/lib/monitor";
import type { DashboardData } from "../../src/lib/types";
export function fixtureData() {
  const d = structuredClone(loadDashboardData());
  d.gdp.series = d.gdp.series.filter((r) => r.quarter <= "2026 Q2");
  d.latestCombo = {
    ...d.latestCombo!,
    status: "ok",
    as_of: "2026-11-16",
    generated_at: "2026-11-16T10:00:00Z",
    target_quarter: "2026 Q3",
    horizons: [
      {
        ...h("2026 Q3", "nowcast", 0.4377, "2026-12-02"),
        gdp_chain_volume_millions: 702523,
        components: { v2: 0.42, v3: 0.4555 },
      },
      {
        ...h("2026 Q4", "forecast", 0.2525, "2027-03-03"),
        components: { v2: 0.3, v3: 0.205 },
      },
    ],
    vintages: ["2026 Q2", "2026 Q3", "2026 Q4"].flatMap((q) =>
      ["2026-11-09", "2026-11-16"].map((date) => ({
        ...h(q, "nowcast", q === "2026 Q4" ? 0.2525 : 0.4377, "2026-12-02"),
        target_quarter: q,
        run_date: date,
        data_through: "2026-09",
      })),
    ),
    components: {
      v2: { as_of: "2026-11-16", run_date: "2026-11-16", stale_days: 0 },
    },
  };
  d.historyCombo = { runs: [...d.latestCombo!.vintages!] };
  if (d.latestV3)
    d.latestV3 = {
      ...d.latestV3,
      status: "ok",
      as_of: "2026-11-16",
      target_quarter: "2026 Q3",
      horizons: [h("2026 Q3", "nowcast", 0.45, "2026-12-02")],
    };
  const anz = d.indicatorsCombo?.indicators.find((i) => i.id === "anz_sent");
  if (anz) {
    anz.source_checked_at = "2026-11-18T12:11:09Z";
    delete anz.last_release_date;
    anz.series = [
      { date: "2026-10", value: 65 },
      { date: "2026-11", value: 65.3, provisional: true },
    ];
  }
  return d;
}
export const finalBuiltAt = "2026-12-01T07:40:00Z";
export function finalFixtureData() {
  const d = fixtureData(), latest = d.latestCombo!;
  const run = "2026-12-01";
  latest.as_of = run;
  latest.generated_at = "2026-12-01T07:30:00Z";
  latest.final_estimate = {
    quarter: latest.target_quarter!, run_date: run,
    generated_at: latest.generated_at, release_at: "2026-12-02T11:30:00+11:00",
  };
  latest.components = { v2: { as_of: run, run_date: run }, v3: { as_of: run } };
  const h = latest.horizons[0];
  h.qoq_growth_pct = 0.48; // A later revision must move the dashed trail.
  h.complete_months = ["2026-07", "2026-08", "2026-09"];
  const early = latest.vintages!.find(r =>
    r.target_quarter === "2026 Q3" && r.run_date === "2026-11-16")!;
  early.horizon = "current";
  early.v2_run_date = early.run_date;
  early.complete_months = h.complete_months;
  latest.vintages!.push({
    ...h, target_quarter: h.quarter, run_date: run, horizon: "current",
    v2_run_date: run, data_through: "2026-10",
    ci_68_low: h.ci_68_low!, ci_68_high: h.ci_68_high!,
    ci_95_low: h.ci_95_low!, ci_95_high: h.ci_95_high!,
  });
  return d;
}
const fresh = fixtureData;
const view = (d: DashboardData) => buildMonitorView(d, "2026-11-19T10:00:00Z");
function addActual(d: DashboardData, q: string, value = 704000) {
  d.gdp.series.push({ quarter: q, value, qoq_pct: 0.5, yoy_pct: 2 });
}
function h(
  quarter: string,
  kind: "nowcast" | "forecast",
  qoq: number,
  release: string,
) {
  return {
    quarter,
    kind,
    qoq_growth_pct: qoq,
    model_qoq_growth_pct: qoq,
    annualised_growth_pct: 0,
    months_with_data: kind === "nowcast" ? 3 : 1,
    release_date: release,
    ci_68_low: qoq - 0.2,
    ci_68_high: qoq + 0.2,
    ci_95_low: qoq - 0.4,
    ci_95_high: qoq + 0.4,
  };
}
export function fixtureViews() {
  const weekly = fresh();
  weekly.latestCombo!.as_of = "2026-11-23";
  weekly.latestCombo!.horizons[0].qoq_growth_pct = 0.53;
  weekly.latestCombo!.vintages!.push({
    ...weekly.latestCombo!.vintages!.at(-1)!,
    target_quarter: "2026 Q3",
    run_date: "2026-11-23",
    qoq_growth_pct: 0.53,
  });
  const input = weekly.indicatorsCombo!.indicators.find(
    (i) => i.id === "employment",
  )!;
  input.series.push({
    date: "2026-10",
    value: input.series.at(-1)!.value + 10,
  });
  input.last_release_date = "2026-11-23";
  input.updated_this_run = true;
  const release = fresh();
  addActual(release, "2026 Q3");
  release.latestCombo!.as_of = "2026-12-07";
  release.latestCombo!.target_quarter = "2026 Q4";
  release.latestCombo!.horizons = [
    h("2026 Q4", "nowcast", -0.12, "2027-03-03"),
    h("2027 Q1", "forecast", 0, "2027-06-02"),
  ];
  const year = fresh();
  addActual(year, "2026 Q3");
  addActual(year, "2026 Q4", 706000);
  year.latestCombo!.target_quarter = "2027 Q1";
  year.latestCombo!.as_of = "2027-03-08";
  year.latestCombo!.horizons = [h("2027 Q1", "nowcast", 1.2, "2027-06-02")];
  for (const d of [release, year])
    for (const horizon of d.latestCombo!.horizons) {
      d.latestCombo!.vintages!.push({
        target_quarter: horizon.quarter,
        run_date: d.latestCombo!.as_of,
        data_through: "2026-11",
        qoq_growth_pct: horizon.qoq_growth_pct,
        ci_68_low: horizon.ci_68_low!,
        ci_68_high: horizon.ci_68_high!,
        ci_95_low: horizon.ci_95_low!,
        ci_95_high: horizon.ci_95_high!,
      });
    }
  if (release.performanceCombo) {
    const previous = release.performanceCombo.errors.at(-1)!;
    release.performanceCombo.errors = [
      ...release.performanceCombo.errors.filter(
        (r) => r.target_quarter !== "2026 Q3",
      ),
      {
        ...previous,
        target_quarter: "2026 Q3",
        qoq_nowcast_pct: 0.4377,
        qoq_actual_pct: 0.5,
        qoq_error_pp: -0.0623,
        is_live: true,
      },
    ];
  }
  const stale = fresh();
  stale.latestCombo!.as_of = "2026-10-01";
  stale.latestCombo!.components!.v2!.stale_days = 7;
  stale.latestCombo!.horizons[1].months_with_data = 0;
  const refused = fresh();
  refused.latestCombo!.status = "refused";
  refused.latestCombo!.refusal_reason = "Test refusal";
  const missing = fresh();
  delete missing.latestCombo;
  delete missing.latestV3;
  delete missing.performanceCombo;
  delete missing.indicatorsCombo;
  const v3 = fresh();
  delete v3.latestCombo;
  const component = fresh();
  component.latestCombo!.horizons[1] = {
    ...component.latestCombo!.horizons[1],
    months_with_data: 0,
    v3_months_with_data: 1,
    components: { v2: null, v3: 0.3 },
  };
  const selection = fresh();
  selection.indicatorsCombo = {
    indicators: [
      ...selection.indicatorsCombo!.indicators.slice(0, 3),
      {
        id: "new-empty-series",
        name: "Newly selected input",
        unit: "index",
        source: "Fixture only",
        group: "New selection",
        series: [],
      },
    ],
  };
  const final = finalFixtureData();
  const expired = buildMonitorView(final, "2026-12-02T00:30:00Z");
  const rolled = finalFixtureData();
  addActual(rolled, "2026 Q3");
  return {
    final: buildMonitorView(final, finalBuiltAt),
    expired,
    rolled: buildMonitorView(rolled, "2026-12-02T01:00:00Z"),
    component: view(component),
    v3: view(v3),
    selection: view(selection),
    weekly: view(weekly),
    release: view(release),
    year: view(year),
    stale: view(stale),
    refused: view(refused),
    missing: view(missing),
  };
}
