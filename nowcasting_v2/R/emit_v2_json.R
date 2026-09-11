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
# nowcast. Those three come from data/gdp.json (the latest vintage), NOT from
# `gdp` (data_raw/rt_dgdp_qtr.csv): since 2026-09 that file holds the ABS's
# initial estimate of each quarter, which is what the model is estimated on, but
# year-ended growth is a comparison with the level a year ago and every other
# year-ended figure on the site is quoted on the latest vintage (gdp.json's own
# yoy_pct, the RBA comparison in gen_performance_v2.py). Compounding initial
# estimates here would move the headline "vs a year ago" by ~0.2pp for no model
# reason. `gdp` still fixes WHICH three quarters (the ones before the target).
# Falls back to `gdp`'s own values, with a warning, if gdp.json lacks them.
.compute_yoy <- function(gdp, nowcast_qoq, repo_root = "..") {
  g <- gdp[order(as.Date(gdp$date)), ]
  last_date <- max(as.Date(g$date))
  # first-of-month dates, so stepping back by whole months is exact
  qdates <- rev(seq(last_date, by = "-3 months", length.out = 3L))
  want <- sprintf("%d Q%d", as.integer(format(qdates, "%Y")),
                  as.integer(format(qdates, "%m")) %/% 3L)
  latest <- tryCatch(jsonlite::fromJSON(file.path(repo_root, "data", "gdp.json"))$series,
                     error = function(e) NULL)
  last3 <- if (!is.null(latest) && all(want %in% latest$quarter)) {
    latest$qoq_pct[match(want, latest$quarter)]
  } else {
    warning(sprintf(paste("emit_v2_json(): data/gdp.json lacks %s; year-ended growth",
                          "compounds the initial-estimate file instead."),
                    paste(want, collapse = ", ")), call. = FALSE)
    tail(g$value, 3L)
  }
  (prod(1 + c(last3, nowcast_qoq) / 100) - 1) * 100
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
emit_v2_json <- function(repo_root = "..", mondays = NULL, rebuild_vintages = FALSE) {
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

  # ---- one model at one as_of: truncate -> transform -> build_mai -> nowcast ----
  mk <- function(tfs, gdpt, id, name, sel_alpha, model, ci_path) {
    # Exclude AiG (dead) and rt (old Retail Trade, superseded by MHSI =
    # household_spending, which the model already uses; rt was never selected).
    # gdp = gdpt: the Wald selection must see only GDP released by this as_of.
    # Without it build_mai reads the full rt_dgdp_qtr.csv and the selection is
    # supervised on quarters that had not yet been published.
    mai <- build_mai(tfs = tfs, gdp = gdpt,
                     sel_alpha = sel_alpha, dfm_q = 1L, exclude_ids = c(AIG, "rt"),
                     out_csv = file.path("cache", paste0("mai_", id, ".csv")),
                     out_rds = file.path("cache", paste0("mai_", id, ".rds")))$mai
    nc  <- nowcast_midas(mai, gdpt, prev_level = prev_level, model = model, qa_lag = 0L:1L)
    ci  <- load_ci_params(ci_path)
    qoq <- as.numeric(nc$qoq_growth)
    # Interval params depend on the within-quarter information stage. A nowcast
    # built with 0 months of target-quarter data is a different estimator from one
    # built with 3 and does not get the same band. ci_params_for_stage() falls back
    # to pooled when a stage was too thin to calibrate, and is a no-op for the flat
    # legacy params v1 still uses.
    cp  <- ci_params_for_stage(ci, nc$n_months_in_quarter)
    b68 <- ci_level_band(qoq, prev_level, cp$bias_pp, cp$sd_pp, cp$z_68)
    b95 <- ci_level_band(qoq, prev_level, cp$bias_pp, cp$sd_pp, cp$z_95)

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
    level_adj <- if (is.na(prev_level)) NA_real_ else prev_level * (1 + qoq_adj / 100)

    list(model_id = id, model_name = name, target_quarter = nc$target_quarter,
         gdp_chain_volume_millions = round(as.numeric(level_adj)),
         qoq_growth_pct = round(qoq_adj, 2),
         qoq_growth_raw_pct = round(qoq, 2),
         yoy_growth_pct = round(.compute_yoy(gdpt, qoq_adj, repo_root), 2),
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

  # Append-only vintage log. The evolution chart must show what was ACTUALLY
  # published each Monday, so we NEVER recompute past Mondays — a from-scratch
  # reconstruction lets data revisions or panel changes silently rewrite history
  # (the 2026-06-15 non_res_ba leak extended the DFM window to 1965 and moved
  # every past point). We compute ONLY the latest Monday and upsert it into the
  # git-tracked log at data/vintages_v2.json; earlier Mondays are read verbatim.
  latest_m <- tail(mondays, 1)
  as_of  <- as.Date(latest_m)
  wide_m <- .truncate_acc(wide_full, as_of)
  gdp_m  <- .truncate_gdp(gdp_full, as_of, gdp_lag = GDP_LAG)
  tfs_m  <- transform_panel(wide_m, "seed/panel_info.csv")
  ids    <- setdiff(names(wide_m), "date")
  has_any <- rowSums(!is.na(as.matrix(wide_m[, ids]))) > 0
  dt_m   <- format(max(wide_m$date[has_any]), "%Y-%m")
  cat(sprintf("[as_of %s] data through %s\n", latest_m, dt_m))

  qa       <- mk(tfs_m, gdp_m, "v2_qa_a10", "MAI to per-stage U-MIDAS", 0.10, "qa", CI_QA)
  headline <- qa
  data_through <- dt_m

  this_vintage <- list(
    run_date = latest_m, target_quarter = qa$target_quarter,
    point = qa$gdp_chain_volume_millions, qoq_growth_pct = qa$qoq_growth_pct,
    days_until_release = if (is.na(release_date)) NA_integer_ else as.integer(as_of - release_date),
    ci_68_low = qa$ci_68_low, ci_68_high = qa$ci_68_high,
    ci_95_low = qa$ci_95_low, ci_95_high = qa$ci_95_high, data_through = dt_m)

  vintage_path <- file.path(repo_root, "data", "vintages_v2.json")
  vlog <- if (file.exists(vintage_path))
    jsonlite::fromJSON(vintage_path, simplifyVector = FALSE) else list()

  if (rebuild_vintages) {
    # Deliberate full rebuild (see the roxygen note on the argument). Recompute
    # every Monday in the cadence under the CURRENT model and discard the old log.
    cat(sprintf("[rebuild_vintages] recomputing all %d Mondays -- this REPLACES published history\n",
                length(mondays)))
    vlog <- list()
    for (m_i in mondays) {
      if (identical(m_i, latest_m)) { vlog[[length(vlog) + 1L]] <- this_vintage; next }
      as_of_i  <- as.Date(m_i)
      wide_i   <- .truncate_acc(wide_full, as_of_i)
      gdp_i    <- .truncate_gdp(gdp_full, as_of_i, gdp_lag = GDP_LAG)
      tfs_i    <- transform_panel(wide_i, "seed/panel_info.csv")
      ids_i    <- setdiff(names(wide_i), "date")
      has_i    <- rowSums(!is.na(as.matrix(wide_i[, ids_i]))) > 0
      qa_i     <- mk(tfs_i, gdp_i, "v2_qa_a10", "MAI to per-stage U-MIDAS", 0.10, "qa", CI_QA)
      cat(sprintf("  [as_of %s] %s QoQ %+.2f%%\n", m_i, qa_i$target_quarter, qa_i$qoq_growth_pct))
      vlog[[length(vlog) + 1L]] <- list(
        run_date = m_i, target_quarter = qa_i$target_quarter,
        point = qa_i$gdp_chain_volume_millions, qoq_growth_pct = qa_i$qoq_growth_pct,
        days_until_release = if (is.na(release_date)) NA_integer_ else as.integer(as_of_i - release_date),
        ci_68_low = qa_i$ci_68_low, ci_68_high = qa_i$ci_68_high,
        ci_95_low = qa_i$ci_95_low, ci_95_high = qa_i$ci_95_high,
        data_through = format(max(wide_i$date[has_i]), "%Y-%m"))
    }
  } else {
    # upsert by run_date (idempotent same-day re-runs); never touch prior Mondays
    vlog <- Filter(function(r) !identical(as.character(r$run_date), latest_m), vlog)
    vlog[[length(vlog) + 1L]] <- this_vintage
  }
  vlog <- vlog[order(vapply(vlog, function(r) as.character(r$run_date), character(1)))]
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
    models         = list(headline = headline),
    vintages       = vintages,
    v1_comparison  = v1,
    note           = "STAGED v2 emit (parallel to live latest.json). Monday cadence; headline = latest Monday. Pending James approval."
  )
  out_path <- file.path(repo_root, "data", "latest_v2.json")
  jsonlite::write_json(out, out_path, pretty = TRUE, auto_unbox = TRUE, na = "null")
  cat(sprintf("\nWROTE %s\n", normalizePath(out_path, mustWork = FALSE)))
  for (v in vintages) cat(sprintf("  vintage %s (%s): QoQ %+.2f%%\n", v$run_date, v$target_quarter, v$qoq_growth_pct))
  cat(sprintf("  HEADLINE (%s) %s: QoQ %+.2f%%\n",
              latest_m, headline$target_quarter, headline$qoq_growth_pct))
  invisible(out)
}

if (sys.nframe() == 0L) emit_v2_json()
