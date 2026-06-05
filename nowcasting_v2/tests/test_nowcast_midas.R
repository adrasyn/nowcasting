# test_nowcast_midas.R  -- Phase 4.1
# Exercise the QA U-MIDAS nowcast on a FIXED historical slice and assert:
#   1. the nowcast is finite,
#   2. |qoq| < 5% (outside COVID), i.e. a sane growth figure,
#   3. reproducible (same input -> identical output),
#   4. implied level = prev_level * (1 + qoq/100).
# The pinned slice (as_of = 2019-08-15) lands mid-quarter (M2 of 2019 Q3) so it
# exercises the partial-quarter QA path (jt = 2), the headline live behaviour.

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

cat(sprintf("\n==> test_nowcast_midas: %s\n", if (pass) "PASS" else "FAIL"))
if (!pass) quit(status = 1L)
