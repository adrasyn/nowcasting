#### test_sync_nab_from_v2.R ####
# Tests for 03d_sync_nab_from_v2.R — the mirror that feeds the legacy v1 NAB CSV
# from the v2 survey scrape (nowcasting_v2/data_raw/nab_conf.csv).
#
# v2 is authoritative: v1 is overwritten in full. v1's old history was misaligned
# by one month across large parts of 2008-2014, so it is not preserved.
#
# The property that matters most here is the opposite of trust: a BROKEN v2 file
# must never be allowed to truncate or corrupt v1. Every validation failure has to
# leave v1 exactly as it was.
#
# Run from pipeline/ with:   Rscript tests/test_sync_nab_from_v2.R

suppressPackageStartupMessages({
  library(readr)
  library(dplyr)
  library(lubridate)
})

if (basename(getwd()) == "tests") setwd("..")
stopifnot(file.exists("run_complete_nowcast.R"))

source("03d_sync_nab_from_v2.R")

pass <- 0L
fail <- 0L
check <- function(label, ok) {
  if (isTRUE(ok)) {
    cat(sprintf("  ok   %s\n", label)); pass <<- pass + 1L
  } else {
    cat(sprintf("  FAIL %s\n", label)); fail <<- fail + 1L
  }
}

tmp <- tempfile("nabsync"); dir.create(tmp)
on.exit(unlink(tmp, recursive = TRUE), add = TRUE)
v1_path <- file.path(tmp, "v1.csv")
v2_path <- file.path(tmp, "v2.csv")

# A valid v2 file: long enough to clear NAB_SYNC_MIN_ROWS, first-of-month, in range.
months_seq <- seq(ymd("1997-03-01"), by = "month", length.out = 350)
good_v2 <- tibble(date = months_seq, value = rep(c(-5, 3, 12, -20, 0), length.out = 350))
write_valid_v2 <- function() write_csv(good_v2, v2_path)

# A small v1 file that disagrees with v2, standing in for the misaligned history.
write_old_v1 <- function() {
  write_csv(tibble(
    date  = c(ymd("2013-09-01"), ymd("2013-10-01"), ymd("2026-06-01")),
    value = c(6, 12, -5)   # the WRONG, one-month-late values
  ), v1_path)
}

read_v1 <- function() read_csv(v1_path, show_col_types = FALSE) |> mutate(date = ymd(date))

cat("\n== 1. v2 is mirrored in full ==\n")
write_valid_v2(); write_old_v1()
res <- sync_nab_from_v2(v1_path = v1_path, v2_path = v2_path, quiet = TRUE)
got <- read_v1()
check("returns every v2 row", nrow(res) == nrow(good_v2))
check("v1 now has v2's row count", nrow(got) == nrow(good_v2))
check("v1 values equal v2 values", identical(got$value, good_v2$value))
check("v1 dates equal v2 dates", identical(got$date, good_v2$date))

cat("\n== 2. the old misaligned v1 history is gone ==\n")
check("old wrong Sep-2013 value (6) removed", !any(got$date == ymd("2013-09-01") & got$value == 6))
check("no duplicate dates", sum(duplicated(got$date)) == 0)
check("dates ascending", all(diff(got$date) > 0))

cat("\n== 3. idempotent ==\n")
before <- readLines(v1_path)
sync_nab_from_v2(v1_path = v1_path, v2_path = v2_path, quiet = TRUE)
check("second run is byte-identical", identical(before, readLines(v1_path)))

cat("\n== 4. a BROKEN v2 must never destroy v1 ==\n")
# Each case writes a bad v2, then asserts v1 is untouched.
expect_v1_untouched <- function(label, bad_v2_tbl) {
  write_valid_v2(); write_old_v1()
  sync_nab_from_v2(v1_path = v1_path, v2_path = v2_path, quiet = TRUE)  # establish good state
  keep <- readLines(v1_path)
  write_csv(bad_v2_tbl, v2_path)
  out <- suppressWarnings(sync_nab_from_v2(v1_path = v1_path, v2_path = v2_path, quiet = TRUE))
  check(label, identical(keep, readLines(v1_path)) && nrow(out) == 0)
}
expect_v1_untouched("truncated scrape (5 rows) rejected", good_v2[1:5, ])
expect_v1_untouched("empty file rejected", good_v2[0, ])
expect_v1_untouched("duplicate dates rejected",
                    bind_rows(good_v2, good_v2[10, ]) |> arrange(date))
expect_v1_untouched("out-of-range values rejected",
                    good_v2 |> mutate(value = ifelse(row_number() == 5, 950, value)))
expect_v1_untouched("mid-month dates rejected",
                    good_v2 |> mutate(date = ifelse(row_number() == 5, date + 14, date) |> as.Date()))

cat("\n== 5. missing v2 leaves v1 alone and does not error ==\n")
write_valid_v2(); write_old_v1()
sync_nab_from_v2(v1_path = v1_path, v2_path = v2_path, quiet = TRUE)
keep <- readLines(v1_path)
out <- tryCatch(
  suppressWarnings(sync_nab_from_v2(v1_path = v1_path, v2_path = file.path(tmp, "gone.csv"), quiet = TRUE)),
  error = function(e) structure(list(), class = "errored")
)
check("missing v2 does not error", !inherits(out, "errored"))
check("missing v2 writes nothing", is.data.frame(out) && nrow(out) == 0)
check("v1 untouched", identical(keep, readLines(v1_path)))

cat("\n== 6. NA rows in v2 are dropped, not written ==\n")
write_csv(good_v2 |> mutate(value = ifelse(row_number() == 7, NA, value)), v2_path)
write_old_v1()
out <- sync_nab_from_v2(v1_path = v1_path, v2_path = v2_path, quiet = TRUE)
got <- read_v1()
check("NA month absent from v1", !any(got$date == good_v2$date[7]))
check("all other months present", nrow(got) == nrow(good_v2) - 1)
check("no NA values written", !any(is.na(got$value)))

cat(sprintf("\n---- %d passed, %d failed ----\n", pass, fail))
if (fail > 0) quit(status = 1)
