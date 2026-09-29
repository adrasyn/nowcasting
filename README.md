# Australian GDP nowcast

[nowcast.wlsn.me](https://nowcast.wlsn.me) publishes a weekly research nowcast of Australian quarterly GDP growth, its input indicators, and a backtested track record. It is a personal research project, **not an official forecast**.

## What the site publishes

The homepage headline is an equal-weight combination of the **v2** and **v3** current-quarter nowcasts. The combination also carries a next-quarter horizon. Its input panel is the union of both models' indicators, and its uncertainty bands are calibrated from the combination's own backtest errors. The site reads committed JSON under `data/`; it does not run a model in the browser.

| Model | Implementation | Role | Main output |
| --- | --- | --- | --- |
| **v1** | `pipeline/` — R dynamic factor model | Legacy weekly pipeline and fallback for `/v2` when v2 data is absent | `data/latest.json` |
| **v2** | `nowcasting_v2/` — RBA Monthly Activity Indicator and U-MIDAS | Weekly component; standalone dashboard at [`/v2`](https://nowcast.wlsn.me/v2) | `data/latest_v2.json` |
| **v3** | `nowcasting_v3/` — Python port of the NY Fed Bayesian dynamic factor model, fitted to Australian data | Weekly component and homepage fallback if combination data is absent | `data/latest_v3.json` |
| **Combination** | `nowcasting_v3/tools/emit_combination.py` | Homepage headline and track record | `data/latest_combo.json` |

`/v3` is retained as an alias of the homepage, so it displays the combination when that payload is available. The v2 headline and its stress specification use different predictor selections and regressions; see [the v2 code and panel registry](nowcasting_v2/). The v2 estimation methods in `nowcasting_v2/R/methods/` and the v3 MATLAB reference in `nowcasting_v3/nyfed_matlab/` are vendored reference code and must remain unchanged.

The comparison that motivated the combination, including its sample and limitations, is in the [September 2026 measurement](docs/measurements/2026-09-12-v2-v3-weekly-combination.md). For current published figures, inspect the [combination payload](data/latest_combo.json) and [performance payload](data/performance_combo.json); historical accuracy figures in research notes are point-in-time measurements.

## Refresh and publication

| Job | Schedule (UTC) | Responsibility |
| --- | --- | --- |
| [v1 + v2 weekly workflow](.github/workflows/nowcast-weekly.yml) | Sunday 19:00 | Fetch accessible ABS/RBA inputs, run v1 and v2, and commit their JSON. It also has a gated pre-GDP-release run. |
| [v3 weekly workflow](.github/workflows/nowcast-v3-weekly.yml) | Sunday 20:30 | Run v3, combine it with v2, validate payloads, commit JSON, and trigger deployment. |
| [v3 estimation workflow](.github/workflows/nowcast-v3-estimate.yml) | Quarterly | Re-estimate the saved v3 model state. |
| [Pages deployment](.github/workflows/deploy.yml) | On relevant pushes or dispatch | Test and build the Next.js static site, then deploy GitHub Pages. |

The Sunday jobs run on Monday morning in Sydney. The survey inputs that cannot reliably be fetched in CI have a separate **Codex cloud scheduled task**; its schedule and run history live in Codex, not in this repository. The task updates the survey CSVs on `main`, and the next model run reads those committed values. See the [current survey refresh guide](docs/weekly-survey-refresh.md) for the series, validation rules, and timing dependency. A week with no new monthly release needs no survey commit.

Both v2 and v3 target the ABS **first release** of quarterly GDP rather than a subsequently revised estimate. The v3 weekly run can refuse to publish when its data or fitted state fails checks; the site surfaces that refusal. The combination emitter also records when it carries a recent v2 component forward. See the [v3 implementation notes](nowcasting_v3/README.md) and [first-print measurement](docs/measurements/2026-09-09-first-print-target-ab.md).

## Work locally

```bash
npm install
npm run dev            # Next.js dashboard at localhost:3000
npm test               # Vitest unit tests
npm run lint
npm run build          # static export to out/
npm run test:e2e       # Playwright checks (requires browser installation)
```

The R and Python model environments are separate from the site. The v1 entry point is `pipeline/run_complete_nowcast.R`; the v2 weekly entry point is `nowcasting_v2/R/emit_v2_json.R` after its ABS/RBA fetchers; the v3 weekly runner is `nowcasting_v3/tools/run_au_nowcast.py`. Use the workflow files above for production ordering and the model READMEs for environment and test details. Running a model locally can rewrite committed data artifacts, so review the diff before keeping generated JSON.

## Repository map

- `src/` — Next.js pages, components, and JSON loaders.
- `data/` — committed site payloads and track records for v1, v2, v3, and the combination.
- `pipeline/` — v1 R pipeline and interval helpers; see its [README](pipeline/README.md).
- `nowcasting_v2/` — RBA-based model, raw input CSVs, fetchers, and NAB parser.
- `nowcasting_v3/` — Python model, Australian panel, combination emitter, tests, and saved model state.
- `.github/workflows/` — refresh, estimation, and deployment jobs.
- `docs/measurements/` and `docs/reviews/` — dated research and review evidence. `docs/superpowers/` contains point-in-time design plans, not current operating instructions.

The v2 candidate series and transformations are listed in [`nowcasting_v2/seed/panel_info.csv`](nowcasting_v2/seed/panel_info.csv); v3's 14-series panel is defined by [`nowcasting_v3/model_spec_AU.csv`](nowcasting_v3/model_spec_AU.csv). Both use ABS National Accounts (5206.0) quarterly chain-volume GDP as the target.
