# Candidate new indicators — panel expansion after the Q1 2026 miss

<!-- POINT-IN-TIME -->
> **Point-in-time record — 2026-06-03. Not current state.**
> This document describes what was true when it was written. The model, panel and
> calibration have changed since; several numbers here are known to be superseded.
> For current state see `README.md`, and for the 2026-08 fidelity review and its
> corrections log see `docs/reviews/2026-08-01-v2-intention-and-bug-review.md`.


**Date:** 2026-06-03
**Status:** For review — *please add comments under each series and cross-cutting item.*
**Author note:** This is a pre-spec worksheet. Once you've annotated it, I'll turn the agreed set into a proper design spec + implementation plan.

---

## Why we're here (one-screen recap)

- **The miss:** final Q1 2026 nowcast **+0.77% qoq** (level 699,140) vs ABS actual **+0.30%** (695,945). Over by **+0.47pp / $3.2B** — *less than one RMSE* (post-COVID RMSE ≈ $4,249M / 0.6%), and inside the 68% band. So: real but unremarkable on n=1. The danger is over-fitting a fix to one print.
- **Root cause (diagnosis):** not the old `trans=0` over-extrapolation (that's fixed) and not a mechanical over-shoot (backtest bias is *negative*). The panel is **hard-activity / labour-dominated** (4/13 labour + firm spending/approvals), so the factor stayed firm while GDP softened. The genuinely soft/contemporaneous signals that *did* arrive — NAB confidence +3→−24, consumer conf →−20, goods exports −1.2% — moved the nowcast by **0.04pp**. The model was deaf to the bad news. Meanwhile the biggest actual drivers were **off-panel**: Cyclone Koji → coal/mining/exports, weak government, net-trade drag. And half the External block (services exp/imp) had **no Q1 data at all**.

## What's already decided (don't re-litigate unless you want to)

- **Architecture unchanged.** Keep the 3-factor DFM straight to GDP level, flat panel, `nowcasting` package. No Treasury-style bridging-equation rewrite, no block-structured factors — deferred until evidence justifies them.
- **No financial-market block.** Both the Atlanta Fed (hard-data only) and NY Fed (DFM, but *explicitly* excludes financial vars — SR830 p.16) leave out equities/VIX/rates/credit; even the Treasury paper's own footnotes 4–5 admit its financial vars were low-value. Commodity/terms-of-trade survives because Australia is a resource exporter and the Q1 miss *was* a commodity/export shock — that's a real driver, not a volatility series.
- **Evidence-gated inclusion.** A variable ships only if it improves POOS backtest metrics vs the current 13-series r=3 baseline. See "Validation" at the bottom.

> **Your comments on the framing / decisions above:**
>we'll test again if 3 factors are still correct or if we need further factors added.
>

---

## Candidate series

Legend — **Value:** ★–★★★ expected contribution to fixing *this* class of miss. **Feasibility:** 🟢 free & automatable / 🟡 some work or external dependency / 🔴 proprietary or discontinued. Transform codes follow the existing per-series `trans_code` scheme and **all need confirming against `nowcasting::Bpanel` semantics** (the open item already flagged in `docs/todo.md`).

### Tier 1 — Commodity / terms-of-trade (targets the Q1 driver directly)

#### 1. RBA Index of Commodity Prices (A$ terms) — `commodity_prices`
- **Value:** ★★★  **Feasibility:** 🟢
- **What:** RBA's Laspeyres index of prices received by Australian commodity exporters (A$ terms). The single best proxy for the coal/mining/export price shock that drove the Q1 miss.
- **Source / id:** RBA statistical table **I2** (Commodity Prices). Non-ABS → needs a small new fetch module (pattern: existing `03b_fetch_fred_data.R`).
- **Frequency / lag:** monthly, ~weeks lag. **Proposed transform:** MoM % change (code `1`).
- **Risk:** RBA publishes as CSV/XLS on a stable URL; fetch is straightforward. Also available on FRED in USD terms if RBA fetch is awkward, but A$ terms is the more GDP-relevant one.

> **Comments:**
>Approved
>

#### 2. AUD/USD exchange rate — `aud_usd`
- **Value:** ★★  **Feasibility:** 🟢
- **What:** Commodity-currency / external-conditions signal. Co-moves with terms of trade; cheap to add.
- **Source / id:** FRED **`DEXUSAL`** (US$ per A$, daily) — extend `03b_fetch_fred_data.R`. Alt: RBA table F11.1.
- **Frequency / lag:** daily → monthly avg, ~no lag. **Proposed transform:** 1st difference (code `2`?) — confirm.
- **Risk:** trivial. Question is whether it adds anything beyond the commodity index (may be collinear — let the backtest decide).

> **Comments:**
>Approved noting your risks.
>

#### 3. (Optional) Oil price (Brent) — `oil_brent`
- **Value:** ★  **Feasibility:** 🟢
- **What:** External/inflation signal; Treasury uses Tapis. Less AU-specific than the commodity index.
- **Source / id:** FRED **`DCOILBRENTEU`** (or `DCOILWTICO`). Extend FRED fetch.
- **Frequency / lag:** daily → monthly. **Proposed transform:** MoM % change (code `1`).
- **Risk:** none; low marginal value — include only if backtest likes it.

> **Comments:**
>agreed, only include if backtest likes it
>

### Tier 2 — Real activity for the weak components (GDPNow lesson: inventories & net exports are the big error sources)

#### 4. Business inventories — `inventories`
- **Value:** ★★  **Feasibility:** 🟡
- **What:** GDPNow flags inventories + net exports as its two largest error sources — and net trade was exactly our Q1 drag. Gives the model a direct read on the most volatile GDP component.
- **Source / id:** ABS **5676.0** Business Indicators — Inventories, chain volume, SA. Add a `component_metadata` row with the ABS series id → auto-fetched. **Exact `abs_series_id` to be looked up via `readabs`.**
- **Frequency / lag:** **quarterly**, ~2-month lag. **Proposed transform:** confirm (code `1` or `7`).
- **Risk:** quarterly + lagged means limited ragged-edge timeliness (similar issue to services trade). Still informative for the bridging/level.

> **Comments:**
>yeah same problem as services imports/exports. i think we should still include.
>

#### 5. Short-term visitor arrivals — `arrivals`
- **Value:** ★  **Feasibility:** 🟢
- **What:** Tourism / services-export proxy. Directly addresses the finding that the **services-export series was mute (no Q1 data)**.
- **Source / id:** ABS **3401.0** Overseas Arrivals & Departures — short-term visitor arrivals, SA. Metadata row. **Exact `abs_series_id` TBD.**
- **Frequency / lag:** monthly, ~5-week lag. **Proposed transform:** MoM % change (code `1`).
- **Risk:** low. Post-COVID arrivals are still normalising — backtest window includes that distortion.

> **Comments:**
>this also matters for services exports for education. this data is very seasonal, so we'll need to use seasonally adjusted.
>

#### 6. New motor vehicle sales — `motor_vehicles`
- **Value:** ★  **Feasibility:** 🔴→🟡
- **What:** Durable-goods consumption signal.
- **Source / id:** ⚠️ **ABS 9314.0 was discontinued in early 2018** (per Treasury paper fn 8); the live series is **VFACTS (FCAI)** which is **proprietary**. Options: (a) find a current free proxy, (b) drop this candidate. **This is the least feasible Tier-2 item — flagging honestly.**
- **Frequency / lag:** monthly. **Proposed transform:** MoM % change (code `1`).
- **Risk:** **High — no obvious free live source.** Recommend dropping unless you know a feed.

> **Comments:**
>the only source is a monthly media release from the FCAI. https://www.fcai.com.au/news-and-media/
>

### Tier 3 — Soft / survey block (high value per NY Fed, but has a manual-data cost)

#### 7. NAB business *conditions* — `nab_conditions`
- **Value:** ★★  **Feasibility:** 🟡
- **What:** NAB *conditions* (trading/profitability/employment) tracks actual activity better than *confidence* (which we already have). NY Fed gives surveys their own block as the most timely inputs.
- **Source / id:** Same NAB monthly survey we already ingest — but the current `nab_business_confidence_raw.csv` is **`date,value` (confidence only)**. ~~Needs: extend CSV schema, update the **user-owned NAB scheduled task** (`docs/nab-update-task.md`) to capture conditions, and **backfill history**.~~ **Update 2026-08-23:** that scheduled task is retired (see `docs/nab-update-task.md`) and this is now much cheaper — `nowcasting_v2/data_raw/nab_cond.csv` already holds conditions with full history, alongside six more sub-indices (`trade`, `profit`, `emp`, `forward`, `stocks`, `cu`). No new scraping needed; this is a panel-wiring job, not a data-acquisition one.
- **Frequency / lag:** monthly. **Proposed transform:** net-balance level (code `2`).
- **Risk:** external manual-data dependency + backfill before it can be backtested. Higher effort than Tier 1–2.

> **Comments:**
>there aren't any good sources for business conditions except the monthly NAB pdf. For historical data, we would need to download and scrape all the previously quarterly NAB surveys, which includes the monthly data as well.
>

#### 8. NAB capacity utilisation — `nab_capacity`
- **Value:** ★  **Feasibility:** 🟡
- **What:** Capacity utilisation — supply-side activity / output-gap signal. Same survey, same manual-data path as #7.
- **Source / id:** NAB monthly survey → same CSV/task extension as #7.
- **Frequency / lag:** monthly. **Proposed transform:** level (code `2`).
- **Risk:** as #7.

> **Comments:**
>Same as for the NAB business conditions data
>

#### 9. (Noted, not proposed) Westpac–MI Consumer Sentiment
- We already carry a consumer-confidence proxy (OECD via FRED). Westpac-MI is proprietary. **Recommend keeping the existing proxy** rather than adding this. Listed only for completeness.

> **Comments:**
>yeah ignore.
>

---

## Cross-cutting items (also need your steer)

### A. Services-trade staleness cleanup
`services_exports` / `services_imports` sat at **Dec-2025** values through the whole Q1 run (ABS services trade is slower-cadence than goods). Options: find a timelier source, improve ragged-edge handling so they don't sit flat, or accept the lag. Arrivals (#5) partly compensates on the export side.

> **Comments:**
>there is no other source, just the ABS data from national accounts (which is also where our gdp data comes from unfortunately) which we're already using.
>

### B. Factor count after expansion
Keep r=3 to estimate, then **re-run the sweep (r=2/3/4)** on the wider panel. r=4 previously failed on rank-deficiency *because 13 indicators were too few* — more series may make it feasible. Decide by backtest, not assumption.

> **Comments:**
>yup sounds good.
>

### C. Validation / acceptance gate (the pragmatic core)
1. Re-run `run_backtest_sweep.R` / `09_backtest_model.R` on the expanded panel (2020–2025 + post-COVID 2022–2025).
2. **Accept a variable only if it improves** post-COVID QoQ RMSE (now 0.42pp) and/or hit rate (now 93.8%) vs the current 13-series r=3 baseline. Drop any that don't earn their place.
3. **Held-out test on the actual miss:** does the expanded panel nowcast 2026 Q1 closer to the realised **+0.30%**? That's the direct test that we fixed *this* problem rather than just added complexity.

> **Comments:**
>
>

---

## Summary table

| # | Series | Tier | Value | Feasibility | Source | Transform (confirm) |
|---|---|---|---|---|---|---|
| 1 | RBA Commodity Price Index (A$) | 1 | ★★★ | 🟢 | RBA I2 | MoM % (`1`) |
| 2 | AUD/USD | 1 | ★★ | 🟢 | FRED DEXUSAL | 1st diff (`2`?) |
| 3 | Oil (Brent) | 1 opt | ★ | 🟢 | FRED DCOILBRENTEU | MoM % (`1`) |
| 4 | Business inventories | 2 | ★★ | 🟡 | ABS 5676.0 | tbd |
| 5 | Short-term arrivals | 2 | ★ | 🟢 | ABS 3401.0 | MoM % (`1`) |
| 6 | Motor vehicle sales | 2 | ★ | 🔴→🟡 | ABS 9314 (disc.) / VFACTS | MoM % (`1`) |
| 7 | NAB conditions | 3 | ★★ | 🟡 | NAB task | level (`2`) |
| 8 | NAB capacity util | 3 | ★ | 🟡 | NAB task | level (`2`) |

> **Overall comments / anything missing:**
>i think we're just a bit stuck because Australia just doesn't have as good data as the USA. let me know if you have any proposed steps forward for getting/scraping the NAB quarterly business reports. maybe we can use cowork to search through the website to find them all, and then a scheduled task to grab the latest each month from the monthly reports. same things for the FCAI motor vehicle sales.
>
