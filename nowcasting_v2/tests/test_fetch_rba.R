# testthat tests for the RBA Tier-1 CSV parser. Run:
#   Rscript nowcasting_v2/tests/test_fetch_rba.R
# Offline + deterministic: uses tests/fixtures/rba_*.csv.

root <- local({
  cand <- c("nowcasting_v2/R/_setup.R", "R/_setup.R", "../R/_setup.R")
  for (p in cand) if (file.exists(p)) return(normalizePath(dirname(dirname(p))))
  normalizePath(".")
})
source(file.path(root, "R", "_setup.R"))
suppressMessages({ library(testthat); library(dplyr) })
source(file.path(root, "R", "fetch", "fetch_rba_panel.R"))

fx <- function(f) file.path(root, "tests", "fixtures", f)
D2   <- fx("rba_d2.csv")
F2_1 <- fx("rba_f2_1_monthly.csv")
F1_1 <- fx("rba_f1_1_monthly.csv")
C1   <- fx("rba_c1.csv")

basic_checks <- function(out, lo, hi, min_n) {
  expect_named(out, c("date", "value"))
  expect_true(all(diff(out$date) > 0))
  expect_false(any(is.na(out$value)))
  expect_gte(nrow(out), min_n)
  expect_true(all(out$value >= lo & out$value <= hi))
  expect_true(all(format(out$date, "%d") == "01"))
}

test_that("parse_rba_csv errors on unknown series_id", {
  expect_error(parse_rba_csv(D2, "NOTASERIES"), "not found")
})

test_that("credit (D2, spliced Total credit $b) is long AND current", {
  out <- fetch_credit(src = D2, write = FALSE)
  basic_checks(out, 10, 1e5, 400)
  expect_true(min(out$date) <= as.Date("1990-01-01"))
  expect_true(max(out$date) >= as.Date("2025-01-01"))   # splice reaches present
  # no duplicate/gap at the 2019-07 splice boundary
  expect_true(as.Date("2019-06-01") %in% out$date)
  expect_true(as.Date("2019-07-01") %in% out$date)
})

test_that("credit_housing = owner-occ + investor (D2) parses", {
  out <- fetch_credit_housing(src = D2, write = FALSE)
  basic_checks(out, 10, 5e4, 200)
})

test_that("credit_business (D2 DLCACBN) parses", {
  out <- fetch_credit_business(src = D2, write = FALSE)
  basic_checks(out, 10, 5e4, 200)
})

test_that("AGS 3/5/10yr yields (F2.1) parse as % pa", {
  for (f in list(fetch_fcmygbag3, fetch_fcmygbag5, fetch_fcmygbag10)) {
    out <- f(src = F2_1, write = FALSE)
    basic_checks(out, -1, 20, 100)
  }
})

test_that("BBSW 90d (F1.1 FIRMMBAB90) parses with long history", {
  out <- fetch_firmmbab90(src = F1_1, write = FALSE)
  basic_checks(out, -1, 25, 400)
  expect_true(min(out$date) <= as.Date("1990-01-01"))
})

test_that("spread scrigbag3 = AGS3 - BBSW, plausible range", {
  out <- fetch_scrigbag3(f2src = F2_1, f1src = F1_1, write = FALSE)
  basic_checks(out, -8, 8, 100)
})

test_that("credit_card (C1 CCCCSTPVSA, value of purchases $m) parses", {
  out <- fetch_credit_card(src = C1, write = FALSE)
  basic_checks(out, 50, 6e4, 300)
})

cat("\n[test_fetch_rba] all RBA parser tests defined.\n")
