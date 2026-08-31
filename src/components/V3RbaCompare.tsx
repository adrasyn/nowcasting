import type { RbaComparison } from "@/lib/types";

// Two magnitudes side by side, which is a bar chart, not a stat tile.
//
// The tile this replaces read "Our miss vs RBA / 0.27 v 0.32pp / Average miss
// against actual GDP" — a label, two numbers, a separator and a qualifier in a
// box sized for one figure. A tile answers "what is this number"; this section
// answers "which of these two is smaller", and the bar lengths answer it before
// the digits are read.
//
// No colour coding of winner and loser. Six observations is not enough to call
// a race, and a green bar against a grey one would assert more than the data
// supports. The bars are the same weight; the reader compares them.

interface Props {
  rba: RbaComparison;
}

export default function V3RbaCompare({ rba }: Props) {
  if (rba.ours_mae == null || rba.rba_mae == null || rba.n === 0) return null;

  const max = Math.max(rba.ours_mae, rba.rba_mae);
  const rows: [string, number][] = [
    ["Our model", rba.ours_mae],
    ["RBA", rba.rba_mae],
  ];

  return (
    <div className="mb-4 border border-border p-4">
      <p className="mb-3 text-[10px] uppercase tracking-wider text-label">
        MAE comparison over last 3 years (year-ended)
      </p>
      <div className="space-y-2">
        {rows.map(([label, value]) => (
          <div key={label} className="flex items-center gap-3">
            <span className="w-24 shrink-0 text-xs text-label">{label}</span>
            <span
              className="h-3 bg-teal"
              style={{ width: `${(value / max) * 72}%` }}
              aria-hidden="true"
            />
            <span className="text-xs tabular-nums">{value.toFixed(2)}pp</span>
          </div>
        ))}
      </div>
    </div>
  );
}
