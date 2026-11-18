"use client";

import { useState } from "react";
import type { IndicatorData, Indicator, IndicatorGroup } from "@/lib/types";
import { formatMonth } from "@/lib/format";
import { indicatorDisplayUnit } from "@/lib/indicatorDisplay";
import IndicatorSparkline, { type SparklineMode } from "./IndicatorSparkline";
import IndicatorDetailCard from "./IndicatorDetailCard";
import IndicatorsTable from "./IndicatorsTable";

// Preferred ordering; v1's four groups first, then v2's. Any group present in
// the data but not listed here is appended in encounter order.
const GROUP_PREF: IndicatorGroup[] = [
  "Labour", "Consumer", "Business", "External",
  "Jobs & labour", "Households", "Business surveys", "Financial & credit", "Trade",
];

// Keys must match indicator IDs in data/indicators.json (source of truth:
// pipeline/seed/component_metadata.rds). Any unknown key falls through to
// "level" in the component.
// Monthly-change bars for the series whose levels are near-flat lines (credit
// aggregates + household spending); everything else falls back to "level".
const SPARKLINE_MODE: Record<string, SparklineMode> = {
  credit: "bar",
  credit_housing: "bar",
  credit_business: "bar",
  credit_card: "bar",
  household_spending: "bar",
};

interface Props {
  indicators: IndicatorData;
}

export default function IndicatorGrid({ indicators }: Props) {
  const [selected, setSelected] = useState<Indicator | null>(null);

  const present = Array.from(new Set(indicators.indicators.map((i) => i.group)));
  const ordered = [
    ...GROUP_PREF.filter((g) => present.includes(g)),
    ...present.filter((g) => !GROUP_PREF.includes(g)),
  ];
  const byGroup = ordered.map((group) => ({
    group,
    items: indicators.indicators.filter((i) => i.group === group),
  })).filter((g) => g.items.length > 0);

  const anyUpdated = indicators.indicators.some((i) => i.updated_this_run);

  return (
    <section className="mb-10">
      <div className="flex items-baseline justify-between gap-3 mb-2">
        <p className="font-headline text-3xl text-black">
          Indicators
        </p>
        {anyUpdated && (
          <span className="flex items-center gap-1.5 text-[10px] text-label">
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-teal" aria-hidden />
            updated this week
          </span>
        )}
      </div>
      {byGroup.map((g) => (
        <div key={g.group} className="mb-4">
          <p className="text-xs text-label mb-2 border-b border-border pb-1">{g.group}</p>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
            {g.items.map((ind) => (
              <button
                key={ind.id}
                onClick={() => setSelected(ind)}
                className={`relative text-left border p-2 hover:border-border-heavy ${
                  selected?.id === ind.id ? "border-border-heavy bg-panel" : "border-border"
                }`}
              >
                {ind.updated_this_run && (
                  <span
                    className="absolute top-1.5 right-1.5 w-1.5 h-1.5 rounded-full bg-teal"
                    title={
                      ind.prev_period && ind.latest_period
                        ? `Updated this week: ${formatMonth(ind.prev_period)} → ${formatMonth(ind.latest_period)}`
                        : "Updated this week"
                    }
                    aria-label="Updated this week"
                  />
                )}
                <p className="text-xs text-border-heavy pr-3">{ind.name}</p>
                <p className="text-[10px] text-label-light mb-1">{indicatorDisplayUnit(ind)}</p>
                <IndicatorSparkline
                  series={ind.series}
                  mode={SPARKLINE_MODE[ind.id] ?? "level"}
                />
              </button>
            ))}
          </div>
        </div>
      ))}
      {selected && <IndicatorDetailCard indicator={selected} onClose={() => setSelected(null)} />}
      <IndicatorsTable
        indicators={indicators.indicators}
        selectedId={selected?.id ?? null}
        onSelect={setSelected}
      />
    </section>
  );
}
