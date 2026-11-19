# Approved homepage production handover

The approved deployed-style v10 layout has been ported into Next.js. The private
preview is a visual reference only and remains unchanged; its snapshot, build,
hard-coded dates and quarter-specific DOM are not production inputs.

## Publication contract

- `loadDashboardData()` reads committed files at every static build, including
  `nowcast_history_combo.json` / `nowcast_history_v3.json`. Current vintages merge
  into the saved archive by target and run, with a corrected current row winning.
- `buildMonitorView()` chooses a model bundle consistently: latest, panel,
  performance and archive. A refused combination never silently becomes v3.
- Verified ABS observations in `gdp.json` determine the next unprinted quarter.
  The run date and the calendar never masquerade as an actual GDP release.
  A prior next-quarter forecast can be carried after release, with an explicit
  warning, until the new current-quarter estimate arrives. An absent following
  quarter is shown as unavailable. Q4 advances to Q1 of the following year.
- Headline levels, y/y denominators, date labels, uncertainty, vintage deltas,
  tables and counts are derived. Zero-month forecasts withhold figures. Release
  dates must match the target's following quarter; source check dates stay checks.
- Empirical combination error bands and v3 posterior bands retain their different
  meanings. A v3-only next horizon is labelled posterior. Provisional pooled
  next-quarter calibration is disclosed when the payload flags it.
- Indicator row and expanded charts share one calculation and type. Employment
  bars subtract stored thousands of people without dividing twice. Selected
  other level series use adjacent monthly/quarterly percentage changes; gaps,
  zero denominators and duplicate periods are not interpolated. Raw tables stay
  levels. Survey/rate presentation retains the PR #46 semantics; ANZ inputs and
  the PR #49 source provenance are unchanged.
- All weekly vintages, GDP quarters and score rows remain inline. Native indicator
  disclosures contain complete raw observation lists. No modal, search, filter
  or evolution slider is introduced. Phone rows reclaim the mini-chart column.
- Axes are measured in the rendered SVG box so labels do not shrink with the
  desktop viewBox on phones. SVG points support keyboard, touch and labelled
  readouts. Reduced motion shows the final view immediately.

## Validation and delivery

The Pages workflow verifies pull requests without publishing them. Main pushes
and the existing weekly dispatch still use the same test/build/postbuild path,
including `/simple/`. No model, dataset, weekly schedule, estimate job, vendored
method, `/v2` implementation or simple-page generator is changed.

Unit tests verify data contracts/calculations and render stable regression
fixtures from isolated test memory. Browser tests check current generated data,
full archive/observation counts, first-print scores, ANZ provenance, PR #46
formatting, mini/detail parity, native disclosures, focus and keyboard behavior,
reduced motion and 320/375/390/667/844/1024/1440 widths. Nine additional fixture
renders cover a new weekly vintage, ABS rollover, the year boundary, missing and
refused payloads, stale data, v3 fallback a next horizon waiting for its second component, and a newly selected empty series.
They are inspected at 375, 390 and 1440 pixels. Fixtures never enter production.

After merging, the Pages action runs `scripts/check_deployed.py` against `/` and `/simple/`
with fresh cache keys and checks their `build-commit` metadata. It also checks
current figures against committed inputs, both font assets, JS/CSS chunks and
`/v2`, `/v3` and the simple-page GIFs. Failed verification fails the action.
The check can be run locally against any export server with `--base` and
`--commit`; it does not run a model or change any data.

## Rollback

Revert the homepage integration merge with a normal pull request and let the
same Pages workflow publish. The preceding baseline source is
`0cb5b244325721af782fb1ab59b5b6a41dc73e72`. Revert the integration commit rather
than resetting main or restoring old datasets, so future model/data commits are
preserved. Private previews are separate and need no rollback.
