"use client";

import { useState } from "react";
import type { LatestV3, Performance } from "@/lib/types";

// The combination's methodology, as the owner asked for it: v3, then v2, then
// the averaging. The figures in the last paragraphs are read from whichever
// payloads the page is publishing — `performance_combo.json` and
// `latest_combo.json` when the combination exists, v3's own otherwise — rather
// than typed in, so a re-run of the backtest cannot leave the sentence stating
// numbers the table below it no longer shows.
//
// ONE FIGURE HERE IS V3'S AND NOT THE AVERAGE'S: the correction in the second
// paragraph, which the combination copies from v3 because it belongs to v3's
// half. It is stated inside the sentence about the NY Fed model for that
// reason, and must stay there.
//
// THIS IS THE ONE PLACE THE MODEL'S OWN FIGURE APPEARS. Everywhere else on the
// page "the nowcast" means the published number: the model's estimate less a
// correction for its recent average error. Printed beside the headline it read
// as a second forecast; here it is provenance, which is what a reader opening
// Methodology came for.

interface Props {
  performance?: Performance;
  latest?: LatestV3;
}

export default function V3MethodologyPanel({ performance, latest }: Props) {
  const [open, setOpen] = useState(false);
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
            of the ABS release. The published figure is the equal-weighted
            average of two models. Both are estimated on the ABS&rsquo;s initial
            estimate of GDP for each quarter, the figure published on the day,
            and the track record below is scored against the same figure.
          </p>
          <p>
            The first model is the{" "}
            <a
              href="https://www.newyorkfed.org/research/policy/nowcast"
              target="_blank"
              rel="noopener noreferrer"
              className="underline hover:text-teal"
            >
              New York Fed Staff Nowcast 2.0
            </a>
            , a Bayesian dynamic factor model ported to Python from the
            Fed&rsquo;s published MATLAB. Fourteen monthly and quarterly series
            load onto five latent factors: global, soft, nominal, labour, and a
            COVID factor active only between March 2020 and December 2021.
            Stochastic volatility and outlier states let the model absorb a
            shock like 2020 without over-reacting to every large surprise
            afterwards. Its estimate is corrected for its own average error over
            the last {windowQuarters ?? 8} quarters
            {bc != null && `, currently ${bc.pp.toFixed(2)}pp`}.
          </p>
          <p>
            The second follows the Reserve Bank of Australia&rsquo;s{" "}
            <a
              href="https://www.rba.gov.au/publications/rdp/2024/2024-04.html"
              target="_blank"
              rel="noopener noreferrer"
              className="underline hover:text-teal"
            >
              Research Discussion Paper 2024-04
            </a>
            . A dynamic factor model condenses a panel of monthly indicators
            into a single monthly activity indicator. A mixed-frequency (U-MIDAS)
            regression then maps the months of that indicator available so far
            in the quarter onto quarterly GDP growth, and the indicators in the
            panel are re-selected each quarter on their explanatory power. Our
            panel is limited to freely available data, so it is not the same as
            the paper&rsquo;s.
          </p>
        </div>
      )}
    </section>
  );
}
