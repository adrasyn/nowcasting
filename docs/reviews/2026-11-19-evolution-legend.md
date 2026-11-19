# Match the evolution legend to its rendered chart

The old CSS set translucent legend backgrounds (.40 and .15) and, in later
rules, element opacity (.35 and .15). The resulting swatches had effective
alphas .14 and .0225. The chart itself correctly draws green at .15 for the
95% region, then .35 for the inner 68% region: its overlap has alpha .4475.
The estimate line already used the correct #034159 teal.

The legend now uses small, non-focusable, aria-hidden SVGs. Both its rectangles
and the plot paths use the same band-paint function, the same order and the
existing chartTheme palette. The inner swatch includes the underlying outer
layer, so there is no second CSS alpha multiplication. The estimate swatch
uses the same palette source as the plotted line. Sizes, positions and labels
are retained. Plot geometry, palette, forecasts, animations and card axes are
unchanged; no data, model, scraper, schedule or other route is edited.

The targeted browser regression samples actual PNG pixels from the plotted
chart and legend, checks their computed line/fill/opacities, and requires each
swatch colour to occur inside the plotted chart. It failed on the old source:
the 68% swatch was RGB 221/253/232 instead of the nested green. It covers both
quarter tabs, widths 375/390/1440, light/dark system themes, and overflow. It
accepts the supported no-published-history state after a release rollover
without creating any source observations. Chromium and iPhone WebKit run it
alongside all existing checks. After Pages deployment, it runs again against
fresh public URLs and checks the exact build-commit before sampling colours.

The privately supplied reference JPEG could not be materialized on this
executor after one supported fresh preparation/transfer retry. Its pixels were
not assumed, and the image is not present in this source or any distribution.
Diagnosis and validation use source inspection and actual browser rendering.
Local Chromium chart/legend screenshots were visually inspected; CI supplies
the mobile WebKit and fresh public-page checks. No physical iPhone is claimed.

Rollback: revert this PR through the ordinary tested Pages path. Preserve all
forecast/data commits and the separately published motion/shared-axis fixes.
