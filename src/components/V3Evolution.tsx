"use client";

import { useState } from "react";
import type { V3Horizon, V3Vintage } from "@/lib/types";
import V3VintageChart, { type VintageChartScale } from "@/components/V3VintageChart";

// The two live targets — the quarter about to be printed and the quarter still
// running — one at a time behind a toggle.
//
// WHY A TOGGLE AND NOT SIDE BY SIDE. Two half-width panels shared one y axis, so
// the forecast's wider band (one month of data, 0.39 to 1.06) set the scale for
// both and flattened the nowcast's line to buy resolution only the forecast
// needed. Splitting the y axis instead would have made the two panels different
// pictures at a glance. One chart at a time, full width, keeps each target at
// its own vertical resolution without ever inviting a false comparison.
//
// THE X AXIS IS STILL SHARED, AND STILL DAYS UNTIL EACH TARGET'S OWN RELEASE.
// That lines the quarters up by MATURITY: -90 is the same distance from its own
// print whichever target is on screen, so toggling compares like with like
// instead of sliding the axis under the reader. A calendar axis would destroy
// that — both series are produced every Monday, so they would simply overlap.

const DAY = 86_400_000;

interface Props {
  vintages: V3Vintage[];
  horizons: V3Horizon[];
  /** The fetched date for the nowcast target. Forecast targets carry their own. */
  nowcastReleaseDate: string;
}

function daysToRelease(runDate: string, releaseDate: string): number {
  return Math.round(
    (new Date(runDate + "T00:00:00Z").getTime() -
      new Date(releaseDate + "T00:00:00Z").getTime()) / DAY);
}

export default function V3Evolution({ vintages, horizons, nowcastReleaseDate }: Props) {
  // The CURRENT quarter is the default view. It is the number about to be
  // tested against an ABS print, which is the page's claim to being worth
  // reading; the forecast is there to be chosen, not to greet the reader.
  const [showForecast, setShowForecast] = useState(false);

  const nowcast = horizons.find((h) => h.kind === "nowcast");
  const forecast = horizons.find((h) => h.kind === "forecast");

  // THE HORIZON'S OWN DATE WINS. `nowcastReleaseDate` reaches this from
  // `data/latest.json`, an artefact of the R pipeline, which runs before this
  // model's and can fail on its own; when it does it names the quarter the ABS
  // has just printed while this model has rolled forward. The runner already
  // refuses a date from the wrong month, so this is the second of two guards —
  // but the horizon's `release_date` is derived from the target quarter and
  // cannot name a different one, so it is the one to trust. The fetched date
  // remains the fallback for payloads written before that field existed.
  const curRelease = nowcast?.release_date || nowcastReleaseDate;
  const nxtRelease = forecast?.release_date;

  const cur = nowcast
    ? vintages.filter((v) => v.target_quarter === nowcast.quarter)
    : [];
  // A forecast quarter appears here only once it has a month of data in it —
  // `run_au_nowcast.py` declines to record one before that, because the model
  // conditioning on nothing returns the trend anchor and a flat line of those
  // reads as a settled view rather than the absence of one.
  const nxt =
    forecast && nxtRelease
      ? vintages.filter((v) => v.target_quarter === forecast.quarter)
      : [];

  if (!nowcast || cur.length === 0) return null;

  // One x domain across both targets, so the toggle does not move the axis.
  const xs = [
    ...(curRelease ? cur.map((v) => daysToRelease(v.run_date, curRelease)) : []),
    ...(nxtRelease ? nxt.map((v) => daysToRelease(v.run_date, nxtRelease)) : []),
  ];
  // SNAPPED TO 5 DAYS, NOT 15. Flooring to a 15-multiple and padding first put
  // the axis at -120 when the earliest vintage was -114, which read as six days
  // of missing record rather than as the edge of the chart.
  //
  // NOT HARDCODED AT -115 EITHER, THOUGH THAT IS WHERE IT LANDS TODAY. Both
  // targets happen to start at -114, but that is not a constant: the record
  // starts on the first Monday a quarter has any data, and how far that sits
  // from the release moves with where Mondays fall, when the first indicator
  // for the quarter's opening month publishes, and which Wednesday the ABS
  // picks. A fixed -115 would silently clip the first point of any quarter that
  // began a week earlier.
  const xLo = Math.min(-95, ...xs);
  const xDomain: [number, number] = [Math.floor(xLo / 5) * 5, 5];
  // Ticks run BACK from zero so they stay on 15s whatever the domain edge is,
  // rather than starting at the edge and putting labels on -115, -100, -85.
  const xTicks: number[] = [];
  for (let t = 0; t >= xDomain[0]; t -= 15) xTicks.push(t);
  xTicks.reverse();
  const scale: VintageChartScale = { xDomain, xTicks };

  const canToggle = nxt.length > 0 && !!nxtRelease && !!forecast;
  const showing = canToggle && showForecast;
  const shown = showing && forecast ? forecast : nowcast;
  const shownVintages = showing ? nxt : cur;
  const shownRelease = (showing ? nxtRelease : curRelease) ?? "";

  // The selected state IndicatorGrid already uses for its buttons, so the page
  // has one idea of what "chosen" looks like rather than two.
  const tab = (active: boolean) =>
    [
      "border px-3 py-1 text-xs transition-colors",
      active
        ? "border-border-heavy bg-panel text-black"
        : "border-border text-label hover:border-border-heavy",
    ].join(" ");

  return (
    <section className="mb-10">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <p className="font-headline text-3xl text-black">Nowcast evolution</p>
        {canToggle && forecast && (
          <div className="flex gap-2" role="group" aria-label="Choose a target quarter">
            <button type="button" onClick={() => setShowForecast(false)}
                    aria-pressed={!showForecast} className={tab(!showForecast)}>
              {nowcast.quarter}
            </button>
            <button type="button" onClick={() => setShowForecast(true)}
                    aria-pressed={showForecast} className={tab(showForecast)}>
              {forecast.quarter}
            </button>
          </div>
        )}
      </div>
      <p className="mb-4 text-xs text-label">
        Each point is a weekly point estimate for {shown.quarter}.
        {/* The band sentence belongs to the nowcast only. On the forecast the
            bands are barely legible — five points across twenty-two days — so
            naming them there described something the reader cannot yet see. */}
        {!showing && (
          <> The shaded areas are the model&rsquo;s 68% and 95% probability bands.</>
        )}
      </p>
      <V3VintageChart
        key={shown.quarter}
        vintages={shownVintages}
        targetQuarter={shown.quarter}
        releaseDate={shownRelease}
        scale={scale}
      />
    </section>
  );
}
