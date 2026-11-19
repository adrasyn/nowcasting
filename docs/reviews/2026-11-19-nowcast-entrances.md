# Nowcast entrance motion

This is a separate follow-on to baseline PR #50, deployed and publicly verified
at 04:40 UTC on 19 November 2026 (source `b5c7cce6cf294ee7f1348c8edfd7bb2e3115b3ab`,
[deployment](https://github.com/adrasyn/nowcasting/actions/runs/44459179130)).

The four headline growth values count from zero with the same symmetric
smoothstep S-curve. They share a base interval of 16ms per displayed hundredth,
so their target size determines their finish time. If any value would exceed
3.6 seconds, the shared interval compresses proportionally for the entire group.
Rounding and signs use the same formatter as the final published figures.
Zero and unavailable figures are immediate; no intermediate value is announced.

Each uncertainty ruler reuses its existing blue marker and two green rectangles.
The marker moves from zero to the estimate; both edges grow from the moving
marker to the exact published endpoints. Current/next roles use deterministic
marker durations of 1460/1580ms; the 68% band finishes 80ms later and the 95%
band 160ms later. No extra sweep layer or loop is introduced. Resize continues
the same elapsed timeline rather than restarting it. An unavailable estimate
has no synthetic marker or interval.

Final text stays in the document and reserves its original dimensions. The
changing visual layer is `aria-hidden`; screen readers and copying receive the
exact final value. Without JavaScript the generated visual layer is already
final. Reduced motion shows final values and geometry immediately; enabling
reduced motion during entry cancels and completes it. All animation callbacks
stop after their final frame and clean up on unmount.

Validation includes pure start/mid/end calculations across the existing weekly,
rollover, year-boundary, missing/refused and model/panel fixtures; browser
start/mid/end geometry and unchanged card bounds at 375, 390 and 1440 pixels;
exact final values/band coordinates against a reduced-motion control; no repeat;
preference changes; no-JavaScript output; and the complete baseline browser and
repository suites. The original current-card sheen, evolution/indicator motion,
data, fonts, palette, layout, model jobs and private preview are preserved.

Rollback just this motion by reverting its follow-on PR through a normal PR and
letting the existing Pages workflow publish. The baseline layout remains in
PR #50. No dataset rollback is needed.
