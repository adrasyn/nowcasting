#### test_sync_nab_from_v2.R ####
# Tests for 03d_sync_nab_from_v2.R — the append-only sync that feeds the legacy
# v1 NAB CSV from the v2 survey scrape (nowcasting_v2/data_raw/nab_conf.csv).
#
# The property that matters most: v1's HISTORY MUST NOT MOVE. The two series
# disagree on 83 of 347 overlapping months (a clean one-month misalignment
# across 2013-08..2014-08, plus ±1 aggregator noise), so rewriting history from
# v2 would silently shift the v1 nowcast and the published track record.
# The sync is therefore strictly append-forward.
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
    cat(sprintf("  ok   %s\n", label))
    pass <<- pass + 1L
  } else {
    cat(sprintf("  FAIL %s\n", label))
    fail <<- fail + 1L
  }
}

# Scratch files, cleaned up at exit
tmp <- tempfile("nabsync"); dir.create(tmp)
on.exit(unlink(tmp, recursive = TRUE), add = TRUE)
v1_path <- file.path(tmp, "v1.csv")
v2_path <- file.path(tmp, "v2.csv")

write_csv_rows <- function(path, dates, values) {
  write_csv(tibble(date = dates, value = values), path)
}

read_rows <- function(path) {
  read_csv(path, show_col_types = FALSE) |> mutate(date = ymd(date))
}

cat("\n== 1. appends only months strictly newer than v1's last row ==\n")
# v1 ends May; v2 runs to July AND disagrees with v1 on an existing month.
write_csv_rows(v1_path, c("2026-03-01", "2026-04-01", "2026-05-01"), c(-29, -24, -14))
write_csv_rows(v2_path,
  c("2026-03-01", "2026-04-01", "2026-05-01", "2026-06-01", "2026-07-01"),
  c(-29, -24, -99, -5, -6))  # -99 = deliberate conflict on an existing month

added <- sync_nab_from_v2(v1_path = v1_path, v2_path = v2_path)
res <- read_rows(v1_path)

check("returns the 2 new months", nrow(added) == 2)
check("v1 now ends 2026-07-01", max(res$date) == ymd("2026-07-01"))
check("July value came from v2 (-6)", res$value[res$date == ymd("2026-07-01")] == -6)
check("June value came from v2 (-5)", res$value[res$date == ymd("2026-06-01")] == -5)

cat("\n== 2. HISTORY IS FROZEN: existing rows are never overwritten ==\n")
check("May still -14, NOT v2's -99", res$value[res$date == ymd("2026-05-01")] == -14)
check("row count grew by exactly 2", nrow(res) == 5)
check("no duplicate dates introduced", sum(duplicated(res$date)) == 0)
check("dates remain ascending", all(diff(res$date) > 0))

cat("\n== 3. no-op when v1 is already current ==\n")
added2 <- sync_nab_from_v2(v1_path = v1_path, v2_path = v2_path)
res2 <- read_rows(v1_path)
check("nothing appended on second run", nrow(added2) == 0)
check("file unchanged (idempotent)", identical(res$value, res2$value))

cat("\n== 4. never backfills gaps inside v1's history ==\n")
# v1 is missing April entirely; v2 has it. A gap is history, not a new month.
write_csv_rows(v1_path, c("2026-03-01", "2026-05-01"), c(-29, -14))
sync_nab_from_v2(v1_path = v1_path, v2_path = v2_path)
res3 <- read_rows(v1_path)
check("April gap left alone", !any(res3$date == ymd("2026-04-01")))
check("still appended the new months", max(res3$date) == ymd("2026-07-01"))

cat("\n== 5. degrades safely when v2 is unavailable ==\n")
# Missing v2 must NOT crash the pipeline — the freshness guard downstream is
# what decides whether stale data is fatal.
write_csv_rows(v1_path, c("2026-03-01", "2026-04-01"), c(-29, -24))
added4 <- tryCatch(
  sync_nab_from_v2(v1_path = v1_path, v2_path = file.path(tmp, "does_not_exist.csv")),
  error = function(e) structure(list(), class = "sync_errored")
)
check("missing v2 does not error", !inherits(added4, "sync_errored"))
check("missing v2 appends nothing", is.data.frame(added4) && nrow(added4) == 0)
check("v1 left intact", max(read_rows(v1_path)$date) == ymd("2026-04-01"))

cat("\n== 6. ignores v2 rows with missing values ==\n")
write_csv_rows(v1_path, c("2026-03-01"), c(-29))
write_csv_rows(v2_path, c("2026-03-01", "2026-04-01", "2026-05-01"), c(-29, NA, -14))
sync_nab_from_v2(v1_path = v1_path, v2_path = v2_path)
res5 <- read_rows(v1_path)
check("NA month not appended", !any(res5$date == ymd("2026-04-01")))
check("later real month still appended", any(res5$date == ymd("2026-05-01")))

cat(sprintf("\n---- %d passed, %d failed ----\n", pass, fail))
if (fail > 0) quit(status = 1)
