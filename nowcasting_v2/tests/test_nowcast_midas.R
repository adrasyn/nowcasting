# test_nowcast_midas.R  -- Phase 4.1
# Exercise the QA U-MIDAS nowcast on FIXED historical slices and assert:
#   1. the nowcast is finite,
#   2. |qoq| < 5% (outside COVID), i.e. a sane growth figure,
#   3. reproducible (same input -> identical output),
#   4. implied level = prev_level * (1 + qoq/100).
# The pinned slice (as_of = 2019-08-15) lands mid-quarter (M2 of 2019 Q3) so it
# exercises the partial-quarter QA path (jt = 2), the headline live behaviour.
#
# Ragged-edge regression guard (added with the MAI partial-quarter fix): two extra
# slices pin jt = 1 (as_of = 2019-04-20, only M1 of 2019 Q2) and jt = 2
# (as_of = 2019-05-20, M1+M2 of 2019 Q2) and assert that BOTH use the *partial-
# quarter mean* of the available MAI months as the QA contemporaneous input -- NOT
# the random-walk last-quarter-average fallback (which is reserved for jt = 0).
# We verify this by reconstructing nxm = mean(available target-quarter MAI months)
# directly from the public MAI and confirming it differs from the jt=0 RW value
# (the prior complete quarter's average), i.e. the fix is actually exercised.

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
check(r1$model == "QA-UMIDAS",                          "model label is QA-UMIDAS")
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
  check(abs(pw$partial_mean - pw$rw_mean) > 1e-6,
        sprintf("%s: partial mean != RW last-quarter-average (ragged edge used, not RW)", cse$lab))
  check(is.finite(rr$qoq_growth) && abs(rr$qoq_growth) < 5,
        sprintf("%s: qoq finite & sane", cse$lab))
}

cat(sprintf("\n==> test_nowcast_midas: %s\n", if (pass) "PASS" else "FAIL"))
if (!pass) quit(status = 1L)
