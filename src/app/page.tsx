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

  // v2 evolution chart: the qa nowcast at each Monday (emitted in latest_v2.json).
  const v2Nowcasts = v2 ? { vintages: v2.vintages } : data.nowcasts;

  return (
    <main className="max-w-5xl mx-auto px-4 sm:px-6 py-8">
      <StalenessBanner generatedAt={generatedAt} />
      <Header generatedAt={generatedAt} />
      {v2 ? (
        <NowcastHeadline
          headline={v2.models.headline}
          gdp={data.gdp}
        />
      ) : (
        <HeadlineCard latest={data.latest} gdp={data.gdp} />
      )}
      <VintageChart nowcasts={v2Nowcasts} latest={data.latest} targetQuarter={v2 ? v2.target_quarter : undefined} />
      <IndicatorGrid indicators={data.indicatorsV2 ?? data.indicators} />
      <PerformanceSection
        performance={data.performanceV2 ?? data.performance}
        isBacktest={!!data.performanceV2}
        showGap={false}
      />
      <MethodologyPanel />
      <Footer />
    </main>
  );
}
