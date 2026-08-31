"use client";

import { Bar, BarChart, Cell, ResponsiveContainer } from "recharts";
import type { GdpSeries, LatestV3, Performance } from "@/lib/types";
import { chartColors } from "@/lib/chartTheme";
import { formatPct } from "@/lib/format";

// The homepage headline card, with v3's numbers.
//
// ONE DELIBERATE DIFFERENCE FROM THE v2 CARD: this one shows an interval. v2's
// card carries a note explaining why it does not — its band was the point
// estimate plus or minus a standard deviation of past errors, labelled "about a
// 2-in-3 chance", and it did not hold. v3's is a probability band: the mass of
// the model's own posterior, which the Staff Nowcast 2.0 paper names as one of
// the reasons the model was rebuilt Bayesian. Different object, so it is shown.
//
// The track-record line below the number is kept from v2's card regardless.
// An interval says what the model believes; the track record says how that has
// gone. A reader deserves both, and the second is the one that has teeth.

interface Props {
  latest: LatestV3;
  gdp: GdpSeries;
  performance?: Performance;
}

export default function V3Headline({ latest, gdp, performance }: Props) {
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

  const has68 =
    nowcast.ci_68_low !== undefined && nowcast.ci_68_high !== undefined;

  return (
    <section className="mb-8 border border-border-heavy p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <p className="text-[10px] uppercase tracking-wider text-label">
          {nowcast.quarter} — our GDP estimate
        </p>
        <p className="text-[10px] uppercase tracking-wider text-label">
          data through {latest.data_through}
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
            <span className="font-headline text-2xl text-teal-500">
              {formatPct(yoy)}
            </span>
            <span className="text-xs text-label">vs a year ago</span>
          </div>
        )}
      </div>

      {has68 && (
        <p className="mt-2 text-xs text-label">
          68% probability band {formatPct(nowcast.ci_68_low!)} to{" "}
          {formatPct(nowcast.ci_68_high!)}
          {nowcast.ci_95_low !== undefined && (
            <> · 95% {formatPct(nowcast.ci_95_low)} to {formatPct(nowcast.ci_95_high!)}</>
          )}
        </p>
      )}

      {performance && performance.errors.length > 0 && (
        <p className="mt-3 text-xs text-label">
          Over the last {performance.errors.length} quarters this estimate has
          missed the eventual figure by {performance.mae_pct.toFixed(2)}pp on
          average
          {performance.bias_pct > 0.05 &&
            `, and has tended to run ${performance.bias_pct.toFixed(2)}pp high`}
          {performance.bias_pct < -0.05 &&
            `, and has tended to run ${Math.abs(performance.bias_pct).toFixed(2)}pp low`}
          .
        </p>
      )}

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
