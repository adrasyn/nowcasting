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

  return (
    <main className="max-w-5xl mx-auto px-4 sm:px-6 py-8">
      <StalenessBanner generatedAt={generatedAt} />
      <Header generatedAt={generatedAt} />
      {v2 ? (
        // v2 cutover: new headline (with estimate toggle + likely range +
        // previous-model comparison). Weekly-evolution chart is omitted until v2
        // accrues its own vintage history through live runs.
        <NowcastHeadline
          headline={v2.models.headline}
          stress={v2.models.stress}
          v1QoQ={v2.v1_comparison?.qoq_growth_pct ?? null}
          prevLevel={v2.prev_level.value}
          gdp={data.gdp}
        />
      ) : (
        <>
          <HeadlineCard latest={data.latest} gdp={data.gdp} />
          <VintageChart nowcasts={data.nowcasts} latest={data.latest} />
        </>
      )}
      <IndicatorGrid indicators={data.indicators} />
      <PerformanceSection performance={data.performance} backcasts={data.backcasts} />
      <MethodologyPanel />
      <Footer />
    </main>
  );
}
