# bias_correction_analysis.R
# Task 0 (bias decomposition) + Lever A1 (real-time recursive intercept correction).
#
# Operates directly on the existing backtest result CSVs (v2 + v1 baseline). No
# model re-estimation needed for A1: intercept correction is a post-hoc transform
# of the forecast using ONLY the model's own past realised errors known as-of each
# date. Real-time validity: at the as-of date for target quarter Q, the only errors
# we may use are those for target quarters whose GDP was already RELEASED by that
# date. GDP for quarter Q is released ~gdp_lag (default 60) days after Q's end, and
# the as-of date for Q is Q's quarter-end. So as of the as-of date for Q, the most
# recent target quarter whose actual is known is Q-2 (Q-1's GDP is not out yet at
# Q's quarter-end; Q-1 ends ~3 months before and 60d < 90d). We make this explicit
# and conservative: only errors with (target_quarter_end + gdp_lag) <= as_of_date(Q).
#
# Fail loud: stop() if inputs missing / malformed.

suppressWarnings(suppressMessages({
  here <- tryCatch(dirname(sys.frame(1)$ofile), error = function(e) NA)
}))
if (is.na(here) || !nzchar(here)) here <- "R"
source(file.path(here, "_setup.R"))

suppressMessages({ library(dplyr); library(readr); library(lubridate) })

POSTCOVID_FROM  <- as.Date("2022-01-01")
REALISED_Q1_QOQ <- 0.2743354
GDP_LAG_DAYS    <- 60L

# --- helpers ----------------------------------------------------------------
.q_end_date <- function(tq_date) {
  # tq_date is first-of-month of quarter's last month (e.g. 2022-03-01).
  # quarter-end actual calendar end:
  lubridate::ceiling_date(as.Date(tq_date), "month") - lubridate::days(1)
}

# Real-time recursive intercept correction.
#  df: data.frame with columns as_of (Date), target_quarter_date (Date),
#      qoq_growth_forecast, qoq_actual, qoq_error (= forecast - actual).
#  window: trailing number of realised errors to average (4 or 8).
# Returns df with added columns: bias_est, qoq_forecast_corr, qoq_error_corr,
#   direction_correct_corr.
apply_rt_bias_correction <- function(df, window) {
  df <- df[order(df$as_of), , drop = FALSE]
  df$as_of <- as.Date(df$as_of)
  df$target_quarter_date <- as.Date(df$target_quarter_date)
  n <- nrow(df)
  bias_est <- rep(NA_real_, n)
  for (i in seq_len(n)) {
    as_of_i <- df$as_of[i]
    # errors usable as-of this date: target quarters whose GDP released by as_of_i
    rel_date <- .q_end_date(df$target_quarter_date) + lubridate::days(GDP_LAG_DAYS)
    usable <- which(rel_date <= as_of_i & !is.na(df$qoq_error))
    if (length(usable) == 0L) { bias_est[i] <- 0; next }   # no info yet -> no correction
    usable <- usable[order(df$as_of[usable])]
    take <- tail(usable, window)
    bias_est[i] <- mean(df$qoq_error[take])
  }
  df$bias_est            <- bias_est
  df$qoq_forecast_corr   <- df$qoq_growth_forecast - bias_est
  df$qoq_error_corr      <- df$qoq_forecast_corr - df$qoq_actual
  df$direction_correct_corr <- sign(df$qoq_forecast_corr) == sign(df$qoq_actual)
  df
}

.rmse <- function(e) sqrt(mean(e^2, na.rm = TRUE))
.hit  <- function(d) mean(d, na.rm = TRUE) * 100

# Summarise a (possibly corrected) error vector over windows.
summarise_variant <- function(df, err_col, dir_col, label) {
  d <- df[!is.na(df[[err_col]]), , drop = FALSE]
  pc <- d[d$target_quarter_date >= POSTCOVID_FROM, , drop = FALSE]
  q1 <- d[d$target_quarter == "2026 Q1", , drop = FALSE]
  tibble(
    variant        = label,
    n_full         = nrow(d),
    rmse_full      = .rmse(d[[err_col]]),
    hit_full       = .hit(d[[dir_col]]),
    n_pc           = nrow(pc),
    rmse_pc        = .rmse(pc[[err_col]]),
    hit_pc         = .hit(pc[[dir_col]]),
    bias_pc        = mean(pc[[err_col]], na.rm = TRUE),
    q1_forecast    = if (nrow(q1)) q1[[sub("error","forecast", err_col, fixed=TRUE)]][1] else NA_real_,
    q1_error       = if (nrow(q1)) q1[[err_col]][1] else NA_real_
  )
}

run_analysis <- function(
    v2_csv = "cache/backtest_v2/backtest_results.csv",
    v1_csv = "cache/v1_baseline_r3_backtest.csv",
    um_csv = "cache/backtest_v2/backtest_results_umidas.csv",
    out_csv = "cache/backtest_v2/bias_correction_results.csv") {

  if (!file.exists(v2_csv)) stop("missing v2 backtest: ", v2_csv)
  if (!file.exists(v1_csv)) stop("missing v1 baseline: ", v1_csv)

  v2 <- readr::read_csv(v2_csv, show_col_types = FALSE)
  v1 <- readr::read_csv(v1_csv, show_col_types = FALSE)

  # v1 column harmonisation: it has as_of = backtest_date, target_quarter_date,
  # qoq_growth_forecast, qoq_actual, qoq_error, direction_correct.
  v1 <- v1 %>% rename(as_of = backtest_date)
  v1$direction_correct <- as.logical(v1$direction_correct)
  v2$direction_correct <- as.logical(v2$direction_correct)

  v2$as_of <- as.Date(v2$as_of); v2$target_quarter_date <- as.Date(v2$target_quarter_date)
  v1$as_of <- as.Date(v1$as_of); v1$target_quarter_date <- as.Date(v1$target_quarter_date)

  v1 <- v1[!is.na(v1$qoq_error), , drop = FALSE]
  v2 <- v2[!is.na(v2$qoq_error), , drop = FALSE]

  # ---- TASK 0: bias decomposition (v2 post-COVID, raw) ----
  v2_pc <- v2[v2$target_quarter_date >= POSTCOVID_FROM, , drop = FALSE]
  bias  <- mean(v2_pc$qoq_error)
  rmse2 <- mean(v2_pc$qoq_error^2)
  varc  <- mean((v2_pc$qoq_error - bias)^2)   # population variance of errors
  cat("================= TASK 0: post-COVID bias decomposition (v2 raw) =================\n")
  cat(sprintf("  n (post-COVID >=2022Q1)      : %d\n", nrow(v2_pc)))
  cat(sprintf("  mean error (bias)            : %+.4f pp\n", bias))
  cat(sprintf("  RMSE                         : %.4f pp\n", sqrt(rmse2)))
  cat(sprintf("  RMSE^2                       : %.5f\n", rmse2))
  cat(sprintf("  bias^2                       : %.5f  (%.1f%% of RMSE^2)\n",
              bias^2, 100*bias^2/rmse2))
  cat(sprintf("  variance                     : %.5f  (%.1f%% of RMSE^2)\n",
              varc, 100*varc/rmse2))
  cat(sprintf("  RMSE if bias fully removed   : %.4f pp  (= sqrt(variance))\n", sqrt(varc)))
  cat(sprintf("  v1 post-COVID RMSE (ref)     : (see results matrix below)\n"))

  # ---- LEVER A1: real-time recursive bias correction (roll4, roll8) ----
  v2_r4 <- apply_rt_bias_correction(v2, 4L)
  v2_r8 <- apply_rt_bias_correction(v2, 8L)
  v1_r4 <- apply_rt_bias_correction(v1, 4L)
  v1_r8 <- apply_rt_bias_correction(v1, 8L)

  res <- bind_rows(
    summarise_variant(v2,    "qoq_error",      "direction_correct",      "v2-QA raw"),
    summarise_variant(v2_r4, "qoq_error_corr", "direction_correct_corr", "v2-QA roll4"),
    summarise_variant(v2_r8, "qoq_error_corr", "direction_correct_corr", "v2-QA roll8"),
    summarise_variant(v1,    "qoq_error",      "direction_correct",      "v1 raw"),
    summarise_variant(v1_r4, "qoq_error_corr", "direction_correct_corr", "v1 roll4"),
    summarise_variant(v1_r8, "qoq_error_corr", "direction_correct_corr", "v1 roll8")
  )

  # ---- LEVER A2: full unrestricted U-MIDAS (+ same bias correction) ----
  if (file.exists(um_csv)) {
    um <- readr::read_csv(um_csv, show_col_types = FALSE)
    um$as_of <- as.Date(um$as_of); um$target_quarter_date <- as.Date(um$target_quarter_date)
    um$direction_correct <- as.logical(um$direction_correct)
    um <- um[!is.na(um$qoq_error), , drop = FALSE]
    um_r4 <- apply_rt_bias_correction(um, 4L)
    um_r8 <- apply_rt_bias_correction(um, 8L)
    res <- bind_rows(res,
      summarise_variant(um,    "qoq_error",      "direction_correct",      "v2-UMIDAS raw"),
      summarise_variant(um_r4, "qoq_error_corr", "direction_correct_corr", "v2-UMIDAS roll4"),
      summarise_variant(um_r8, "qoq_error_corr", "direction_correct_corr", "v2-UMIDAS roll8")
    )
  } else {
    cat("(NOTE: U-MIDAS backtest CSV not found; A2 rows omitted: ", um_csv, ")\n", sep = "")
  }

  cat("\n================= LEVER A1: RESULTS MATRIX =================\n")
  print(as.data.frame(res %>% mutate(across(where(is.numeric), ~round(.x, 4)))),
        row.names = FALSE)

  v1_pc_rmse <- res$rmse_pc[res$variant == "v1 raw"]
  cat("\n----- post-COVID RMSE ratios vs v1 raw (", round(v1_pc_rmse,4), "pp) -----\n", sep="")
  for (v in res$variant) {
    r <- res$rmse_pc[res$variant == v]
    cat(sprintf("  %-10s  rmse_pc=%.4f  ratio=%.2fx  within10%% of v1-raw? %s\n",
                v, r, r/v1_pc_rmse, ifelse(r <= v1_pc_rmse*1.10, "YES", "no")))
  }

  dir.create(dirname(out_csv), showWarnings = FALSE, recursive = TRUE)
  readr::write_csv(res, out_csv)
  invisible(list(results = res, bias = bias, rmse2 = rmse2,
                 v2_r4 = v2_r4, v2_r8 = v2_r8))
}

if (sys.nframe() == 0L) {
  run_analysis()
}
