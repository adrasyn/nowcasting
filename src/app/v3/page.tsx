import { loadDashboardData } from "@/lib/data";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import StalenessBanner from "@/components/StalenessBanner";
import IndicatorGrid from "@/components/IndicatorGrid";
import PerformanceSection from "@/components/PerformanceSection";
import MethodologyPanel from "@/components/MethodologyPanel";
import V3Headline from "@/components/V3Headline";
import V3VintageChart from "@/components/V3VintageChart";
import V3TrackRecord from "@/components/V3TrackRecord";
import type { V3Score } from "@/lib/types";

// PREVIEW. v3 is not the published nowcast — nowcast.wlsn.me still serves v2.
// This page exists to run v3 against live data and to design what replacing it
// would look like.
//
// SAME STRUCTURE AS THE HOMEPAGE, ON PURPOSE. Banner, header, headline card,
// nowcast evolution, indicator panel, track record, methodology. The point of
// the comparison is the model, so everything around it is held constant and the
// existing components are reused where the payload shape allows. Two sections
// are v3-only, and both earn it: the evolution chart carries a probability band
// the v2 payload cannot support, and the head-to-head against v2 has no
// counterpart on a page that only knows about one model.

export const metadata = {
  title: "v3 preview — Australian GDP nowcast",
};

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
    <section className="mb-8 border border-border-heavy p-6">
      <p className="text-[10px] uppercase tracking-wider text-label">
        No nowcast published · {asOf}
      </p>
      <h2 className="mt-2 font-headline text-3xl">
        The model declined to publish
      </h2>
      <p className="mt-3 max-w-2xl text-sm">
        <span className="font-semibold">{reason}.</span> {detail}
      </p>
      <p className="mt-4 max-w-2xl text-sm text-label">
        This is the model working, not an outage. v3 refuses rather than
        publishing a figure it cannot stand behind — a feed that has stopped
        updating, or a fitted model that has left GDP disconnected from its
        monthly indicators. In either case the number it would have produced
        looks entirely plausible, which is the reason for a refusal rather than
        a warning.
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
    <section className="mb-10">
      <p className="font-headline text-3xl text-black">
        Is it honest about what it knows?
      </p>
      <p className="mb-2 max-w-2xl text-xs text-label">
        A forecast that is a genuine best guess should vary <em>less</em> than
        reality — by the square root of how much of the variation it can
        explain. Varying more than that is claiming skill it does not have.
      </p>
      <table className="w-full text-sm tabular-nums">
        <thead>
          <tr className="border-b border-border-heavy text-left text-[10px] uppercase tracking-wider text-label">
            <th className="py-2">Model</th>
            <th className="py-2 text-right">Variation explained</th>
            <th className="py-2 text-right">Should vary at</th>
            <th className="py-2 text-right">Actually varies at</th>
            <th className="py-2 text-right">Verdict</th>
          </tr>
        </thead>
        <tbody>{row("v3", v3)}{row("v2", v2)}</tbody>
      </table>
      <p className="mt-2 max-w-2xl text-[10px] text-label-light">
        v3 looks steadier than v2 and that is the point, not a shortcoming.
        Scaling its answers up to match reality&rsquo;s spread was tested and
        made it monotonically worse.
      </p>
    </section>
  );
}

export default function V3Preview() {
  const data = loadDashboardData();
  const v3 = data.latestV3;
  const bt = data.backtestV3;

  if (!v3) {
    return (
      <main className="mx-auto max-w-5xl px-4 py-8 sm:px-6">
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
    <main className="mx-auto max-w-5xl px-4 py-8 sm:px-6">
      <Banner />
      <StalenessBanner generatedAt={v3.generated_at} />
      <Header generatedAt={v3.generated_at} />

      {v3.status === "refused" || !nowcast ? (
        <Refused
          reason={v3.refusal_reason ?? "unavailable"}
          detail={v3.refusal_detail ?? ""}
          asOf={v3.as_of}
        />
      ) : (
        <V3Headline
          latest={v3}
          gdp={data.gdp}
          performance={data.performanceV3}
        />
      )}

      {forecasts.length > 0 && (
        <section className="mb-8 border border-border p-4">
          <p className="text-[10px] uppercase tracking-wider text-label">
            Also forecast, at no extra cost
          </p>
          <ul className="mt-2 space-y-1 text-sm">
            {forecasts.map((f) => (
              <li key={f.quarter}>
                <span className="font-semibold">{f.quarter}</span>{" "}
                {f.qoq_growth_pct > 0 ? "+" : ""}
                {f.qoq_growth_pct.toFixed(2)}%
                {f.ci_68_low !== undefined && (
                  <span className="text-label">
                    {" "}· 68% band {f.ci_68_low.toFixed(2)}% to{" "}
                    {f.ci_68_high!.toFixed(2)}%
                  </span>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      {v3.status === "ok" && v3.vintages && v3.vintages.length > 0 && (
        <V3VintageChart
          vintages={v3.vintages}
          targetQuarter={v3.target_quarter ?? ""}
          releaseDate={v3.next_gdp_release_date ?? ""}
        />
      )}

      {data.indicatorsV3 && <IndicatorGrid indicators={data.indicatorsV3} />}

      {data.performanceV3 && (
        <PerformanceSection
          performance={data.performanceV3}
          isBacktest
          sourceFile="data/backtest_v3.json"
        />
      )}

      {bt && (
        <>
          <V3TrackRecord backtest={bt} />
          <Calibration v3={bt.scores.v3} v2={bt.scores.v2} />
          <section className="mb-10 border-t border-border pt-4">
            <p className="font-headline text-lg">What this does not show</p>
            <ul className="mt-2 max-w-2xl list-disc space-y-1 pl-5 text-[10px] text-label-light">
              {Object.values(bt.notes).map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          </section>
        </>
      )}

      <MethodologyPanel />
      <Footer />
    </main>
  );
}
