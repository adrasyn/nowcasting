"use client";

import * as React from "react";
import { useEffect, useMemo, useState } from "react";
import type { Indicator, V3Vintage } from "@/lib/types";
import type { MonitorView, MonitorHorizon } from "@/lib/monitor";
import {
  bandFor,
  dayLabel,
  finite,
  monthLabel,
  percentage,
  quarterIndex,
  quarterLabel,
  quarterMonths,
  signed,
} from "@/lib/monitor";
import {
  indicatorChart,
  latestValue,
  rawChange,
  relativeChange,
  canonicalUnit,
} from "@/lib/monitor/indicators";
import {
  compareDisplayedUpdates,
  displayUpdateInfo,
} from "@/lib/monitor/indicatorDates.mjs";
import { indicatorDisplayUnit } from "@/lib/indicatorDisplay";
import { RangeChart, Evolution, SeriesChart, bandText } from "./Charts";
import { AnimatedValue } from "./Entrance";
import { sharedQuarterRangeBound } from "@/lib/monitor/rangeScale";
import { entranceGroup, type EntranceGroup } from "@/lib/monitor/entrance";
function Provisional() {
  return (
    <span
      className="provisional"
      role="img"
      title="Provisional observation"
      aria-label="Provisional"
    >
      P
    </span>
  );
}
function QuarterCard({
  h,
  group,
  bound,
}: {
  h: MonitorHorizon;
  group: EntranceGroup;
  bound: number;
}) {
  return (
    <article
      className={`estimate ${h.role}`}
      data-quarter={h.quarter}
      data-state={h.state}
    >
      {h.finalEstimate && (
        <div className="final-estimate-strip">
          Final estimate<span> (no new data)</span>
        </div>
      )}
      <div className="estimate-heading">
        <h2>{quarterLabel(h.quarter)}: GDP nowcast</h2>
        <span>{quarterMonths(h.quarter)}</span>
      </div>
      <dl className="growth-metrics">
        <div className="quarter-growth">
          <dt>Growth this quarter</dt>
          <dd className="estimate-number" data-value="qoq">
            <AnimatedValue value={h.qoq} group={group} />
          </dd>
        </div>
        <div className="year-growth">
          <dt>Growth from a year ago</dt>
          <dd className="year-number" data-value="yoy">
            <AnimatedValue value={h.yoy} group={group} />
          </dd>
        </div>
      </dl>
      {h.state !== "ready" && (
        <p className="estimate-status">
          {h.state === "refused"
            ? "No estimate published"
            : h.state === "no-data"
              ? h.source?.components?.v2 === null
                ? "Awaiting both model estimates"
                : "Awaiting the first month of indicator data"
              : "Estimate not yet available"}
        </p>
      )}
      <dl className="estimate-meta">
        <div>
          <dt>Change since last estimate</dt>
          <dd
            title={
              h.previousRunDate
                ? `Previous estimate: ${dayLabel(h.previousRunDate, true)}`
                : undefined
            }
          >
            {finite(h.delta) && h.state === "ready"
              ? signed(h.delta) + "pp"
              : "—"}
          </dd>
        </div>
        <div>
          <dt>Months of data</dt>
          <dd>{h.months !== null ? `${h.months} / 3` : "—"}</dd>
        </div>
        <div>
          <dt>ABS release</dt>
          <dd>{dayLabel(h.release, true)}</dd>
        </div>
      </dl>
      <div className="range-graphic">
        <RangeChart h={h} group={group} bound={bound} />
      </div>
      <div className="band-numbers">
        <span>
          68% {h.bandKind} band <b>{bandText(h.band68)}</b>
        </span>
        <span>
          95% {h.bandKind} band <b>{bandText(h.band95)}</b>
        </span>
      </div>
    </article>
  );
}
function UpdateDate({
  indicator: i,
  mobile = false,
}: {
  indicator: Indicator;
  mobile?: boolean;
}) {
  const info = displayUpdateInfo(i);
  if (!info.day) return mobile ? null : <>—</>;
  const quiet = i.id === "anz_sent" && info.kind === "checked",
    explanation =
      info.kind === "checked"
        ? "Date the source was retrieved; this is not an observation release date."
        : "Recorded source release date.";
  return (
    <span
      className={mobile ? "mobile-update" : undefined}
      title={`${info.label} ${dayLabel(info.day, true)}. ${explanation}`}
    >
      {mobile ? " · " : ""}
      {info.kind === "checked" || mobile ? (
        <span
          className={quiet ? "visually-hidden" : mobile ? "" : "update-kind"}
        >
          {info.label}{" "}
        </span>
      ) : (
        <span className="visually-hidden">Updated </span>
      )}
      <time dateTime={info.day} aria-label={dayLabel(info.day, true)}>
        {dayLabel(info.day)}
      </time>
    </span>
  );
}
function IndicatorRow({ indicator: i }: { indicator: Indicator }) {
  const [open, setOpen] = useState(false),
    chart = useMemo(() => indicatorChart(i), [i]),
    last = i.series.at(-1),
    previous = i.series.at(-2),
    rel = relativeChange(i),
    update = displayUpdateInfo(i),
    unit = canonicalUnit(i).toLowerCase();
  return (
    <details
      id={`series-${i.id}`}
      className={`series-row ${i.updated_this_run ? "advanced" : ""}`}
      onToggle={(e) => setOpen(e.currentTarget.open)}
    >
      <summary className="series-summary">
        <div>
          <p className="series-name">
            {i.name}
            {last?.provisional && <Provisional />}
          </p>
          <p className="series-date">
            {monthLabel(last?.date)}
            <UpdateDate indicator={i} mobile />
            {i.updated_this_run && (
              <span className="visually-hidden">
                {" "}
                · Updated since last week
              </span>
            )}
          </p>
        </div>
        <div className="spark">
          <SeriesChart data={chart} name={i.name} mini />
        </div>
        <div className="series-latest">
          {latestValue(i, last?.value)}
          {["index", "net balance", "count"].includes(unit) && (
            <small>{indicatorDisplayUnit(i)}</small>
          )}
        </div>
        <div className="series-delta">
          {rawChange(i)}
          {rel !== null && (
            <span className="mobile-relative">{percentage(rel)}</span>
          )}
        </div>
        <div className="series-relative">
          {rel !== null ? percentage(rel) : "—"}
        </div>
        <div
          className="series-release"
          data-update-date={update.day ?? ""}
          data-update-kind={update.kind ?? ""}
        >
          <UpdateDate indicator={i} />
        </div>
        <div className="series-next">{dayLabel(i.next_release_estimate)}</div>
        <span className="expand" aria-hidden="true">
          +
        </span>
      </summary>
      <div className="series-detail">
        <div>
          <div className="detail-heading">
            <h4>{chart.description}</h4>
            <span>{chart.unit}</span>
          </div>
          <div className="series-chart">
            {open && <SeriesChart data={chart} name={i.name} />}
          </div>
          <dl className="detail-meta">
            {last?.provisional && (
              <div>
                <dt>Observation status</dt>
                <dd>Provisional monthly observation</dd>
              </div>
            )}
            <div>
              <dt>Previous observation</dt>
              <dd>
                {previous
                  ? `${monthLabel(previous.date)} / ${latestValue(i, previous.value)}`
                  : "—"}
              </dd>
            </div>
            <div>
              <dt>Change</dt>
              <dd>
                {rawChange(i)}
                {rel !== null ? ` / ${percentage(rel)}` : ""}
              </dd>
            </div>
            <div>
              <dt>Last released</dt>
              <dd>{dayLabel(i.last_release_date, true)}</dd>
            </div>
            {i.source_checked_at && (
              <div>
                <dt>Source checked</dt>
                <dd>
                  {dayLabel(i.source_checked_at, true)} (retrieved, not
                  released)
                </dd>
              </div>
            )}
            <div>
              <dt>Next release · estimate</dt>
              <dd>{dayLabel(i.next_release_estimate, true)}</dd>
            </div>
            {i.updated_this_run && (
              <div>
                <dt>Updated since last week</dt>
                <dd>
                  {monthLabel(i.prev_period)} → {monthLabel(i.latest_period)}
                </dd>
              </div>
            )}
            <div>
              <dt>Source</dt>
              <dd>
                {i.source_url ? (
                  <a href={i.source_url}>Official monthly source</a>
                ) : (
                  i.source
                )}
              </dd>
            </div>
          </dl>
          {i.data_note && <p className="record-note">{i.data_note}</p>}
        </div>
        <section
          className="observations"
          aria-label={`All ${i.name} observations`}
        >
          <h4>
            All {i.series.length} observations · {indicatorDisplayUnit(i)}
            {chart.transformed ? " · levels" : ""}
          </h4>
          <div className="observation-list" role="list">
            {i.series
              .slice()
              .reverse()
              .map((r, j) => (
                <div key={r.date + "-" + j} role="listitem">
                  <span>{monthLabel(r.date)}</span>
                  <span>
                    {latestValue(i, r.value)}
                    {r.provisional && (
                      <>
                        {" "}
                        <Provisional />
                      </>
                    )}
                  </span>
                </div>
              ))}
          </div>
        </section>
      </div>
    </details>
  );
}
function GdpHistory({ view: v }: { view: MonitorView }) {
  const years = new Map<
    string,
    Map<number, { value: number | null; nowcast: boolean }>
  >();
  for (const r of v.gdp) {
    const n = quarterIndex(r.quarter)!;
    const year = String(Math.floor(n / 4));
    if (!years.has(year)) years.set(year, new Map());
    years.get(year)!.set(n % 4, {
      value: finite(r.qoq_pct) ? r.qoq_pct : null,
      nowcast: false,
    });
  }
  if (v.current.state === "ready" && v.current.quarter) {
    const n = quarterIndex(v.current.quarter)!,
      year = String(Math.floor(n / 4));
    if (!years.has(year)) years.set(year, new Map());
    if (!years.get(year)!.has(n % 4))
      years.get(year)!.set(n % 4, { value: v.current.qoq, nowcast: true });
  }
  const keys = [...years.keys()].sort().reverse(),
    cut = Math.ceil(keys.length / 2);
  return (
    <div id="gdp-table">
      {[keys.slice(0, cut), keys.slice(cut)]
        .filter((x) => x.length)
        .map((group, j) => (
          <div key={j} className="table-scroll">
            <table className="matrix">
              <caption className="visually-hidden">
                Quarterly real GDP growth (%), latest published ABS vintage.
                Highlighted cell is a nowcast.
              </caption>
              <thead>
                <tr>
                  <th scope="col">Year</th>
                  {[1, 2, 3, 4].map((q) => (
                    <th key={q} scope="col">
                      Q{q}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {group.map((year) => (
                  <tr key={year}>
                    <th scope="row">{year}</th>
                    {[0, 1, 2, 3].map((q) => {
                      const p = years.get(year)!.get(q);
                      return (
                        <td
                          key={q}
                          className={p?.nowcast ? "nowcast-cell" : undefined}
                          aria-label={
                            p?.nowcast
                              ? `Q${q + 1} ${year} nowcast ${percentage(p.value)}`
                              : undefined
                          }
                        >
                          {finite(p?.value) ? signed(p.value) : "—"}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
    </div>
  );
}
function WeeklyHistory({ rows }: { rows: V3Vintage[] }) {
  const quarters = [...new Set(rows.map((r) => r.target_quarter))];
  return (
    <div id="weekly-tables">
      {quarters.length ? (
        quarters.map((q) => (
          <div key={q}>
            <h4 className="weekly-label">{quarterLabel(q)}</h4>
            <div className="table-scroll" data-history-quarter={q}>
              <table>
                <caption className="visually-hidden">
                  All published weekly estimates for {quarterLabel(q)}; interval
                  type follows the published model and horizon at that run.
                </caption>
                <thead>
                  <tr>
                    {["Run", "q/q", "68% band", "95% band"].map((h) => (
                      <th key={h} scope="col">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows
                    .filter((r) => r.target_quarter === q)
                    .map((r) => (
                      <tr key={r.run_date}>
                        <td>{dayLabel(r.run_date, true)}</td>
                        <td>{percentage(r.qoq_growth_pct)}</td>
                        <td>{bandText(bandFor(r, 68))}</td>
                        <td>{bandText(bandFor(r, 95))}</td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          </div>
        ))
      ) : (
        <p className="empty">No weekly history available.</p>
      )}
    </div>
  );
}
function Methodology({ view: v }: { view: MonitorView }) {
  const bc = v.latest?.bias_correction,
    window = bc?.window_quarters ?? v.performance?.bias_window_quarters,
    panel = v.latest?.panel?.n_series;
  return (
    <section id="methodology" aria-labelledby="method-title">
      <div className="section-heading">
        <h2 id="method-title">Methodology</h2>
        <a
          className="section-link"
          href="https://github.com/adrasyn/nowcasting"
        >
          Source ↗
        </a>
      </div>
      <div className="method-grid">
        <div>
          <p>
            This page nowcasts Australia’s quarterly real GDP growth ahead of
            the ABS release.{" "}
            {v.model === "combination"
              ? "The published figure is the equal-weighted average of two models. Both are estimated on the ABS’s initial estimate of GDP for each quarter, the figure published on the day, and the track record is scored against the same figure."
              : "The published figure is the v3 model’s estimate of the ABS initial quarterly GDP estimate, scored against that same first print."}
          </p>
          <p>
            The{" "}
            <a href="https://www.newyorkfed.org/research/policy/nowcast">
              New York Fed Staff Nowcast 2.0
            </a>{" "}
            is a Bayesian dynamic factor model ported to Python from the Fed’s
            published MATLAB.{" "}
            {finite(panel)
              ? `${panel} monthly and quarterly series load`
              : "Monthly and quarterly series load"}{" "}
            onto five latent factors: global, soft, nominal, labour, and a COVID
            factor active only between March 2020 and December 2021. Stochastic
            volatility and outlier states absorb large shocks. Its estimate is
            corrected for its own average error
            {finite(window) ? ` over the last ${window} quarters` : ""}
            {finite(bc?.pp) ? `, currently ${signed(bc.pp)}pp` : ""}.
          </p>
          {v.model === "combination" && (
            <p>
              The second follows the Reserve Bank of Australia’s{" "}
              <a href="https://www.rba.gov.au/publications/rdp/2024/2024-04.html">
                Research Discussion Paper 2024-04
              </a>
              . A dynamic factor model condenses monthly indicators into a
              monthly activity indicator. A mixed-frequency (U-MIDAS) regression
              maps the available months onto quarterly GDP growth. Indicators
              are re-selected each quarter on explanatory power; our panel is
              limited to freely available data.
            </p>
          )}
        </div>
        <div>
          <p>
            {v.model === "combination"
              ? "Combination error bands use historical absolute-error quantiles, calibrated separately for current and next quarters from weekly vintages. They are empirical error ranges, not posterior probabilities or statistical confidence intervals. A next-quarter estimate from v3 alone retains its posterior bands."
              : "The v3 bands are posterior credible intervals from the Bayesian model; empirical coverage need not match nominal probability."}
            {v.latest?.band_pp?.provisional_next
              ? " The next-quarter empirical calibration is provisional and uses the pooled current-quarter band, which can understate uncertainty."
              : ""}
          </p>
          <p>
            q/q compares the preceding quarter; y/y compares the same quarter a
            year earlier using the run’s GDP level. A next-quarter level can
            depend on the current-quarter estimate. Published GDP history uses
            the latest ABS vintage; track-record actuals use the initial
            estimate. A verified ABS observation advances the current target;
            calendar dates alone do not.
          </p>
          <p>
            MAE is the mean absolute miss; mean signed error is nowcast minus
            actual. Positive bias means estimates tend to be high. Rows marked
            Live were published before the ABS release; Backtest rows re-use
            data already known and do not establish live forecast performance.{" "}
            {v.performance?.rba_comparison?.n
              ? `RBA comparisons cover ${v.performance.rba_comparison.n} matched June/December quarters; the RBA forecast is published mid-quarter, earlier than the full-quarter nowcast.`
              : ""}
          </p>
        </div>
        <div>
          <p>
            Indicator changes compare adjacent observations. Monthly and
            quarterly chart changes are not annualised. Employment charts show
            monthly change in people employed, in thousands; their tables retain
            source levels. Gaps remain gaps. Rate changes use percentage points;
            survey changes use points. P means provisional.
          </p>
          <p>
            Updated dates are recorded source release dates; Checked dates are
            source retrieval dates, not publication dates. Next-release dates
            are estimates. Observation periods are shown separately. The
            indicator panel, scores and full weekly archive follow the selected
            model; a missing section is reported rather than borrowed from
            another model.
          </p>
          <p>
            <a href="https://github.com/adrasyn/nowcasting/tree/main/docs">
              Methodology and measurements
            </a>{" "}
            ·{" "}
            <a href="https://github.com/adrasyn/nowcasting/tree/main/data">
              Data and archives
            </a>{" "}
            · <a href="/v2">v2 comparison</a> ·{" "}
            <a href="/simple/">Simple HTML version</a>
          </p>
        </div>
      </div>
    </section>
  );
}
export default function Monitor({
  view: v,
}: {
  view: MonitorView;
}): React.JSX.Element {
  const indicators = useMemo(
      () => [...v.indicators.indicators].sort(compareDisplayedUpdates),
      [v.indicators],
    ),
    p = v.performance,
    errors = [...(p?.errors ?? [])].sort(
      (a, b) =>
        (quarterIndex(b.target_quarter) ?? 0) -
        (quarterIndex(a.target_quarter) ?? 0),
    );
  const bound = sharedQuarterRangeBound([v.current, v.next]);
  const group = useMemo(
    () => entranceGroup([v.current.qoq, v.current.yoy, v.next.qoq, v.next.yoy]),
    [v],
  );
  const [today, setToday] = useState(v.builtAt);
  const final = v.current.finalEstimate;
  useEffect(() => {
    const updateClock = () => setToday(new Date().toISOString());
    updateClock();
    if (!final) return;
    const remaining = Date.parse(final.release_at) - Date.now();
    const timer = remaining > 0 ? window.setTimeout(updateClock, remaining) : undefined;
    // A suspended mobile tab may not have run the release-time timer yet.
    document.addEventListener("visibilitychange", updateClock);
    return () => {
      window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", updateClock);
    };
  }, [final]);
  const showFinal = final && Date.parse(today) >= Date.parse(final.generated_at) &&
    Date.parse(today) < Date.parse(final.release_at);
  const current = showFinal ? v.current : { ...v.current, finalEstimate: undefined };
  const age = v.asOf
    ? (Date.parse(today) - Date.parse(v.asOf)) / 86400000
    : null;
  return (
    <main className="nowcast-monitor">
      <a className="skip" href="#readout">
        Skip to nowcasts
      </a>
      <header className="page-header">
        <h1>Australia GDP nowcast</h1>
        <p>
          This nowcast is a real-time estimate of GDP growth for the latest
          quarter, produced before the ABS publishes the official figure with a
          roughly 3-month lag after the end of the quarter. Estimates are
          updated every Monday morning, Sydney time, with a final update before
          the ABS release when the model inputs are complete.
        </p>
        <p>Last updated: {dayLabel(v.asOf, true)}</p>
      </header>
      {(v.warnings.length > 0 || (age !== null && age > 8)) && (
        <aside className="data-warning" aria-label="Data status">
          {v.warnings.map((w) => (
            <p key={w}>{w}</p>
          ))}
          {age !== null && age > 8 && (
            <p>
              The latest model run is more than eight days old (
              {dayLabel(v.asOf, true)}).
            </p>
          )}
        </aside>
      )}
      <div className="overview-grid">
        <section id="readout" aria-label="Quarterly GDP nowcasts">
          <div className="estimate-ledger" data-final={showFinal ? "true" : undefined}>
            <QuarterCard h={current} group={group} bound={bound} />
            <QuarterCard h={v.next} group={group} bound={bound} />
          </div>
        </section>
        <Evolution horizons={[current, v.next]} />
      </div>
      <section id="indicators" aria-labelledby="indicators-title">
        <div className="section-heading">
          <h2 id="indicators-title">Indicators</h2>
        </div>
        <div className="series-columns" aria-hidden="true">
          {[
            "Indicator / observation",
            "Recent history",
            "Latest",
            "Change",
            "Relative change",
            "Updated",
            "Next · est.",
            "",
          ].map((x, i) => (
            <span key={i}>{x}</span>
          ))}
        </div>
        <div id="series-list">
          {indicators.map((i) => (
            <IndicatorRow key={i.id} indicator={i} />
          ))}
          {!indicators.length && (
            <p className="empty">No indicator panel is available.</p>
          )}
        </div>
        {indicators.some((i) => i.updated_this_run) && (
          <p className="panel-foot">
            <span>
              <i className="update-dot" />
              Updated since last week
            </span>
          </p>
        )}
      </section>
      <section id="history" aria-labelledby="history-title">
        <div className="section-heading">
          <h2 id="history-title">Historical data</h2>
        </div>
        <div className="history-grid">
          <section className="gdp-history" aria-labelledby="gdp-title">
            <div className="history-heading">
              <h3 id="gdp-title">Published GDP</h3>
            </div>
            <GdpHistory view={v} />
          </section>
          <section id="weekly-history" aria-labelledby="weekly-title">
            <div className="history-heading">
              <h3 id="weekly-title">Weekly nowcasts</h3>
            </div>
            <WeeklyHistory rows={v.history} />
          </section>
          <section className="record" aria-labelledby="record-title">
            <div className="history-heading">
              <h3 id="record-title">Track record</h3>
            </div>
            {p ? (
              <>
                <dl className="accuracy">
                  <div>
                    <dt>Mean absolute error</dt>
                    <dd>
                      {finite(p.mae_pct) ? p.mae_pct.toFixed(2) : "—"}
                      <span>pp</span>
                    </dd>
                  </div>
                  <div>
                    <dt>Mean signed error</dt>
                    <dd>
                      {signed(p.bias_pct)}
                      <span>pp</span>
                    </dd>
                  </div>
                </dl>
                <div id="record-table" className="table-scroll">
                  <table>
                    <caption className="visually-hidden">
                      Published quarterly estimates scored against the ABS
                      initial estimate
                    </caption>
                    <thead>
                      <tr>
                        {[
                          "Quarter",
                          "Nowcast",
                          "ABS initial",
                          "Error · pp",
                          "Type",
                        ].map((h) => (
                          <th scope="col" key={h}>
                            {h}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {errors.map((r) => (
                        <tr key={r.target_quarter}>
                          <th scope="row">{quarterLabel(r.target_quarter)}</th>
                          <td>{percentage(r.qoq_nowcast_pct)}</td>
                          <td>{percentage(r.qoq_actual_pct)}</td>
                          <td>{signed(r.qoq_error_pp)}</td>
                          <td>
                            {r.is_live === true
                              ? "Live"
                              : r.is_live === false
                                ? "Backtest"
                                : "—"}
                            {r.adjusted_retroactively && (
                              <span
                                title="Adjusted retrospectively"
                                aria-label="Adjusted retrospectively"
                              >
                                *
                              </span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {p.rba_comparison?.n > 0 && (
                  <p className="record-note">
                    Matched RBA comparison: nowcast MAE{" "}
                    {finite(p.rba_comparison.ours_mae)
                      ? p.rba_comparison.ours_mae.toFixed(2)
                      : "—"}
                    pp; RBA{" "}
                    {finite(p.rba_comparison.rba_mae)
                      ? p.rba_comparison.rba_mae.toFixed(2)
                      : "—"}
                    pp.
                  </p>
                )}
              </>
            ) : (
              <p className="empty">
                The selected model’s track record is unavailable.
              </p>
            )}
          </section>
        </div>
      </section>
      <Methodology view={v} />
      <footer>
        <div>
          <span>
            With love from <a href="https://home.wlsn.me">James Wilson</a>
          </span>
          <a href="https://github.com/adrasyn/nowcasting/tree/main/data">
            Data archive ↗
          </a>
          <a href="/simple/">Simple HTML</a>
        </div>
      </footer>
    </main>
  );
}
