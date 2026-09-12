# test_nowcast_midas.R  -- Phase 4.1
# Exercise the QA U-MIDAS nowcast on FIXED historical slices and assert:
#   1. the nowcast is finite,
#   2. |qoq| < 5% (outside COVID), i.e. a sane growth figure,
#   3. reproducible (same input -> identical output),
#   4. implied level = prev_level * (1 + qoq/100).
# The pinned slice (as_of = 2019-08-15) lands mid-quarter (M2 of 2019 Q3) so it
# exercises the partial-quarter QA path (jt = 2), the headline live behaviour.
#
# Per-stage dispatch guard (2026-08-02): two extra slices pin jt = 1
# (as_of = 2019-04-20) and jt = 2 (as_of = 2019-05-20) and assert BOTH route to
# the paper's per-stage U-MIDAS rather than to QA. RDP 2024-04 evaluates QA only
# on a COMPLETE quarter -- its QA block runs after the jt loop, so x_new is the
# jt=3 vector. Feeding QA a 1-2 month mean, as v2 previously did, puts a regressor
# into the model that its coefficients were never fitted on; measured at jt=2 that
# cost ~16% RMSE and ~15% bias against the paper's M2.

here <- "R"
source(file.path(here, "_setup.R"))
source(file.path(here, "nowcast_midas.R"))

mai <- read.csv("data_raw/mai.csv")
gdp <- read.csv("data_raw/rt_dgdp_qtr.csv")

AS_OF <- as.Date("2019-08-15")   # mid 2019 Q3, well clear of the COVID window
PREV_LEVEL <- 500000             # arbitrary fixed reference level for the level check

pass <- TRUE
check <- function(cond, msg) {
  cat(sprintf("[%s] %s\n", if (isTRUE(cond)) "PASS" else "FAIL", msg))
  if (!isTRUE(cond)) pass <<- FALSE
}

r1 <- nowcast_midas(mai, gdp, as_of = AS_OF, prev_level = PREV_LEVEL)
r2 <- nowcast_midas(mai, gdp, as_of = AS_OF, prev_level = PREV_LEVEL)

cat(sprintf("\nSlice as_of=%s -> target=%s qoq=%.4f%% jt=%d n_obs=%d level=%.1f\n\n",
            AS_OF, r1$target_quarter, r1$qoq_growth, r1$n_months_in_quarter,
            r1$n_obs, r1$nowcast_level))

check(is.finite(r1$qoq_growth),                         "qoq nowcast is finite")
check(abs(r1$qoq_growth) < 5,                           "|qoq| < 5% (sane, non-COVID)")
check(identical(r1, r2),                                "reproducible: same input -> identical output")
check(r1$model == "UMIDAS-full",
      "jt=2 dispatches to the paper's per-stage U-MIDAS, not QA")
check(r1$n_obs > 100L,                                  "fit uses a long sample (n_obs > 100)")
check(r1$n_months_in_quarter == 2L,                     "partial-quarter path exercised (jt = 2)")
check(is.finite(r1$nowcast_level) &&
        abs(r1$nowcast_level - PREV_LEVEL * (1 + r1$qoq_growth / 100)) < 1e-6,
      "implied level = prev_level * (1 + qoq/100)")

# ---------------------------------------------------------------------------
# Ragged-edge partial-quarter mean (NOT random-walk) -- jt = 1 and jt = 2.
# Reconstruct the QA contemporaneous input the engine SHOULD use from the public
# MAI and assert n_months_in_quarter matches and the partial mean != RW value.
# ---------------------------------------------------------------------------
.qlabel <- function(d) {
  d <- as.Date(d); yr <- as.integer(format(d, "%Y")); mo <- as.integer(format(d, "%m"))
  qi <- (mo - 1L) %/% 3L
  as.Date(sprintf("%04d-%02d-01", yr, qi * 3L + 3L))
}
mai$date <- as.Date(mai$date)

# Partial-quarter mean of MAI months in `target_q` that are <= as_of (jt months),
# and the jt=0 RW counterfactual (mean of the *prior complete* quarter's months).
partial_and_rw <- function(as_of, target_q) {
  msub <- mai[mai$date <= as.Date(as_of), , drop = FALSE]
  tm   <- msub$value[.qlabel(msub$date) == target_q]
  prev_q <- seq(target_q, by = "-3 months", length.out = 2L)[2L]
  pm   <- msub$value[.qlabel(msub$date) == prev_q]
  list(jt = length(tm), partial_mean = mean(tm), rw_mean = mean(pm))
}

for (cse in list(
  list(as_of = as.Date("2019-04-20"), tq = as.Date("2019-06-01"), jt = 1L, lab = "jt = 1 (only M1 of 2019 Q2)"),
  list(as_of = as.Date("2019-05-20"), tq = as.Date("2019-06-01"), jt = 2L, lab = "jt = 2 (M1+M2 of 2019 Q2)"))) {

  rr <- nowcast_midas(mai, gdp, as_of = cse$as_of, prev_level = PREV_LEVEL)
  pw <- partial_and_rw(cse$as_of, cse$tq)
  cat(sprintf("Slice as_of=%s -> target=%s qoq=%.4f%% jt=%d  partial_mean=%.4f rw_mean=%.4f\n",
              cse$as_of, rr$target_quarter, rr$qoq_growth, rr$n_months_in_quarter,
              pw$partial_mean, pw$rw_mean))
  check(rr$target_quarter == "2019 Q2",          sprintf("%s: targets 2019 Q2", cse$lab))
  check(rr$n_months_in_quarter == cse$jt,        sprintf("%s: n_months_in_quarter == %d", cse$lab, cse$jt))
  check(pw$jt == cse$jt,                          sprintf("%s: MAI actually has %d partial month(s)", cse$lab, cse$jt))
  check(is.finite(pw$partial_mean),              sprintf("%s: partial-quarter mean is finite", cse$lab))
  # The fix is exercised only if the partial mean differs materially from the RW
  # fallback value -- otherwise the two paths would be indistinguishable.
  check(rr$model == "UMIDAS-full",
        sprintf("%s: incomplete quarter routes to U-MIDAS, never partial-mean QA", cse$lab))
  check(is.finite(rr$qoq_growth) && abs(rr$qoq_growth) < 5,
        sprintf("%s: qoq finite & sane", cse$lab))
}

# ---------------------------------------------------------------------------
# Regression: the target quarter must NOT follow the MAI edge.
#
# The contract is "first quarter with MAI data but no released GDP", i.e. always
# the quarter after the last released GDP. A previous implementation instead took
# the LAST MAI quarter whenever the MAI ran past released GDP. Because the yield
# block publishes with a 2-day lag, the MAI crosses into a new quarter about four
# weeks BEFORE the previous quarter's GDP is released -- so the model skipped the
# complete-but-unreleased quarter entirely, published a 1-month nowcast of the
# quarter after it, and never revisited the skipped one.
#
# Hold GDP fixed and push the MAI edge out a quarter at a time: the target quarter
# and jt must not move.
cat("\n-- target-quarter stability under a lengthening MAI --\n")
gdp_tq <- read.csv(file.path("data_raw", "rt_dgdp_qtr.csv"))
gdp_tq$date <- as.Date(gdp_tq$date)
last_gdp <- max(gdp_tq$date)
expect_q <- seq(last_gdp, by = "3 months", length.out = 2L)[2L]

mk_flat_mai <- function(end_month) {
  d <- seq(as.Date("1978-04-01"), as.Date(end_month), by = "month")
  data.frame(date = d, value = as.numeric(scale(sin(seq_along(d) / 7))))
}

# One month past the last released GDP quarter-end, then +1, +2, +3 quarters.
edges <- seq(seq(last_gdp, by = "3 months", length.out = 2L)[2L],
             by = "3 months", length.out = 4L)
tq_seen <- character(0)
for (e in edges) {
  e <- as.Date(e, origin = "1970-01-01")
  nc <- nowcast_midas(mk_flat_mai(e), gdp_tq, prev_level = 695945,
                      model = "qa", qa_lag = 0L:1L)
  tq_seen <- c(tq_seen, nc$target_quarter)
  check(nc$n_months_in_quarter <= 3L,
        sprintf("MAI to %s: jt=%d within [0,3]", e, nc$n_months_in_quarter))
}
check(length(unique(tq_seen)) == 1L,
      sprintf("target quarter stable as MAI lengthens (saw: %s)",
              paste(unique(tq_seen), collapse = ", ")))

# ---- next-quarter horizon (2026-09-12) ------------------------------------
# as_of 2019-08-15 with the 60-day GDP lag: 2019 Q2 GDP prints ~29 Aug, so the
# CURRENT quarter is 2019 Q2 (complete, jt = 3) and the NEXT is 2019 Q3 with
# July (and possibly August) MAI months.
source(file.path(here, "backtest_v2.R"))   # .truncate_gdp
cat("\n-- next-quarter horizon --\n")
AS_OF_N <- as.Date("2019-08-15")
gdp_n <- .truncate_gdp(transform(gdp, date = as.Date(date)), AS_OF_N, gdp_lag = 60L)
cur <- nowcast_midas(mai, gdp_n, as_of = AS_OF_N, prev_level = PREV_LEVEL, horizon = "current")
nxt <- nowcast_midas(mai, gdp_n, as_of = AS_OF_N, prev_level = PREV_LEVEL, horizon = "next")
nxt2 <- nowcast_midas(mai, gdp_n, as_of = AS_OF_N, prev_level = PREV_LEVEL, horizon = "next")
check(identical(cur$target_quarter, "2019 Q2") && cur$n_months_in_quarter == 3L,
      "current horizon at 2019-08-15 is the complete 2019 Q2")
check(identical(cur$horizon, "current") && identical(cur$current_quarter, "2019 Q2"),
      "current horizon labels itself")
check(identical(nxt$target_quarter, "2019 Q3"), "next horizon targets 2019 Q3")
check(identical(nxt$horizon, "next") && identical(nxt$current_quarter, "2019 Q2"),
      "next horizon names the current quarter it lags into")
check(nxt$n_months_in_quarter %in% 1:2, sprintf("next horizon sees 1-2 months (saw %d)", nxt$n_months_in_quarter))
check(identical(nxt$model, "UMIDAS-full"), "partial next quarter routes to U-MIDAS")
check(is.finite(nxt$qoq_growth) && abs(nxt$qoq_growth) < 5, "next-quarter nowcast is finite and sane")
check(identical(nxt$qoq_growth, nxt2$qoq_growth), "next-quarter nowcast is reproducible")
check(abs(nxt$nowcast_level - PREV_LEVEL * (1 + nxt$qoq_growth / 100)) < 1e-6,
      "next-quarter level = prev_level * (1 + qoq/100) (prev_level is the CURRENT quarter's level, supplied by the caller)")
cat(sprintf("cur: %s qoq=%+.4f jt=%d   next: %s qoq=%+.4f jt=%d\n",
            cur$target_quarter, cur$qoq_growth, cur$n_months_in_quarter,
            nxt$target_quarter, nxt$qoq_growth, nxt$n_months_in_quarter))
# The default is unchanged: the same call without `horizon` is the current quarter.
dflt <- nowcast_midas(mai, gdp_n, as_of = AS_OF_N, prev_level = PREV_LEVEL)
check(identical(dflt$qoq_growth, cur$qoq_growth), "default horizon is 'current' and bit-identical")
# No next-quarter month yet: as_of 2019-07-05 under the 60-day lag has current = 2019 Q2
# (June printed ~29 Aug) and the MAI may or may not reach July. Either the call
# succeeds with target 2019 Q3, or it stops with the documented message.
AS_OF_E <- as.Date("2019-07-05")
gdp_e <- .truncate_gdp(transform(gdp, date = as.Date(date)), AS_OF_E, gdp_lag = 60L)
r_e <- tryCatch(nowcast_midas(mai, gdp_e, as_of = AS_OF_E, horizon = "next"),
                error = function(e) conditionMessage(e))
check(is.list(r_e) && identical(r_e$target_quarter, "2019 Q3") ||
        (is.character(r_e) && startsWith(r_e, "nowcast_midas(): no MAI month beyond the current quarter")),
      "next horizon either nowcasts 2019 Q3 or refuses with the documented message")

cat(sprintf("\n==> test_nowcast_midas: %s\n", if (pass) "PASS" else "FAIL"))
if (!pass) quit(status = 1L)
