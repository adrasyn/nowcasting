#### 03d_sync_nab_from_v2.R ####
# Keep the legacy v1 NAB Business Confidence CSV in step with the v2 survey scrape.
#
# WHY THIS EXISTS
# ---------------
# There were two NAB inputs, written by two different automations:
#
#   v1: pipeline/nab_business_confidence_raw.csv  <- a monthly Claude Desktop task
#                                                    that scraped investing.com
#   v2: nowcasting_v2/data_raw/nab_conf.csv       <- the weekly cloud routine, which
#                                                    reads NAB's own survey PDF
#
# The v1 task was deleted and replaced by the cloud routine, but that routine only
# writes the v2 files. This left v1 with no feeder. v1 then went stale in May, June
# and July 2026. Each time, the v1 freshness guard (03c) called stop(), and the v2
# workflow step is gated on `if: success()`. So a stale v1 CSV killed the whole
# weekly job, and the correct number was in nab_conf.csv the entire time. Issue #16.
#
# V2 IS AUTHORITATIVE
# -------------------
# v2 reads NAB's own published survey. v1 came from an aggregator, and v1 is WRONG.
# It records values one month too late across large parts of 2008 to 2014:
#
#   2008-03..2008-06   2008-10..2008-12   2009-02..2009-11   2010-02..2010-11
#   2011-01..2011-10   2011-12..2012-12   2013-02..2013-10   2013-12..2014-08
#
# 70 of the 89 months that disagreed are this one-month shift. Proof: NAB published
# business confidence of 12 for September 2013 and 5 for October 2013. v2 holds
# 12 and 5 on those months. v1 holds 6 and 12 — one month late.
#
# So this script MIRRORS v2 in full. It does not merge, and it does not preserve
# v1's history. The old history was misaligned, and the v1 model read NAB confidence
# a month late through the GFC and the recovery.
#
# KNOWN GAPS
# ----------
# v2 has no data for 2000-05, 2008-02, 2009-12 and 2010-12, which v1 did have. Those
# v1 values are NOT carried over: each sits on the edge of a shift run, so they are
# very likely a month out as well. Importing them would put known-bad values back in.
# Recovering those 4 months from NAB's own history is an open follow-up.
# The mirror also drops v1's duplicate rows for 2008-10, 2009-02 and 2010-12, which
# the loader never de-duplicated.

suppressPackageStartupMessages({
  library(readr)
  library(dplyr)
  library(lubridate)
})

# A broken or half-written scrape must never be allowed to truncate v1. The series
# starts in 1997, so a healthy v2 file always holds several hundred months.
NAB_SYNC_MIN_ROWS <- 300L
# NAB business confidence is a net-balance index. It reached about -66 in the worst
# of the 2020 shutdown, so this range is wide enough to pass real data and still
# catch a parse that returned page numbers or percentages.
NAB_SYNC_MIN_VALUE <- -80
NAB_SYNC_MAX_VALUE <- 80

#' Mirror the v2 NAB business confidence series into the legacy v1 CSV
#'
#' v2 is treated as authoritative: the v1 file is overwritten in full. The write
#' only happens if the v2 file passes validation, so a failed scrape leaves the
#' existing v1 file untouched rather than destroying it.
#'
#' @param v1_path Path to the legacy v1 CSV (date,value) — overwritten
#' @param v2_path Path to the v2 survey CSV (date,value) — read only
#' @param quiet Suppress progress messages
#' @return A tibble of the rows written (zero rows if the sync was skipped)
sync_nab_from_v2 <- function(v1_path = "nab_business_confidence_raw.csv",
                             v2_path = "../nowcasting_v2/data_raw/nab_conf.csv",
                             quiet = FALSE) {
  say <- function(...) if (!quiet) message(...)
  none <- tibble(date = as.Date(character()), value = numeric())

  say("  → Mirroring NAB confidence from the v2 scrape (v2 is authoritative)...")

  # A missing v2 file must not be fatal. If this leaves v1 stale, the freshness
  # guard in 03c is what decides that is an error. Two competing failure modes for
  # one condition would only confuse the next person to read a failed run.
  if (!file.exists(v2_path)) {
    warning(glue::glue("v2 NAB source not found at '{v2_path}' — v1 CSV left as-is."))
    say("    v2 source missing; v1 left unchanged.")
    return(none)
  }

  v2 <- tryCatch(
    read_csv(v2_path, show_col_types = FALSE) |>
      mutate(date = ymd(date), value = as.numeric(value)) |>
      filter(!is.na(date), !is.na(value)) |>
      arrange(date),
    error = function(e) {
      warning(glue::glue("Could not read v2 NAB source: {conditionMessage(e)}"))
      NULL
    }
  )
  if (is.null(v2)) {
    say("    v2 source unreadable; v1 left unchanged.")
    return(none)
  }

  # Validate before overwriting. Each check below has to pass or v1 stays as it is.
  problems <- character()
  if (nrow(v2) < NAB_SYNC_MIN_ROWS) {
    problems <- c(problems, glue::glue("only {nrow(v2)} rows (expected >= {NAB_SYNC_MIN_ROWS})"))
  }
  if (any(duplicated(v2$date))) {
    problems <- c(problems, glue::glue("{sum(duplicated(v2$date))} duplicate date(s)"))
  }
  if (any(day(v2$date) != 1)) {
    problems <- c(problems, "date(s) not on the first of the month")
  }
  out_of_range <- v2$value < NAB_SYNC_MIN_VALUE | v2$value > NAB_SYNC_MAX_VALUE
  if (any(out_of_range)) {
    problems <- c(problems, glue::glue("{sum(out_of_range)} value(s) outside [{NAB_SYNC_MIN_VALUE}, {NAB_SYNC_MAX_VALUE}]"))
  }

  if (length(problems) > 0) {
    warning(glue::glue(
      "v2 NAB source failed validation ({paste(problems, collapse = '; ')}) — v1 CSV left as-is."
    ))
    say("    v2 source failed validation; v1 left unchanged.")
    return(none)
  }

  # Report the change before making it, so a surprising rewrite is visible in the log.
  if (file.exists(v1_path)) {
    old <- tryCatch(
      read_csv(v1_path, show_col_types = FALSE) |> mutate(date = ymd(date), value = as.numeric(value)),
      error = function(e) NULL
    )
    if (!is.null(old) && nrow(old) > 0) {
      cmp <- dplyr::full_join(
        old |> select(date, old = value),
        v2  |> select(date, new = value),
        by = "date"
      )
      changed <- sum(!is.na(cmp$old) & !is.na(cmp$new) & cmp$old != cmp$new)
      dropped <- sum(is.na(cmp$new))
      gained  <- sum(is.na(cmp$old))
      say(glue::glue("    {changed} month(s) changed, {gained} added, {dropped} dropped."))
    }
  }

  write_csv(v2 |> select(date, value), v1_path)
  say(glue::glue(
    "    Wrote {nrow(v2)} month(s): {format(min(v2$date), '%b %Y')} to {format(max(v2$date), '%b %Y')}."
  ))
  v2 |> select(date, value)
}
