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
# Two models (James 2026-06-10): headline = qa_a05 (precision), stress = umidas_a20
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
CI_UMIDAS <- "../pipeline/seed/ci_params_v2_umidas.json"

# Accurate publication lags (days from END of reference month). Corrects the
# coarse backtest map (.lag_for_id) after the 2026-06-11 Fable review, which showed
# the lag-45 ABS-activity block and lag-30 financial block withheld data that was
# actually public (MHSI April released 28 May; daily AGS yields/spreads/BBSW are
# available within days). Used for the LIVE as-of truncation here and mirrored in
# the indicators release-date generator. NB: the CI params remain calibrated on
# the backtest's coarser lags — a known follow-up to recalibrate.
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

# yoy from the last 3 actual QoQ growths + the target-quarter nowcast.
.compute_yoy <- function(gdp, nowcast_qoq) {
  g <- gdp[order(as.Date(gdp$date)), ]
  last3 <- tail(g$value, 3L)
  (prod(1 + c(last3, nowcast_qoq) / 100) - 1) * 100
}

emit_v2_json <- function(repo_root = "..", mondays = NULL) {
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
    mai <- build_mai(tfs = tfs, sel_alpha = sel_alpha, dfm_q = 1L, exclude_ids = AIG,
                     out_csv = file.path("cache", paste0("mai_", id, ".csv")),
                     out_rds = file.path("cache", paste0("mai_", id, ".rds")))$mai
    nc  <- nowcast_midas(mai, gdpt, prev_level = prev_level, model = model, qa_lag = 0L:1L)
    ci  <- load_ci_params(ci_path)
    qoq <- as.numeric(nc$qoq_growth)
    b68 <- ci_level_band(qoq, prev_level, ci$qoq_bias_pp, ci$qoq_sd_pp, ci$z_68)
    b95 <- ci_level_band(qoq, prev_level, ci$qoq_bias_pp, ci$qoq_sd_pp, ci$z_95)
    list(model_id = id, model_name = name, target_quarter = nc$target_quarter,
         gdp_chain_volume_millions = round(as.numeric(nc$nowcast_level)),
         qoq_growth_pct = round(qoq, 2), yoy_growth_pct = round(.compute_yoy(gdpt, qoq), 2),
         ci_68_low = b68$low, ci_68_high = b68$high, ci_95_low = b95$low, ci_95_high = b95$high,
         n_months_in_quarter = nc$n_months_in_quarter,
         ci_basis = ci$basis, ci_n = ci$n, ci_sd_pp = ci$qoq_sd_pp, ci_bias_pp = ci$qoq_bias_pp)
  }

  latest_m <- tail(mondays, 1)
  vintages <- list(); headline <- NULL; stress <- NULL; data_through <- NA

  for (m in mondays) {
    as_of  <- as.Date(m)
    wide_m <- .truncate_acc(wide_full, as_of)
    gdp_m  <- .truncate_gdp(gdp_full, as_of, gdp_lag = GDP_LAG)
    tfs_m  <- transform_panel(wide_m, "seed/panel_info.csv")
    ids    <- setdiff(names(wide_m), "date")
    has_any <- rowSums(!is.na(as.matrix(wide_m[, ids]))) > 0
    dt_m   <- format(max(wide_m$date[has_any]), "%Y-%m")
    cat(sprintf("[as_of %s] data through %s\n", m, dt_m))

    qa <- mk(tfs_m, gdp_m, "v2_qa_a05", "MAI to QA U-MIDAS (precision)", 0.05, "qa", CI_QA)
    vintages[[length(vintages) + 1L]] <- list(
      run_date = m, target_quarter = qa$target_quarter,
      point = qa$gdp_chain_volume_millions, qoq_growth_pct = qa$qoq_growth_pct,
      days_until_release = if (is.na(release_date)) NA_integer_ else as.integer(as_of - release_date),
      ci_68_low = qa$ci_68_low, ci_68_high = qa$ci_68_high,
      ci_95_low = qa$ci_95_low, ci_95_high = qa$ci_95_high, data_through = dt_m)

    if (identical(m, latest_m)) {
      headline <- qa
      stress   <- mk(tfs_m, gdp_m, "v2_umidas_a20", "MAI to full U-MIDAS (stress / big-events)", 0.20, "umidas", CI_UMIDAS)
      data_through <- dt_m
    }
  }

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
    models         = list(headline = headline, stress = stress),
    vintages       = vintages,
    v1_comparison  = v1,
    note           = "STAGED v2 emit (parallel to live latest.json). Monday cadence; headline = latest Monday. Pending James approval."
  )
  out_path <- file.path(repo_root, "data", "latest_v2.json")
  jsonlite::write_json(out, out_path, pretty = TRUE, auto_unbox = TRUE, na = "null")
  cat(sprintf("\nWROTE %s\n", normalizePath(out_path, mustWork = FALSE)))
  for (v in vintages) cat(sprintf("  vintage %s (%s): QoQ %+.2f%%\n", v$run_date, v$target_quarter, v$qoq_growth_pct))
  cat(sprintf("  HEADLINE (%s) %s: QoQ %+.2f%% | STRESS: QoQ %+.2f%%\n",
              latest_m, headline$target_quarter, headline$qoq_growth_pct, stress$qoq_growth_pct))
  invisible(out)
}

if (sys.nframe() == 0L) emit_v2_json()
