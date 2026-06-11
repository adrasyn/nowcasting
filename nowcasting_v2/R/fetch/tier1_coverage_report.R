# =============================================================================
# tier1_coverage_report.R — refresh + audit the Tier-1 free predictor panel.
# Runs both fetchers (ABS + RBA), then prints a coverage table and checks:
#   (a) history back to >= 2005-01-01
#   (b) latest obs within ~3 months of today
# Series flagged in panel_info_tier1.csv with a documented short-history /
# discontinuation are reported as WARN (not a hard failure).
#
#   Rscript nowcasting_v2/R/fetch/tier1_coverage_report.R          # refresh+audit
#   Rscript nowcasting_v2/R/fetch/tier1_coverage_report.R --audit  # audit only
# =============================================================================
root <- local({
  cand <- c("nowcasting_v2/R/_setup.R", "R/_setup.R", "../R/_setup.R", "../../R/_setup.R")
  for (p in cand) if (file.exists(p)) return(normalizePath(dirname(dirname(p))))
  normalizePath(".")
})
source(file.path(root, "R", "_setup.R"))
suppressMessages({ library(dplyr); library(readr); library(lubridate) })

audit_only <- "--audit" %in% commandArgs(trailingOnly = TRUE)

if (!audit_only) {
  source(file.path(root, "R", "fetch", "fetch_abs_panel.R"))
  source(file.path(root, "R", "fetch", "fetch_rba_panel.R"))
  cat("===== Fetching ABS Tier-1 panel =====\n"); fetch_abs_panel()
  cat("===== Fetching RBA Tier-1 panel =====\n"); fetch_rba_panel()
}

info_path <- file.path(root, "seed", "panel_info_tier1.csv")
info <- readr::read_csv(info_path, show_col_types = FALSE)
data_raw <- file.path(root, "data_raw")

today        <- Sys.Date()
hist_target  <- as.Date("2005-01-01")
recency_days <- 100L   # ~3 months

cat("\n===== Tier-1 coverage report =====\n")
cat(sprintf("%-16s %-8s %-6s %-10s %-10s %-6s %-5s %-5s\n",
            "id", "status", "n", "first", "last", "hist05", "recent", "ok"))
rows <- list()
for (i in seq_len(nrow(info))) {
  id     <- info$id[i]
  status <- info$status[i]
  f <- file.path(data_raw, paste0(id, ".csv"))
  if (status == "MISSING" || !file.exists(f)) {
    cat(sprintf("%-16s %-8s %-6s %-10s %-10s %-6s %-5s %-5s\n",
                id, status, "-", "-", "-", "-", "-", "-"))
    rows[[id]] <- data.frame(id, status, n = NA, first = NA, last = NA,
                             hist05 = NA, recent = NA, ok = NA)
    next
  }
  d <- readr::read_csv(f, show_col_types = FALSE)
  d$date <- as.Date(d$date)
  n <- nrow(d); first <- min(d$date); last <- max(d$date)
  hist_ok   <- first <= hist_target
  recent_ok <- as.integer(today - last) <= recency_days
  ok <- hist_ok && recent_ok
  cat(sprintf("%-16s %-8s %-6d %-10s %-10s %-6s %-5s %-5s\n",
              id, status, n, format(first), format(last),
              ifelse(hist_ok, "Y", "n"), ifelse(recent_ok, "Y", "n"),
              ifelse(ok, "OK", "WARN")))
  rows[[id]] <- data.frame(id, status, n, first = format(first), last = format(last),
                           hist05 = hist_ok, recent = recent_ok, ok = ok)
}

summ <- do.call(rbind, rows)
n_ok      <- sum(summ$status == "OK", na.rm = TRUE)
n_missing <- sum(summ$status == "MISSING", na.rm = TRUE)
n_full    <- sum(summ$ok %in% TRUE)
cat(sprintf("\nSeries: %d OK fetchers, %d MISSING. %d meet BOTH >=2005 & <3mo.\n",
            n_ok, n_missing, n_full))

# Hard-fail guard: every OK series must at least parse to a non-empty CSV.
empty <- summ$id[summ$status == "OK" & (is.na(summ$n) | summ$n == 0)]
if (length(empty) > 0) stop("Empty CSV for OK series: ", paste(empty, collapse = ", "))
invisible(summ)
