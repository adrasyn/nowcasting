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
        <Tile
          label="MAE"
          value={`${performance.mae_pct.toFixed(2)}pp`}
          sub={tileBasis ? `${tileBasis} · ${formatMillions(performance.mae_millions)}` : formatMillions(performance.mae_millions)}
        />
        <Tile
          label="Bias"
          value={`${performance.bias_pct > 0 ? "+" : ""}${performance.bias_pct.toFixed(2)}pp`}
          sub={`${formatMillions(performance.bias_millions)} · ${performance.bias_millions < 0 ? "underpredicts" : performance.bias_millions > 0 ? "overpredicts" : "neutral"}`}
        />
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
      <table className="w-full text-xs border-collapse">
        <thead>
          <tr className="border-b border-border-heavy text-left text-[10px] uppercase text-label">
            <th className="py-2">Quarter</th>
            {/* Header widths set the column widths in this table, so they
                are kept short. "Simulated nowcast" was also becoming untrue:
                the shaded rows below are live nowcasts, not simulations, and
                the intro paragraph already says which rows are which. */}
            <th className="py-2">Nowcast</th>
            <th className="py-2">Actual</th>
            <th className="py-2">Error (pp)</th>
            <th className="py-2">Nowcast (YoY)</th>
            <th className="py-2">RBA (YoY)</th>
            <th className="py-2">Actual (YoY)</th>
            {showGap && <th className="py-2">Gap (pp)</th>}
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
              <td className="py-2">{e.target_quarter}</td>
              <td className="py-2">
                {e.qoq_nowcast_pct == null ? formatMillions(e.final_nowcast) : formatPct(e.qoq_nowcast_pct)}
              </td>
              <td className="py-2">
                {e.qoq_actual_pct == null ? formatMillions(e.actual) : formatPct(e.qoq_actual_pct)}
              </td>
              <td className={`py-2 ${(e.qoq_error_pp ?? e.error_pct) > 0 ? "text-teal" : "text-[#c0392b]"}`}>
                {(() => {
                  const v = e.qoq_error_pp ?? e.error_pct;
                  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(2)}`;
                })()}
              </td>
              <td className="py-2 text-label">
                {e.yoy_nowcast == null ? "—" : `${e.yoy_nowcast.toFixed(2)}%`}
              </td>
              <td className="py-2 text-label">
                {e.yoy_rba == null ? "—" : `${e.yoy_rba.toFixed(2)}%`}
              </td>
              <td className="py-2 text-label">
                {e.yoy_actual == null ? "—" : `${e.yoy_actual.toFixed(2)}%`}
              </td>
              {showGap && (
                <td className={`py-2 ${e.edge_pp == null ? "text-label" : e.edge_pp < 0 ? "text-teal" : "text-[#c0392b]"}`}>
                  {e.edge_pp == null ? "—" : `${e.edge_pp > 0 ? "+" : e.edge_pp < 0 ? "−" : ""}${Math.abs(e.edge_pp).toFixed(2)}`}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
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
