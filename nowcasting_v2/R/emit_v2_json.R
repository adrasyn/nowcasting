# emit_v2_json.R
# STAGED v2 emit (Phase 5). Produces data/latest_v2.json — a PARALLEL, NON-
# DESTRUCTIVE artifact that does NOT touch the live data/latest.json.
#
# Monday cadence (matches the production weekly cron). For each Monday `as_of`
# we truncate the raw panel + GDP to what was published by that date (via the
# backtest_v2 publication-lag logic — real-time faithful), then build_mai +
# nowcast. The HEADLINE/STRESS boxes show the LATEST Monday; the evolution chart
# shows the qa nowcast at every Monday (the vintages array).
#
# ONE model: headline = qa_a10. A second "stress / volatility" spec (umidas_a20)
# was emitted alongside it until 2026-08-02 and shown behind a toggle on the site.
# Removed: it was v2's own construct rather than anything in RDP 2024-04, it was
# the estimate carrying a significant +0.34pp bias, and keeping it meant ~20 min of
# every recalibration plus a second params file maintained for something no longer
# displayed. Recoverable from git if it is ever wanted back.
# The headline threshold moved 0.05 -> 0.10 on 2026-08-02 to match RDP 2024-04.
# The 0.05 deviation had been justified by SPEC-SWEEP-RESULTS.md, but that sweep
# fixed the targeted-predictor selection once on the FULL sample and forced it at
# every historical as-of -- a look-ahead that flattered the stricter threshold
# most, because the advantage scales with how many series are admitted. Re-run
# without it, alpha=0.05 vs 0.10 is not statistically distinguishable (paired test
# on squared error, full sample n=49: p=0.43; post-COVID n=17: p=0.63), so the
# tie now breaks toward the paper.
# (big-events). Both on panel B3_nab_wmi (exclude AiG). Bias-aware CI level-bands
# from pipeline/seed/ci_params_v2*.json. yoy = 4-quarter QoQ chain.
#
# TWO HORIZONS (2026-09-12). Each Monday also nowcasts the quarter AFTER the
# current one, off the same MAI, once that quarter has a month of data —
# models$next_quarter in the payload, and a second vintage row carrying
# horizon = "next" and the next quarter's target_quarter. The headline is
# untouched: the next-quarter block is simply absent in the weeks when the MAI
# has no month past the current quarter. The vintage log's upsert key is
# (run_date, target_quarter), not run_date alone.
#
# THE ROWS OUTLIVE THE HORIZON. A next-quarter row written in August targets the
# quarter that BECOMES the current one in September, so from that Monday on the
# log holds several rows for the headline's own quarter that were made at the
# next horizon. /v2's evolution chart selects on target_quarter alone, so it must
# drop horizon = "next" explicitly (src/app/v2/page.tsx does) or those rows
# silently extend its line. This is the promotion problem noted in docs/todo.md.
#
# Usage (from nowcasting_v2/, native Rscript + R_LIBS=pipeline lib):
#   Rscript R/emit_v2_json.R

suppressWarnings(suppressMessages({
  here <- tryCatch(dirname(sys.frame(1)$ofile), error = function(e) NA)
}))
if (is.na(here) || !nzchar(here)) here <- "R"
source(file.path(here, "_setup.R"))
source(file.path(here, "build_panel.R"))
source(file.path(here, "transform_panel.R"))
source(file.path(here, "build_mai.R"))
source(file.path(here, "nowcast_midas.R"))
source(file.path(here, "run_nowcast_v2.R"))      # get_prev_level() (guarded; no auto-run)
source(file.path(here, "backtest_v2.R"))         # .truncate_panel(), .truncate_gdp(), .lag_for_id()
source(file.path(here, "..", "..", "pipeline", "ci_bands.R"))  # ci_level_band(), load_ci_params()
suppressMessages({ library(jsonlite) })

AIG       <- c("aig_pmi", "aig_pci", "aig_psi")   # B3_nab_wmi panel excludes the AiG block
GDP_LAG   <- 60L                                  # National Accounts ~9wk after quarter-end
CI_QA     <- "../pipeline/seed/ci_params_v2.json"

# Accurate publication lags (days from END of reference month). Corrects the
# coarse backtest map (.lag_for_id) after the 2026-06-11 Fable review, which showed
# the lag-45 ABS-activity block and lag-30 financial block withheld data that was
# actually public (MHSI April released 28 May; daily AGS yields/spreads/BBSW are
# available within days). Used for the LIVE as-of truncation here and mirrored in
# the indicators release-date generator. The CI params (ci_params_v2*.json) are now
# calibrated on these accurate lags (backtest_v2.R .lag_acc), EXCEPT MHSI which the
# calibration holds at its true historical 35d (the 28d schedule only began Apr 2026,
# after the calibration window; using 28d historically would leak look-ahead).
.LAG_ACC <- c(emp = 15, ft_emp = 15, pt_emp = 15, ue = 15, ud = 15, hours = 15,
              household_spending = 28, rt = 33, export = 35, building_app = 33,
              credit = 30, credit_housing = 30, credit_business = 30, credit_card = 30,
              fcmygbag3 = 2, fcmygbag5 = 2, fcmygbag10 = 2,
              scrigbag3 = 2, scrigbag5 = 2, scrigbag10 = 2, firmmbab90 = 2,
              nab_conf = 10, nab_cond = 10, nab_trade = 10, nab_profit = 10,
              nab_emp = 10, nab_forward = 10, nab_stocks = 10, nab_cu = 10,
              anz_ads = 10, anz_sent = 10, wmi_sent = -15)
.lag_acc <- function(id) if (id %in% names(.LAG_ACC)) .LAG_ACC[[id]] else 30L

# Truncate the panel to data published by as_of, using the accurate lags above.
.truncate_acc <- function(wide, as_of_date) {
  as_of_date <- as.Date(as_of_date)
  ids <- setdiff(names(wide), "date")
  ref_end <- lubridate::ceiling_date(wide$date, unit = "month") - lubridate::days(1)
  out <- wide
  for (id in ids) {
    rel <- ref_end + lubridate::days(.lag_acc(id))
    out[[id]][rel > as_of_date] <- NA_real_
  }
  out
}

# Monday cadence: every Monday from the first Monday after the prior quarter's GDP
# became available (so the target is the current quarter) up to today. Programmatic
# so the weekly cron advances on its own (Fable review BLOCKER 2).
.mondays_to_date <- function(gdp_full) {
  last_q_end    <- lubridate::ceiling_date(max(as.Date(gdp_full$date)), "quarter") - 1
  prior_release <- as.Date(last_q_end) + GDP_LAG
  d <- prior_release
  while (as.integer(format(d, "%u")) != 1L) d <- d + 1   # next Monday on/after
  today <- Sys.Date()
  if (d > today) return(format(d, "%Y-%m-%d"))
  format(seq(d, today, by = "week"), "%Y-%m-%d")
}

# yoy: the three quarters before the target compounded with the target-quarter
# nowcast. `chain_qoq` holds any quarters between the last ACTUAL and the target
# that are themselves nowcasts -- for the next-quarter horizon that is the
# current quarter's own nowcast -- and each one replaces a trailing actual, so
# the compound is always exactly four quarters. Empty for the headline, where
# this is unchanged. Those actuals come from data/gdp.json (the latest vintage), NOT from
# `gdp` (data_raw/rt_dgdp_qtr.csv): since 2026-09 that file holds the ABS's
# initial estimate of each quarter, which is what the model is estimated on, but
# year-ended growth is a comparison with the level a year ago and every other
# year-ended figure on the site is quoted on the latest vintage (gdp.json's own
# yoy_pct, the RBA comparison in gen_performance_v2.py). Compounding initial
# estimates here would move the headline "vs a year ago" by ~0.2pp for no model
# reason. `gdp` still fixes WHICH three quarters (the ones before the target).
# Falls back to `gdp`'s own values, with a warning, if gdp.json lacks them.
.compute_yoy <- function(gdp, nowcast_qoq, repo_root = "..", chain_qoq = numeric(0)) {
  g <- gdp[order(as.Date(gdp$date)), ]
  last_date <- max(as.Date(g$date))
  n_act <- 3L - length(chain_qoq)
  if (n_act < 0L) stop("emit_v2_json(): chain_qoq longer than the year-ended window")
  # first-of-month dates, so stepping back by whole months is exact
  qdates <- if (n_act == 0L) as.Date(character(0)) else
    rev(seq(last_date, by = "-3 months", length.out = n_act))
  want <- sprintf("%d Q%d", as.integer(format(qdates, "%Y")),
                  as.integer(format(qdates, "%m")) %/% 3L)
  latest <- tryCatch(jsonlite::fromJSON(file.path(repo_root, "data", "gdp.json"))$series,
                     error = function(e) NULL)
  acts <- if (!n_act) numeric(0) else if (!is.null(latest) && all(want %in% latest$quarter)) {
    latest$qoq_pct[match(want, latest$quarter)]
  } else {
    warning(sprintf(paste("emit_v2_json(): data/gdp.json lacks %s; year-ended growth",
                          "compounds the initial-estimate file instead."),
                    paste(want, collapse = ", ")), call. = FALSE)
    tail(g$value, n_act)
  }
  (prod(1 + c(acts, chain_qoq, nowcast_qoq) / 100) - 1) * 100
}

# Order the vintage log by (run_date, target_quarter). A Monday now carries up to
# two rows -- the current quarter and the next -- and "YYYY Qn" sorts
# chronologically as a string, so the current quarter always precedes the next.
.sort_vlog <- function(vlog) {
  if (!length(vlog)) return(vlog)
  k <- vapply(vlog, function(r) paste(as.character(r$run_date),
                                      as.character(r$target_quarter)), character(1))
  vlog[order(k)]
}

# jsonlite reads JSON null as R NULL and writes R NULL as {}, which silently
# corrupts any null-valued field on a read-modify-write. Mapping NULL -> NA first
# makes the round trip byte-exact under na = "null".
.nulls_to_na <- function(x) {
  if (is.null(x)) return(NA)
  if (is.list(x)) { for (i in seq_along(x)) x[[i]] <- .nulls_to_na(x[[i]]); return(x) }
  x
}

#' @param rebuild_vintages If TRUE, recompute the nowcast for EVERY Monday in the
#'   cadence instead of only the latest, replacing data/vintages_v2.json wholesale.
#'
#'   Default FALSE, and it must stay that way for the weekly cron. The log is
#'   deliberately append-only: recomputing history on every run lets data
#'   revisions silently rewrite what was already published (the 2026-06-15
#'   non_res_ba leak extended the DFM window to 1965 and moved every past point).
#'
#'   Use this ONLY after a deliberate model change, when leaving the old points in
#'   place would be the more misleading option — e.g. the 2026-08-02 fidelity work,
#'   after which eight of the nine points came from a model with a known
#'   look-ahead in its predictor selection. Rebuilding then makes the series
#'   internally consistent, at the cost that it no longer shows exactly what was
#'   published live on each of those Mondays.
#'
#' @param backfill_next If TRUE, compute ONLY next-quarter rows, for every Monday
#'   in the cadence, and upsert them into the vintage log. Nothing about the
#'   current quarter is written: the headline in data/latest_v2.json is left
#'   exactly as it was, existing vintage rows for the current quarter are left
#'   exactly as they were, and only the `vintages` array is refreshed in place.
#'
#'   This is a one-off for the week the next horizon shipped (2026-09-12): the
#'   append-only log has no next-quarter rows before that date, so the
#'   combination's evolution chart would start from nothing. It is a backfill of
#'   a series that was never published, not a rewrite of one that was, which is
#'   why it is allowed where `rebuild_vintages` is not. A Monday whose MAI has no
#'   month past the current quarter is skipped, as it would have been live.
emit_v2_json <- function(repo_root = "..", mondays = NULL, rebuild_vintages = FALSE,
                         backfill_next = FALSE) {
  if (rebuild_vintages && backfill_next)
    stop("emit_v2_json: rebuild_vintages and backfill_next are mutually exclusive")
  cat("=== emit_v2_json (Monday cadence, staged) ===\n")

  # ---- shared inputs (full panel; truncated per as_of below) ----
  cat("[1] panel: build_panel() from data_raw/*.csv\n")
  wide_full <- build_panel()
  if (!("wmi_sent" %in% names(wide_full)))
    stop("emit_v2_json: panel has no 'wmi_sent' — survey block missing; refusing to nowcast the baseline panel under B3 bands.")
  nab_n <- sum(!is.na(wide_full[["nab_conf"]]))
  if (nab_n < 120L)
    stop(sprintf("emit_v2_json: nab_conf has only %d months — looks like the 39-month stub, not the extended B3 series.", nab_n))
  cat(sprintf("[1] panel OK: %d series; wmi_sent present, extended NAB (n=%d)\n", ncol(wide_full) - 1L, nab_n))
  gdp_full <- read.csv("data_raw/rt_dgdp_qtr.csv")
  gdp_full$date <- as.Date(gdp_full$date)   # .truncate_gdp needs Date, not character
  if (is.null(mondays)) mondays <- .mondays_to_date(gdp_full)
  cat(sprintf("[0] Monday cadence: %s\n", paste(mondays, collapse = ", ")))

  jlatest <- tryCatch(jsonlite::fromJSON(file.path(repo_root, "data", "latest.json")), error = function(e) NULL)
  # prev_level = realized level of the quarter BEFORE target (the $ anchor).
  pl <- if (!is.null(jlatest) && !is.null(jlatest$latest_actual$gdp_chain_volume_millions))
    list(level = as.numeric(jlatest$latest_actual$gdp_chain_volume_millions),
         date = jlatest$latest_actual$quarter, source = "latest.json latest_actual (realized ABS)")
  else get_prev_level(no_fetch = TRUE, repo_root = repo_root)
  if (is.null(pl)) stop("emit_v2_json: could not resolve prev GDP level")
  prev_level <- pl$level
  release_date <- if (!is.null(jlatest$next_gdp_release_date)) as.Date(jlatest$next_gdp_release_date) else NA

  # ---- the MAI at one as_of (both horizons read the same one) ------------------
  # Exclude AiG (dead) and rt (old Retail Trade, superseded by MHSI =
  # household_spending, which the model already uses; rt was never selected).
  # gdp = gdpt: the Wald selection must see only GDP released by this as_of.
  # Without it build_mai reads the full rt_dgdp_qtr.csv and the selection is
  # supervised on quarters that had not yet been published.
  #
  # Split out of mk() on 2026-09-12 so the current- and next-quarter nowcasts at
  # the same Monday share one MAI: they are the same index read at two horizons,
  # and building it twice would double the run for no difference in the result.
  mk_mai <- function(tfs, gdpt, id, sel_alpha) {
    build_mai(tfs = tfs, gdp = gdpt,
              sel_alpha = sel_alpha, dfm_q = 1L, exclude_ids = c(AIG, "rt"),
              out_csv = file.path("cache", paste0("mai_", id, ".csv")),
              out_rds = file.path("cache", paste0("mai_", id, ".rds")))$mai
  }

  # ---- one model at one as_of, at one horizon ----------------------------------
  # horizon = "next" nowcasts the quarter AFTER the current one off the same MAI.
  # It needs no unpublished GDP (the U-MIDAS has no lagged-GDP regressor), but its
  # LEVEL chains off the current quarter's level, which is itself a nowcast -- so
  # the caller passes the headline's level as `prev_lvl` and the headline's growth
  # as `chain_qoq`, and the published next-quarter level and year-ended figure
  # inherit the headline's error. Bands come from the `next` block of the params.
  mk <- function(mai, gdpt, id, name, model, ci_path,
                 horizon = "current", prev_lvl = prev_level, chain_qoq = numeric(0)) {
    nc  <- nowcast_midas(mai, gdpt, prev_level = prev_lvl, model = model, qa_lag = 0L:1L,
                         horizon = horizon)
    ci  <- load_ci_params(ci_path)
    qoq <- as.numeric(nc$qoq_growth)
    # Interval params depend on the within-quarter information stage. A nowcast
    # built with 0 months of target-quarter data is a different estimator from one
    # built with 3 and does not get the same band. ci_params_for_stage() falls back
    # to pooled when a stage was too thin to calibrate, and is a no-op for the flat
    # legacy params v1 still uses.
    cp  <- ci_params_for_stage(ci, nc$n_months_in_quarter, horizon)
    b68 <- ci_level_band(qoq, prev_lvl, cp$bias_pp, cp$sd_pp, cp$z_68)
    b95 <- ci_level_band(qoq, prev_lvl, cp$bias_pp, cp$sd_pp, cp$z_95)

    # PUBLISH THE BIAS-CORRECTED POINT.
    #
    # ci_level_band centres the interval on (qoq - bias). Publishing the RAW qoq
    # alongside that interval meant the headline figure was not the centre of its
    # own range. On the now-removed stress spec this had become incoherent: its
    # bias was +0.34pp (t=4.9) against a 68% half-width of 0.28pp, so the offset
    # EXCEEDED the half-width and the published point necessarily fell OUTSIDE
    # its own interval. The headline has never had a significant bias, but the
    # correction stays wired up in case that changes.
    #
    # If the model demonstrably runs hot by a statistically significant margin,
    # the bias-corrected value is the better estimate — so that is what we
    # publish, and the interval is then centred on it by construction. The raw
    # model output is retained as qoq_growth_raw_pct for auditability.
    #
    # Where the bias is NOT significant, cp$bias_pp is 0 and this is a no-op:
    # the headline model currently publishes its raw output unchanged.
    qoq_adj <- qoq - cp$bias_pp
    level_adj <- if (is.na(prev_lvl)) NA_real_ else prev_lvl * (1 + qoq_adj / 100)

    list(model_id = id, model_name = name, target_quarter = nc$target_quarter,
         # "current" (the earliest quarter the ABS has not printed) or "next".
         horizon = nc$horizon, current_quarter = nc$current_quarter,
         gdp_chain_volume_millions = round(as.numeric(level_adj)),
         qoq_growth_pct = round(qoq_adj, 2),
         qoq_growth_raw_pct = round(qoq, 2),
         yoy_growth_pct = round(.compute_yoy(gdpt, qoq_adj, repo_root, chain_qoq), 2),
         ci_68_low = b68$low, ci_68_high = b68$high, ci_95_low = b95$low, ci_95_high = b95$high,
         n_months_in_quarter = nc$n_months_in_quarter,
         # which of the paper's per-stage models actually produced this figure:
         # "QA-UMIDAS" on a complete quarter, "UMIDAS-full" below it. The name
         # above is the family; this is the specific estimator on the day.
         estimator = nc$model,
         ci_basis = ci$basis, ci_n = cp$n, ci_sd_pp = cp$sd_pp, ci_bias_pp = cp$bias_pp,
         # Track-record disclosure, published in place of a probability interval.
         # The ci_* band fields above remain for the record but the site does not
         # render them as a confidence level -- centred on an uncorrected point,
         # the 68% band only achieved 41% coverage. See compute_ci_params_v2.R.
         err_mae_pp  = if (is.na(cp$mae_pp)) NULL else round(cp$mae_pp, 2),
         err_bias_pp = if (is.na(cp$bias_measured_pp)) NULL else round(cp$bias_measured_pp, 2),
         err_n       = cp$n,
         # which information stage's params were used ("pooled" if this stage was
         # too thin to calibrate; "flat" for legacy params). Surfaced so the site
         # can say what the band is conditioned on.
         ci_stage = cp$stage)
  }

  # ---- one Monday, both horizons ----------------------------------------------
  # The next-quarter figure is OPTIONAL: nowcast_midas() refuses the horizon when
  # the MAI has no month past the current quarter, which is the ordinary state for
  # the first weeks of a quarter. That refusal, and only that one, means "no
  # next-quarter nowcast this week"; anything else is a real failure and is
  # re-raised.
  run_monday <- function(m_i) {
    as_of_i <- as.Date(m_i)
    wide_i  <- .truncate_acc(wide_full, as_of_i)
    gdp_i   <- .truncate_gdp(gdp_full, as_of_i, gdp_lag = GDP_LAG)
    tfs_i   <- transform_panel(wide_i, "seed/panel_info.csv")
    ids_i   <- setdiff(names(wide_i), "date")
    has_i   <- rowSums(!is.na(as.matrix(wide_i[, ids_i]))) > 0
    dt_i    <- format(max(wide_i$date[has_i]), "%Y-%m")
    mai_i   <- mk_mai(tfs_i, gdp_i, "v2_qa_a10", 0.10)
    qa_i    <- mk(mai_i, gdp_i, "v2_qa_a10", "MAI to per-stage U-MIDAS", "qa", CI_QA)
    nq_i    <- tryCatch(
      mk(mai_i, gdp_i, "v2_qa_a10", "MAI to per-stage U-MIDAS", "qa", CI_QA,
         horizon = "next", prev_lvl = qa_i$gdp_chain_volume_millions,
         chain_qoq = qa_i$qoq_growth_pct),
      error = function(e) {
        msg <- conditionMessage(e)
        if (startsWith(msg, "nowcast_midas(): no MAI month beyond")) NULL else stop(e)
      })
    list(as_of = as_of_i, data_through = dt_i, current = qa_i, next_quarter = nq_i)
  }

  # The ABS release date that applies to a TARGET QUARTER, not to the run.
  #
  # `release_date` (latest.json's next_gdp_release_date) is the release of the
  # quarter the ABS has not printed yet, i.e. the quarter after the last row of
  # gdp_full. Every other quarter's release is that date stepped by whole
  # quarters, the ABS printing roughly 9 weeks after each quarter ends. Used only
  # for the x-axis of the evolution chart (days_until_release), never for model
  # logic, so a step of exactly three months is close enough.
  #
  # Deriving it from the target quarter rather than from the run matters as soon
  # as a run writes rows for two different quarters: the live weekly run's
  # current-quarter row is offset 0 and therefore unchanged, its next-quarter row
  # is one step out, and a backfill over past Mondays gets each quarter's OWN
  # release date instead of whichever one happens to be next today.
  .q_idx <- function(q) {
    p <- as.integer(strsplit(as.character(q), " Q", fixed = TRUE)[[1]])
    p[1] * 4L + p[2]
  }
  live_cur_q <- local({
    d <- seq(max(as.Date(gdp_full$date)), by = "3 months", length.out = 2L)[2L]
    sprintf("%d Q%d", as.integer(format(d, "%Y")), as.integer(format(d, "%m")) %/% 3L)
  })
  .release_for <- function(tq) {
    if (is.na(release_date)) return(release_date)
    off <- .q_idx(tq) - .q_idx(live_cur_q)
    if (off == 0L) release_date
    else seq(release_date, by = sprintf("%d months", 3L * off), length.out = 2L)[2L]
  }

  .vintage_row <- function(m_i, mdl, as_of_i, dt_i, rel) list(
    run_date = m_i, target_quarter = mdl$target_quarter,
    # "current" or "next". Rows written before 2026-09-12 have no horizon field;
    # read a missing field as "current".
    horizon = mdl$horizon,
    point = mdl$gdp_chain_volume_millions, qoq_growth_pct = mdl$qoq_growth_pct,
    days_until_release = if (is.na(rel)) NA_integer_ else as.integer(as_of_i - rel),
    ci_68_low = mdl$ci_68_low, ci_68_high = mdl$ci_68_high,
    ci_95_low = mdl$ci_95_low, ci_95_high = mdl$ci_95_high, data_through = dt_i)

  # Upsert on (run_date, target_quarter), not run_date alone: a Monday now carries
  # up to two rows, one per horizon, and they must not evict each other.
  .upsert <- function(vlog, row) {
    vlog <- Filter(function(r) !(identical(as.character(r$run_date), as.character(row$run_date)) &&
                                 identical(as.character(r$target_quarter), as.character(row$target_quarter))),
                   vlog)
    c(vlog, list(row))
  }

  .rows_for <- function(m_i, res) {
    rows <- list(.vintage_row(m_i, res$current, res$as_of, res$data_through,
                              .release_for(res$current$target_quarter)))
    if (!is.null(res$next_quarter))
      rows <- c(rows, list(.vintage_row(m_i, res$next_quarter, res$as_of, res$data_through,
                                        .release_for(res$next_quarter$target_quarter))))
    rows
  }

  vintage_path <- file.path(repo_root, "data", "vintages_v2.json")
  vlog <- if (file.exists(vintage_path))
    jsonlite::fromJSON(vintage_path, simplifyVector = FALSE) else list()

  # Append-only vintage log. The evolution chart must show what was ACTUALLY
  # published each Monday, so we NEVER recompute past Mondays — a from-scratch
  # reconstruction lets data revisions or panel changes silently rewrite history
  # (the 2026-06-15 non_res_ba leak extended the DFM window to 1965 and moved
  # every past point). We compute ONLY the latest Monday and upsert it into the
  # git-tracked log at data/vintages_v2.json; earlier Mondays are read verbatim.
  latest_m <- tail(mondays, 1)

  if (backfill_next) {
    # Next-quarter rows only. Existing rows -- current-quarter ones, and any row
    # with no horizon field, which is the same thing -- are read verbatim and
    # written back untouched. Nothing here writes a headline.
    cat(sprintf("[backfill_next] next-quarter rows only, %d Mondays\n", length(mondays)))
    added <- 0L
    for (m_i in mondays) {
      res <- run_monday(m_i)
      if (is.null(res$next_quarter)) {
        cat(sprintf("  [as_of %s] no MAI month past %s -- skipped\n",
                    m_i, res$current$target_quarter))
        next
      }
      nrow_i <- .vintage_row(m_i, res$next_quarter, res$as_of, res$data_through,
                             .release_for(res$next_quarter$target_quarter))
      cat(sprintf("  [as_of %s] NEXT %s QoQ %+.2f%% (%d month(s) of data)\n",
                  m_i, res$next_quarter$target_quarter, res$next_quarter$qoq_growth_pct,
                  res$next_quarter$n_months_in_quarter))
      vlog  <- .upsert(vlog, nrow_i)
      added <- added + 1L
    }
    vlog <- .sort_vlog(vlog)
    jsonlite::write_json(vlog, vintage_path, pretty = TRUE, auto_unbox = TRUE, na = "null")
    cat(sprintf("[backfill_next] %d next-quarter row(s) upserted into %s\n",
                added, normalizePath(vintage_path, mustWork = FALSE)))
    # Refresh ONLY the vintages array of the published payload, in place. The
    # round trip is byte-exact on everything else (verified 2026-09-12), so the
    # headline this backfill must not touch stays exactly as it was published.
    latest_path <- file.path(repo_root, "data", "latest_v2.json")
    if (file.exists(latest_path)) {
      lj <- jsonlite::fromJSON(latest_path, simplifyVector = FALSE)
      lj$vintages <- vlog
      cat(as.character(jsonlite::toJSON(.nulls_to_na(lj), pretty = TRUE,
                                        auto_unbox = TRUE, na = "null", digits = NA)),
          file = latest_path)
      cat(sprintf("[backfill_next] refreshed the vintages array of %s (headline untouched)\n",
                  normalizePath(latest_path, mustWork = FALSE)))
    }
    return(invisible(vlog))
  }

  res_m    <- run_monday(latest_m)
  as_of    <- res_m$as_of
  dt_m     <- res_m$data_through
  cat(sprintf("[as_of %s] data through %s\n", latest_m, dt_m))
  qa       <- res_m$current
  nq       <- res_m$next_quarter
  headline <- qa
  data_through <- dt_m

  if (rebuild_vintages) {
    # Deliberate full rebuild (see the roxygen note on the argument). Recompute
    # every Monday in the cadence under the CURRENT model and discard the old log.
    cat(sprintf("[rebuild_vintages] recomputing all %d Mondays -- this REPLACES published history\n",
                length(mondays)))
    vlog <- list()
    for (m_i in mondays) {
      res_i <- if (identical(m_i, latest_m)) res_m else run_monday(m_i)
      cat(sprintf("  [as_of %s] %s QoQ %+.2f%%%s\n", m_i, res_i$current$target_quarter,
                  res_i$current$qoq_growth_pct,
                  if (is.null(res_i$next_quarter)) "" else
                    sprintf("   next %s QoQ %+.2f%%", res_i$next_quarter$target_quarter,
                            res_i$next_quarter$qoq_growth_pct)))
      for (row in .rows_for(m_i, res_i)) vlog <- .upsert(vlog, row)
    }
  } else {
    # upsert by (run_date, target_quarter); never touch prior Mondays
    for (row in .rows_for(latest_m, res_m)) vlog <- .upsert(vlog, row)
  }
  vlog <- .sort_vlog(vlog)
  jsonlite::write_json(vlog, vintage_path, pretty = TRUE, auto_unbox = TRUE, na = "null")
  vintages <- vlog

  v1 <- if (!is.null(jlatest)) list(
    model_name = "v1 (13-series DFM)", target_quarter = jlatest$target_quarter,
    qoq_growth_pct = jlatest$nowcast$qoq_growth_pct, yoy_growth_pct = jlatest$nowcast$yoy_growth_pct,
    gdp_chain_volume_millions = jlatest$nowcast$gdp_chain_volume_millions, source = "data/latest.json") else NULL

  out <- list(
    # The data vintage = the latest Monday (matches the production cron), not the
    # wall-clock time this script happened to run.
    generated_at   = paste0(latest_m, "T02:00:00Z"),
    schema         = "v2-staged-2",
    as_of          = latest_m,
    target_quarter = headline$target_quarter,
    data_through   = data_through,
    prev_level     = list(value = round(prev_level), date = as.character(pl$date), source = pl$source),
    # `next_quarter` is absent, not null, in the weeks when the MAI has no month
    # past the current quarter. The /v2 page reads only `headline`.
    models         = if (is.null(nq)) list(headline = headline)
                     else list(headline = headline, next_quarter = nq),
    vintages       = vintages,
    v1_comparison  = v1,
    note           = "STAGED v2 emit (parallel to live latest.json). Monday cadence; headline = latest Monday. Pending James approval."
  )
  out_path <- file.path(repo_root, "data", "latest_v2.json")
  jsonlite::write_json(out, out_path, pretty = TRUE, auto_unbox = TRUE, na = "null")
  cat(sprintf("\nWROTE %s\n", normalizePath(out_path, mustWork = FALSE)))
  for (v in vintages) cat(sprintf("  vintage %s (%s, %s): QoQ %+.2f%%\n", v$run_date,
                                  v$target_quarter,
                                  if (is.null(v$horizon)) "current" else v$horizon,
                                  v$qoq_growth_pct))
  cat(sprintf("  HEADLINE (%s) %s: QoQ %+.2f%%\n",
              latest_m, headline$target_quarter, headline$qoq_growth_pct))
  if (is.null(nq)) cat("  NEXT QUARTER: none yet (no MAI month past the current quarter)\n")
  else cat(sprintf("  NEXT QUARTER (%s) %s: QoQ %+.2f%% (%d month(s) of data)\n",
                   latest_m, nq$target_quarter, nq$qoq_growth_pct, nq$n_months_in_quarter))
  invisible(out)
}

if (sys.nframe() == 0L) emit_v2_json()
