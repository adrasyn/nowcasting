# analyse_monthly.R -- summary tables for the monthly-cadence v2 backtest.
# Reports v2 accuracy grouped by n_months_in_quarter on two post-COVID windows:
#   - 2020-10-01 (v2 head-to-head convention)
#   - 2022-01-01 (the window under which v1's stated 0.340pp RMSE was computed)
# plus the v1 baseline and the existing quarter-end v2 sanity reference.
source("R/_setup.R")

grp <- function(d, label) {
  d <- d[!is.na(d$qoq_error), , drop = FALSE]
  do.call(rbind, lapply(sort(unique(d$n_months_in_quarter)), function(j) {
    g <- d[d$n_months_in_quarter == j, , drop = FALSE]
    data.frame(window = label, n_months = j, n = nrow(g),
               rmse = round(sqrt(mean(g$qoq_error^2)), 3),
               mae  = round(mean(abs(g$qoq_error)), 3),
               bias = round(mean(g$qoq_error), 3),
               hit  = round(mean(g$direction_correct, na.rm = TRUE), 3),
               stringsAsFactors = FALSE)
  }))
}

m <- read.csv("cache/backtest_v2/backtest_monthly_results.csv", stringsAsFactors = FALSE)
m$tqd <- as.Date(m$target_quarter_date)

cat("=== v2 MONTHLY: accuracy by n_months_in_quarter ===\n\n")
cat("-- post-COVID from 2020-10-01 --\n")
print(grp(m[m$tqd >= as.Date("2020-10-01"), ], "pc2020Q4"), row.names = FALSE)
cat("\n-- post-COVID from 2022-01-01 (v1's 0.340pp window) --\n")
print(grp(m[m$tqd >= as.Date("2022-01-01"), ], "pc2022Q1"), row.names = FALSE)
cat("\n-- full window (>=2015) --\n")
print(grp(m, "full"), row.names = FALSE)

# v1 baseline (quarter-end cadence)
v1 <- read.csv("cache/v1_baseline_r3_backtest.csv", stringsAsFactors = FALSE)
v1$tqd <- as.Date(v1$target_quarter_date); v1 <- v1[!is.na(v1$qoq_error), ]
v1pc <- function(cut) { p <- v1[v1$tqd >= as.Date(cut), ]
  sprintf("v1 q-end from %s: n=%d RMSE=%.3f hit=%.3f bias=%+.3f", cut, nrow(p),
          sqrt(mean(p$qoq_error^2)), mean(p$direction_correct, na.rm = TRUE), mean(p$qoq_error)) }
cat("\n=== v1 baseline (quarter-end cadence) ===\n")
cat(v1pc("2020-10-01"), "\n"); cat(v1pc("2022-01-01"), "\n")

# existing quarter-end v2 (sanity: should match monthly n_months=2)
q <- read.csv("cache/backtest_v2/backtest_results.csv", stringsAsFactors = FALSE)
q$tqd <- as.Date(q$target_quarter_date); q <- q[!is.na(q$qoq_error), ]
qpc <- function(cut) { p <- q[q$tqd >= as.Date(cut), ]
  sprintf("v2 q-end(orig) from %s: n=%d RMSE=%.3f (all jt=%s)", cut, nrow(p),
          sqrt(mean(p$qoq_error^2)), paste(unique(p$n_months_in_quarter), collapse=",")) }
cat("\n=== existing quarter-end v2 (sanity ref for n_months=2) ===\n")
cat(qpc("2020-10-01"), "\n"); cat(qpc("2022-01-01"), "\n")
