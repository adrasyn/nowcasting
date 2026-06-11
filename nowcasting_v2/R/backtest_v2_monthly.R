# backtest_v2_monthly.R
# Phase 6.2 -- MONTHLY-cadence real-time (POOS) backtest of nowcast v2.
#
# Motivation
# ----------
# backtest_v2.R only nowcasts at quarter-END as-of dates. Empirically that always
# yields exactly 2 within-quarter MAI months (jt=2): at a quarter-end as-of date
# the last two months of the quarter are published but the final month isn't yet.
# But v2 runs CONTINUOUSLY -- as a quarter progresses it sees 0->1->2->3 months of
# its own MAI. MIDAS's whole point is exploiting that ragged edge. This harness
# sweeps MULTIPLE as-of dates per target quarter to trace the within-quarter
# accuracy trajectory by n_months_in_quarter.
#
# Cadence definition (lag -> n_months), confirmed empirically against the panel
# truncation in backtest_v2.R::.truncate_panel for a quarter starting month M1:
#   as_of = quarter_start + 30d  (~M1 month-end):    0 target-quarter MAI months
#   as_of = quarter_start + 60d  (~start of M3):     1 target-quarter MAI month  (M1)
#   as_of = quarter_start + 90d  (~quarter end):     2 target-quarter MAI months (M1,M2)  == backtest_v2 cadence
#   as_of = quarter_start + 120d (~M3+1 month-end):  3 target-quarter MAI months (M1,M2,M3)
# (A month's MAI exists once enough of its panel series are published; the slowest
#  selected series -- ABS activity at +45d -- sets the edge, hence the ~30d steps.)
#
# Real-time validity: each as_of only uses panel/GDP data published by then, via
# the SAME .truncate_panel / .truncate_gdp lag truncation reused from backtest_v2.R.
# No look-ahead. Fixed full-sample targeted-predictor selection (standard POOS
# simplification, identical to backtest_v2). Fail loud; errored as-of dates are
# logged and SKIPPED, never fabricated.
#
# The n_months=0 case
# -------------------
# nowcast_midas() auto-selects the target quarter as "first quarter with MAI but no
# released GDP". A genuine, real-time-faithful jt=0 nowcast of quarter Q requires an
# as_of that is (a) AFTER Q-1's GDP has been released (so Q-1 is no longer the live
# target) and (b) BEFORE any of Q's own MAI months are available. In practice that
# window is a knife-edge (Q-1 GDP releases ~60d after it ends, i.e. ~Q's first month,
# which is also roughly when Q's first MAI month starts to appear), so jt=0 is NOT a
# natural operating state -- the model essentially always has >=1 month of the live
# quarter once the prior quarter's GDP is out. To measure jt=0 fairly for a GIVEN Q
# we set force_jt0=TRUE: GDP is trimmed to <= Q-1 (forcing the engine onto Q) AND the
# MAI is trimmed to < Q's start so the engine sees zero within-quarter months and
# takes its production jt=0 path (random-walk-in-level contemporaneous input). The
# as_of for this case is pinned to just after Q-1's GDP release.
#
# Writes cache/backtest_v2/backtest_monthly_results.csv (one row per (target_q, as_of)).

suppressWarnings(suppressMessages({
  here <- tryCatch(dirname(sys.frame(1)$ofile), error = function(e) NA)
}))
if (is.na(here) || !nzchar(here)) here <- "R"
source(file.path(here, "_setup.R"))
source(file.path(here, "backtest_v2.R"))   # reuse helpers: .truncate_panel/.truncate_gdp/
                                           # .lag_for_id/.q_label/.q_name + build_mai/nowcast_midas

suppressMessages({
  library(dplyr)
  library(readr)
  library(lubridate)
})

# ---------------------------------------------------------------------------
# Single-as-of estimation step. Extracted verbatim from backtest_v2()'s loop body
# (same truncation, same fixed-selection intersection, same MAI build) so monthly
# and quarter-end backtests share identical real-time estimation. Returns the
# nowcast_midas() result list, or a "bt_error" on failure.
#
# force_jt0_q : if non-NULL, a quarter-end first-of-month Date Q. We (a) trim GDP to
#   quarters strictly before Q (so the engine targets Q) and (b) trim the panel to
#   reference months strictly before Q's start, so the resulting MAI has zero months
#   in Q -> the engine takes its production jt=0 (1-step-ahead) path. as_of should be
#   ~just after Q-1's GDP release for a faithful real-time edge.
# ---------------------------------------------------------------------------
.bt_step <- function(wide_full, gdp_full, fixed_selection, as_of, gdp_lag = 60L,
                     model = "qa", panel_info_csv = "seed/panel_info.csv",
                     gdp_csv = "data_raw/rt_dgdp_qtr.csv", force_jt0_q = NULL) {
  as_of <- as.Date(as_of, origin = "1970-01-01")
  tryCatch({
    wide_t <- .truncate_panel(wide_full, as_of)
    gdp_t  <- .truncate_gdp(gdp_full, as_of, gdp_lag = gdp_lag)

    if (!is.null(force_jt0_q)) {
      fq <- as.Date(force_jt0_q)
      # Q's start = first-of-month of the quarter's first month (fq is the q-END
      # first-of-month, e.g. Mar-01 for Q1; start = Jan-01 = fq - 2 months).
      q_start <- fq %m-% months(2L)
      gdp_t  <- gdp_t[gdp_t$date < fq, , drop = FALSE]                 # release through Q-1 only
      wide_t[wide_t$date >= q_start, setdiff(names(wide_t), "date")] <- NA_real_  # no MAI in Q
    }

    ids <- setdiff(names(wide_t), "date")
    keep_ids <- ids[vapply(wide_t[ids], function(x) any(!is.na(x)), logical(1))]
    keep_ids <- keep_ids[vapply(wide_t[keep_ids],
                                function(x) sum(!is.na(x)) >= 6L, logical(1))]
    wide_t <- wide_t[, c("date", keep_ids), drop = FALSE]

    anyobs <- apply(wide_t[keep_ids], 1, function(r) any(!is.na(r)))
    wide_t <- wide_t[which(anyobs)[1]:max(which(anyobs)), , drop = FALSE]

    tfs_t <- transform_panel(wide_t, panel_info_csv)

    sel_t <- fixed_selection[
      vapply(fixed_selection, function(id)
        id %in% names(tfs_t) && sum(!is.na(tfs_t[[id]])) >= 24L, logical(1))]
    mai_res <- build_mai(tfs = tfs_t, panel_info_csv = panel_info_csv,
                         gdp_csv = gdp_csv, out_csv = NULL, out_rds = NULL,
                         force_selected = sel_t, verbose_dfm = FALSE)
    mai <- mai_res$mai

    nc <- nowcast_midas(mai = mai, gdp_growth = gdp_t, as_of = as_of, model = model)

    list(nc = nc, n_sel = length(mai_res$diagnostics$selected))
  }, error = function(e) {
    structure(list(msg = conditionMessage(e)), class = "bt_error")
  })
}

# ---------------------------------------------------------------------------
# Monthly-cadence backtest driver.
# For each target quarter from start_year onward, nowcast it at as_of =
# quarter_start + offsets (default 30/60/90/120 days). Records, per (target_q,
# as_of): the natural target quarter the engine produced, n_months_in_quarter,
# nowcast vs realised growth, the as_of offset, and the cadence step label.
# ---------------------------------------------------------------------------
backtest_v2_monthly <- function(panel_rds      = "cache/panel_vintage_latest.rds",
                                panel_info_csv = "seed/panel_info.csv",
                                gdp_csv        = "data_raw/rt_dgdp_qtr.csv",
                                out_csv        = "cache/backtest_v2/backtest_monthly_results.csv",
                                start_year     = 2015L,
                                offsets_days   = c(60L, 90L, 120L),  # natural jt = 1,2,3
                                include_jt0    = TRUE,               # add forced jt=0 per quarter
                                gdp_lag        = 60L,
                                model          = c("qa", "umidas"),
                                verbose        = TRUE) {
  model <- match.arg(model)
  t0 <- Sys.time()

  wide_full <- readRDS(panel_rds)
  gdp_full  <- readr::read_csv(gdp_csv, show_col_types = FALSE)
  gdp_full$date <- as.Date(gdp_full$date)
  gdp_full <- gdp_full[order(gdp_full$date), ]

  if (verbose) cat("Fixing full-sample targeted-predictor selection...\n")
  full_sel_res <- build_mai(panel_info_csv = panel_info_csv, gdp_csv = gdp_csv,
                            out_csv = NULL, out_rds = NULL, verbose_dfm = FALSE)
  fixed_selection <- full_sel_res$diagnostics$selected
  cat(sprintf("Fixed selection (%d series): %s\n",
              length(fixed_selection), paste(fixed_selection, collapse = ", ")))

  # Target quarters: quarter-START first-of-month dates (Jan/Apr/Jul/Oct-01) from
  # start_year, up to one quarter past the last monthly obs.
  last_data <- max(wide_full$date)
  q_starts <- seq(as.Date(sprintf("%d-01-01", start_year)),
                  lubridate::floor_date(last_data, "quarter"),
                  by = "3 months")
  # quarter-end first-of-month label for each target quarter start
  q_ends <- lubridate::ceiling_date(q_starts, "quarter") - lubridate::days(1)
  target_q_dates <- as.Date(vapply(q_ends, function(d) as.character(.q_label(d)), character(1)))

  n_plan <- length(offsets_days) + as.integer(isTRUE(include_jt0))
  cat(sprintf("Monthly backtest: %d target quarters (%s..%s) x %d as-of%s = up to %d nowcasts\n",
              length(q_starts), .q_name(min(target_q_dates)), .q_name(max(target_q_dates)),
              n_plan, if (include_jt0) " (offsets + forced jt=0)" else " (offsets)",
              length(q_starts) * n_plan))

  rows <- list(); skipped <- list()

  # one (offset, force_jt0_q) plan per target quarter
  for (i in seq_along(q_starts)) {
    qs   <- q_starts[i]
    tq   <- target_q_dates[i]              # target quarter (q-end first-of-month)
    tqnm <- .q_name(tq)

    # plan: natural offsets (jt 1/2/3), plus an explicit forced jt=0 evaluation.
    # jt=0 as_of is pinned to just after Q-1's GDP release: Q-1 quarter-end + gdp_lag
    # + 1 day. Q-1 quarter-end = (qs - 1 day). So as_of0 = qs - 1 + gdp_lag + 1.
    plan <- lapply(offsets_days, function(o) list(as_of = qs + lubridate::days(o),
                                                  off = o, jt0 = FALSE))
    if (include_jt0) {
      as_of0 <- (qs - lubridate::days(1)) + lubridate::days(gdp_lag + 1L)
      plan <- c(list(list(as_of = as_of0, off = 0L, jt0 = TRUE)), plan)
    }

    for (p in plan) {
      as_of <- p$as_of; off <- p$off
      if (as_of > Sys.Date()) next
      force_q <- if (isTRUE(p$jt0)) tq else NULL

      res <- .bt_step(wide_full, gdp_full, fixed_selection, as_of,
                      gdp_lag = gdp_lag, model = model,
                      panel_info_csv = panel_info_csv, gdp_csv = gdp_csv,
                      force_jt0_q = force_q)

      if (inherits(res, "bt_error")) {
        skipped[[length(skipped) + 1L]] <- data.frame(
          intended_target = tqnm, as_of = as.character(as_of), offset = off,
          reason = gsub("\\s+", " ", res$msg), stringsAsFactors = FALSE)
        if (verbose) cat(sprintf("  [SKIP] %s @ %s (+%dd): %s\n", tqnm,
                                 as.character(as_of), off, gsub("\\s+", " ", res$msg)))
        next
      }

      nc <- res$nc
      nat_tq <- nc$target_quarter        # quarter the engine actually nowcast
      fc <- nc$qoq_growth
      jt <- nc$n_months_in_quarter

      # realised growth for the NATURAL target (so error is always vs the right quarter)
      nat_yr <- as.integer(sub(" .*", "", nat_tq))
      nat_q  <- as.integer(sub(".*Q", "", nat_tq))
      nat_tq_date <- as.Date(sprintf("%04d-%02d-01", nat_yr, nat_q * 3L))
      nat_actual  <- gdp_full$value[match(nat_tq_date, gdp_full$date)]

      qoq_err <- if (is.na(nat_actual)) NA_real_ else fc - nat_actual
      dir_ok  <- if (is.na(nat_actual)) NA else (sign(fc) == sign(nat_actual))

      rows[[length(rows) + 1L]] <- data.frame(
        intended_target     = tqnm,
        target_quarter      = nat_tq,
        target_quarter_date = as.character(nat_tq_date),
        as_of               = as.character(as_of),
        offset_days         = off,
        forced              = isTRUE(p$jt0),
        qoq_growth_forecast = fc,
        qoq_actual          = nat_actual,
        qoq_error           = qoq_err,
        direction_correct   = dir_ok,
        n_months_in_quarter = jt,
        n_series_selected   = res$n_sel,
        stringsAsFactors    = FALSE
      )
      if (verbose) cat(sprintf("  %s (+%3dd) -> tgt %-8s jt=%d fc=%+.3f act=%s err=%s\n",
                               as.character(as_of), off, nat_tq, jt, fc,
                               ifelse(is.na(nat_actual), "NA", sprintf("%+.3f", nat_actual)),
                               ifelse(is.na(qoq_err), "NA", sprintf("%+.3f", qoq_err))))
    }
  }

  results <- if (length(rows)) do.call(rbind, rows) else data.frame()
  skipped_df <- if (length(skipped)) do.call(rbind, skipped) else
    data.frame(intended_target=character(0), as_of=character(0), offset=integer(0), reason=character(0))

  dir.create(dirname(out_csv), showWarnings = FALSE, recursive = TRUE)
  readr::write_csv(results, out_csv)

  el <- as.numeric(difftime(Sys.time(), t0, units = "mins"))
  cat(sprintf("\nbacktest_v2_monthly(): %d nowcasts, %d skipped, %.1f min -> %s\n",
              nrow(results), nrow(skipped_df), el, out_csv))

  invisible(list(results = results, skipped = skipped_df,
                 fixed_selection = fixed_selection, runtime_min = el))
}

# ---------------------------------------------------------------------------
# Summary: RMSE / hit / bias grouped by n_months_in_quarter, post-COVID only.
# post_covid_from default 2020-10-01 (2020 Q4) matches the v1/v2 head-to-head
# convention (excludes the COVID-shock quarters 2020 Q1-Q3).
# ---------------------------------------------------------------------------
summarise_monthly <- function(results, post_covid_from = "2020-10-01") {
  df <- results[!is.na(results$qoq_error), , drop = FALSE]
  df$tqd <- as.Date(df$target_quarter_date)
  pc <- df[df$tqd >= as.Date(post_covid_from), , drop = FALSE]

  by_grp <- function(d) {
    do.call(rbind, lapply(sort(unique(d$n_months_in_quarter)), function(j) {
      g <- d[d$n_months_in_quarter == j, , drop = FALSE]
      data.frame(
        n_months = j,
        n        = nrow(g),
        rmse     = sqrt(mean(g$qoq_error^2)),
        mae      = mean(abs(g$qoq_error)),
        bias     = mean(g$qoq_error),
        hit_rate = mean(g$direction_correct, na.rm = TRUE),
        stringsAsFactors = FALSE)
    }))
  }
  list(post_covid = by_grp(pc), full = by_grp(df),
       post_covid_from = post_covid_from)
}

if (sys.nframe() == 0L) {
  bt <- backtest_v2_monthly()
  cat("\n===== v2 monthly accuracy by n_months_in_quarter (post-COVID) =====\n")
  s <- summarise_monthly(bt$results)
  print(s$post_covid, row.names = FALSE)
  cat("\n----- full window -----\n")
  print(s$full, row.names = FALSE)
  if (nrow(bt$skipped)) { cat("\nSkipped:\n"); print(bt$skipped, row.names = FALSE) }
}
