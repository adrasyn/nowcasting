#### Tests for bias-aware CI bands ####
# Run: cd pipeline && Rscript tests/test_ci_bands.R
suppressMessages(library(testthat))
# Resolve ci_bands.R whether run from pipeline/ or pipeline/tests/.
ci_path <- if (file.exists("ci_bands.R")) "ci_bands.R" else "../ci_bands.R"
source(ci_path)

# Worked example = the Q1-2026 baseline r=3 nowcast + post-COVID error params.
QOQ  <- 0.7972761
BIAS <- 0.2174
SD   <- 0.2705

test_that("ci_qoq_band centers on the bias-corrected forecast", {
  b68 <- ci_qoq_band(QOQ, BIAS, SD, 1.0)
  expect_equal(b68$low,  0.3094, tolerance = 1e-3)
  expect_equal(b68$high, 0.8504, tolerance = 1e-3)
  b95 <- ci_qoq_band(QOQ, BIAS, SD, 1.96)
  expect_equal(b95$low,  0.0497, tolerance = 1e-3)
  expect_equal(b95$high, 1.1101, tolerance = 1e-3)
})

test_that("band is asymmetric about the displayed point (runs-hot)", {
  b68 <- ci_qoq_band(QOQ, BIAS, SD, 1.0)
  # the raw point sits inside the 68% band but above its centre...
  expect_true(QOQ > (b68$low + b68$high) / 2)
  expect_true(QOQ < b68$high && QOQ > b68$low)
  # ...so the interval extends much further below the point than above it.
  expect_gt(QOQ - b68$low, b68$high - QOQ)
})

test_that("ci_prev_level inverts the QoQ growth", {
  expect_equal(ci_prev_level(699574, QOQ), 699574 / (1 + QOQ/100), tolerance = 1e-6)
})

test_that("ci_level_band maps QoQ edges onto levels", {
  prev <- ci_prev_level(699574, QOQ)
  lv <- ci_level_band(QOQ, prev, BIAS, SD, 1.0)
  # level edges = prev * (1 + qoq_edge/100)
  expect_equal(lv$low,  round(prev * (1 + 0.3094/100)), tolerance = 1)
  expect_equal(lv$high, round(prev * (1 + 0.8504/100)), tolerance = 1)
  # realised Q1-2026 (+0.30% => 695945) lands at/below the 68% low edge:
  expect_lte(695945, lv$low + 200)   # within rounding of the lower edge
})

test_that("functions vectorise over multiple forecasts", {
  qoq <- c(0.8, 0.5, 1.2); prev <- c(700000, 690000, 695000)
  lv <- ci_level_band(qoq, prev, BIAS, SD, 1.0)
  expect_length(lv$low, 3); expect_length(lv$high, 3)
  expect_true(all(lv$high > lv$low))
})

cat("\nall ci_bands tests executed\n")
