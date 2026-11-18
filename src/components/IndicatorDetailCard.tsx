"use client";

import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";
import type { Indicator } from "@/lib/types";
import { formatMonth } from "@/lib/format";
import { indicatorDisplayUnit } from "@/lib/indicatorDisplay";
import { chartColors, axisTick } from "@/lib/chartTheme";

interface Props {
  indicator: Indicator;
  onClose: () => void;
}

export default function IndicatorDetailCard({ indicator, onClose }: Props) {
  return (
    <div className="border border-border-heavy p-4 mt-2 mb-4 bg-panel">
      <div className="flex items-baseline justify-between mb-2">
        <div>
          <p className="font-headline text-xl text-teal">{indicator.name}</p>
          <p className="text-[10px] text-label-light">{indicator.group} · {indicatorDisplayUnit(indicator)} · {indicator.source}</p>
          {indicator.data_note && <p className="text-xs text-label mt-1">{indicator.data_note}</p>}
          {indicator.source_url && (
            <a className="text-xs underline" href={indicator.source_url}>Official monthly source</a>
          )}
        </div>
        <button
          onClick={onClose}
          className="text-[10px] uppercase tracking-wider text-label hover:text-border-heavy"
        >
          Close
        </button>
      </div>
      <div className="h-[240px]" key={indicator.id}>
        <ResponsiveContainer>
          <LineChart data={indicator.series} margin={{ top: 5, right: 10, bottom: 5, left: 10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={chartColors.border} />
            <XAxis dataKey="date" tickFormatter={formatMonth} tick={axisTick} interval="preserveStartEnd" />
            <YAxis tick={axisTick} tickFormatter={(v) => v.toLocaleString()} domain={["auto", "auto"]} />
            <Tooltip
              labelFormatter={(l) => formatMonth(String(l))}
              formatter={(v, _name, item) => {
                if (typeof v === "number") return [v.toLocaleString(), item.payload?.provisional ? "Provisional monthly average" : ""];
                return ["", ""];
              }}
              contentStyle={{ fontSize: 11 }}
            />
            <Line type="monotone" dataKey="value" stroke={chartColors.primary} strokeWidth={1.5} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
