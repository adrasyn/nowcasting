import { loadDashboardData } from "@/lib/data";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import StalenessBanner from "@/components/StalenessBanner";
import IndicatorGrid from "@/components/IndicatorGrid";
import PerformanceSection from "@/components/PerformanceSection";
import V3RbaCompare from "@/components/V3RbaCompare";
import V3MethodologyPanel from "@/components/V3MethodologyPanel";
import V3Headline from "@/components/V3Headline";
import V3Evolution from "@/components/V3Evolution";
import V3NextQuarter from "@/components/V3NextQuarter";

// PREVIEW. v3 is not the published nowcast — nowcast.wlsn.me still serves v2.
// This page exists to run v3 against live data and to design what replacing it
// would look like.
//
// SAME STRUCTURE AS THE HOMEPAGE, ON PURPOSE. Banner, header, headline card,
// nowcast evolution, indicator panel, track record, methodology — in that order,
// rendered by the homepage's own components wherever the payload shape allows.
// The point of the page is a comparison between two models, so everything around
// the model is held constant and only the model differs.
//
// The one section with no homepage counterpart is the evolution chart, because
// it carries a probability band the v2 payload cannot support. The v3-vs-v2
// comparison and the calibration table that used to sit here were removed: they
// are analysis of the model rather than the nowcast a reader came for, and they
// live in `docs/measurements/` and the PR instead.

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

export default function V3Preview() {
  const data = loadDashboardData();
  const v3 = data.latestV3;

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
        <V3Headline latest={v3} gdp={data.gdp} />
      )}

      <V3NextQuarter latest={v3} gdp={data.gdp} />

      {v3.status === "ok" && v3.vintages && v3.vintages.length > 0 && (
        <V3Evolution
          vintages={v3.vintages}
          horizons={v3.horizons}
          nowcastReleaseDate={v3.next_gdp_release_date ?? ""}
        />
      )}

      {data.indicatorsV3 && <IndicatorGrid indicators={data.indicatorsV3} />}

      {data.performanceV3 && (
        <PerformanceSection
          performance={data.performanceV3}
          isBacktest
          sourceFile="data/backtest_v3.json"
          title="Track record"
          intro="These are backtested estimates, not live nowcasts."
          notes={
            "MAE (mean absolute error) is the average size of the miss, ignoring " +
            "direction. Bias is the average signed miss, so a positive value means " +
            "the model tends to come in a little high. For comparison, the RBA " +
            "column shows the RBA's forecast published mid-quarter (about two " +
            "months before our full-quarter estimate) for each June and December " +
            "quarter."
          }
          showGap={false}
          showRbaTile={false}
          tileBasis="quarterly growth"
          afterTiles={
            <V3RbaCompare rba={data.performanceV3.rba_comparison} />
          }
        />
      )}


      <V3MethodologyPanel performance={data.performanceV3} />
      <Footer />
    </main>
  );
}
