# Claude Cowork brief — hunt long-history AU survey data (media releases / PDFs)

**Hand this to a Claude Cowork session (browser + file tools).** Goal: build the longest, cleanest possible **monthly history** for Australia's business- and consumer-survey indicators by locating and extracting their **media-release PDFs/web pages** — because these series are not published as free downloadable CSVs, but their headline numbers appear in public monthly/quarterly releases (and archives).

## Why this matters
Our GDP nowcast models (v1 and v2/MAI) are labour- and finance-heavy and go "deaf" when the labour market and GDP decouple (e.g. the 2024 per-capita recession: strong jobs, flat output). The fix is a **long-history demand-survey block** — exactly what the RBA's own MAI relies on. The blocker has only ever been *history*: we can already scrape these surveys from ~2023, but the DFM needs ~15+ years to weight them. Your job is to recover that history from the public record.

**Output contract (so it drops straight into our pipeline):** for each series, a tidy CSV named `<id>.csv` with columns `date,value` where `date` = first-of-month `YYYY-MM-01` (the reference month, not the release month), plus a `provenance.csv` mapping every `(id,date)` → source URL/PDF. Monthly series. Log every gap explicitly. **Never fabricate or interpolate a missing value — leave it out and record the gap.**

## Target series (priority order)

### 1. NAB Business Survey — HIGHEST VALUE
Monthly net-balance indices. We already have 2023→present; we need history back as far as the public record allows (ideally ≥2010).
- **Series (ids):** `nab_cond` (business conditions), `nab_conf` (business confidence), and the sub-indices `nab_trade` (trading), `nab_profit` (profitability), `nab_emp` (employment), `nab_forward` (forward orders), `nab_stocks` (stocks), `nab_cu` (capacity utilisation, %).
- **Where to look:** `business.nab.com.au/tag/business-survey`, `news.nab.com.au` (search "Monthly Business Survey" + "Quarterly Business Survey"), NAB Group Economics archives, and the **Internet Archive (web.archive.org)** for older monthly + quarterly PDFs. The **Quarterly** survey PDFs contain a "Data Appendix" with the cleanest monthly tables (5 months per release) — prefer these for backfill; use the monthly releases to fill between.
- **Extract:** the national, seasonally-adjusted headline + each sub-index, per reference month. Conditions/confidence are net balances (~[-40,30]); capacity utilisation is a % (~[78,86]).

### 2. PMIs (manufacturing / services / construction)
- **Live successor — Judo Bank / S&P Global Australia PMI** (`pmi_mfg`, `pmi_svcs`): monthly, ~2016→present. Sources: Judo Bank media releases, S&P Global PMI press releases.
- **Legacy — AiG Australian PMI/PSI/PCI** (`aig_pmi`, `aig_psi`, `aig_pci`): discontinued ~2023 but ~1992–2023 history exists in AiG media-release archives + Wayback. Splice AiG (pre-2023) with Judo/S&P (2016+) only if levels align; otherwise keep separate and note the break.
- **Extract:** the headline diffusion index per month (50 = neutral).

### 3. Consumer sentiment
- **Westpac–Melbourne Institute Consumer Sentiment** (`wmi_sent`): monthly index, long history (1970s+). Sources: Westpac IQ, Melbourne Institute releases, Wayback. Headline index (~80–120).
- (ANZ–Roy Morgan consumer confidence we already have back to the 1970s — no action unless you find a cleaner long series.)

## Method (workflow for the Cowork agent)
1. For each series, **enumerate releases chronologically** from the institution's release-archive/listing pages; do NOT guess/template URLs — follow links. Then sweep the **Wayback CDX index** (`http://web.archive.org/cdx/search/cdx?url=<site>*&output=json`) for older captures.
2. Download each PDF/page as a fixture; extract the headline number(s) for the reference month. Validate the parser against ≥2–3 known months before trusting it (wording varies: "rose to", "fell to", "remained at").
3. Assemble each series chronologically; dedup by reference month (prefer the *revised* value from a later quarterly appendix over a first-print monthly bullet). Record provenance per data point.
4. Produce a **coverage report**: earliest month reached, latest, and every gap, per series.

## Licensing / attribution (read before publishing)
These are proprietary indices. We are extracting **published headline figures from public media releases for internal research/nowcasting**. Before any of this is used on the public site: (a) record the source + publisher for attribution, (b) check each publisher's terms — some prohibit redistribution of the underlying series (showing a derived nowcast/indicator is usually fine; republishing their raw series may not be). Flag any source whose terms look restrictive. When in doubt, we use the data as a model *input* (not re-published) and attribute.

## Definition of done
- One tidy `<id>.csv` per series with the longest clean monthly history obtainable + a `provenance.csv`.
- A coverage report (earliest/latest/gaps per series) and a short note on licensing per source.
- Fixtures saved for reproducibility. Drop the CSVs in a folder we can copy into `nowcasting_v2/data_raw/`, then we re-run the targeted selection — series with enough history will finally earn weight in the MAI.

**Success = NAB conditions/confidence + a PMI + Westpac-MI sentiment, each back to ~2010 or earlier, as clean monthly CSVs with provenance.** That's the data most likely to fix the labour-vs-GDP blind spot.
