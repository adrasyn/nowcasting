import type { GdpSeries, LatestV3 } from "@/lib/types";
import { firstDataMonth, formatPct, formatQuarterLabel } from "@/lib/format";

// The quarter AFTER the one being nowcast.
//
// WHY THIS EXISTS. The ABS prints a quarter about nine weeks after it ends, so
// for roughly two months in every three the page's headline was a quarter that
// had already closed — nothing new could be learned about it, while the quarter
// actually underway was invisible. This strip is that quarter.
//
// IT IS DELIBERATELY NOT A SECOND HEADLINE. The nowcast is the number about to
// be tested against an ABS print, and that test is the page's whole claim to
// being worth reading. This one is a forecast of a quarter still in progress, so
// every figure in the box wears the same muted grey: it is here to be found, not
// to compete with the headline for the eye.
//
// THE ZERO-MONTH GUARD IS THE POINT OF THE COMPONENT. In the first weeks after a
// print the next quarter has not started, so the model has no observation in it
// and its "forecast" is the unconditional trend anchor and nothing else. That
// anchor was measured on 2026-09-01 at +0.658%/qtr against realised 2023–26
// growth of +0.409% — 2.9 standard errors high (docs/2026-09-01-upside-bias-
// report.md, §4.2a). Publishing it as a figure would put a known defect on the
// page dressed as a forecast.
//
// SO IT SHOWS THE QUARTER, NOT THE NUMBER. The guard first rendered nothing at
// all, which was correct about the figure and wrong about the page: a quarter
// prints about nine weeks after it ends, so the next one has no data for two
// months in every three, and for those two months the box simply vanished. A
// reader could not tell a feature that was waiting from one that was broken.
// Naming the quarter and saying when its first data arrives costs nothing and
// publishes no number.

/** "2026 Q3" -> "Q3", for a note that already names the quarter above it. */
function shortQuarter(quarter: string): string {
  return quarter.split(" ")[1] ?? quarter;
}

interface Props {
  latest: LatestV3;
  gdp: GdpSeries;
}

export default function V3NextQuarter({ latest, gdp }: Props) {
  const nowcast = latest.horizons.find((h) => h.kind === "nowcast");
  const forecast = latest.horizons.find((h) => h.kind === "forecast");
  if (!forecast) return null;

  const months = forecast.months_with_data;
  const label = formatQuarterLabel(forecast.quarter);

  // `undefined` means an older payload that predates the field — treat it as
  // having data, since the alternative is hiding a figure the model produced.
  if (months === 0) {
    const due = firstDataMonth(forecast.quarter);
    return (
      <section className="mb-8 border border-border p-4 text-label">
        <p className="text-[10px] uppercase tracking-wider">
          {label}: GDP nowcast
        </p>
        <p className="mt-2 text-sm">
          No data yet.{" "}
          {due
            ? `The first indicators covering ${forecast.quarter} arrive in early ${due}.`
            : `Waiting on the quarter's first indicators.`}
        </p>
      </section>
    );
  }

  // YEAR ON YEAR CHAINS TWO ESTIMATES, AND THAT IS WORTH KNOWING.
  // The headline card's year-ended figure runs the nowcast off the last
  // PUBLISHED level. This one has to run the forecast off the nowcast, which is
  // itself unpublished — two model quarters compounded onto one actual. It is
  // the only way to state a year-ended rate for a quarter two prints away, and
  // it is the reason `nowcast_payload` emits a level for the nowcast alone: the
  // arithmetic belongs where it can be labelled, not in the artefact.
  const levelNowcast = nowcast?.gdp_chain_volume_millions;
  const levelForecast =
    levelNowcast !== undefined
      ? levelNowcast * (1 + forecast.qoq_growth_pct / 100)
      : undefined;
  // Four quarters back from the forecast: the series ends at the last published
  // quarter, the nowcast is one past it and the forecast two, so the base sits
  // three from the end.
  const fourBack = gdp.series.at(-3)?.value;
  const yoy =
    levelForecast && fourBack ? (levelForecast / fourBack - 1) * 100 : undefined;

  return (
    <section className="mb-8 border border-border p-4 text-label">
      <p className="text-[10px] uppercase tracking-wider">{label}: GDP nowcast</p>

      <div className="mt-2 flex flex-wrap items-baseline gap-x-8 gap-y-2">
        <span className="flex items-baseline gap-x-2">
          <span className="font-headline text-3xl">
            {formatPct(forecast.qoq_growth_pct)}
          </span>
          <span className="text-xs">growth this quarter</span>
        </span>
        {yoy !== undefined && (
          <span className="flex items-baseline gap-x-2">
            <span className="font-headline text-3xl">{formatPct(yoy)}</span>
            <span className="text-xs">vs a year ago</span>
          </span>
        )}
      </div>

      <p className="mt-2 text-xs">
        {months !== undefined && <>{months} of 3 months of data</>}
        {months !== undefined && yoy !== undefined && <> · </>}
        {/* The year-ended figure is the one that really chains: it runs this
            forecast off the nowcast's LEVEL, which the ABS has not published,
            so it carries both estimates' error. Only shown when there is a
            year-ended figure to qualify. */}
        {yoy !== undefined && (
          <>
            {shortQuarter(forecast.quarter)} values calculated using{" "}
            {nowcast ? shortQuarter(nowcast.quarter) : "the current quarter's"}{" "}
            nowcast
          </>
        )}
      </p>
    </section>
  );
}
