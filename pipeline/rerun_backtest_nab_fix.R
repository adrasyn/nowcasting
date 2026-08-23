#### rerun_backtest_nab_fix.R ####
# One-off: re-run the v1 POOS backtest after the NAB history correction.
#
# WHY
# ---
# v1's NAB business confidence series was one month late across large parts of
# 2008-2014 (see 03d_sync_nab_from_v2.R). Every backtest result produced before
# that fix used misaligned NAB inputs, so the stored accuracy metrics describe a
# model that was reading the survey a month late.
#
# WHAT IT DOES
# ------------
#   1. Rebuilds the master dataset so the corrected NAB series is actually used.
#      The cached copy predates the fix and would silently reproduce the old run.
#   2. Runs the POOS backtest at the production config (r = 3, VAR(1)).
#   3. Writes to .cache/backtest_output/nab_fix_r3/ and prints an old-vs-new
#      comparison against the previous results, if any are on disk.
#
# It does NOT emit site JSON. Publishing stays with the weekly cron.
#
# Usage (from pipeline/):  Rscript rerun_backtest_nab_fix.R
# Runtime: roughly 45-60 minutes.

if (!file.exists("09_backtest_model.R")) {
  if (file.exists("pipeline/09_backtest_model.R")) setwd("pipeline") else
    stop("rerun_backtest_nab_fix.R: run from the pipeline/ directory")
}

suppressPackageStartupMessages({
  library(tidyverse)
  library(lubridate)
  library(glue)
})

cat("\n========================================\n")
cat("  BACKTEST RE-RUN — NAB history fix\n")
cat("========================================\n")
cat(sprintf("Started: %s\n\n", format(Sys.time(), "%Y-%m-%d %H:%M:%S")))

OUT_DIR <- ".cache/backtest_output/nab_fix_r3"
dir.create(OUT_DIR, recursive = TRUE, showWarnings = FALSE)

#### Step 1: rebuild the master dataset with the corrected NAB series ####
cat("STEP 1: Rebuilding master dataset (corrected NAB)...\n")

source("03c_nab_business_confidence.R")
source("03d_sync_nab_from_v2.R")
source("03_data_ingestion.R")
source("03b_fetch_fred_data.R")

sync_nab_from_v2()

nab_check <- readr::read_csv("nab_business_confidence_raw.csv", show_col_types = FALSE) |>
  dplyr::mutate(date = lubridate::ymd(date))
sep13 <- nab_check$value[nab_check$date == as.Date("2013-09-01")]
oct13 <- nab_check$value[nab_check$date == as.Date("2013-10-01")]
cat(sprintf("  NAB Sep-2013 = %s, Oct-2013 = %s (NAB published 12 and 5)\n", sep13, oct13))
if (!identical(as.numeric(sep13), 12) || !identical(as.numeric(oct13), 5)) {
  stop("NAB correction is NOT in place — aborting rather than backtesting stale inputs.")
}

manual_data <- fetch_all_manual_indicators()
abs_data    <- fetch_all_abs_indicators(use_cache = FALSE)
fred_data   <- fetch_all_fred_indicators(use_cache = FALSE)
all_indicators <- c(abs_data, fred_data, manual_data)

master <- build_master_dataset(all_indicators)
cat(sprintf("  Master: %d periods x %d indicators\n", nrow(master$wide), ncol(master$wide) - 1))

dir.create(".cache/processed", recursive = TRUE, showWarnings = FALSE)
saveRDS(master, ".cache/processed/master_dataset_complete.rds")
cat("  Saved .cache/processed/master_dataset_complete.rds\n\n")

#### Step 2: run the backtest at the production config ####
cat("STEP 2: Running POOS backtest (r = 3, VAR(1))...\n")
source("09_backtest_model.R")

config <- configure_dfm(n_factors = 3, var_order = 1)
results <- run_backtest(master, config)

saveRDS(results$backtest_results,  file.path(OUT_DIR, "backtest_results.rds"))
saveRDS(results$accuracy_metrics,  file.path(OUT_DIR, "accuracy_metrics.rds"))
saveRDS(results,                   file.path(OUT_DIR, "backtest_complete.rds"))
readr::write_csv(results$backtest_results, file.path(OUT_DIR, "backtest_results.csv"))
readr::write_csv(results$accuracy_metrics, file.path(OUT_DIR, "accuracy_metrics.csv"))
cat(sprintf("\n  Wrote results to %s\n", OUT_DIR))

#### Step 3: compare against the pre-fix run ####
cat("\nSTEP 3: Old vs new accuracy\n")
cat("----------------------------------------\n")
print(as.data.frame(results$accuracy_metrics))

prior_path <- ".cache/backtest_output/r3/accuracy_metrics.rds"
if (file.exists(prior_path)) {
  cat("\nPrevious run (pre-fix, .cache/backtest_output/r3/):\n")
  print(as.data.frame(readRDS(prior_path)))
} else {
  cat(sprintf("\nNo pre-fix metrics at %s — nothing to diff against.\n", prior_path))
}

cat(sprintf("\nFinished: %s\n", format(Sys.time(), "%Y-%m-%d %H:%M:%S")))
