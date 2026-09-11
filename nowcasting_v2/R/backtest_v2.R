# backtest_v2.R
# Phase 6.1 -- real-time (pseudo-real-time / POOS) backtest of nowcast v2.
#
# For each quarter-end as-of date over the backtest window we:
#   1. Truncate every raw panel series to what would have been published by that
#      as-of date (each obs available at  ref-period-END + per-series lag).
#   2. transform_panel() the truncated panel (per-series centring/scaling over the
#      *observed* span -> real-time faithful: no future data leaks in).
#   3. build_mai() on the truncated/transformed panel, with the targeted-predictor
#      SELECTION FIXED to the full-sample selection (standard pseudo-real-time
#      simplification) -- only the DFM is re-estimated each step. The fixed set is
#      intersected with the series available at the as-of date, so early as-of
#      dates that predate (e.g.) the NAB/yield series simply drop them.
#   4. nowcast_midas() the target quarter and record forecast vs the rt_dgdp_qtr
#      actual, qoq_error, direction_correct. Also nowcast the NEXT quarter
#      (horizon = "next") whenever it already has a MAI month, into the
#      next_target_quarter / qoq_growth_forecast_next / qoq_actual_next /
#      n_months_in_next_quarter columns (all NA when it does not).
#
# This file is harness GLUE ONLY: all estimation math is the v2/RBA code reused
# via build_mai() + nowcast_midas(). Fail loud: a step that errors at an as-of
# date is logged and SKIPPED (never a fabricated nowcast).
#
# Writes cache/backtest_v2/backtest_results.csv with v1-comparable columns.

suppressWarnings(suppressMessages({
  here <- tryCatch(dirname(sys.frame(1)$ofile), error = function(e) NA)
}))
if (is.na(here) || !nzchar(here)) here <- "R"
source(file.path(here, "_setup.R"))
source(file.path(here, "build_panel.R"))     # not strictly needed; for parity
source(file.path(here, "transform_panel.R"))
source(file.path(here, "build_mai.R"))
source(file.path(here, "nowcast_midas.R"))

suppressMessages({
  library(dplyr)
  library(readr)
  library(lubridate)
})

# ---------------------------------------------------------------------------
# Per-series publication-lag map (days, measured from the END of the reference
# period -- the same end-of-period convention as v1's 04_release_calendar.R).
# Source -> lag:
#   labour (ABS 6202)        ~ +15d   (Labour Force ~2wk after ref month)
#   ABS activity (rt,export) ~ +45d   (retail/trade ~6wk after ref month)
#   RBA monthly (credit/rates) +30d   (RBA aggregates ~end of following month)
#   NAB business survey       ~ +10d  (2nd Tue of following month ~8-14d)
#   ANZ (job ads / sentiment) ~ +10d  (early following month)
#   GDP (target, quarterly)   ~ +60d  (National Accounts ~9wk after quarter-end)
# These mirror v1 to keep the head-to-head comparable.
# ---------------------------------------------------------------------------
.lag_for_id <- function(id) {
  labour <- c("emp","ft_emp","pt_emp","ue","ud","hours")
  abs_act <- c("rt","export","household_spending","building_app")
  rba_m  <- c("credit","credit_housing","credit_business","credit_card",
              "fcmygbag3","fcmygbag5","fcmygbag10",
              "scrigbag3","scrigbag5","scrigbag10","firmmbab90")
  nab    <- c("nab_conf","nab_cond","nab_trade","nab_profit","nab_emp",
              "nab_forward","nab_stocks","nab_cu")
  anz    <- c("anz_ads","anz_sent")
  aig    <- c("aig_pmi","aig_pci","aig_psi")   # released ~1st business day of following month
  if (id %in% labour)  return(15L)
  if (id %in% abs_act) return(45L)
  if (id %in% rba_m)   return(30L)
  if (id %in% nab)     return(10L)
  if (id %in% anz)     return(10L)
  if (id %in% aig)     return(5L)
  # Westpac consumer sentiment is released MID its own reference month, so it is
  # available ~15 days BEFORE month-end (negative lag from ref-period-END).
  if (id == "wmi_sent") return(-15L)
  # default: 30d (RBA-monthly-like)
  30L
}

# Accurate, HISTORICALLY-FAITHFUL publication lags for CI calibration. Matches
# the live emit's .LAG_ACC EXCEPT household_spending = 35 (not 28): ABS published
# the MHSI ~35-38d after the reference month for the entire calibration window
# (post-COVID .. 2026 Q1). The faster ~28d schedule only began with the Apr-2026
# edition, which is AFTER this window, so 35 is correct here and avoids the
# look-ahead leakage Fable caught (28d falsely surfaced month-2 MHSI at quarter
# ends). NB: if the calibration window ever extends past Apr 2026, MHSI must
# become month-aware (28d only for non-quarter-month editions). At quarter-end
# as-of dates this map yields the SAME information set as the coarse .lag_for_id,
# so the calibrated bands should match the shipped ones (modulo panel revisions).
.LAG_ACC_BT <- c(emp = 15, ft_emp = 15, pt_emp = 15, ue = 15, ud = 15, hours = 15,
                 household_spending = 35, rt = 33, export = 35, building_app = 33,
                 credit = 30, credit_housing = 30, credit_business = 30, credit_card = 30,
                 fcmygbag3 = 2, fcmygbag5 = 2, fcmygbag10 = 2,
                 scrigbag3 = 2, scrigbag5 = 2, scrigbag10 = 2, firmmbab90 = 2,
                 nab_conf = 10, nab_cond = 10, nab_trade = 10, nab_profit = 10,
                 nab_emp = 10, nab_forward = 10, nab_stocks = 10, nab_cu = 10,
                 anz_ads = 10, anz_sent = 10, wmi_sent = -15)
.lag_acc <- function(id) if (id %in% names(.LAG_ACC_BT)) .LAG_ACC_BT[[id]] else 30L

# Truncate the wide raw panel to data published by as_of_date.
# `date` column is first-of-(reference)-month. Reference period END = end of that
# month; an obs is available when end-of-month + lag <= as_of.
.truncate_panel <- function(wide, as_of_date, lag_fn = .lag_for_id) {
  as_of_date <- as.Date(as_of_date)
  ids <- setdiff(names(wide), "date")
  ref_end <- lubridate::ceiling_date(wide$date, unit = "month") - lubridate::days(1)
  out <- wide
  for (id in ids) {
    lag <- lag_fn(id)
    rel <- ref_end + lubridate::days(lag)
    out[[id]][rel > as_of_date] <- NA_real_
  }
  out
}

# Truncate the quarterly GDP growth series the same way (target/estimation).
# GDP `date` is first-of-month of the quarter's last month (Mar/Jun/Sep/Dec-01).
.truncate_gdp <- function(gdp, as_of_date, gdp_lag = 60L) {
  as_of_date <- as.Date(as_of_date)
  ref_end <- lubridate::ceiling_date(gdp$date, unit = "quarter") - lubridate::days(1)
  rel <- ref_end + lubridate::days(gdp_lag)
  gdp[rel <= as_of_date, , drop = FALSE]
}

# Quarter-end first-of-month label for a date (03/06/09/12-01).
.q_label <- function(d) {
  yr <- as.integer(format(d, "%Y")); mo <- as.integer(format(d, "%m"))
  qi <- (mo - 1L) %/% 3L
  as.Date(sprintf("%04d-%02d-01", yr, qi * 3L + 3L))
}
.q_name <- function(qend) {
  yr <- as.integer(format(qend, "%Y")); q <- as.integer(format(qend, "%m")) / 3L
  sprintf("%d Q%d", yr, q)
}

# ---------------------------------------------------------------------------
# Main backtest driver.
# ---------------------------------------------------------------------------
backtest_v2 <- function(panel_rds      = "cache/panel_vintage_latest.rds",
                        panel_info_csv = "seed/panel_info.csv",
                        gdp_csv        = "data_raw/rt_dgdp_qtr.csv",
                        out_csv        = "cache/backtest_v2/backtest_results.csv",
                        start_year     = 2012L,
                        as_of_freq     = c("quarter_end", "weekly"),  # "weekly" = Monday cadence,
                                                         # required for per-stage CI calibration
                        gdp_lag        = 60L,
                        model          = c("qa", "umidas"),
                        exclude_ids    = character(0),   # sweep: drop these from the candidate set
                        sel_alpha      = 0.10,           # sweep: targeted-predictor selection threshold
                        dfm_q          = 1L,             # sweep: number of dynamic factors in the MAI
                        covid_dummies  = TRUE,           # spec lever: COVID dummies in selection (FALSE = drop)
                        qa_lag         = 0L:1L,          # sweep: QA quarterly lag in nowcast_midas
                        lag_fn         = .lag_for_id,    # publication lags; pass .lag_acc for CI calibration
                        force_full_selection = NULL,     # if set, USE this exact fixed selection (bypass the Wald gate) -- e.g. to force-include a series the gate rejects
                        recursive_selection = TRUE,      # TRUE = re-run the Wald gate at EVERY as-of on the
                                                         # truncated panel, exactly as production does.
                                                         # FALSE = the old behaviour: fix the selection once on
                                                         # the FULL sample and force it at every historical
                                                         # as-of. That is a look-ahead leak -- the gate sees the
                                                         # GDP outcomes of the quarters it is about to
                                                         # "nowcast", so a series that only cleared the
                                                         # threshold because of (say) 2020Q2 is present in the
                                                         # MAI for 2015. Errors come out smaller than any
                                                         # real-time analyst could have achieved, and those
                                                         # errors are what calibrate the published CI bands.
                                                         # Forced to FALSE when force_full_selection is set.
                        verbose        = TRUE) {
  model      <- match.arg(model)
  as_of_freq <- match.arg(as_of_freq)

  t0 <- Sys.time()
  wide_full <- readRDS(panel_rds)
  gdp_full  <- readr::read_csv(gdp_csv, show_col_types = FALSE)
  gdp_full$date <- as.Date(gdp_full$date)
  gdp_full <- gdp_full[order(gdp_full$date), ]

  # ---- Fix the targeted-predictor selection ONCE on the full sample ----
  # Build the full-sample tfs FROM THIS BACKTEST'S panel_rds (not the hardcoded
  # cache/panel_vintage_latest.rds default inside build_mai) so the sweep can vary
  # the panel. exclude_ids/sel_alpha/dfm_q are honoured here so each variant's
  # fixed selection is computed on that variant's candidate set.
  if (!is.null(force_full_selection)) recursive_selection <- FALSE

  fixed_selection <- NULL
  if (recursive_selection) {
    cat("Targeted-predictor selection: RECURSIVE (re-run at every as-of, matches production)\n")
  } else {
    if (verbose) cat("Fixing full-sample targeted-predictor selection...\n")
    tfs_full <- transform_panel(wide_full, panel_info_csv)
    full_sel_res <- build_mai(tfs = tfs_full, panel_info_csv = panel_info_csv,
                              gdp_csv = gdp_csv, out_csv = NULL, out_rds = NULL,
                              exclude_ids = exclude_ids, sel_alpha = sel_alpha,
                              dfm_q = dfm_q, covid_dummies = covid_dummies,
                              verbose_dfm = FALSE)
    fixed_selection <- full_sel_res$diagnostics$selected
    if (!is.null(force_full_selection)) {
      fixed_selection <- force_full_selection
      cat(sprintf("[force_full_selection] overriding Wald gate with %d series\n", length(fixed_selection)))
    }
    cat(sprintf("Fixed selection (%d series, LOOK-AHEAD: full-sample): %s\n",
                length(fixed_selection), paste(fixed_selection, collapse = ", ")))
  }

  # ---- As-of dates: quarter-ends from start_year to latest ----
  # Build from quarter-START first-of-month dates (Jan/Apr/Jul/Oct-01, which are
  # unambiguous) then take each quarter's END. NB: seq(..., by="3 months") from a
  # day-31 anchor silently overshoots short months (Mar-31 + 3m -> Jul-01), which
  # previously dropped every Q2 as-of date; quarter-starts avoid that.
  last_data <- max(wide_full$date)
  q_starts <- seq(as.Date(sprintf("%d-01-01", start_year)),
                  lubridate::floor_date(last_data, "quarter") +
                    months(3),   # allow one quarter past last monthly obs
                  by = "3 months")
  as_of_dates <- if (as_of_freq == "quarter_end") {
    lubridate::ceiling_date(q_starts, "quarter") - lubridate::days(1)
  } else {
    # Weekly (Monday) grid -- the cadence production actually publishes on.
    # Quarter-end as-ofs all land at the SAME within-quarter information stage
    # (jt = 2 for every one of them), so a band calibrated on them is calibrated
    # at one stage and then applied at jt = 0..3. Walking Mondays covers every
    # stage the site actually publishes, and multiplies n by ~13.
    first_mon <- as.Date(sprintf("%d-01-01", start_year))
    while (as.integer(format(first_mon, "%u")) != 1L) first_mon <- first_mon + 1
    seq(first_mon, Sys.Date(), by = "week")
  }
  as_of_dates <- as_of_dates[as_of_dates <= Sys.Date()]
  as_of_dates <- sort(unique(as_of_dates))

  cat(sprintf("Backtest window: %s .. %s  (%d as-of dates, freq = %s)\n",
              as.character(min(as_of_dates)), as.character(max(as_of_dates)),
              length(as_of_dates), as_of_freq))

  rows <- list()
  skipped <- list()

  for (as_of in as_of_dates) {
    as_of <- as.Date(as_of, origin = "1970-01-01")
    res <- tryCatch({
      # 1. truncate raw panel + GDP to as-of
      wide_t <- .truncate_panel(wide_full, as_of, lag_fn = lag_fn)
      gdp_t  <- .truncate_gdp(gdp_full, as_of, gdp_lag = gdp_lag)

      # drop all-NA columns (series not yet started as of this date)
      ids <- setdiff(names(wide_t), "date")
      keep_ids <- ids[vapply(wide_t[ids], function(x) any(!is.na(x)), logical(1))]
      # also drop columns too short to transform (need >= ~3 obs after diff)
      keep_ids <- keep_ids[vapply(wide_t[keep_ids],
                                  function(x) sum(!is.na(x)) >= 6L, logical(1))]
      wide_t <- wide_t[, c("date", keep_ids), drop = FALSE]

      # trim trailing all-NA monthly rows (after truncation)
      anyobs <- apply(wide_t[keep_ids], 1, function(r) any(!is.na(r)))
      wide_t <- wide_t[which(anyobs)[1]:max(which(anyobs)), , drop = FALSE]

      # 2. transform truncated panel
      tfs_t <- transform_panel(wide_t, panel_info_csv)

      # 3. build MAI with FIXED selection (intersect w/ available).
      # Drop forced-selection series that are too SHORT at this as-of date to
      # be estimated stably (the DFM goes non-conformable on <~24 monthly obs,
      # e.g. the yield/spread series in 2013-14). This keeps the date in the
      # backtest on a slightly smaller selection rather than skipping it.
      # Recursive: let build_mai run its own Wald gate on the truncated panel
      # (sel_t = NULL -> force_selected = NULL). Non-recursive: intersect the
      # fixed set with series long enough to estimate stably at this as-of.
      sel_t <- if (is.null(fixed_selection)) NULL else fixed_selection[
        vapply(fixed_selection, function(id)
          id %in% names(tfs_t) && sum(!is.na(tfs_t[[id]])) >= 24L, logical(1))]
      # gdp = gdp_t (as-of truncated), not the full gdp_csv: the Wald ranking now
      # also fixes the DFM2 anchor order, so it must not see unreleased quarters.
      mai_res <- build_mai(tfs = tfs_t, panel_info_csv = panel_info_csv,
                           gdp = gdp_t, out_csv = NULL, out_rds = NULL,
                           force_selected = sel_t, exclude_ids = exclude_ids,
                           sel_alpha = sel_alpha, dfm_q = dfm_q,
                           covid_dummies = covid_dummies, verbose_dfm = FALSE)
      mai <- mai_res$mai

      # 4. nowcast the target quarter as-of this date
      nc <- nowcast_midas(mai = mai, gdp_growth = gdp_t, as_of = as_of,
                          model = model, qa_lag = qa_lag)

      # 4b. and the NEXT quarter, once it has a MAI month. Same panel, same MAI,
      # same estimation sample -- only the target moves on one quarter. NULL (not a
      # skip) while the next quarter has no month yet: that is the normal state for
      # the first weeks after a print, not an error.
      nc_next <- tryCatch(
        nowcast_midas(mai = mai, gdp_growth = gdp_t, as_of = as_of,
                      model = model, qa_lag = qa_lag, horizon = "next"),
        error = function(e) {
          msg <- conditionMessage(e)
          if (startsWith(msg, "nowcast_midas(): no MAI month beyond the current quarter")) NULL
          else stop(e)
        })

      list(mai = mai, nc = nc, nc_next = nc_next,
           n_sel = length(mai_res$diagnostics$selected),
           sel = paste(mai_res$diagnostics$selected, collapse = "|"))
    }, error = function(e) {
      structure(list(msg = conditionMessage(e)), class = "bt_error")
    })

    if (inherits(res, "bt_error")) {
      skipped[[length(skipped) + 1L]] <- data.frame(
        as_of = as.character(as_of), reason = gsub("\\s+", " ", res$msg))
      if (verbose) cat(sprintf("  [SKIP] %s : %s\n", as.character(as_of),
                               gsub("\\s+", " ", res$msg)))
      next
    }

    nc <- res$nc
    tq_name <- nc$target_quarter
    # quarter-end first-of-month date for the target quarter
    tq_yr <- as.integer(sub(" .*", "", tq_name))
    tq_q  <- as.integer(sub(".*Q", "", tq_name))
    tq_date <- as.Date(sprintf("%04d-%02d-01", tq_yr, tq_q * 3L))

    # actual from FULL gdp (latest vintage) at that quarter label
    actual <- gdp_full$value[match(tq_date, gdp_full$date)]
    fc <- nc$qoq_growth
    qoq_err <- if (is.na(actual)) NA_real_ else fc - actual
    dir_ok  <- if (is.na(actual)) NA else (sign(fc) == sign(actual))

    # Next-quarter horizon: same columns, computed the same way. All NA when the
    # next quarter has no MAI month at this as-of.
    nc_n <- res$nc_next
    if (is.null(nc_n)) {
      nq_name <- NA_character_; nq_date_chr <- NA_character_
      nq_fc <- NA_real_; nq_actual <- NA_real_; nq_jt <- NA_integer_
    } else {
      nq_name <- nc_n$target_quarter
      nq_yr <- as.integer(sub(" .*", "", nq_name))
      nq_q  <- as.integer(sub(".*Q", "", nq_name))
      nq_date <- as.Date(sprintf("%04d-%02d-01", nq_yr, nq_q * 3L))
      nq_date_chr <- as.character(nq_date)
      nq_fc <- nc_n$qoq_growth
      nq_actual <- gdp_full$value[match(nq_date, gdp_full$date)]
      nq_jt <- as.integer(nc_n$n_months_in_quarter)
    }
    if (length(nq_actual) != 1L || is.na(nq_actual)) nq_actual <- NA_real_

    rows[[length(rows) + 1L]] <- data.frame(
      as_of               = as.character(as_of),
      target_quarter      = tq_name,
      target_quarter_date = as.character(tq_date),
      qoq_growth_forecast = fc,
      qoq_actual          = actual,
      qoq_error           = qoq_err,
      direction_correct   = dir_ok,
      n_months_in_quarter = nc$n_months_in_quarter,
      n_series_selected   = res$n_sel,
      next_target_quarter      = nq_name,
      next_target_quarter_date = nq_date_chr,
      qoq_growth_forecast_next = nq_fc,
      qoq_actual_next          = nq_actual,
      n_months_in_next_quarter = nq_jt,
      stringsAsFactors    = FALSE
    )
    if (verbose) cat(sprintf("  %s  target %-8s  fc=%+.3f  act=%s  err=%s  dir=%s  (nsel=%d, jt=%d)  next=%s\n",
                             as.character(as_of), tq_name, fc,
                             ifelse(is.na(actual), "NA", sprintf("%+.3f", actual)),
                             ifelse(is.na(qoq_err), "NA", sprintf("%+.3f", qoq_err)),
                             ifelse(is.na(dir_ok), "NA", as.character(dir_ok)),
                             res$n_sel, nc$n_months_in_quarter,
                             ifelse(is.na(nq_fc), "NA",
                                    sprintf("%s %+.3f (jt=%d)", nq_name, nq_fc, nq_jt))))
  }

  results <- if (length(rows)) do.call(rbind, rows) else
    data.frame(as_of=character(0))
  skipped_df <- if (length(skipped)) do.call(rbind, skipped) else
    data.frame(as_of=character(0), reason=character(0))

  dir.create(dirname(out_csv), showWarnings = FALSE, recursive = TRUE)
  readr::write_csv(results, out_csv)

  el <- as.numeric(difftime(Sys.time(), t0, units = "mins"))
  cat(sprintf("\nbacktest_v2(): %d nowcasts, %d skipped, %.1f min -> %s\n",
              nrow(results), nrow(skipped_df), el, out_csv))

  invisible(list(results = results, skipped = skipped_df,
                 fixed_selection = fixed_selection,
                 as_of_dates = as_of_dates, runtime_min = el))
}

if (sys.nframe() == 0L) {
  bt <- backtest_v2()
  if (nrow(bt$skipped)) { cat("\nSkipped dates:\n"); print(bt$skipped) }
}
