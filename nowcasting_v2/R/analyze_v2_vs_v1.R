# analyze_v2_vs_v1.R
# Phase 6.2 -- head-to-head of the v2 POOS backtest vs the v1 (13-series DFM r=3)
# baseline backtest.
#
# Definitions are taken VERBATIM from last night's analyze_results.R (recovered
# from panel-expansion-research:pipeline/experimental/analyze_results.R):
#   - post-COVID  = target quarters with target_quarter_date >= 2022-01-01
#   - QoQ RMSE    = sqrt(mean(qoq_error^2, na.rm = TRUE))      [percentage points]
#   - hit rate    = mean(direction_correct, na.rm = TRUE) * 100  [%]
#   - n           = number of forecasts in the window (non-NA actual)
#
# v1 baseline recovered (without switching branches) to:
#   cache/v1_baseline_r3_backtest.csv
# via: git show panel-expansion-research:pipeline/experimental/backtest_output_baseline/r3/backtest_results.csv
#
# Writes cache/backtest_v2/v2_vs_v1.csv and prints the competitive-enough signal.
# REPORTS the numbers; does NOT decide cutover (that's Phase 6.3, user-gated).

suppressWarnings(suppressMessages({
  here <- tryCatch(dirname(sys.frame(1)$ofile), error = function(e) NA)
}))
if (is.na(here) || !nzchar(here)) here <- "R"
source(file.path(here, "_setup.R"))

suppressMessages({ library(dplyr); library(readr) })

POSTCOVID_FROM  <- as.Date("2022-01-01")
REALISED_Q1_QOQ <- 0.2743354   # 2026 Q1 actual (695945 / 694041 - 1), as in v1's script

# Summarise one backtest results frame over a window.
.metrics <- function(df, label, window) {
  df <- df[!is.na(df$qoq_error), , drop = FALSE]
  tibble(
    model              = label,
    window             = window,
    n                  = nrow(df),
    rmse_qoq_pp        = sqrt(mean(df$qoq_error^2, na.rm = TRUE)),
    hit_rate_pct       = mean(df$direction_correct, na.rm = TRUE) * 100,
    mean_abs_err_pp    = mean(abs(df$qoq_error), na.rm = TRUE)
  )
}

analyze_v2_vs_v1 <- function(
    v2_csv  = "cache/backtest_v2/backtest_results.csv",
    v1_csv  = "cache/v1_baseline_r3_backtest.csv",
    out_csv = "cache/backtest_v2/v2_vs_v1.csv") {

  v2 <- readr::read_csv(v2_csv, show_col_types = FALSE)
  v1 <- readr::read_csv(v1_csv, show_col_types = FALSE)

  v2$target_quarter_date <- as.Date(v2$target_quarter_date)
  v1$target_quarter_date <- as.Date(v1$target_quarter_date)

  # v1 carries direction_correct as logical; coerce if char
  if (is.character(v1$direction_correct))
    v1$direction_correct <- toupper(v1$direction_correct) %in% c("TRUE","T")
  if (is.character(v2$direction_correct))
    v2$direction_correct <- toupper(v2$direction_correct) %in% c("TRUE","T")

  # Drop v1 rows with no forecast (model_converged FALSE -> NA qoq_error)
  v1f <- v1[!is.na(v1$qoq_error), , drop = FALSE]
  v2f <- v2[!is.na(v2$qoq_error), , drop = FALSE]

  v1_pc <- v1f[v1f$target_quarter_date >= POSTCOVID_FROM, , drop = FALSE]
  v2_pc <- v2f[v2f$target_quarter_date >= POSTCOVID_FROM, , drop = FALSE]

  # Common post-COVID window (intersection of target quarters present in both),
  # plus each model's own post-COVID and full-sample figures.
  common_q <- intersect(v2_pc$target_quarter, v1_pc$target_quarter)
  v2_cm <- v2_pc[v2_pc$target_quarter %in% common_q, , drop = FALSE]
  v1_cm <- v1_pc[v1_pc$target_quarter %in% common_q, , drop = FALSE]

  tbl <- bind_rows(
    .metrics(v2f,  "v2 (31-series MAI->QA-UMIDAS)", "full-sample"),
    .metrics(v1f,  "v1 (13-series DFM r=3)",        "full-sample"),
    .metrics(v2_pc, "v2 (31-series MAI->QA-UMIDAS)", "post-COVID (>=2022Q1)"),
    .metrics(v1_pc, "v1 (13-series DFM r=3)",        "post-COVID (>=2022Q1)"),
    .metrics(v2_cm, "v2 (31-series MAI->QA-UMIDAS)", "post-COVID COMMON quarters"),
    .metrics(v1_cm, "v1 (13-series DFM r=3)",        "post-COVID COMMON quarters")
  )

  dir.create(dirname(out_csv), showWarnings = FALSE, recursive = TRUE)
  readr::write_csv(tbl, out_csv)

  # ---- Console readout ----
  cat("\n================= v2 vs v1 HEAD-TO-HEAD =================\n")
  print(as.data.frame(tbl |> mutate(across(where(is.numeric), ~round(.x, 3)))),
        row.names = FALSE)

  # Competitive-enough signal (post-COVID, common quarters preferred; fall back
  # to each model's own post-COVID window if the common set is empty).
  use_common <- length(common_q) > 0L
  v2row <- if (use_common) .metrics(v2_cm, "v2", "pc") else .metrics(v2_pc, "v2", "pc")
  v1row <- if (use_common) .metrics(v1_cm, "v1", "pc") else .metrics(v1_pc, "v1", "pc")

  rmse_ratio <- v2row$rmse_qoq_pp / v1row$rmse_qoq_pp
  within_10  <- v2row$rmse_qoq_pp <= v1row$rmse_qoq_pp * 1.10
  hit_gap    <- v2row$hit_rate_pct - v1row$hit_rate_pct
  hit_ok     <- hit_gap >= -5  # "not materially worse" = within 5pp

  cat("\n================= COMPETITIVE-ENOUGH SIGNAL =================\n")
  cat(sprintf("Window: %s (n_v2=%d, n_v1=%d)\n",
              if (use_common) "post-COVID, common target quarters" else "post-COVID (each own)",
              v2row$n, v1row$n))
  cat(sprintf("  v2 post-COVID QoQ RMSE: %.3f pp | hit %.1f%%\n",
              v2row$rmse_qoq_pp, v2row$hit_rate_pct))
  cat(sprintf("  v1 post-COVID QoQ RMSE: %.3f pp | hit %.1f%%\n",
              v1row$rmse_qoq_pp, v1row$hit_rate_pct))
  cat(sprintf("  RMSE ratio v2/v1: %.2fx  ->  within ~10%% of v1? %s\n",
              rmse_ratio, ifelse(within_10, "YES", "NO")))
  cat(sprintf("  hit-rate gap (v2 - v1): %+.1f pp  ->  not materially worse (>= -5pp)? %s\n",
              hit_gap, ifelse(hit_ok, "YES", "NO")))
  cat(sprintf("  COMPETITIVE-ENOUGH SIGNAL: %s  (report only; cutover is Phase 6.3, user-gated)\n",
              ifelse(within_10 && hit_ok, "YES", "NO")))

  # ---- 2026 Q1 held-out point ----
  q1v2 <- v2f[v2f$target_quarter == "2026 Q1", , drop = FALSE]
  if (nrow(q1v2)) {
    cat("\n----------------- 2026 Q1 HELD-OUT (actual +0.274%) -----------------\n")
    cat(sprintf("  v2 forecast: %+.3f%%  | actual %+.3f%%  | err %+.3f pp\n",
                q1v2$qoq_growth_forecast[1], REALISED_Q1_QOQ,
                q1v2$qoq_growth_forecast[1] - REALISED_Q1_QOQ))
    q1v1 <- v1f[v1f$target_quarter == "2026 Q1", , drop = FALSE]
    if (nrow(q1v1))
      cat(sprintf("  v1 forecast: %+.3f%%  | err %+.3f pp\n",
                  q1v1$qoq_growth_forecast[1],
                  q1v1$qoq_growth_forecast[1] - REALISED_Q1_QOQ))
  } else {
    cat("\n(2026 Q1 not in v2 backtest window.)\n")
  }

  invisible(list(table = tbl, common_quarters = common_q,
                 within_10 = within_10, hit_ok = hit_ok))
}

if (sys.nframe() == 0L) {
  analyze_v2_vs_v1()
}
