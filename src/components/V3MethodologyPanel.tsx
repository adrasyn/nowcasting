"use client";

import { useState } from "react";
import type { Performance } from "@/lib/types";

// Copy supplied by James, used as written. The three figures in the last
// paragraph are read from `performance_v3.json` rather than typed in, so a
// re-run of the backtest cannot leave the sentence stating numbers the table
// below it no longer shows.

interface Props {
  performance?: Performance;
}

export default function V3MethodologyPanel({ performance }: Props) {
  const [open, setOpen] = useState(false);
  const n = performance?.errors.length ?? 0;

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
          {performance && n > 0 && (
            <p>
              Over the last {n} backtested quarters this estimate has missed the
              actual GDP figure by {performance.mae_pct.toFixed(2)}pp on average
              {performance.bias_pct > 0.05 &&
                `, and has tended to run ${performance.bias_pct.toFixed(2)}pp high`}
              {performance.bias_pct < -0.05 &&
                `, and has tended to run ${Math.abs(performance.bias_pct).toFixed(2)}pp low`}
              .
            </p>
          )}
        </div>
      )}
    </section>
  );
}
