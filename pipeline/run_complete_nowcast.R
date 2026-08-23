#### Run Complete Australian GDP Nowcast ####
# Purpose: Single script to run entire nowcast pipeline
# Author: James Wilson
# Date: 2026-01-01 (migrated to nowcasting/ repo 2026-04-16)
#
# What this does:
#   1. Fetches all 13 indicators (ABS + FRED + NAB)
#   2. Builds master dataset
#   3. Estimates Dynamic Factor Model
#   4. Generates GDP nowcast
#   5. (Task 14) Emits JSON artifacts for the website
#
# Usage (from repo root): Rscript -e 'setwd("pipeline"); source("run_complete_nowcast.R")'
# Usage (from pipeline/): Rscript run_complete_nowcast.R

#### Setup ####
# Find the pipeline directory regardless of where R was launched from.
# Works locally (from repo root or from pipeline/) and in CI.
if (!exists("PIPELINE_ROOT")) {
  PIPELINE_ROOT <- if (file.exists("pipeline/run_complete_nowcast.R")) {
    normalizePath("pipeline")
  } else if (file.exists("run_complete_nowcast.R")) {
    normalizePath(".")
  } else {
    stop("Cannot locate pipeline/ — run from repo root or pipeline/.")
  }
}
setwd(PIPELINE_ROOT)

# Ensure cache directories exist
dir.create(".cache/abs_raw", showWarnings = FALSE, recursive = TRUE)
dir.create(".cache/fred_raw", showWarnings = FALSE, recursive = TRUE)
dir.create(".cache/processed", showWarnings = FALSE, recursive = TRUE)
dir.create(".cache/model_output", showWarnings = FALSE, recursive = TRUE)
dir.create(".cache/model_output/vintages", showWarnings = FALSE, recursive = TRUE)

cat("\n")
cat("========================================\n")
cat("  AUSTRALIAN GDP NOWCAST MODEL\n")
cat("========================================\n\n")

#### Step 1: Fetch All Data ####
cat("STEP 1: Fetching all indicators...\n")
cat("----------------------------------------\n")

# Load data fetching scripts
source("03c_nab_business_confidence.R")
source("03d_sync_nab_from_v2.R")
source("03_data_ingestion.R")
source("03b_fetch_fred_data.R")

# NAB first — fails fast if stale.
# New months are pulled from the v2 survey scrape (nowcasting_v2/data_raw/nab_conf.csv,
# refreshed weekly from NAB's own PDF) rather than a second scraper of its own; see
# 03d for why this is append-only. Manual top-up is still available if v2 is down:
#   update_nab_data('2026-02-01', 3)
sync_nab_from_v2()

cat("  → Loading NAB Business Confidence (1)...\n")
manual_data <- fetch_all_manual_indicators()

cat("\n  → Loading ABS indicators (11)...\n")
abs_data <- fetch_all_abs_indicators(use_cache = FALSE)

cat("\n  → Loading FRED indicators (1)...\n")
fred_data <- fetch_all_fred_indicators(use_cache = FALSE)

# Combine all sources
cat("\n  → Combining all data sources...\n")
all_indicators <- c(abs_data, fred_data, manual_data)

cat("\n✓ Data fetching complete!\n")
cat(sprintf("  Total indicators: %d\n", length(all_indicators)))
cat(sprintf(
  "  Indicator IDs: %s\n",
  paste(names(all_indicators), collapse = ", ")
))

#### Step 2: Build Master Dataset ####
cat("\nSTEP 2: Building master dataset...\n")
cat("----------------------------------------\n")

master <- build_master_dataset(all_indicators)

cat(sprintf(
  "  Dimensions: %d periods × %d indicators\n",
  nrow(master$wide),
  ncol(master$wide) - 1
))

# Save complete dataset
saveRDS(master, ".cache/processed/master_dataset_complete.rds")
cat("  Saved to: .cache/processed/master_dataset_complete.rds\n")

cat("\n✓ Master dataset built!\n")

#### Step 2.5: Evaluate Previous Nowcast Accuracy ####
cat("\nSTEP 2.5: Checking nowcast accuracy against new actuals...\n")
cat("----------------------------------------\n")

source("08_vintage_tracking.R")

newly_evaluated <- evaluate_accuracy(master$wide)

if (!is.null(newly_evaluated) && nrow(newly_evaluated) > 0) {
  cat(sprintf(
    "  ✓ Evaluated %d quarter(s) with new actual data:\n",
    nrow(newly_evaluated)
  ))
  for (i in seq_len(nrow(newly_evaluated))) {
    row <- newly_evaluated[i, ]
    cat(sprintf(
      "    %s: Nowcast %+.2f%% vs Actual %+.2f%% (error: %+.2f pp)\n",
      row$target_quarter,
      row$nowcast_qoq,
      row$actual_qoq,
      row$error_qoq_pp
    ))
  }
  cat("  → Accuracy log: .cache/model_output/vintages/accuracy_log.csv\n")
} else {
  cat("  ℹ No new quarters to evaluate (no new actuals since last run)\n")
}

#### Step 3: Estimate Dynamic Factor Model ####
cat("\nSTEP 3: Estimating Dynamic Factor Model...\n")
cat("----------------------------------------\n")

source("05_estimate_model.R")

# Configure model
cat("  → Configuring DFM (3 factors, VAR(1))...\n")
config <- configure_dfm(n_factors = 3, var_order = 1)

# Estimate model
cat("  → Running EM algorithm (this may take 1-2 minutes)...\n\n")
model <- estimate_component_dfm(master$wide, config = config)

cat("\n✓ Model estimation complete!\n")

# Save model
saveRDS(model, ".cache/model_output/estimated_model.rds")
cat("  Saved to: .cache/model_output/estimated_model.rds\n")

#### Step 4: Generate GDP Nowcast ####
cat("\nSTEP 4: Generating GDP nowcast...\n")
cat("----------------------------------------\n")

source("06_generate_nowcast.R")

cat("  → Applying Kalman filter...\n")
nowcast <- generate_nowcast(model, master$wide)

# Save vintage snapshot
cat("  → Saving vintage snapshot...\n")
source("08_vintage_tracking.R")
vintage_info <- save_vintage(
  nowcast_result = nowcast,
  model = model,
  master_data = master$wide,
  all_indicators = all_indicators
)
cat(sprintf("     ✓ Vintage saved: %s\n", vintage_info$vintage_id))

cat("\n✓ Nowcast generated!\n\n")

# Display results
cat("========================================\n")
cat("  NOWCAST RESULTS\n")
cat("========================================\n\n")

cat(sprintf("Target Quarter:     %s\n", nowcast$target_quarter))
cat(sprintf(
  "Forecast GDP:       $%s million\n",
  format(round(nowcast$nowcast_value), big.mark = ",")
))
cat(sprintf("QoQ Growth:         %+.2f%%\n", nowcast$qoq_growth))
cat(sprintf("YoY Growth:         %+.2f%%\n", nowcast$yoy_growth))
cat(sprintf(
  "\nLatest Actual GDP:  $%s million (%s)\n",
  format(round(nowcast$latest_actual_value), big.mark = ","),
  nowcast$latest_actual_quarter
))
cat(sprintf("Generated:          %s\n", as.character(nowcast$generated_date)))
cat("\n")

#### Step 5: Emit JSON artifacts for the website ####
# Implemented in Task 14 — writes public-facing JSON to ../data/ for the Next.js site.
# Until then, the pipeline ends here. Local PNG/markdown rendering (previously Steps 5-6)
# has been retired as part of the web-deployment migration; the JSON contract replaces it.
if (file.exists("04_emit_json.R")) {
  cat("\nSTEP 5: Emitting JSON artifacts for the website...\n")
  cat("----------------------------------------\n")
  source("04_emit_json.R")
  emit_json(
    target_dir = "../data",
    nowcast = nowcast,
    master = master,
    vintage_info = vintage_info
  )
  cat("  ✓ JSON artifacts written to ../data/\n")
} else {
  cat("\nℹ JSON emission (Step 5) not yet wired — run requires 04_emit_json.R (Task 14).\n")
}

#### Summary ####
cat("\n")
cat("========================================\n")
cat("  COMPLETE!\n")
cat("========================================\n\n")

cat("Artifacts saved to:\n")
cat("  • .cache/model_output/estimated_model.rds\n")
cat("  • .cache/processed/master_dataset_complete.rds\n")
cat(sprintf("  • %s\n", vintage_info$file_path))
cat("  • .cache/model_output/vintages/vintage_tracking.csv\n")
cat("\n")
