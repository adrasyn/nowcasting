# Regular responsive evolution ticks

The phone reference was identified by private inspection in the parent task as
the Q3 2026 evolution chart, showing 1.1 at the top and 0.0/-0.1 crowded below.
The same pattern was independently reproduced locally. The consumer executor
could not retrieve the private JPEG after one supported transfer retry; no
reference image is included in source, test fixtures or distributions.

The previous axis used only its padded minimum, zero and padded maximum.
For a mainly positive series that placed two ticks almost on top of each other
and omitted intermediate gridlines. The evolution-only axis now rounds its
extent outward to regular multiples of a nice step (1/2/2.5/5 times powers of
ten), retaining the existing zero baseline. It includes every estimate and
both the 68% and 95% bounds. Tick count follows available height, capped at six
and allowing 26 CSS pixels per interval at the supported chart sizes. Labels
use step-appropriate precision, avoid negative zero, and stay in percentage
units. Empty/all-zero, tight, wide and negative inputs have defined behavior.

The current Q3 view now has 0.00/0.25/0.50/0.75/1.00/1.25 ticks. This is a
change to its y-axis projection and grid only. Forecasts, source observations,
x-axis code/labels, palette, legend layout, mini-card axes, and animation
timing/visibility lifecycle remain unchanged. Other charts still use their
existing domain function. No data, models, scrapers or schedules change.

Two pure axis tests cover positive/negative/mixed/tight/wide/single/zero/empty
and non-finite input cases at several heights. Browser checks for both quarter
views at 375/390/1440 verify regular numeric intervals, unique labels, readable
11px text, at least 8px between adjacent label boxes, zero, all source bounds
inside the domain, no clipped band paths and no overflow. The entire local
Chromium suite (42 tests) and the production build passed; phone and desktop
output was visually inspected. The same targeted test runs in iPhone WebKit
and again on fresh public pages with an exact build-commit assertion.

The inherited legend pixel regression also preserves legitimate no-history,
one-point and unavailable-interval states after rollover: it checks the paint
contract without demanding area pixels from a zero-width one-point polygon.
Current multi-point views retain the strict chart/swatch pixel comparison.

Rollback is an ordinary tested revert of this PR through Pages. Preserve the
legend/motion/card-axis fixes and all later data commits.
