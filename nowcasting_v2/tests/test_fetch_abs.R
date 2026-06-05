# testthat tests for the ABS Tier-1 parsers. Run:
#   Rscript nowcasting_v2/tests/test_fetch_abs.R
# Uses saved fixtures (tests/fixtures/abs_*.rds) so it is offline + deterministic.

root <- local({
  cand <- c("nowcasting_v2/R/_setup.R", "R/_setup.R", "../R/_setup.R")
  for (p in cand) if (file.exists(p)) return(normalizePath(dirname(dirname(p))))
  normalizePath(".")
})
source(file.path(root, "R", "_setup.R"))
suppressMessages({ library(testthat); library(dplyr) })
source(file.path(root, "R", "fetch", "fetch_abs_panel.R"))

fx  <- function(f) file.path(root, "tests", "fixtures", f)
lf  <- readRDS(fx("abs_6202_all.rds"))     # full 6202.0 catalogue
exf <- readRDS(fx("abs_export.rds"))       # A2718577A
rtf <- readRDS(fx("abs_8501_t1.rds"))      # 8501.0 table 1
hpf <- readRDS(fx("abs_6416.rds"))         # 6416.0 RPPI

check_series <- function(df, series_id, min_first, min_n, lo, hi, sa = TRUE) {
  src <- if (sa) df |> dplyr::filter(.data$series_type == "Seasonally Adjusted") else df
  out <- parse_abs_series(src, series_id)
  expect_named(out, c("date", "value"))
  expect_true(all(diff(out$date) > 0))                       # strictly sorted
  expect_false(any(is.na(out$value)))
  expect_gte(nrow(out), min_n)
  expect_true(min(out$date) <= as.Date(min_first))           # history >= target
  expect_true(all(out$value >= lo & out$value <= hi))        # plausible range
  expect_true(all(format(out$date, "%d") == "01"))           # first-of-month
  out
}

test_that("emp (Employed total Persons SA) parses, level in '000", {
  check_series(lf, "A84423043C", "2005-01-01", 240, 5000, 20000)
})
test_that("ft_emp parses", {
  check_series(lf, "A84423041X", "2005-01-01", 240, 4000, 15000)
})
test_that("pt_emp parses", {
  check_series(lf, "A84423042A", "2005-01-01", 240, 800, 8000)
})
test_that("ue is a RATE in percent (0,30)", {
  out <- check_series(lf, "A84423050A", "2005-01-01", 240, 0, 30)
  expect_lt(median(out$value), 15)
})
test_that("ud (underemployed total SA) is a level in '000", {
  check_series(lf, "A85255719L", "2005-01-01", 200, 100, 3000)
})
test_that("hours worked parses (large '000 hours)", {
  check_series(lf, "A84426277X", "2005-01-01", 200, 800000, 3000000)
})
test_that("export (total goods credits SA, $m) parses", {
  check_series(exf, "A2718577A", "2005-01-01", 240, 300, 80000)
})
test_that("rt (retail turnover total SA, $m) parses with long history", {
  out <- check_series(rtf, "A3348585R", "2005-01-01", 240, 3000, 60000)
  expect_true(min(out$date) <= as.Date("1990-01-01"))
})
test_that("house_prices RPPI 8-cap parses (index) but is discontinued", {
  out <- check_series(hpf, "A83728455L", "2005-01-01", 50, 30, 300, sa = FALSE)
  expect_true(max(out$date) < as.Date("2023-01-01"))   # confirms discontinuation
})

cat("\n[test_fetch_abs] all ABS parser tests defined.\n")
