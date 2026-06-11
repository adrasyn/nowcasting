import { loadDashboardData } from "@/lib/data";
import Header from "@/components/Header";
import Footer from "@/components/Footer";
import StalenessBanner from "@/components/StalenessBanner";
import HeadlineCard from "@/components/HeadlineCard";
import NowcastHeadline from "@/components/NowcastHeadline";
import VintageChart from "@/components/VintageChart";
import IndicatorGrid from "@/components/IndicatorGrid";
import PerformanceSection from "@/components/PerformanceSection";
import MethodologyPanel from "@/components/MethodologyPanel";

export default function Home() {
  const data = loadDashboardData();
  const v2 = data.latestV2;
  const generatedAt = v2 ? v2.generated_at : data.latest.generated_at;

  // v2 has no weekly vintage history yet (the quarter just rolled over), so the
  // evolution chart starts with a single point — this quarter's current estimate
  // — kept consistent with the headline. It fills in week by week as v2 runs.
  const v2Nowcasts = v2
    ? {
        vintages: [
          {
            run_date: v2.generated_at.slice(0, 10),
            target_quarter: v2.target_quarter,
            point: v2.models.headline.gdp_chain_volume_millions,
            qoq_growth_pct: v2.models.headline.qoq_growth_pct,
            // negative = before the release (matches the chart's x convention)
            days_until_release: Math.round(
              (new Date(v2.generated_at).getTime() -
                new Date(data.latest.next_gdp_release_date).getTime()) /
                86_400_000,
            ),
            ci_68_low: v2.models.headline.ci_68_low,
            ci_68_high: v2.models.headline.ci_68_high,
            ci_95_low: v2.models.headline.ci_95_low,
            ci_95_high: v2.models.headline.ci_95_high,
            data_through: v2.data_through,
          },
        ],
      }
    : data.nowcasts;

  return (
    <main className="max-w-5xl mx-auto px-4 sm:px-6 py-8">
      <StalenessBanner generatedAt={generatedAt} />
      <Header generatedAt={generatedAt} />
      {v2 ? (
        <NowcastHeadline
          headline={v2.models.headline}
          stress={v2.models.stress}
          prevLevel={v2.prev_level.value}
          gdp={data.gdp}
        />
      ) : (
        <HeadlineCard latest={data.latest} gdp={data.gdp} />
      )}
      <VintageChart nowcasts={v2Nowcasts} latest={data.latest} />
      <IndicatorGrid indicators={data.indicatorsV2 ?? data.indicators} />
      <PerformanceSection
        performance={data.performanceV2 ?? data.performance}
        isBacktest={!!data.performanceV2}
      />
      <MethodologyPanel />
      <Footer />
    </main>
  );
}
