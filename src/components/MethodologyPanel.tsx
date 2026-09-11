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
            This dashboard nowcasts Australia&rsquo;s quarterly real GDP growth ahead of the ABS
            release using a Monthly Activity Indicator (MAI) and an unrestricted MIDAS (U-MIDAS)
            regression, following the Reserve Bank of Australia&rsquo;s approach in{" "}
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
            The main deviation from the RBA&rsquo;s methodology is the choice of input variables:
            ours are limited to data that is freely and publicly available, so the panel behind the
            indicator is not the same as the paper&rsquo;s. The estimation method follows the paper.
          </p>
          <p>
            The model is estimated on the ABS&rsquo;s initial estimate of each quarter &mdash; the
            figure published on the day, not the later-revised series &mdash; as the paper does. That
            is also the number the track record below is scored against.
          </p>
        </div>
      )}
    </section>
  );
}
