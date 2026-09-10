"use client";

import { useState } from "react";
import type { LatestV3, Performance } from "@/lib/types";
import { formatPct } from "@/lib/format";

// Copy supplied by James, used as written. The figures in the last paragraphs
// are read from `performance_v3.json` and `latest_v3.json` rather than typed
// in, so a re-run of the backtest cannot leave the sentence stating numbers the
// table below it no longer shows.
//
// THIS IS THE ONE PLACE THE MODEL'S OWN FIGURE APPEARS. Everywhere else on the
// page "the nowcast" means the published number: the model's estimate less its
// own rolling miss against the first print. Printed beside the headline it read
// as a second forecast; here it is provenance, which is what a reader opening
// Methodology came for.

interface Props {
  performance?: Performance;
  latest?: LatestV3;
}

export default function V3MethodologyPanel({ performance, latest }: Props) {
  const [open, setOpen] = useState(false);
  const n = performance?.n ?? performance?.errors.length ?? 0;
  const horizon = latest?.horizons?.find((h) => h.kind === "nowcast");
  const model = horizon?.model_qoq_growth_pct;
  // The correction itself rides on `latest_v3.json`; the window it averages
  // over is also on `performance_v3.json`, which is the fallback when this
  // week's payload predates the field. Numbers are stated only from the
  // payload that carries them — a window with no correction beside it still
  // describes the method truthfully, an invented pp would not.
  const bc = latest?.bias_correction;
  const windowQuarters = bc?.window_quarters ?? performance?.bias_window_quarters;

  return (
    <section id="methodology" className="mb-10">
      <button
        onClick={() => setOpen(!open)}
        className={`flex w-full items-center justify-between border border-border-heavy px-4 py-3 text-left font-headline hover:bg-panel ${open ? "border-b-0" : ""}`}
      >
        <span className="font-headline text-3xl text-black">Methodology</span>
        <span className="font-body text-xs text-label">{open ? "Hide" : "Show"}</span>
      </button>
      {open && (
        <div className="space-y-3 border border-t-0 border-border-heavy px-4 py-4 text-sm text-border-heavy">
          <p>
            This page nowcasts Australia&rsquo;s quarterly real GDP growth ahead
            of the ABS release using the{" "}
            <a
              href="https://www.newyorkfed.org/research/policy/nowcast"
              target="_blank"
              rel="noopener noreferrer"
              className="underline hover:text-teal"
            >
              New York Fed Staff Nowcast 2.0
            </a>{" "}
            — a Bayesian dynamic factor model, ported to Python from the
            Fed&rsquo;s published MATLAB.
          </p>
          <p>
            Fourteen monthly and quarterly series load onto five latent factors:
            global, soft, nominal, labour, and a COVID factor active only
            between March 2020 and December 2021. Stochastic volatility and
            outlier states let the model absorb a shock like 2020 without
            over-reacting to every large surprise afterwards. The estimation
            matches the NY Fed&rsquo;s method; what differs is the data series
            used, because Australia publishes no monthly equivalent of several
            US series and we use only freely available data.
          </p>
          {windowQuarters != null && (
            <p>
              This is a nowcast of the figure the ABS will print first. The
              model is trained on first-print GDP rather than the later revised
              series, and the published number is the model&rsquo;s estimate
              less its own rolling miss: the average gap between its final
              nowcast and the first print over the last {windowQuarters} printed
              quarters
              {bc != null &&
                `, currently ${bc.pp.toFixed(2)}pp over ${bc.n} quarters`}
              . The correction is re-estimated each week from quarters that have
              already printed, so it uses no information from the quarter being
              nowcast.
              {model != null && (
                <>
                  {" "}The model&rsquo;s own estimate for this quarter is{" "}
                  {formatPct(model)}.
                </>
              )}
            </p>
          )}
          {performance && n > 0 && (
            <p>
              Over the last {n} quarters the published nowcast has missed the
              first print by {performance.mae_pct.toFixed(2)}pp on average
              {performance.bias_pct > 0.05 &&
                `, and has run ${performance.bias_pct.toFixed(2)}pp high`}
              {performance.bias_pct < -0.05 &&
                `, and has run ${Math.abs(performance.bias_pct).toFixed(2)}pp low`}
              .
              {performance.model_mae_vs_first_print_pct != null &&
                performance.model_bias_vs_first_print_pct != null && (
                  <>
                    {" "}Before the correction the model&rsquo;s own figure
                    missed by {performance.model_mae_vs_first_print_pct.toFixed(2)}pp
                    with a bias of {performance.model_bias_vs_first_print_pct > 0 ? "+" : ""}
                    {performance.model_bias_vs_first_print_pct.toFixed(2)}pp.
                  </>
                )}
            </p>
          )}
        </div>
      )}
    </section>
  );
}
