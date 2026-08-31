"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { V3Backtest } from "@/lib/types";
import { chartColors, axisTick } from "@/lib/chartTheme";

// Grouped bars rather than lines: these are fourteen discrete quarters, not a
// continuous series, and a line between them would imply a path through values
// nobody nowcast.
export default function V3TrackRecord({ backtest }: { backtest: V3Backtest }) {
  const data = backtest.by_quarter.map((q) => ({
    quarter: q.target.replace(" ", " "),
    Actual: q.actual,
    v3: q.v3,
    v2: q.v2,
  }));

  return (
    <section className="mt-10">
      <h2 className="font-headline text-2xl">Track record</h2>
      <p className="mt-1 text-sm text-label">
        Every quarter both models were scored on, against what the ABS
        published. {backtest.window.n_vintages} model runs across{" "}
        {backtest.window.n_quarters} quarters.
      </p>
      <div className="mt-4 h-72 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 8, right: 8, left: -18, bottom: 4 }}>
            <CartesianGrid stroke={chartColors.border} vertical={false} />
            <XAxis dataKey="quarter" tick={axisTick} interval={0} angle={-40}
                   textAnchor="end" height={54} />
            <YAxis tick={axisTick} width={44}
                   tickFormatter={(v: number) => `${v.toFixed(1)}%`} />
            <Tooltip
              formatter={(v, n) => [`${Number(v).toFixed(2)}%`, String(n)]}
              contentStyle={{ fontSize: 12, borderColor: chartColors.border }}
            />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Bar dataKey="Actual" fill={chartColors.textHeavy} />
            <Bar dataKey="v3" fill={chartColors.primary} />
            <Bar dataKey="v2" fill={chartColors.labelLight} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}
