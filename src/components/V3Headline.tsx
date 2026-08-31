"use client";

import { Bar, BarChart, Cell, ResponsiveContainer } from "recharts";
import type { GdpSeries, LatestV3 } from "@/lib/types";
import { chartColors } from "@/lib/chartTheme";
import { formatPct } from "@/lib/format";

// The homepage headline card, with v3's numbers.
//
// Deliberately just the numbers. The probability band is on the evolution
// chart, where its width can be seen changing week to week — printed here it was
// a second row of digits competing with the figure it qualifies. The track
// record moved to Methodology, which is where a reader goes to ask how much to
// trust any of this.

interface Props {
  latest: LatestV3;
  gdp: GdpSeries;
}

export default function V3Headline({ latest, gdp }: Props) {
  const nowcast = latest.horizons.find((h) => h.kind === "nowcast");
  if (!nowcast) return null;

  const bars = [
    ...gdp.series.slice(-12).map((q) => ({
      quarter: q.quarter,
      growth: q.qoq_pct,
      isNowcast: false,
    })),
    {
      quarter: nowcast.quarter,
      growth: nowcast.qoq_growth_pct,
      isNowcast: true,
    },
  ];

  // Year on year, from the implied level against the level four quarters back.
  // Computed here rather than emitted because it is arithmetic on data the page
  // already has, and emitting it would tie the figure to the last 95-minute
  // production run.
  const level = nowcast.gdp_chain_volume_millions;
  const fourBack = gdp.series.at(-4)?.value;
  const yoy =
    level && fourBack ? ((level / fourBack - 1) * 100) : undefined;

  return (
    <section className="mb-8 border border-border-heavy p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <p className="text-[10px] uppercase tracking-wider text-label">
          {nowcast.quarter} — our GDP estimate
        </p>
      </div>

      <div className="flex flex-wrap items-baseline gap-x-8 gap-y-2">
        <div className="flex items-baseline gap-x-2">
          <span className="font-headline text-5xl text-teal">
            {formatPct(nowcast.qoq_growth_pct)}
          </span>
          <span className="text-xs text-label">growth this quarter</span>
        </div>
        {yoy !== undefined && (
          <div className="flex items-baseline gap-x-2">
            <span className="font-headline text-5xl text-teal-500">
              {formatPct(yoy)}
            </span>
            <span className="text-xs text-label">vs a year ago</span>
          </div>
        )}
      </div>



      <div className="mt-4 h-20">
        <ResponsiveContainer>
          <BarChart data={bars} margin={{ top: 5, right: 5, bottom: 5, left: 5 }}>
            <Bar dataKey="growth" isAnimationActive={false}>
              {bars.map((row, i) => (
                <Cell
                  key={i}
                  fill={row.isNowcast ? chartColors.accent : chartColors.primary}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="text-[10px] text-label-light">
        Quarterly growth over the last 12 quarters (dark teal); this
        quarter&rsquo;s estimate in green.
      </p>
    </section>
  );
}
