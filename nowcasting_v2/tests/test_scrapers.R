#### Tests for Tier-2 scrapers (NAB full suite, ANZ Job Ads, ANZ-RM Consumer ####
#### Confidence). Run from nowcasting_v2/:  Rscript tests/test_scrapers.R       ####
#
# These tests validate the PARSERS against cached fixtures (no network). They
# assert known-good values hand-verified against the raw PDF/HTML text, so a
# regex regression is caught. Per the prime directive we test that the parsers
# extract REAL numbers correctly — never that they invent anything.

local({
  for (p in c("R/_setup.R", "../R/_setup.R", "nowcasting_v2/R/_setup.R"))
    if (file.exists(p)) { source(p); break }
})
suppressMessages(library(testthat))

# Resolve repo-relative roots whether run from nowcasting_v2/ or repo root.
ROOT <- if (dir.exists("R/fetch")) "." else if (dir.exists("nowcasting_v2/R/fetch")) "nowcasting_v2" else "."
source(file.path(ROOT, "R/fetch/scrape_nab_full.R"))
source(file.path(ROOT, "R/fetch/scrape_anz_ivi.R"))
FIX_NAB <- file.path(ROOT, "tests/fixtures/nab")
FIX_ANZ <- file.path(ROOT, "tests/fixtures/anz")

get_val <- function(df, d) df$value[df$date == as.Date(d)]

# ---------------------------------------------------------------------------
test_that("NAB quarterly appendix parses all 8 sub-indices with correct values", {
  q <- parse_nab_quarterly_full(file.path(FIX_NAB, "nab_quarterly_2026q1.pdf"))
  expect_setequal(unique(q$id),
                  c("nab_conf","nab_cond","nab_trade","nab_profit",
                    "nab_emp","nab_forward","nab_stocks","nab_cu"))
  # Hand-verified against the 2026q1 Data Appendix (2025m10..2026m2 columns).
  pick <- function(id, d) q$value[q$id == id & q$date == as.Date(d)]
  expect_equal(pick("nab_conf",   "2026-02-01"), -1)
  expect_equal(pick("nab_cond",   "2025-10-01"), 11)
  expect_equal(pick("nab_trade",  "2025-12-01"), 17)
  expect_equal(pick("nab_profit", "2025-10-01"), 10)
  expect_equal(pick("nab_emp",    "2026-01-01"), 5)
  expect_equal(pick("nab_forward","2026-02-01"), 6)
  expect_equal(pick("nab_stocks", "2025-12-01"), 11)
  expect_equal(pick("nab_cu",     "2026-02-01"), 82.8)
})

test_that("NAB quarterly values are stable across an older fixture (2023q2)", {
  q <- parse_nab_quarterly_full(file.path(FIX_NAB, "nab_quarterly_2023q2.pdf"))
  pick <- function(id, d) q$value[q$id == id & q$date == as.Date(d)]
  # From the 2023q2 appendix (2023m2..2023m6).
  expect_equal(pick("nab_cond",   "2023-02-01"), 19)
  expect_equal(pick("nab_conf",   "2023-06-01"), 0)
  expect_equal(pick("nab_forward","2023-05-01"), -5)
  expect_equal(pick("nab_cu",     "2023-02-01"), 85.3)
})

test_that("NAB monthly Table 1 parses all 8 sub-indices (clean 2026_04 table)", {
  m <- parse_nab_monthly_full(file.path(FIX_NAB, "nab_monthly_2026_04.pdf"))
  pick <- function(id, d) m$value[m$id == id & m$date == as.Date(d)]
  expect_equal(pick("nab_conf",   "2026-04-01"), -24)
  expect_equal(pick("nab_cond",   "2026-04-01"), 3)
  expect_equal(pick("nab_trade",  "2026-04-01"), 7)
  expect_equal(pick("nab_profit", "2026-04-01"), 0)
  expect_equal(pick("nab_emp",    "2026-04-01"), 1)
  expect_equal(pick("nab_forward","2026-04-01"), -5)
  expect_equal(pick("nab_stocks", "2026-04-01"), 4)
  expect_equal(pick("nab_cu",     "2026-04-01"), 82.5)
})

test_that("NAB letter-spaced 2023_07 table is NOT mis-parsed (table empty)", {
  # The 2023_07 monthly Table 1 is letter-spaced ("B usiness co nfidence"); the
  # clean-table parser must return 0 rows rather than emit garbage.
  m <- parse_nab_monthly_full(file.path(FIX_NAB, "nab_monthly_2023_07.pdf"))
  expect_equal(nrow(m), 0)
})

test_that("NAB assembly chains quarterly + monthly into gap-light series", {
  res <- assemble_nab_full(
    monthly_paths   = list.files(FIX_NAB, "^nab_monthly_.*pdf$", full.names = TRUE),
    quarterly_paths = list.files(FIX_NAB, "^nab_quarterly_.*pdf$", full.names = TRUE),
    live = FALSE)
  for (id in c("nab_conf","nab_cond","nab_trade","nab_profit",
               "nab_emp","nab_forward","nab_cu")) {
    df <- res$series[[id]]
    expect_gt(nrow(df), 30)                       # >2.5y monthly coverage
    expect_false(anyDuplicated(df$date) > 0)      # one obs per month
    expect_true(all(diff(df$date) > 0))           # sorted ascending
  }
  # No revision conflict: quarterly (revised) must win over monthly bullet.
  expect_equal(get_val(res$series$nab_cond, "2026-04-01"), 3)
})

# ---------------------------------------------------------------------------
test_that("ANZ Job Ads PDF parses the SA index level series", {
  a <- parse_anz_ads(file.path(FIX_ANZ, "anz_jobads_2026_03.pdf"))
  expect_gt(nrow(a), 50)
  expect_false(anyDuplicated(a$date) > 0)
  # Hand-verified SA-index values from the page-2 table.
  expect_equal(get_val(a, "2026-03-01"), 114.6)
  expect_equal(get_val(a, "2026-02-01"), 118.2)
  expect_equal(get_val(a, "2021-01-01"), 95.0)
  expect_true(all(a$value > 40 & a$value < 220))
})

test_that("ANZ-Roy Morgan monthly ratings parse with footnotes stripped", {
  s <- parse_anz_sent(file.path(FIX_ANZ, "rm_cc_monthly.html"))
  expect_gt(nrow(s), 500)                          # 1973+ monthly history
  expect_false(anyDuplicated(s$date) > 0)
  # "66.5**" (incomplete-month footnote) must parse to 66.5, not 665 / NA.
  expect_equal(get_val(s, "2026-05-01"), 66.5)
  expect_equal(get_val(s, "2026-04-01"), 63.6)
  expect_equal(get_val(s, "2025-12-01"), 84.4)
  expect_true(all(s$value > 50 & s$value < 150))
})

cat("\nAll Tier-2 scraper tests completed.\n")
