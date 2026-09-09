import type { ReactNode } from "react";
import type { Performance } from "@/lib/types";
import { formatMillions, formatPct } from "@/lib/format";

interface Props {
  performance: Performance;
  isBacktest?: boolean;
  // Where the underlying runs live. v2's backtest writes `backcasts.json`;
  // v3's writes `backtest_v3.json`. Naming the wrong file is worse than naming
  // none — it sends a reader checking the number to a file that does not
  // contain it.
  sourceFile?: string;
  // v3's page asks for shorter copy and one fewer column. Defaults keep the
  // homepage exactly as it is: this component is live on production, and
  // changing its wording is not something a v3 design pass should do quietly.
  title?: string;
  intro?: string;
  notes?: string;
  showGap?: boolean;
  // v3 renders the RBA comparison as its own paired-bar section, which a
  // one-number tile cannot hold. Default keeps v2's third tile.
  showRbaTile?: boolean;
  // Rendered between the tiles and the table, where a comparison belongs:
  // after the summary figures, before the quarter-by-quarter detail.
  afterTiles?: ReactNode;
  // Prefixed into the MAE and Bias subtitles. Both tiles report a miss in
  // pp, and so does the RBA comparison below them — but on a different
  // basis and a different number of quarters. Without each saying which,
  // 0.26 beside 0.27 reads as one of them being wrong.
  tileBasis?: string;
  // v3 scores against the ABS's first print as well as the latest vintage.
  // When true the tiles headline the first-print figures, the table gains a
  // "First print" column and the error is measured against it. Defaults off
  // because v1 and v2 payloads carry no first prints.
  firstPrint?: boolean;
}

export default function PerformanceSection({
  performance,
  isBacktest = false,
  sourceFile = "data/backcasts.json",
  title,
  intro,
  notes,
  showGap = true,
  showRbaTile = true,
  afterTiles,
  tileBasis,
  firstPrint = false,
}: Props) {
  const rba = performance.rba_comparison;
  const edge = rba.avg_edge_pp;
  const edgeValue = edge === null ? "—" : `${edge > 0 ? "+" : edge < 0 ? "−" : ""}${Math.abs(edge).toFixed(2)}pp`;
  // Only claim an edge when it's material (|gap| >= 0.1pp); a 0.05pp average over
  // 6 quarters is not significant, so call it level (Fable review B1).
  const edgeMag = edge === null ? 0 : Math.abs(edge);
  const edgeSub = performance.rba_comparison.n > 0
    ? `${performance.rba_comparison.n} year-ended comparison${performance.rba_comparison.n === 1 ? "" : "s"} (Q2/Q4) · ${edgeMag < 0.1 ? "roughly level with the RBA" : edge !== null && edge < 0 ? "we edge the RBA" : "RBA edges us"}`
    : isBacktest
    ? "Not compared for tested quarters"
    : "Year-ended forecast, updates twice yearly (Q2 & Q4)";

  return (
    <section className="mb-10">
      <p className="font-headline text-3xl text-black mb-2">
        {title ?? (isBacktest ? "Track record (simulated)" : "Track record")}
      </p>
      {isBacktest &&
        (intro !== undefined ? (
          <p className="text-xs text-label mb-3">{intro}</p>
        ) : (
          <p className="text-xs text-label mb-3">
            <strong>These are backtested estimates, not live nowcasts.</strong> The model was re-run
            over past quarters using only the data that had been published at the time, to give it a
            track record before it had accumulated one. No figure below was actually produced on the
            day. See <code>{sourceFile}</code> for the underlying runs.
          </p>
        ))}
      <div className={`grid gap-3 mb-4 ${showRbaTile ? "grid-cols-3" : "grid-cols-2"}`}>
        {firstPrint && performance.mae_first_print_pct != null ? (
          <Tile
            label="MAE"
            value={`${performance.mae_first_print_pct.toFixed(2)}pp`}
            sub={`vs the ABS first print · ${performance.mae_pct.toFixed(2)}pp vs the latest vintage`}
          />
        ) : (
          <Tile
            label="MAE"
            value={`${performance.mae_pct.toFixed(2)}pp`}
            sub={tileBasis ? `${tileBasis} · ${formatMillions(performance.mae_millions)}` : formatMillions(performance.mae_millions)}
          />
        )}
        {firstPrint && performance.bias_first_print_pct != null ? (
          <Tile
            label="Bias"
            value={`${performance.bias_first_print_pct > 0 ? "+" : ""}${performance.bias_first_print_pct.toFixed(2)}pp`}
            sub={`vs the ABS first print · ${performance.bias_pct > 0 ? "+" : ""}${performance.bias_pct.toFixed(2)}pp vs the latest vintage`}
          />
        ) : (
          <Tile
            label="Bias"
            value={`${performance.bias_pct > 0 ? "+" : ""}${performance.bias_pct.toFixed(2)}pp`}
            sub={`${formatMillions(performance.bias_millions)} · ${performance.bias_millions < 0 ? "underpredicts" : performance.bias_millions > 0 ? "overpredicts" : "neutral"}`}
          />
        )}
        {showRbaTile &&
          (rba.ours_mae != null && rba.rba_mae != null ? (
            <Tile
              label="Our miss vs RBA"
              value={`${rba.ours_mae.toFixed(2)} v ${rba.rba_mae.toFixed(2)}pp`}
              sub="Average miss against actual GDP"
            />
          ) : (
            <Tile label="Accuracy gap vs RBA" value={edgeValue} sub={edgeSub} />
          ))}
      </div>
      {afterTiles}
      {notes !== undefined ? (
        <p className="text-xs text-label mb-3">{notes}</p>
      ) : isBacktest ? (
        <p className="text-xs text-label mb-3">
          MAE (mean absolute error) is the average size of the miss, ignoring direction. Bias is the
          average signed miss, so a positive value means the model tends to come in a little high. The
          RBA column shows the RBA&rsquo;s forecast published mid-quarter (about two months before our
          full-quarter estimate) for each June and December quarter. We use more within-quarter data
          than that RBA forecast, and both are measured against later-revised GDP.
        </p>
      ) : (
        <p className="text-xs text-label mb-3">
          Each quarter the final nowcast (latest vintage before the release) is compared against the actual GDP value. MAE (mean absolute error) is the average size of the miss, ignoring direction. Bias is the average signed error, so a negative value means we systematically underpredict. The RBA gap compares our year-ended error to the RBA Statement on Monetary Policy forecast closest to quarter-end; a negative gap means our nowcast was closer to the final number.
        </p>
      )}
      {/* Seven number columns need about 560px. A phone gives this table
          roughly 326px, and a table with no room left distributes none: the
          cells carry no horizontal padding of their own, so at that width the
          first three columns ran together into "quarternowcastactual". The
          min-width keeps the columns readable and the wrapper scrolls the
          overflow, so a phone loses nothing -- the RBA comparison in the
          right-hand columns is the most interesting part of this table and
          should not be desktop-only. Only this box scrolls; the page does not.
          `pr-4` is the gap the columns never had at any width, and it is on
          every column including the last -- exempting the last one left the
          rightmost value butting against the edge of the scroll box.

          The min-width is 500px, deliberately below the width that fits every
          column, so that the last column a phone can reach is cut off
          mid-cell rather than landing just past the edge. A clipped column is
          the only thing telling a reader there is more to scroll to. Padding
          cannot do this job: the table holds its minimum width regardless, so
          freed padding is redistributed straight back into the columns --
          dropping `pr-4` to `pr-2` moved that column six pixels.

          The minimum was 440px when the table had seven number columns:
          measured at the three common iPhone widths (343/361/398px of table
          box), 440px left 12/30/58px of the sixth column showing, at the cost
          of four headers wrapping to two lines below 500px. The first-print
          column (v3) made it eight columns, and 500px keeps the same rule --
          the same clipped-column effect one column further along, and no
          header wrapping at the minimum. That 500px position is the rule
          applied, not a fresh measurement. At the width any real desktop
          gives this table the minimum does not bind. The values carry
          `whitespace-nowrap` for the same reason in reverse: at 440px "2025
          Q4" broke across two lines and the rows lost a common height.
          Headers may wrap; figures may not. */}
      <div className="overflow-x-auto">
      <table className="w-full min-w-[500px] text-xs border-collapse">
        <thead>
          <tr className="border-b border-border-heavy text-left text-[10px] uppercase text-label">
            <th className="py-2 pr-4">Quarter</th>
            {/* Header widths set the column widths in this table, so they
                are kept short. "Simulated nowcast" was also becoming untrue:
                the shaded rows below are live nowcasts, not simulations, and
                the intro paragraph already says which rows are which. */}
            <th className="py-2 pr-4">Nowcast</th>
            {firstPrint && <th className="py-2 pr-4">First print</th>}
            <th className="py-2 pr-4">{firstPrint ? "Latest" : "Actual"}</th>
            <th className="py-2 pr-4">{firstPrint ? "Error vs first (pp)" : "Error (pp)"}</th>
            <th className="py-2 pr-4">Nowcast (YoY)</th>
            <th className="py-2 pr-4">RBA (YoY)</th>
            <th className="py-2 pr-4">Actual (YoY)</th>
            {showGap && <th className="py-2 pr-4">Gap (pp)</th>}
          </tr>
        </thead>
        <tbody>
          {[...performance.errors]
            .sort((a, b) => b.target_quarter.localeCompare(a.target_quarter))
            .map((e) => (
            <tr
              key={e.target_quarter}
              className={`border-b border-border ${e.is_live ? "bg-panel" : ""}`}
              title={e.is_live
                ? `Published ${e.live_run_date} — before the ABS printed this quarter`
                : undefined}
            >
              <td className="whitespace-nowrap py-2 pr-4">{e.target_quarter}</td>
              <td className="whitespace-nowrap py-2 pr-4">
                {e.qoq_nowcast_pct == null ? formatMillions(e.final_nowcast) : formatPct(e.qoq_nowcast_pct)}
              </td>
              {firstPrint && (
                <td className="whitespace-nowrap py-2 pr-4">
                  {e.qoq_first_print_pct == null ? "—" : formatPct(e.qoq_first_print_pct)}
                </td>
              )}
              <td className="whitespace-nowrap py-2 pr-4">
                {e.qoq_actual_pct == null ? formatMillions(e.actual) : formatPct(e.qoq_actual_pct)}
              </td>
              {(() => {
                // Under an "Error vs first (pp)" header, a latest-vintage error
                // would be a different number wearing the same label. A quarter
                // with no first print recorded shows an em dash instead.
                if (firstPrint && e.qoq_error_first_print_pp == null) {
                  return <td className="whitespace-nowrap py-2 pr-4 text-label">—</td>;
                }
                const v = firstPrint
                  ? e.qoq_error_first_print_pp!
                  : (e.qoq_error_pp ?? e.error_pct);
                return (
                  <td className={`whitespace-nowrap py-2 pr-4 ${v > 0 ? "text-teal" : "text-[#c0392b]"}`}>
                    {`${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(2)}`}
                  </td>
                );
              })()}
              <td className="whitespace-nowrap py-2 pr-4 text-label">
                {e.yoy_nowcast == null ? "—" : `${e.yoy_nowcast.toFixed(2)}%`}
              </td>
              <td className="whitespace-nowrap py-2 pr-4 text-label">
                {e.yoy_rba == null ? "—" : `${e.yoy_rba.toFixed(2)}%`}
              </td>
              <td className="whitespace-nowrap py-2 pr-4 text-label">
                {e.yoy_actual == null ? "—" : `${e.yoy_actual.toFixed(2)}%`}
              </td>
              {showGap && (
                <td className={`whitespace-nowrap py-2 pr-4 ${e.edge_pp == null ? "text-label" : e.edge_pp < 0 ? "text-teal" : "text-[#c0392b]"}`}>
                  {e.edge_pp == null ? "—" : `${e.edge_pp > 0 ? "+" : e.edge_pp < 0 ? "−" : ""}${Math.abs(e.edge_pp).toFixed(2)}`}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
      </div>
      {performance.errors.some((e) => e.is_live) && (
        <p className="mt-2 flex items-center gap-2 text-[10px] text-label">
          <span
            aria-hidden="true"
            className="inline-block h-3 w-6 border border-border bg-panel"
          />
          Shaded rows are live nowcasts — published before the ABS printed that
          quarter. The rest are backtested: the model re-run over data that was
          already known.
        </p>
      )}
    </section>
  );
}

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="border border-border p-3">
      <p className="text-[10px] uppercase tracking-wider text-label">{label}</p>
      <p className="font-headline text-2xl text-teal mt-1">{value}</p>
      {sub && <p className="text-[10px] text-label-light mt-1">{sub}</p>}
    </div>
  );
}
