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

// The published nowcast. v3 replaced v2 here in September 2026, on the strength
// of a 14-quarter backtest (MAE 0.242pp against v2's 0.340) and a calibration
// check v2 fails. v2 is still built, still updated weekly, and still reachable
// at /v2 — the comparison only stays honest while both keep running.
//
// AND SINCE THE COMBINATION LANDED, THE FIGURE IS THE AVERAGE OF THE TWO. The
// two models miss in different quarters, so the equal-weight average beats both
// of them. `data/latest_combo.json` is written in v3's schema on purpose: every
// component below renders it without knowing, so the page is the same page and
// only the payload behind it changed.
//
// THE FALLBACK IS NOT DECORATION. The combination needs v2's payload as well as
// v3's, and v2 runs in a different workflow on a different runner; a checkout
// from before the emitter existed has no combination file at all. In either
// case the page serves v3 alone, exactly as it did before this change, rather
// than serving nothing.
//
// SAME STRUCTURE AS /v2, ON PURPOSE. Banner, header, headline card, nowcast
// evolution, indicator panel, track record, methodology — in that order, and
// rendered by the same components wherever the payload shape allows. The site
// exists to compare two models, so everything around the model is held constant
// and only the model differs.
//
// The one section with no v2 counterpart is the evolution chart, because it
// carries a probability band the v2 payload cannot support. The v3-vs-v2
// comparison and the calibration table that used to sit here were removed: they
// are analysis of the model rather than the nowcast a reader came for, and they
// live in `docs/measurements/` and the PR instead.

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

export default function Home() {
  const data = loadDashboardData();
  const v3 = data.latestCombo ?? data.latestV3;
  const performance = data.performanceCombo ?? data.performanceV3;

  if (!v3) {
    return (
      <main className="mx-auto max-w-5xl px-4 py-8 sm:px-6">
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

      {performance && (
        <PerformanceSection
          performance={performance}
          isBacktest
          // Where the runs behind the table live. `intro=""` below means this
          // page does not currently print it, but it must still name the file
          // the figures came from rather than the one they used to.
          sourceFile={
            data.performanceCombo
              ? "data/nowcast_history_combo.json"
              : "data/backtest_v3.json"
          }
          title="Track record"
          intro=""
          actualLabel="Actual"
          notes={
            "Actual is the ABS's initial estimate of quarterly GDP growth, the " +
            "figure the nowcast is built to match. The nowcast is the model's " +
            "estimate less its average error over recent quarters. MAE (mean " +
            "absolute error) is the average size of the miss, ignoring " +
            "direction. Bias is the average signed miss, so a positive value " +
            "means the nowcast tends to come in high. For comparison, the RBA " +
            "column shows the RBA's forecast published mid-quarter (about two " +
            "months before our full-quarter estimate) for each June and " +
            "December quarter."
          }
          showGap={false}
          showRbaTile={false}
          tileBasis="quarterly growth"
          maeTile={
            <V3RbaCompare rba={performance.rba_comparison} />
          }
        />
      )}


      <V3MethodologyPanel performance={performance} latest={v3} />
      <Footer />
    </main>
  );
}
