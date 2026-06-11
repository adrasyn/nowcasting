"use client";

import { useState } from "react";
import { BarChart, Bar, Cell, ResponsiveContainer } from "recharts";
import type { V2Model, GdpSeries } from "@/lib/types";
import { formatPct } from "@/lib/format";
import { chartColors } from "@/lib/chartTheme";

interface Props {
  headline: V2Model;
  stress: V2Model;
  v1QoQ: number | null;
  prevLevel: number;
  gdp: GdpSeries;
}

// 68% likely range in growth terms, derived from the published level band so it
// matches the data exactly. Returns plain {low, high} percentages.
function growthRange(m: V2Model, prev: number) {
  return {
    low: (m.ci_68_low / prev - 1) * 100,
    high: (m.ci_68_high / prev - 1) * 100,
  };
}

export default function NowcastHeadline({ headline, stress, v1QoQ, prevLevel, gdp }: Props) {
  const [mode, setMode] = useState<"main" | "volatile">("main");
  const model = mode === "main" ? headline : stress;
  const range = growthRange(model, prevLevel);

  const blurb =
    mode === "main"
      ? "Our standard estimate — most reliable in normal quarters."
      : "A more flexible estimate that reacts faster during big swings. Worth watching in volatile times.";

  const bars = [
    ...gdp.series.slice(-12).map((q) => ({ quarter: q.quarter, growth: q.qoq_pct, isNowcast: false })),
    { quarter: model.target_quarter, growth: model.qoq_growth_pct, isNowcast: true },
  ];

  return (
    <section className="mb-8 border border-border-heavy p-4">
      <div className="flex items-center justify-between flex-wrap gap-2 mb-3">
        <p className="text-[10px] uppercase tracking-wider text-label">
          {model.target_quarter} — our GDP estimate
        </p>
        {/* Estimate toggle */}
        <div className="flex border border-border-heavy text-[10px] uppercase tracking-wider">
          <button
            onClick={() => setMode("main")}
            className={`px-3 py-1 ${mode === "main" ? "bg-border-heavy text-white" : "text-label hover:bg-panel"}`}
          >
            Main
          </button>
          <button
            onClick={() => setMode("volatile")}
            className={`px-3 py-1 border-l border-border-heavy ${mode === "volatile" ? "bg-border-heavy text-white" : "text-label hover:bg-panel"}`}
          >
            Volatile-times
          </button>
        </div>
      </div>

      {/* Big number */}
      <div className="flex flex-wrap items-baseline gap-x-8 gap-y-2">
        <div className="flex items-baseline gap-x-2">
          <span className="font-headline text-5xl text-teal">{formatPct(model.qoq_growth_pct)}</span>
          <span className="text-xs text-label">growth this quarter</span>
        </div>
        <div className="flex items-baseline gap-x-2">
          <span className="font-headline text-2xl text-teal-500">{formatPct(model.yoy_growth_pct)}</span>
          <span className="text-[10px] uppercase tracking-wider text-label">vs a year ago</span>
        </div>
      </div>

      <p className="text-xs text-label mt-1">{blurb}</p>

      {/* Likely range + previous-model comparison */}
      <div className="flex flex-wrap gap-x-8 gap-y-1 mt-3 text-sm">
        <div>
          <span className="text-label">Likely range: </span>
          <span className="text-border-heavy">{formatPct(range.low)} to {formatPct(range.high)}</span>
          <span className="text-label-light text-xs"> (about a 2-in-3 chance)</span>
        </div>
        {v1QoQ !== null && (
          <div>
            <span className="text-label">Our previous model: </span>
            <span className="text-border-heavy">{formatPct(v1QoQ)}</span>
          </div>
        )}
      </div>

      {/* Last 12 quarters + this quarter's estimate */}
      <div className="mt-4 h-20">
        <ResponsiveContainer>
          <BarChart data={bars} margin={{ top: 5, right: 5, bottom: 5, left: 5 }}>
            <Bar dataKey="growth" isAnimationActive={false}>
              {bars.map((row, i) => (
                <Cell key={i} fill={row.isNowcast ? chartColors.accent : chartColors.primary} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="text-[10px] text-label-light">
        Quarterly growth over the last 12 quarters (dark teal); this quarter&rsquo;s estimate in green.
        The range reflects how far past estimates have typically landed from the final figure.
      </p>
    </section>
  );
}
