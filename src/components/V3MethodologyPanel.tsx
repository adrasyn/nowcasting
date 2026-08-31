"use client";

import { useState } from "react";
import type { Performance } from "@/lib/types";

// v3's methodology, and the model's track record with it.
//
// The track-record sentence lives HERE rather than beside the headline number.
// It is the honest qualifier on every figure this page shows, and a reader who
// opens Methodology is the one asking how much to trust them. Next to the big
// number it competed with the number; here it answers the question that brought
// someone to look.

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
            Fed&rsquo;s published MATLAB and pointed at an Australian panel. It
            replaces the Monthly Activity Indicator and U-MIDAS regression the
            homepage uses, which follows{" "}
            <a
              href="https://www.rba.gov.au/publications/rdp/2024/2024-04.html"
              target="_blank"
              rel="noopener noreferrer"
              className="underline hover:text-teal"
            >
              RBA Research Discussion Paper 2024-04
            </a>
            .
          </p>
          <p>
            Fourteen monthly and quarterly series load onto five latent factors
            — global, soft, nominal, labour, and a COVID factor active only
            between March 2020 and December 2021. Stochastic volatility and
            outlier states let the model absorb a shock like 2020 without
            over-reacting to every large surprise afterwards. The estimation is
            the Fed&rsquo;s unchanged; what differs is the panel, because
            Australia publishes no monthly equivalent of several US series and
            we use only freely available data.
          </p>
          <p>
            Because it is estimated Bayesianly it reports{" "}
            <strong>probability bands</strong> alongside each point estimate:
            the spread of the model&rsquo;s own posterior, not a margin derived
            from how wrong it has been before. That is why the bands respond to
            how hard a particular quarter is.
          </p>
          {performance && n > 0 && (
            <p>
              <strong>Track record.</strong> Over the last {n} backtested
              quarters this estimate has missed the eventual figure by{" "}
              {performance.mae_pct.toFixed(2)}pp on average
              {performance.bias_pct > 0.05 &&
                `, and has tended to run ${performance.bias_pct.toFixed(2)}pp high`}
              {performance.bias_pct < -0.05 &&
                `, and has tended to run ${Math.abs(performance.bias_pct).toFixed(2)}pp low`}
              . Those are backtested figures, not live ones: the model was
              re-run over past quarters using the data published at the time, so
              no number in that record was actually produced on the day.
            </p>
          )}
          <p className="text-xs text-label">
            One caveat that applies to every figure here and to the homepage
            alike: the backtest feeds the model revised ABS data and scores it
            against revised outcomes. Real-time data is messier, so both models
            look better in a backtest than they would have at the time.
          </p>
        </div>
      )}
    </section>
  );
}
