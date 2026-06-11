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
            This dashboard estimates Australia&rsquo;s quarterly GDP growth before the ABS publishes
            the official figure. It uses a Monthly Activity Indicator (MAI) and a MIDAS regression,
            the approach the Reserve Bank of Australia set out in{" "}
            <a
              href="https://www.rba.gov.au/publications/rdp/2024/2024-04.html"
              target="_blank"
              rel="noopener noreferrer"
              className="underline hover:text-teal"
            >
              Research Discussion Paper 2024-04
            </a>
            .
          </p>
          <p>
            The MAI is a single monthly gauge of economic activity. A dynamic factor model builds it
            by pulling the common signal out of about 30 monthly series: jobs, household spending,
            trade, credit, financial markets, and business and consumer surveys. The MIDAS step links
            the months of the MAI we already have to quarterly GDP growth, even when the latest month
            for some series has not been published yet. The estimate updates every week as new data
            comes in.
          </p>
          <p>
            There are two estimates you can switch between. The <strong>Main</strong> estimate is
            built for accuracy in normal quarters. The <strong>Volatile-times</strong> estimate
            reacts faster to large swings, so it tends to do better around shocks. Both use the same
            data; they differ in how much weight they put on the most recent months.
          </p>
          <p>
            The likely range comes from the model&rsquo;s own track record. We look at how far past
            estimates landed from the final GDP figure, then use that spread to size the range and
            adjust for any tendency to run high or low. It is based on a limited run of recent
            quarters, so treat it as a guide rather than a precise interval.
          </p>
        </div>
      )}
    </section>
  );
}
