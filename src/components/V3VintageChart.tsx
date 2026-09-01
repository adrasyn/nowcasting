"use client";

import {
  Area,
  CartesianGrid,
  ComposedChart,
  Label,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { V3Vintage } from "@/lib/types";
import { chartColors, axisTick } from "@/lib/chartTheme";
import { formatDayMonth } from "@/lib/format";

// How far right of the release line its label sits. Same value the v2 chart
// uses, so the two pages place the label identically.
const LABEL_GAP_X = 12;

// Same shape as the v2 chart — weekly nowcasts against days until the ABS
// release — with the model's probability interval drawn around the path.
//
// WHY THIS CHART CAN SHOW A BAND AND THE v2 ONE CANNOT. They are not the same
// object. v2's is the point estimate plus or minus one standard deviation of its
// own past errors — a frequentist coverage claim, labelled "about a 2-in-3
// chance", which it did not achieve; it was removed for that reason.
//
// v3's is a PROBABILITY BAND: the 68% and 95% mass of the model's posterior,
// which the Staff Nowcast 2.0 paper names as one of the reasons the model was
// rebuilt Bayesian, and which the NY Fed's own figures label exactly that. It is
// computed by `density_nowcast` — their function — on the same chain as the
// point estimate, and it NARROWS as data arrives, which an error-dispersion band
// cannot. Coverage was measured before this shipped (`tools/band_coverage.py`,
// rows in `docs/measurements/`); the page reports the band, not the audit.
// which the NY Fed Staff Nowcast 2.0 paper names as one of the reasons the model
// was rebuilt Bayesian ("our Bayesian estimation approach ... enables us to
// report probability intervals alongside each point estimate"). It is computed
// from `density_nowcast` — the NY Fed's own function — on the same chain as the
// point. It also NARROWS as data arrives, which an error-dispersion band cannot.
//
// The label matters: this is a probability interval, not a confidence interval.
interface Props {
  vintages: V3Vintage[];
  targetQuarter: string;
  releaseDate: string;
}

export default function V3VintageChart({ vintages, targetQuarter, releaseDate }: Props) {
  const release = new Date(releaseDate + "T00:00:00Z").getTime();
  const day = 86_400_000;

  const data = vintages
    .map((v) => ({
      x: Math.round((new Date(v.run_date + "T00:00:00Z").getTime() - release) / day),
      point: v.qoq_growth_pct,
      band68: [v.ci_68_low, v.ci_68_high] as [number, number],
      band95: [v.ci_95_low, v.ci_95_high] as [number, number],
      runDate: v.run_date,
      dataThrough: v.data_through,
    }))
    .sort((a, b) => a.x - b.x);

  // ONE POINT IS NOT A CHART. On the first Monday of a quarter the history holds
  // a single estimate, and Recharts draws that as an empty box: no line to join,
  // areas with nothing to span, and an axis collapsed around one value. That is
  // the homepage on the first Monday of every quarter, so it says what it has
  // instead of drawing a frame around nothing.
  if (data.length < 2) {
    const only = data[0];
    return (
      <section className="mb-10">
        <p className="font-headline text-3xl text-black">Nowcast evolution</p>
        <p className="mb-3 text-xs text-label">
          The first weekly estimate for {targetQuarter}. This chart traces how
          the nowcast moves as indicator data arrives, so it fills in over the
          quarter.
        </p>
        {only && (
          <div className="border border-border p-4 text-sm">
            <span className="font-semibold">{only.runDate}</span>
            <span className="text-label"> · data through {only.dataThrough}</span>
            <div className="mt-1">
              {only.point > 0 ? "+" : ""}
              {only.point.toFixed(2)}%
              <span className="text-label">
                {" "}· 68% probability band {only.band68[0].toFixed(2)}% to{" "}
                {only.band68[1].toFixed(2)}%
              </span>
            </div>
          </div>
        )}
      </section>
    );
  }

  const all = data.flatMap((d) => [d.band95[0], d.band95[1]]).concat(0);

  // Snapping the domain ends to a round number does nothing on its own: with
  // no `ticks`, Recharts divides the domain into five equal parts and labels
  // whatever falls there, which is where "0.65%" and "1.10%" came from. The
  // ticks have to be handed to it.
  //
  // Pick the smallest round step that leaves at most six labels, then run the
  // ticks off that step so every label is a multiple of it. 0 is a multiple of
  // every step, so the zero line always gets a label when the bands cross it.
  //
  // The count is taken from the padded, snapped domain rather than from the
  // data range: snapping outward adds up to a step at each end, so a range
  // that divides into five neat intervals can still end up with eight labels
  // once the axis is rounded off.
  const lo = Math.min(...all);
  const hi = Math.max(...all);
  const PAD = 0.05;
  const snap = (s: number) => [
    Math.floor((lo - PAD) / s) * s,
    Math.ceil((hi + PAD) / s) * s,
  ];
  const LADDER = [0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 25, 50];
  const STEP =
    LADDER.find((s) => {
      const [a, b] = snap(s);
      return Math.round((b - a) / s) + 1 <= 6;
    }) ?? LADDER[LADDER.length - 1];

  const [yMin, yMax] = snap(STEP);
  const yTicks: number[] = [];
  for (let v = yMin; v <= yMax + STEP / 1000; v += STEP) {
    yTicks.push(Number(v.toFixed(4)));
  }
  // A 0.5 step reads better as "1.5%" than "1.50%"; 0.05 and 0.25 need the
  // second decimal or half their labels round away.
  const yDp = Number.isInteger(STEP * 10) ? 1 : 2;

  return (
    <section className="mb-10">
      <p className="font-headline text-3xl text-black">Nowcast evolution</p>
      <p className="mb-2 text-xs text-label">
        Each point is a weekly point estimate for {targetQuarter}. The shaded
        areas are the model&rsquo;s 68% and 95% probability bands.
      </p>
      <div className="h-[340px]">
        <ResponsiveContainer>
          <ComposedChart data={data} margin={{ top: 20, right: 40, bottom: 20, left: 20 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={chartColors.border} />
            <XAxis
              type="number"
              dataKey="x"
              domain={[-95, 5]}
              ticks={[-90, -75, -60, -45, -30, -15, 0]}
              tick={axisTick}
              tickFormatter={(v: number) => `${v}`}
            >
              <Label value="Days until next GDP release" offset={-12} position="insideBottom"
                     style={{ fontSize: 10, fill: chartColors.label }} />
            </XAxis>
            <YAxis
              domain={[yMin, yMax]}
              ticks={yTicks}
              tick={axisTick}
              width={52}
              tickFormatter={(v: number) => `${v.toFixed(yDp)}%`}
            />
            <Tooltip
              contentStyle={{ fontSize: 12, borderColor: chartColors.border }}
              labelFormatter={(x) => `${x} days to release`}
              formatter={(value, name) => {
                if (name === "point") return [`${Number(value).toFixed(2)}%`, "Point estimate"];
                const [lo, hi] = value as unknown as [number, number];
                return [`${lo.toFixed(2)}% to ${hi.toFixed(2)}%`,
                        name === "band68" ? "68% probability band"
                                          : "95% probability band"];
              }}
            />
            {/* The theme's own green (`--color-green`, chartColors.accent), the
                same one the headline card uses for this quarter's estimate.
                `chartColors.band` is a blend of primary and accent that reads as
                a third green next to the other two. */}
            <Area dataKey="band95" stroke="none" fill={chartColors.accent} fillOpacity={0.14} />
            <Area dataKey="band68" stroke="none" fill={chartColors.accent} fillOpacity={0.32} />
            <ReferenceLine y={0} stroke={chartColors.label} strokeWidth={1} />
            <ReferenceLine x={0} stroke={chartColors.label} strokeDasharray="4 4">
              {/* Recharts derives both coordinates of a positioned label
                  from the one `offset` scalar, so no value places the text
                  clear of the line AND clear of the top of the plot: the
                  negative offset that clears the line horizontally lifts the
                  text above the plot edge. Drawing it ourselves separates
                  the two, and centres it the way the v2 chart does. A
                  vertical ReferenceLine's viewBox is the line -- `x` is the
                  line, `y` is the top of the plot area. */}
              <Label content={(props) => {
                const vb = (props as { viewBox?: { x: number; y: number; height: number } }).viewBox;
                if (!vb) return null;
                const [tx, ty] = [vb.x + LABEL_GAP_X, vb.y + vb.height / 2];
                return (
                  <text x={tx} y={ty} transform={`rotate(-90, ${tx}, ${ty})`}
                        textAnchor="middle"
                        style={{ fontSize: 10, fill: chartColors.label }}>
                    {`GDP release: ${formatDayMonth(releaseDate)}`}
                  </text>
                );
              }} />
            </ReferenceLine>
            <Line
              type="monotone"
              dataKey="point"
              stroke={chartColors.primary}
              strokeWidth={2}
              dot={{ r: 3, fill: chartColors.primary }}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}
