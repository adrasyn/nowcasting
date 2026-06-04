#### Generate CI band params from a POOS backtest ####
# Reads a backtest_results.csv (per-quarter forecast vs actual, as written by
# run_backtest_sweep.R / 09_backtest_model.R) and computes the post-COVID QoQ
# forecast-error bias + sd. Writes seed/ci_params.json, consumed by ci_bands.R /
# 04_emit_json.R. Re-run after each validated backtest so the public bands track
# the model's measured accuracy.
#
# Usage:
#   cd pipeline && Rscript compute_ci_params.R [backtest_results.csv] [out.json]
# Defaults to the r=3 sweep output and seed/ci_params.json.

suppressMessages({ library(dplyr); library(readr); library(jsonlite) })

args <- commandArgs(trailingOnly = TRUE)
src  <- if (length(args) >= 1) args[[1]] else ".cache/backtest_output/r3/backtest_results.csv"
out  <- if (length(args) >= 2) args[[2]] else "seed/ci_params.json"
POSTCOVID_FROM <- as.Date("2022-01-01")

if (!file.exists(src)) stop("backtest results not found: ", src,
                            " — run run_backtest_sweep.R first")

br <- read_csv(src, show_col_types = FALSE) |>
  mutate(target_quarter_date = as.Date(target_quarter_date)) |>
  filter(!is.na(qoq_error), target_quarter_date >= POSTCOVID_FROM)

if (nrow(br) < 8) stop("only ", nrow(br),
                       " post-COVID forecasts — too few to estimate CI params reliably")

bias <- mean(br$qoq_error)
sdv  <- sd(br$qoq_error)
rmse <- sqrt(mean(br$qoq_error^2))

params <- list(
  basis        = "post-COVID (target quarter >= 2022-01-01)",
  factor_count = 3L,
  n            = nrow(br),
  qoq_bias_pp  = round(bias, 4),   # mean(forecast - actual); >0 => model runs hot
  qoq_sd_pp    = round(sdv, 4),    # dispersion of errors about their mean
  qoq_rmse_pp  = round(rmse, 4),
  z_68         = 1.0,
  z_95         = 1.96,
  method       = "bias-aware: interval centred on (forecast - bias), half-width z*sd",
  source       = src,
  computed_at  = format(Sys.time(), "%Y-%m-%dT%H:%M:%SZ", tz = "UTC")
)
write_json(params, out, auto_unbox = TRUE, pretty = TRUE)
cat(sprintf("wrote %s  (n=%d, bias=%+.4f, sd=%.4f, rmse=%.4f)\n",
            out, params$n, bias, sdv, rmse))
