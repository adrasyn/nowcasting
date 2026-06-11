"use client";

import { useState } from "react";

export default function MethodologyPanel() {
  const [open, setOpen] = useState(false);

  return (
    <section id="methodology" className="mb-10">
      <button
        onClick={() => setOpen(!open)}
        className={`w-full text-left font-headline border border-border-heavy px-4 py-3 flex items-center justify-between hover:bg-panel ${open ? "border-b-0" : ""}`}
      >
        <span className="font-headline text-3xl text-black">Methodology</span>
        <span className="text-xs text-label font-body">{open ? "Hide" : "Show"}</span>
      </button>
      {open && (
        <div className="border border-t-0 border-border-heavy px-4 py-4 text-sm text-border-heavy space-y-3">
          <p>
            This dashboard nowcasts Australian real GDP growth using a Monthly Activity Indicator
            (MAI) combined with an unrestricted MIDAS regression (U-MIDAS), following the Reserve
            Bank of Australia&rsquo;s methodology (RDP 2024-04).
          </p>
          <p>
            The MAI is a single monthly activity factor distilled by a dynamic factor model from a
            broad panel of monthly series &mdash; labour, household spending, trade, credit, financial
            markets, and business- and consumer-survey indicators. The U-MIDAS step maps the
            within-quarter MAI to quarterly GDP growth using whatever months have been released so
            far (the &ldquo;ragged edge&rdquo;). The nowcast updates each week as new data arrives.
          </p>
          <p>
            You can switch between two estimates. The <strong>Main</strong> estimate is tuned for
            accuracy in normal quarters. The <strong>Volatile-times</strong> estimate is a more
            flexible version that reacts faster during big swings and large shocks &mdash; worth
            watching when conditions are choppy. Both are built from the same indicators; they differ
            only in how heavily they weight the most recent months.
          </p>
          <p>
            Confidence bands are empirical: they are derived from the model&rsquo;s own out-of-sample
            backtest errors, bias-corrected, so they widen or narrow to reflect measured accuracy.
            They are calibrated on a limited recent backtest sample and should be read as
            approximate, not exact. Reference: Reserve Bank of Australia, <em>Research Discussion
            Paper 2024-04</em>.
          </p>
        </div>
      )}
    </section>
  );
}
