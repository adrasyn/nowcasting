# Shared quarter-card uncertainty scale

The two quarter cards use one symmetric q/q percentage axis. Its default is
−1% to +1%, with visible end ticks and zero. If either displayed point, 68% band
or 95% band exceeds that range, both cards widen together to the next clean
symmetric bound (1, 1.5, 2, 2.5, 3, 4, 5, 7.5, 10 times a power of ten).
Withheld/no-data quarters do not contribute their unpublished source numbers.
No plotted estimate or interval is clipped, and zero stays at the same centre.

Only the card projection and tick labels change. Source estimates, interval
bounds, colours and all entry durations/cadence remain identical. Markers still
start at zero, bands still grow from the moving markers, and final/reduced-motion
and no-JavaScript data remain exact. The evolution scale and its separately
corrected visibility/paint lifecycle are unchanged.

Pure cases verify normal, widened, non-finite, missing-quarter and zero data.
Rendered fixtures cover normal/widened/missing-quarter pairs and check all
animation frames stay inside the shared bound. Browser cases at 375, 390 and
1440 pixels check common axes, explicit percentage ticks, 9px labels, final
point/band coordinates, no overflow and the existing animation/reduced-motion
endpoints. The missing quarter keeps its unavailable figure and no synthetic
marker. The full repository/mobile-WebKit suites run after integration.

This change is kept separate from the evolution first-visible-frame fix and
rebased onto its latest main before publication. Revert this PR through the
ordinary Pages path to undo only the shared card scale; no data rollback or
model rerun is needed.
