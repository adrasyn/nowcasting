"use client";

import * as React from "react";
import {
  useEffect,
  useId,
  useRef,
  useState,
  useLayoutEffect,
  useCallback,
} from "react";
import type { KeyboardEvent, ReactNode } from "react";
import type { V3Vintage } from "@/lib/types";
import {
  bandFor,
  dayLabel,
  finite,
  monthLabel,
  percentage,
  signed,
} from "@/lib/monitor";
import type { MonitorHorizon } from "@/lib/monitor";
import type { IndicatorChart } from "@/lib/monitor/indicators";
import {
  rangeFrame,
  rangeDurations,
  type EntranceGroup,
} from "@/lib/monitor/entrance";
import { startEntrance } from "./Entrance";
import { useEvolutionMotion } from "./useEvolutionMotion";
import { rangeTick } from "@/lib/monitor/rangeScale";
import { chartColors } from "@/lib/chartTheme";
import { evolutionAxis, evolutionTick } from "@/lib/monitor/evolutionAxis";
const teal = "#034159",
  green = "#0cf25d",
  line = "#e2e8f0";
export const bandText = (b: [number, number] | null) =>
  b
    ? `${signed(b[0]).replace(/^\+/, "")}–${percentage(b[1]).replace(/^\+/, "")}`
    : "—";
// Measure the SVG's CSS box: axes retain their pixel font size on phones.
function useSvgSize(
  ref: React.RefObject<SVGSVGElement | null>,
  width: number,
  height: number,
) {
  const [size, setSize] = useState({ width, height });
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const update = () => {
      const box = el.getBoundingClientRect();
      if (box.width > 0 && box.height > 0)
        setSize((old) =>
          old.width === box.width && old.height === box.height
            ? old
            : { width: box.width, height: box.height },
        );
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, [ref]);
  return size;
}
export function useChartMotion(
  ref: React.RefObject<SVGSVGElement | null>,
  key: unknown,
) {
  useEffect(() => {
    const host = ref.current;
    if (!host) return;
    const media = matchMedia("(prefers-reduced-motion: reduce)");
    if (media.matches) return;
    const animations: Animation[] = [];
    host.querySelectorAll<SVGPathElement>(".chart-line").forEach((p) => {
      // A normalized dash follows the rendered path when ResizeObserver replaces
      // the initial SVG geometry. A cached pixel length leaves a gap at the end
      // on wider charts, which disappears abruptly when the animation releases.
      const l = p.pathLength.baseVal || p.getTotalLength();
      if (l)
        animations.push(
          p.animate(
            [
              { strokeDasharray: `${l} ${l}`, strokeDashoffset: l },
              { strokeDasharray: `${l} ${l}`, strokeDashoffset: 0 },
            ],
            { duration: 1500, easing: "ease" },
          ),
        );
    });
    host.querySelectorAll<SVGRectElement>(".employment-bar").forEach((p) =>
      animations.push(
        p.animate(
          [
            { y: p.dataset.zero + "px", height: "0px" },
            {
              y: p.getAttribute("y") + "px",
              height: p.getAttribute("height") + "px",
            },
          ],
          { duration: 1500, easing: "ease" },
        ),
      ),
    );
    host
      .querySelectorAll<SVGRectElement>(".band-reveal")
      .forEach((p) =>
        animations.push(
          p.animate(
            [{ width: "0px" }, { width: p.getAttribute("width") + "px" }],
            { duration: 1500, easing: "ease" },
          ),
        ),
      );
    host.querySelectorAll(".chart-point").forEach((p) =>
      animations.push(
        p.animate([{ opacity: 0 }, { opacity: 1 }], {
          duration: 1500,
          easing: "steps(1, end)",
        }),
      ),
    );
    const cancel = () => animations.forEach((a) => a.cancel());
    media.addEventListener("change", cancel);
    return () => {
      cancel();
      media.removeEventListener("change", cancel);
    };
  }, [ref, key]);
}
function chooseKey(
  e: KeyboardEvent<SVGGElement>,
  index: number,
  count: number,
  set: (n: number) => void,
) {
  if (!["ArrowLeft", "ArrowRight", "Home", "End", "Enter", " "].includes(e.key))
    return;
  e.preventDefault();
  const n =
    e.key === "Home"
      ? 0
      : e.key === "End"
        ? count - 1
        : e.key === "ArrowLeft"
          ? Math.max(0, index - 1)
          : e.key === "ArrowRight"
            ? Math.min(count - 1, index + 1)
            : index;
  set(n);
  const elements =
    e.currentTarget.parentElement?.querySelectorAll<SVGGElement>(
      "[data-point]",
    );
  elements?.[n]?.focus();
}
function brokenPath(
  rows: { value: number | null }[],
  x: (i: number) => number,
  y: (v: number) => number,
) {
  let active = false;
  return rows
    .map((r, i) => {
      if (!finite(r.value)) {
        active = false;
        return "";
      }
      const cmd = active ? "L" : "M";
      active = true;
      return `${cmd}${x(i)},${y(r.value)}`;
    })
    .join(" ");
}
function domain(values: number[], zero = false) {
  const lo = Math.min(...values, ...(zero ? [0] : [])),
    hi = Math.max(...values, ...(zero ? [0] : [])),
    pad = Math.max((hi - lo) * 0.09, Math.abs(hi) * 0.001, 0.01);
  return [lo - pad, hi + pad];
}
export function RangeChart({
  h,
  group,
  bound,
}: {
  h: MonitorHorizon;
  group: EntranceGroup;
  bound: number;
}) {
  const ref = useRef<SVGSVGElement>(null),
    { width: w, height: H } = useSvgSize(ref, 300, 44);
  const min = -bound,
    max = bound;
  const x = useCallback(
    (v: number) => 8 + ((v - min) / (max - min)) * (w - 16),
    [min, max, w],
  );
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || !finite(h.qoq)) return;
    const media = matchMedia("(prefers-reduced-motion: reduce)");
    let raf = 0;
    const paint = (elapsed: number) => {
      const frame = rangeFrame(h, elapsed),
        marker = el.querySelector("[data-estimate-marker]");
      if (frame.marker !== null) {
        marker?.setAttribute("x1", String(x(frame.marker)));
        marker?.setAttribute("x2", String(x(frame.marker)));
      }
      for (const n of [68, 95] as const) {
        const band = n === 68 ? frame.band68 : frame.band95,
          rect = el.querySelector(`[data-band="${n}"]`);
        if (band && rect) {
          rect.setAttribute("x", String(x(band[0])));
          rect.setAttribute("width", String(x(band[1]) - x(band[0])));
        }
      }
    };
    const duration = rangeDurations(h.role).band95,
      finish = () => {
        cancelAnimationFrame(raf);
        paint(duration);
      };
    if (media.matches) {
      finish();
      return;
    }
    const start = startEntrance(group),
      tick = (now: number) => {
        const elapsed = Math.max(0, now - start);
        paint(elapsed);
        if (elapsed < duration) raf = requestAnimationFrame(tick);
      };
    tick(performance.now());
    const changed = () => {
      if (media.matches) finish();
    };
    media.addEventListener("change", changed);
    return () => {
      cancelAnimationFrame(raf);
      media.removeEventListener("change", changed);
    };
  }, [h, group, x]);
  if (!finite(h.qoq))
    return (
      <svg
        ref={ref}
        viewBox={`0 0 ${w} ${H}`}
        role="img"
        data-range-bound={bound}
        aria-label={`${h.quarter}: estimate and uncertainty not yet available`}
      />
    );
  return (
    <svg
      ref={ref}
      viewBox={`0 0 ${w} ${H}`}
      role="img"
      data-range-bound={bound}
      aria-label={`${h.quarter}: shared q/q axis ${rangeTick(min)} to ${rangeTick(max)}; quarterly growth ${percentage(h.qoq)}; 68% ${h.bandKind} band ${bandText(h.band68)}; 95% ${bandText(h.band95)}`}
    >
      {[min, 0, max].map((v) => (
        <g key={v}>
          <line
            x1={x(v)}
            x2={x(v)}
            y1="0"
            y2="24"
            stroke={v === 0 ? "#9ca3af" : line}
          />
          {(v !== 0 || (x(0) - 8 > 30 && w - 8 - x(0) > 30)) && (
            <text
              x={x(v)}
              y={H - 3}
              textAnchor={v === min ? "start" : v === max ? "end" : "middle"}
              fontSize="9"
              fill="#6b7280"
            >
              {rangeTick(v)}
            </text>
          )}
        </g>
      ))}
      {([95, 68] as const).map((n) => {
        const b = n === 95 ? h.band95 : h.band68;
        return b ? (
          <rect
            key={n}
            data-band={n}
            x={x(b[0])}
            y={n === 95 ? 8 : 5}
            width={x(b[1]) - x(b[0])}
            height={n === 95 ? 7 : 13}
            fill={green}
            opacity={n === 95 ? 0.15 : 0.4}
          />
        ) : null;
      })}
      {finite(h.qoq) && (
        <line
          data-estimate-marker
          x1={x(h.qoq)}
          x2={x(h.qoq)}
          y1="1"
          y2="23"
          stroke={teal}
          strokeWidth="2"
        />
      )}
    </svg>
  );
}
export function SeriesChart({
  data,
  name,
  mini = false,
}: {
  data: IndicatorChart;
  name: string;
  mini?: boolean;
}) {
  const rows = data.points.slice(-36),
    valid = rows
      .map((r, index) => ({ ...r, index }))
      .filter((r) => finite(r.value));
  const [chosen, setChosen] = useState(-1);
  const ref = useRef<SVGSVGElement>(null);
  useChartMotion(ref, data);
  const { width: w, height: H } = useSvgSize(
    ref,
    mini ? 80 : 500,
    mini ? 24 : 180,
  );
  const m = mini ? { l: 2, r: 2, t: 2, b: 2 } : { l: 58, r: 12, t: 12, b: 25 };
  if (!valid.length)
    return mini ? (
      <span className="visually-hidden">
        No adjacent observations available
      </span>
    ) : (
      <p className="chart-observation">
        No chart data available from adjacent valid observations.
      </p>
    );
  const values = valid.map((r) => r.value as number),
    [min, max] = domain(values, data.transformed),
    y = (v: number) => m.t + ((max - v) / (max - min)) * (H - m.t - m.b),
    spacing = (w - m.l - m.r) / Math.max(1, rows.length),
    x = (i: number) =>
      data.kind === "bars"
        ? m.l + (i + 0.5) * spacing
        : m.l + (i / Math.max(1, rows.length - 1)) * (w - m.l - m.r),
    zero = y(0),
    selected =
      valid[Math.min(chosen < 0 ? valid.length - 1 : chosen, valid.length - 1)],
    format = (v: number) =>
      data.transformed
        ? signed(v, data.kind === "bars" ? 1 : 2) +
          (data.kind === "bars" ? " thousand people" : "%")
        : v.toLocaleString("en-AU", { maximumFractionDigits: 2 });
  let ticks = [min, (min + max) / 2, max];
  if (data.transformed) ticks = [min, 0, max];
  const label = (v: number) =>
    data.transformed
      ? `${v.toFixed(data.kind === "bars" ? 0 : 1)}${data.kind === "bars" ? "" : "%"}`
      : Math.abs(v) >= 1e6
        ? (v / 1e6).toFixed(1) + "m"
        : Math.abs(v) >= 1e4
          ? (v / 1000).toFixed(1) + "k"
          : v.toFixed(1);
  const body: ReactNode =
    data.kind === "bars" ? (
      rows.map((r, i) =>
        finite(r.value) ? (
          <rect
            key={r.date}
            className="employment-bar"
            data-zero={zero}
            data-chart-date={r.date}
            data-chart-value={r.value}
            x={x(i) - spacing * 0.35}
            y={Math.min(zero, y(r.value))}
            width={Math.max(0.6, spacing * 0.7)}
            height={Math.abs(y(r.value) - zero)}
            fill={r.value < 0 ? "#065a7a" : teal}
          />
        ) : null,
      )
    ) : (
      <path
        className="chart-line"
        pathLength="1"
        d={brokenPath(rows, x, y)}
        stroke={teal}
        strokeWidth={mini ? 1.2 : 1.7}
        fill="none"
      />
    );
  return (
    <>
      <svg
        ref={ref}
        viewBox={`0 0 ${w} ${H}`}
        role={mini ? "img" : "group"}
        aria-label={`${name}: ${data.description}, ${data.unit}. Missing periods are not bridged.`}
        data-chart-type={data.kind}
        data-chart-unit={data.unit}
        data-last-date={rows.at(-1)?.date}
        data-last-value={rows.at(-1)?.value ?? ""}
      >
        {!mini &&
          ticks.map((v, j) => (
            <g key={j}>
              <line
                className={v === 0 ? "zero-guide" : ""}
                x1={m.l}
                x2={w - m.r}
                y1={y(v)}
                y2={y(v)}
                stroke={v === 0 ? "#9ca3af" : line}
              />
              <text
                x={m.l - 6}
                y={y(v) + 3}
                textAnchor="end"
                fontSize="10"
                fill="#6b7280"
              >
                {label(v)}
              </text>
            </g>
          ))}
        {body}
        {!mini &&
          valid.map((r, j) => (
            <g
              key={r.date}
              data-point
              data-chart-date={r.date}
              data-chart-value={r.value}
              role="button"
              tabIndex={selected.date === r.date ? 0 : -1}
              aria-pressed={selected.date === r.date}
              aria-label={`${monthLabel(r.date)}: ${format(r.value as number)}`}
              onClick={() => setChosen(j)}
              onFocus={() => setChosen(j)}
              onMouseEnter={() => setChosen(j)}
              onKeyDown={(e) => chooseKey(e, j, valid.length, setChosen)}
            >
              <title>{`${monthLabel(r.date)}: ${format(r.value as number)}`}</title>
              <rect
                x={x(r.index) - Math.max(6, spacing / 2)}
                y={m.t}
                width={Math.max(12, spacing)}
                height={H - m.t - m.b}
                fill="transparent"
              />
              {data.kind === "line" ? (
                <circle
                  cx={x(r.index)}
                  cy={y(r.value as number)}
                  r={selected.date === r.date ? 3 : 1.5}
                  fill={selected.date === r.date ? green : teal}
                  stroke={teal}
                />
              ) : selected.date === r.date ? (
                <rect
                  x={x(r.index) - spacing * 0.35}
                  y={Math.min(zero, y(r.value as number))}
                  width={Math.max(0.6, spacing * 0.7)}
                  height={Math.max(1, Math.abs(y(r.value as number) - zero))}
                  fill="none"
                  stroke={teal}
                  strokeWidth="2"
                />
              ) : null}
            </g>
          ))}
        {!mini && (
          <>
            <text x={m.l} y={H - 5} fontSize="10" fill="#6b7280">
              {monthLabel(rows[0].date)}
            </text>
            <text
              x={w - m.r}
              y={H - 5}
              textAnchor="end"
              fontSize="10"
              fill="#6b7280"
            >
              {monthLabel(rows.at(-1)?.date)}
            </text>
          </>
        )}
      </svg>
      {!mini && (
        <p className="chart-observation" aria-live="polite">
          {monthLabel(selected.date)} · {format(selected.value as number)}
        </p>
      )}
    </>
  );
}
// Both the plot and legend paint the same layers in the same order. The 68%
// region is green at .35 over the outer .15 region, not .35 over white.
const evolutionBandPaint = (band: 68 | 95) => ({
  fill: chartColors.accent,
  opacity: band === 95 ? 0.15 : 0.35,
});
function EvolutionLegendKey({ band }: { band?: 68 | 95 }) {
  return (
    <svg
      className={`legend-key ${band ? `band${band}-key` : "line-key"}`}
      width={band ? 9 : 14}
      height={band ? 9 : 2}
      viewBox={band ? "0 0 9 9" : "0 0 14 2"}
      aria-hidden="true"
      focusable="false"
    >
      {band ? (
        <>
          <rect width="9" height="9" {...evolutionBandPaint(95)} />
          {band === 68 && (
            <rect width="9" height="9" {...evolutionBandPaint(68)} />
          )}
        </>
      ) : (
        <line
          x1="0"
          x2="14"
          y1="1"
          y2="1"
          stroke={chartColors.primary}
          strokeWidth="2"
        />
      )}
    </svg>
  );
}
export function Evolution({ horizons }: { horizons: MonitorHorizon[] }) {
  const [target, setTarget] = useState(horizons[0]?.quarter),
    [chosen, setChosen] = useState(-1);
  const h = horizons.find((h) => h.quarter === target) ?? horizons[0];
  const rows = h?.runs ?? [],
    ref = useRef<SVGSVGElement>(null),
    id = useId().replaceAll(":", "");
  useEvolutionMotion(ref, h?.quarter, rows.length);
  const { width: w, height: H } = useSvgSize(ref, 620, 280);
  const select = (n: number) => {
    setTarget(horizons[n].quarter);
    setChosen(-1);
  };
  if (!h) return null;
  const final = h.finalEstimate ? rows.at(-1) : undefined;
  const active =
      rows[Math.min(chosen < 0 ? rows.length - 1 : chosen, rows.length - 1)],
    m = { l: 40, r: 24, t: 15, b: 28 };
  const release = h.release ? Date.parse(h.release + "T00:00:00Z") : null,
    days = (r: V3Vintage) =>
      (Date.parse(r.run_date + "T00:00:00Z") -
        (release ?? Date.parse(rows[0]?.run_date + "T00:00:00Z"))) /
      86400000,
    ds = rows.map(days),
    xmin = Math.min(-120, ...ds),
    xmax = Math.max(0, ...ds),
    xDay = (day: number) =>
      m.l + ((day - xmin) / Math.max(1, xmax - xmin)) * (w - m.l - m.r),
    x = (r: V3Vintage) => xDay(days(r)),
    finalX = final ? x(final) : 0,
    releaseX = xDay(0),
    vals = rows.flatMap((r) => [
      r.qoq_growth_pct, ...(bandFor(r, 68) ?? []), ...(bandFor(r, 95) ?? []),
    ]),
    { min, max, ticks, step } = evolutionAxis(vals, H - m.t - m.b),
    y = (v: number) => m.t + ((max - v) / (max - min)) * (H - m.t - m.b),
    p = (rs: V3Vintage[], get: (r: V3Vintage) => number) =>
      rs.map((r, j) => `${j ? "L" : "M"}${x(r)},${y(get(r))}`).join(" ");
  return (
    <section className="evolution-block" aria-labelledby="evolution-title">
      <div className="block-heading">
        <h2 id="evolution-title">Nowcast evolution</h2>
        <div
          className="target-tabs"
          role="tablist"
          aria-label="Estimate target"
        >
          {horizons
            .filter((h) => h.quarter)
            .map((a, j) => (
              <button
                key={a.quarter}
                id={`tab-${id}-${j}`}
                role="tab"
                aria-selected={h.quarter === a.quarter}
                tabIndex={h.quarter === a.quarter ? 0 : -1}
                aria-controls={`path-${id}`}
                onClick={() => select(j)}
                onKeyDown={(e) => {
                  if (
                    ["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)
                  ) {
                    e.preventDefault();
                    const n =
                      e.key === "Home"
                        ? 0
                        : e.key === "End"
                          ? horizons.length - 1
                          : (j + 1) % horizons.length;
                    select(n);
                    e.currentTarget.parentElement
                      ?.querySelectorAll("button")
                      [n]?.focus();
                  }
                }}
              >
                {a.quarter?.split(" ").reverse().join(" ")}
              </button>
            ))}
        </div>
      </div>
      <div
        id={`path-${id}`}
        role="tabpanel"
        aria-labelledby={`tab-${id}-${horizons.indexOf(h)}`}
      >
        <div className="path-readout">
          <p>
            {active
              ? `${dayLabel(active.run_date, true)} · ${percentage(active.qoq_growth_pct)}`
              : "No weekly estimates available"}
          </p>
          <span>Quarterly real GDP growth (%)</span>
        </div>
        <div id="path-chart">
          {rows.length ? (
            <svg
              ref={ref}
              viewBox={`0 0 ${w} ${H}`}
              role="group"
              aria-label={`${h.quarter} weekly GDP estimates.${final ? " Final estimate held through release day." : ""} Full weekly history is below.`}
            >
              {ticks.map((v) => (
                <g key={v} data-evolution-tick={v}>
                  <line
                    x1={m.l}
                    x2={w - m.r}
                    y1={y(v)}
                    y2={y(v)}
                    stroke={line}
                  />
                  <text
                    x={m.l - 6}
                    y={y(v) + 3}
                    textAnchor="end"
                    fontSize="11"
                    fill="#6b7280"
                  >
                    {evolutionTick(v, step)}
                  </text>
                </g>
              ))}
              {[0, 0.25, 0.5, 0.75, 1].map((t) => {
                const d = xmin + t * (xmax - xmin),
                  cx = m.l + t * (w - m.l - m.r);
                return (
                  <g key={t}>
                    <line
                      x1={cx}
                      x2={cx}
                      y1={m.t}
                      y2={H - m.b}
                      stroke={line}
                      strokeDasharray="2 4"
                    />
                    <text
                      x={cx}
                      y={H - 7}
                      fontSize="10"
                      textAnchor="middle"
                      fill="#6b7280"
                    >
                      {release
                        ? Math.round(d)
                        : dayLabel(
                            rows[
                              Math.min(
                                rows.length - 1,
                                Math.round(t * (rows.length - 1)),
                              )
                            ].run_date,
                          )}
                    </text>
                  </g>
                );
              })}
              {final && <line x1={releaseX} x2={releaseX} y1={m.t} y2={H - m.b}
                stroke="#94a3b8" strokeDasharray="3 4" />}
              <defs>
                <clipPath id={`band-${id}`}>
                  <rect className="band-reveal" width={w} height={H} />
                </clipPath>
              </defs>
              <g clipPath={`url(#band-${id})`}>
                {([95, 68] as const).map((n) => {
                  const valid = rows.filter((r) => bandFor(r, n));
                  const hold = final && bandFor(final, n);
                  const lower = hold ? ` L${releaseX},${y(hold[0])}` : "",
                    upper = hold ? ` L${releaseX},${y(hold[1])}` : "";
                  return valid.length ? (
                    <path
                      key={n}
                      className="band-fill"
                      d={`${p(valid, (r) => bandFor(r, n)![0])}${lower}${upper} ${p([...valid].reverse(), (r) => bandFor(r, n)![1]).replace(/^M/, "L")} Z`}
                      {...evolutionBandPaint(n)}
                    />
                  ) : null;
                })}
                {final && <line data-final-extension x1={finalX} x2={releaseX}
                  y1={y(final.qoq_growth_pct)} y2={y(final.qoq_growth_pct)}
                  stroke={chartColors.primary} strokeWidth="1.8" strokeDasharray="4 3" />}
              </g>
              <path
                className="chart-line"
                d={p(rows, (r) => r.qoq_growth_pct)}
                fill="none"
                stroke={chartColors.primary}
                strokeWidth="1.8"
              />
              {final && <g className="final-estimate-marker" pointerEvents="none">
                <line data-final-marker x1={finalX} x2={finalX} y1={m.t} y2={H - m.b}
                  stroke="#0a7d99" strokeDasharray="3 3" />
                <text x={finalX > m.l + 94 ? finalX - 6 : finalX + 6}
                  y={m.t + 15} textAnchor={finalX > m.l + 94 ? "end" : "start"}
                  fontSize="11" fontWeight="650" fill={chartColors.primary}
                  paintOrder="stroke" stroke="white" strokeWidth="3" strokeLinejoin="round">
                  Final estimate
                </text>
              </g>}
              {rows.map((r, j) => (
                <g
                  key={r.run_date}
                  className="chart-point"
                  data-point
                  role="button"
                  tabIndex={active === r ? 0 : -1}
                  aria-pressed={active === r}
                  aria-label={`${dayLabel(r.run_date, true)}: ${percentage(r.qoq_growth_pct)}; 68% ${bandText(bandFor(r, 68))}; 95% ${bandText(bandFor(r, 95))}`}
                  onClick={() => setChosen(j)}
                  onFocus={() => setChosen(j)}
                  onKeyDown={(e) => chooseKey(e, j, rows.length, setChosen)}
                >
                  <title>{`${dayLabel(r.run_date, true)}: ${percentage(r.qoq_growth_pct)}`}</title>
                  <circle
                    cx={x(r)}
                    cy={y(r.qoq_growth_pct)}
                    r="11"
                    fill="transparent"
                  />
                  <circle
                    cx={x(r)}
                    cy={y(r.qoq_growth_pct)}
                    r={active === r ? 4 : 2.1}
                    stroke={teal}
                    fill={active === r ? green : teal}
                  />
                </g>
              ))}
            </svg>
          ) : (
            <p className="empty">
              Awaiting published estimates for this quarter.
            </p>
          )}
        </div>
        <div className="chart-key">
          <span>
            {release
              ? "Days before ABS release"
              : "Run date · release date unavailable"}
          </span>
          <div className="legend">
            <span>
              <EvolutionLegendKey />
              Weekly estimate
            </span>
            <span>
              <EvolutionLegendKey band={68} />
              68% {h.bandKind} band
            </span>
            <span>
              <EvolutionLegendKey band={95} />
              95% {h.bandKind} band
            </span>
          </div>
        </div>
      </div>
    </section>
  );
}
