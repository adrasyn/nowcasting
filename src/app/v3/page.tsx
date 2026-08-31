import { loadDashboardData } from "@/lib/data";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import V3TrackRecord from "@/components/V3TrackRecord";
import type { V3Horizon, V3Score } from "@/lib/types";

// PREVIEW. v3 is not the published nowcast — nowcast.wlsn.me still serves v2.
// This page exists to run v3 against live data and to design what replacing
// that would look like.

export const metadata = {
  title: "v3 preview — Australian GDP nowcast",
};

function pct(n: number, dp = 2) {
  return `${n >= 0 ? "+" : ""}${n.toFixed(dp)}%`;
}

function Banner() {
  return (
    <div className="mb-6 border-l-2 border-border-heavy bg-panel px-4 py-3">
      <p className="text-xs font-semibold uppercase tracking-wide">Preview</p>
      <p className="mt-1 text-sm text-label">
        Not the published nowcast. The homepage still serves v2. This page runs
        the NY&nbsp;Fed Staff Nowcast 2.0 port on an Australian panel so it can
        be checked against live data before anything is switched over.
      </p>
    </div>
  );
}

function Refused({ reason, detail, asOf }: {
  reason: string; detail: string; asOf: string;
}) {
  return (
    <section className="border border-border-heavy p-6">
      <p className="text-xs uppercase tracking-wide text-label">
        No nowcast published · {asOf}
      </p>
      <h1 className="mt-2 font-headline text-3xl">The model declined to publish</h1>
      <p className="mt-3 max-w-2xl text-sm">
        <span className="font-semibold">{reason}.</span> {detail}
      </p>
      <p className="mt-4 max-w-2xl text-sm text-label">
        This is the model working, not an outage. v3 refuses rather than
        publishing a figure it cannot stand behind — a feed that has stopped
        updating, or a fitted model that has left GDP disconnected from its
        monthly indicators. In either case the number it would have produced
        looks entirely plausible, which is the reason for the refusal rather
        than a warning.
      </p>
    </section>
  );
}

function Headline({ h, ciBasis }: { h: V3Horizon; ciBasis?: string }) {
  const has68 = h.ci_68_low !== undefined && h.ci_68_high !== undefined;
  return (
    <section className="border border-border-heavy p-6">
      <p className="text-xs uppercase tracking-wide text-label">
        Nowcast · {h.quarter} · quarter on quarter
      </p>
      <div className="mt-1 flex flex-wrap items-baseline gap-x-4">
        <span className="font-headline text-6xl text-teal">{pct(h.qoq_growth_pct)}</span>
        {has68 && (
          <span className="text-lg text-label">
            68% band {pct(h.ci_68_low!)} to {pct(h.ci_68_high!)}
          </span>
        )}
      </div>
      <dl className="mt-5 grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
        <div>
          <dt className="text-label">Annualised</dt>
          <dd>{pct(h.annualised_growth_pct)}</dd>
        </div>
        {h.gdp_chain_volume_millions !== undefined && (
          <div>
            <dt className="text-label">Implied level</dt>
            <dd>${h.gdp_chain_volume_millions.toLocaleString()}m</dd>
          </div>
        )}
        {h.ci_95_low !== undefined && (
          <div>
            <dt className="text-label">95% band</dt>
            <dd>{pct(h.ci_95_low)} to {pct(h.ci_95_high!)}</dd>
          </div>
        )}
      </dl>
      {ciBasis && (
        <p className="mt-4 max-w-2xl text-xs text-label">
          Bands are the model&apos;s own posterior — the same chain that produced
          the point estimate, so a harder quarter widens them. v2&apos;s bands are
          reconstructed afterwards from how wrong it has been on average, which
          cannot know that.
        </p>
      )}
    </section>
  );
}

function Scoreboard({ v3, v2, window: w }: {
  v3: V3Score; v2: V3Score; window: { n_vintages: number; n_quarters: number };
}) {
  const rows: [string, keyof V3Score, number][] = [
    ["Mean absolute error", "mae", 3],
    ["RMSE", "rmse", 3],
    ["Bias", "bias", 3],
  ];
  const better = (k: keyof V3Score) => Math.abs(v3[k]) < Math.abs(v2[k]);
  return (
    <section className="mt-10">
      <h2 className="font-headline text-2xl">Scoreboard</h2>
      <p className="mt-1 text-sm text-label">
        Percentage points of quarterly growth, over {w.n_quarters} quarters.
        Smaller is better — for bias that means closer to zero, in either
        direction.
      </p>
      <table className="mt-4 w-full text-sm tabular-nums">
        <thead>
          <tr className="border-b border-border-heavy text-left text-xs uppercase tracking-wide text-label">
            <th className="py-2">Measure</th>
            <th className="py-2 text-right">v3</th>
            <th className="py-2 text-right">v2</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([label, key, dp]) => (
            <tr key={key} className="border-b border-border">
              <td className="py-2">{label}</td>
              <td className={`py-2 text-right ${better(key) ? "font-semibold text-teal" : ""}`}>
                {v3[key].toFixed(dp)}
              </td>
              <td className="py-2 text-right">{v2[key].toFixed(dp)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-3 text-xs text-label">
        Both models see revised data and are scored against revised outcomes.
        That flatters both, comparably. v2&apos;s backtest also fixes its
        predictor selection using the full sample — a look-ahead with no
        counterpart in v3 — so if anything the gap is understated.
      </p>
    </section>
  );
}

function Calibration({ v3, v2 }: { v3: V3Score; v2: V3Score }) {
  const row = (name: string, s: V3Score) => {
    const honest = Math.abs(s.dispersion_ratio - s.calibrated_ratio) < 0.12;
    return (
      <tr key={name} className="border-b border-border">
        <td className="py-2">{name}</td>
        <td className="py-2 text-right">{(s.r_squared * 100).toFixed(1)}%</td>
        <td className="py-2 text-right">{s.calibrated_ratio.toFixed(2)}</td>
        <td className="py-2 text-right">{s.dispersion_ratio.toFixed(2)}</td>
        <td className={`py-2 text-right ${honest ? "text-teal" : "text-label"}`}>
          {honest ? "calibrated" : "over-confident"}
        </td>
      </tr>
    );
  };
  return (
    <section className="mt-10">
      <h2 className="font-headline text-2xl">Is it honest about what it knows?</h2>
      <p className="mt-1 max-w-2xl text-sm text-label">
        A forecast that is a genuine best guess should vary <em>less</em> than
        reality — by exactly the square root of how much of the variation it can
        explain. Swinging around more than that is claiming skill it does not
        have.
      </p>
      <table className="mt-4 w-full text-sm tabular-nums">
        <thead>
          <tr className="border-b border-border-heavy text-left text-xs uppercase tracking-wide text-label">
            <th className="py-2">Model</th>
            <th className="py-2 text-right">Variation explained</th>
            <th className="py-2 text-right">Should vary at</th>
            <th className="py-2 text-right">Actually varies at</th>
            <th className="py-2 text-right">Verdict</th>
          </tr>
        </thead>
        <tbody>{row("v3", v3)}{row("v2", v2)}</tbody>
      </table>
      <p className="mt-3 max-w-2xl text-xs text-label">
        v3 looks steadier than v2 and that is the point, not a shortcoming.
        Scaling its answers up to match reality&apos;s spread was tested and made
        it monotonically worse.
      </p>
    </section>
  );
}

export default function V3Preview() {
  const { latestV3: v3, backtestV3: bt } = loadDashboardData();

  if (!v3) {
    return (
      <main className="mx-auto max-w-4xl px-4 py-8 sm:px-6">
        <Banner />
        <p className="text-sm">
          No <code>data/latest_v3.json</code> yet — run{" "}
          <code>nowcasting_v3/tools/run_au_nowcast.py</code>.
        </p>
      </main>
    );
  }

  const nowcast = v3.horizons.find((h) => h.kind === "nowcast");
  const forecasts = v3.horizons.filter((h) => h.kind === "forecast");

  return (
    <main className="mx-auto max-w-4xl px-4 py-8 sm:px-6">
      <Banner />
      <Header generatedAt={v3.generated_at} />

      {v3.status === "refused" || !nowcast ? (
        <Refused
          reason={v3.refusal_reason ?? "unavailable"}
          detail={v3.refusal_detail ?? ""}
          asOf={v3.as_of}
        />
      ) : (
        <>
          <Headline h={nowcast} ciBasis={v3.ci_basis} />

          {forecasts.length > 0 && (
            <section className="mt-6 border border-border p-4">
              <p className="text-xs uppercase tracking-wide text-label">
                Also forecast, at no extra cost
              </p>
              <ul className="mt-2 space-y-1 text-sm">
                {forecasts.map((f) => (
                  <li key={f.quarter}>
                    <span className="font-semibold">{f.quarter}</span>{" "}
                    {pct(f.qoq_growth_pct)}
                    {f.ci_68_low !== undefined && (
                      <span className="text-label">
                        {" "}· 68% {pct(f.ci_68_low)} to {pct(f.ci_68_high!)}
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {v3.panel && (
            <section className="mt-6 grid grid-cols-2 gap-x-6 gap-y-2 border border-border p-4 text-sm sm:grid-cols-4">
              <div><dt className="text-label">Panel</dt><dd>{v3.panel.n_series} series</dd></div>
              <div><dt className="text-label">History from</dt><dd>{v3.panel.first_month}</dd></div>
              <div><dt className="text-label">Data through</dt><dd>{v3.data_through}</dd></div>
              <div>
                <dt className="text-label">GDP factor loading</dt>
                <dd>
                  {v3.diagnostics?.gdp_global_loading.toFixed(2)}
                  <span className="text-label">
                    {" "}(refuses below {v3.diagnostics?.collapse_floor})
                  </span>
                </dd>
              </div>
            </section>
          )}
        </>
      )}

      {bt && (
        <>
          <V3TrackRecord backtest={bt} />
          <Scoreboard v3={bt.scores.v3} v2={bt.scores.v2} window={bt.window} />
          <Calibration v3={bt.scores.v3} v2={bt.scores.v2} />
          <section className="mt-10 border-t border-border pt-4">
            <h2 className="font-headline text-lg">What this does not show</h2>
            <ul className="mt-2 max-w-2xl list-disc space-y-1 pl-5 text-xs text-label">
              {Object.values(bt.notes).map((n) => <li key={n}>{n}</li>)}
            </ul>
          </section>
        </>
      )}

      <Footer />
    </main>
  );
}
