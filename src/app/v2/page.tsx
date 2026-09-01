import { loadDashboardData } from "@/lib/data";
import type { V2Model } from "@/lib/types";

// PREVIEW ONLY — a functional read-only view of the staged v2 emit so James can
// eyeball the real numbers in the browser. This is NOT the final designed UI
// (CI band shading, comparison line, and backcast
// table on the real dashboard are still to be built to the jw_pal design system).

function pct(n: number) {
  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;
}
function dollars(n: number) {
  return `$${n.toLocaleString()}m`;
}

function ModelCard({ m, accent }: { m: V2Model; accent: string }) {
  return (
    <div className="border border-border-heavy p-4">
      <div className="text-xs uppercase tracking-wide text-label">{m.model_name}</div>
      <div className={`font-headline text-4xl ${accent}`}>{pct(m.qoq_growth_pct)}</div>
      <div className="text-sm text-label">QoQ · {m.target_quarter}</div>
      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
        <dt className="text-label">Level</dt><dd>{dollars(m.gdp_chain_volume_millions)}</dd>
        <dt className="text-label">YoY</dt><dd>{pct(m.yoy_growth_pct)}</dd>
        <dt className="text-label">68% band</dt><dd>{dollars(m.ci_68_low)} – {dollars(m.ci_68_high)}</dd>
        <dt className="text-label">95% band</dt><dd>{dollars(m.ci_95_low)} – {dollars(m.ci_95_high)}</dd>
        <dt className="text-label">MAI months in qtr</dt><dd>{m.n_months_in_quarter}</dd>
        <dt className="text-label">CI basis</dt><dd>{m.ci_basis} (n={m.ci_n})</dd>
      </dl>
    </div>
  );
}

export default function V2Preview() {
  const { latestV2, backcasts } = loadDashboardData();

  if (!latestV2) {
    return (
      <main className="mx-auto max-w-3xl p-8">
        <p>No <code>data/latest_v2.json</code> found — run <code>Rscript nowcasting_v2/R/emit_v2_json.R</code> first.</p>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-3xl p-6 space-y-6">
      <div className="border-2 border-dashed border-border-heavy bg-panel p-3 text-sm">
        <strong>v2 PREVIEW</strong> — staged, read-only. This is the model output, <em>not</em> the
        final dashboard design. Live site is unchanged. Generated {latestV2.generated_at}, data
        through {latestV2.data_through}.
      </div>

      <h1 className="font-headline text-3xl">v2 nowcast — {latestV2.target_quarter}</h1>

      <div className="grid gap-4 sm:grid-cols-2">
        <ModelCard m={latestV2.models.headline} accent="text-black" />
      </div>

      {latestV2.v1_comparison && (
        <div className="border border-border-heavy p-4 text-sm">
          <div className="text-xs uppercase tracking-wide text-label">
            {latestV2.v1_comparison.model_name} — comparison ({latestV2.v1_comparison.target_quarter})
          </div>
          <span className="font-headline text-2xl">{pct(latestV2.v1_comparison.qoq_growth_pct)}</span>
          <span className="ml-3 text-label">QoQ · {dollars(latestV2.v1_comparison.gdp_chain_volume_millions)}</span>
        </div>
      )}

      <p className="text-xs text-label">
        Prev-quarter level anchor: {dollars(latestV2.prev_level.value)} ({latestV2.prev_level.source}).
        Bands are bias-aware and calibrated on a limited recent backtest — approximate.
      </p>

      {backcasts && (
        <section className="space-y-2">
          <h2 className="font-headline text-2xl">Backcast track record</h2>
          <p className="text-xs text-label">
            {backcasts.note} — {backcasts.model}. MAE {backcasts.mae_pp}pp · hit {backcasts.hit_rate_pct}% (n={backcasts.n}).
          </p>
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="border-b border-border-heavy text-left text-label">
                <th className="py-1 pr-4">Quarter</th>
                <th className="py-1 pr-4">Forecast</th>
                <th className="py-1 pr-4">Actual</th>
                <th className="py-1 pr-4">Error (pp)</th>
                <th className="py-1">Dir.</th>
              </tr>
            </thead>
            <tbody>
              {backcasts.backcasts.map((b) => (
                <tr key={b.target_quarter} className="border-b border-border">
                  <td className="py-1 pr-4">{b.target_quarter} <span className="text-label text-xs">(backtest)</span></td>
                  <td className="py-1 pr-4">{pct(b.qoq_forecast_pct)}</td>
                  <td className="py-1 pr-4">{pct(b.qoq_actual_pct)}</td>
                  <td className="py-1 pr-4">{b.error_pp >= 0 ? "+" : ""}{b.error_pp}</td>
                  <td className="py-1">{b.direction_correct ? "✓" : "✗"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </main>
  );
}
