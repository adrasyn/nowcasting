import type { Performance, BackcastData } from "@/lib/types";
import { formatMillions, formatPct } from "@/lib/format";

interface Props {
  performance: Performance;
  backcasts?: BackcastData;
}

export default function PerformanceSection({ performance, backcasts }: Props) {
  // v2 cutover: show the new model's pre-launch test record (it has no live
  // track record yet). Clearly flagged as tested, not live.
  if (backcasts && backcasts.backcasts.length > 0) {
    return (
      <section className="mb-10">
        <p className="font-headline text-3xl text-black mb-2">Track record</p>
        <div className="grid grid-cols-3 gap-3 mb-4">
          <Tile label="Typical miss" value={`${backcasts.mae_pp.toFixed(2)}pp`} sub="vs the final figure" />
          <Tile label="Right direction" value={`${backcasts.hit_rate_pct.toFixed(0)}%`} sub="of quarters (up vs down)" />
          <Tile label="Quarters tested" value={`${backcasts.n}`} sub="before launch" />
        </div>
        <p className="text-xs text-label mb-3">
          How the new model would have performed if it had been running over the last few years.
          These are <strong>tested estimates</strong> — run on past quarters before the model went
          live, not real-time predictions — shown so the model has a track record from day one.
        </p>
        <table className="w-full text-xs border-collapse">
          <thead>
            <tr className="border-b border-border-heavy text-left text-[10px] uppercase text-label">
              <th className="py-2">Quarter</th>
              <th className="py-2">Our estimate</th>
              <th className="py-2">Actual</th>
              <th className="py-2">Miss</th>
              <th className="py-2">Direction</th>
            </tr>
          </thead>
          <tbody>
            {backcasts.backcasts.slice().reverse().map((b) => (
              <tr key={b.target_quarter} className="border-b border-border">
                <td className="py-2">
                  {b.target_quarter} <span className="text-label-light">(tested)</span>
                </td>
                <td className="py-2">{formatPct(b.qoq_forecast_pct)}</td>
                <td className="py-2">{formatPct(b.qoq_actual_pct)}</td>
                <td className="py-2 text-label">
                  {Math.abs(b.error_pp).toFixed(2)}pp
                </td>
                <td className={`py-2 ${b.direction_correct ? "text-teal" : "text-[#c0392b]"}`}>
                  {b.direction_correct ? "✓ right" : "✗ wrong"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    );
  }

  const edge = performance.rba_comparison.avg_edge_pp;
  const edgeValue = edge === null ? "—" : `${edge > 0 ? "+" : edge < 0 ? "−" : ""}${Math.abs(edge).toFixed(2)}pp`;
  const edgeSub = performance.rba_comparison.n === 0
    ? "Year-ended forecast, updates twice yearly (Q2 & Q4)"
    : `${performance.rba_comparison.n} comparison${performance.rba_comparison.n === 1 ? "" : "s"} · ${edge !== null && edge < 0 ? "we beat RBA" : "RBA beats us"}`;

  return (
    <section className="mb-10">
      <p className="font-headline text-3xl text-black mb-2">
        Track record
      </p>
      <div className="grid grid-cols-3 gap-3 mb-4">
        <Tile label="MAE" value={formatMillions(performance.mae_millions)} sub={`${performance.mae_pct.toFixed(2)}% of GDP`} />
        <Tile
          label="Bias"
          value={formatMillions(performance.bias_millions)}
          sub={`${formatPct(performance.bias_pct)} · ${performance.bias_millions < 0 ? "underpredicts" : performance.bias_millions > 0 ? "overpredicts" : "neutral"}`}
        />
        <Tile
          label="Accuracy gap vs RBA"
          value={edgeValue}
          sub={edgeSub}
        />
      </div>
      <p className="text-xs text-label mb-3">
        Each quarter, the final nowcast (latest vintage before the release) is compared against the actual GDP value. Bias is the average signed error, so a negative value means we systematically underpredict. Accuracy gap vs RBA compares our year-ended error to the RBA Statement on Monetary Policy forecast closest to quarter-end; a negative gap means our nowcast was closer to the final number.
      </p>
      <table className="w-full text-xs border-collapse">
        <thead>
          <tr className="border-b border-border-heavy text-left text-[10px] uppercase text-label">
            <th className="py-2">Quarter</th>
            <th className="py-2">Final nowcast</th>
            <th className="py-2">Actual</th>
            <th className="py-2">Error ($M)</th>
            <th className="py-2">Error (%)</th>
            <th className="py-2">RBA (YE)</th>
            <th className="py-2">Gap (pp)</th>
          </tr>
        </thead>
        <tbody>
          {performance.errors.map((e) => (
            <tr key={e.target_quarter} className="border-b border-border">
              <td className="py-2">{e.target_quarter}</td>
              <td className="py-2">{formatMillions(e.final_nowcast)}</td>
              <td className="py-2">{formatMillions(e.actual)}</td>
              <td className={`py-2 ${e.error_millions > 0 ? "text-teal" : "text-[#c0392b]"}`}>
                {e.error_millions > 0 ? "+" : ""}{e.error_millions.toLocaleString()}
              </td>
              <td className={`py-2 ${e.error_pct > 0 ? "text-teal" : "text-[#c0392b]"}`}>
                {formatPct(e.error_pct)}
              </td>
              <td className="py-2 text-label">
                {e.yoy_rba === null ? "—" : `${e.yoy_rba.toFixed(2)}%`}
              </td>
              <td className={`py-2 ${e.edge_pp === null ? "text-label" : e.edge_pp < 0 ? "text-teal" : "text-[#c0392b]"}`}>
                {e.edge_pp === null ? "—" : `${e.edge_pp > 0 ? "+" : e.edge_pp < 0 ? "−" : ""}${Math.abs(e.edge_pp).toFixed(2)}`}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
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
