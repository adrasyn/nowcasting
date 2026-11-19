# Evolution draw: visible, measured first frame

The prior deployed Recharts implementation mounted its keyed quarterly chart
inside `ResponsiveContainer`, after dimensions were measured. The SVG port
started native WAAPI timelines in a mount effect, before the responsive SVG had
settled and without checking the plotted line's visibility. On an iPhone-sized
390×664 visual viewport, the chart header was visible but the line was below the
screen. The timeline nevertheless advanced. Initial dash lengths could also
come from the server's wider viewBox rather than the measured phone geometry.

Regression run [44462705841](https://github.com/adrasyn/nowcasting/actions/runs/44462705841)
used the old production implementation and new tests before the fix. Chromium
was 53.8% through its offscreen draw. Mobile WebKit was fully advanced offscreen,
and 41.0% advanced during the delayed-font case. All production publishing steps
were skipped: this was the draft PR's reproduction check, not a failed public
deployment. Public main stayed at `3626f26` from successful run 44461398002.

Only the evolution chart now uses `useEvolutionMotion`. It prepares paused
native timelines at zero, then waits for fonts, matching measured SVG dimensions,
a visible document and the plotted line within the actual visual viewport. Two
frame opportunities prime the layout, then a zero frame precedes advancement.
A RAF driver seeks the existing native 1500ms/ease timelines; long paint gaps do
not consume the beginning of the draw. Offscreen scrolling pauses/resumes the
same elapsed position, and completion disconnects observers and never replays
on ordinary scrolling. A deliberate quarter change gets its own first draw. Keyboard focus can enter
the waiting plot and keeps the selected point visible without interrupting or
resetting the draw.
Resizing rebuilds measured dash/clip geometry at the same elapsed position.

Server/no-JavaScript and reduced-motion output remains final and unmasked.
Enabling reduced motion during the draw completes immediately. No card motion,
indicator motion, chart scale, data, model or schedule is changed. The paired
card-axis request is a separate change.

Tests run the iPhone viewport in WebKit and Chromium with delayed visibility,
font loads and a 650ms blocked paint; they check frame zero, pause/resume, no
scroll replay, quarter selection, desktop completion and no-JS/reduced-motion
fallbacks. Browser captures are retained as the `browser-qa` Actions artifact.
Local WebKit download is blocked by the managed network, so actual WebKit runs
are executed in CI. Chromium and the production build also run locally.

Rollback this correction by reverting its PR through the same Pages workflow;
keep the previously approved card animation and production data commits.

CI includes sufficient time for both browser engines and their OS dependencies;
a previous run passed all 33 checks but reached the former 15-minute job limit
during the final build. No publishing step executed on that cancelled PR run.
