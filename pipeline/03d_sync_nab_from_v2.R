#### 03d_sync_nab_from_v2.R ####
# Keep the legacy v1 NAB Business Confidence CSV fed from the v2 survey scrape.
#
# WHY THIS EXISTS
# ---------------
# There were two NAB inputs maintained by two separate automations:
#
#   v1: pipeline/nab_business_confidence_raw.csv  <- monthly Claude Desktop task
#                                                    scraping investing.com
#   v2: nowcasting_v2/data_raw/nab_conf.csv       <- weekly routine reading NAB's
#                                                    own monthly survey PDF
#
# The v1 task died and missed Jun + Jul 2026. Because the v1 freshness guard
# (03c) hard-stops the run and the v2 workflow step is gated on `if: success()`,
# a stale v1 CSV killed the ENTIRE weekly job — including the v2 nowcast, the
# commit and the deploy — while the correct number was already sitting in
# nab_conf.csv, fetched from the primary source. See issue #16.
#
# One number, one fetcher. v1 now derives from v2 and the monthly task retires.
#
# WHY APPEND-ONLY (do not "simplify" this into a straight file copy)
# -----------------------------------------------------------------
# The two series do NOT agree historically: 83 of 347 overlapping months differ.
# Most of that is a clean one-month misalignment across 2013-08..2014-08 (there,
# v2[m] == v1[m+1] exactly); the rest is aggregator-vs-primary noise, ±1 in the
# modern era (2015+: 12 of 139 months differ, max 4).
#
# Rewriting v1's history from v2 would therefore silently move the v1 model's
# inputs and the published track record. So history is FROZEN: we only ever
# append months strictly newer than v1's last row, and never backfill gaps.
# That accepts a source seam at the join, which is the deliberate trade — a
# frozen past beats a series that stops dead every time a scraper dies.
#
# The 2013-14 misalignment is a real data bug in one of the two series and is
# NOT fixed here; fixing it means re-running the v1 backtest.

suppressPackageStartupMessages({
  library(readr)
  library(dplyr)
  library(lubridate)
})

#' Sync new NAB business confidence months from the v2 scrape into the v1 CSV
#'
#' Append-only: copies across just those months strictly newer than the v1
#' CSV's last row. Existing v1 values are never modified, and gaps inside v1's
#' history are never backfilled.
#'
#' @param v1_path Path to the legacy v1 CSV (date,value)
#' @param v2_path Path to the v2 survey CSV (date,value)
#' @param quiet Suppress progress messages
#' @return A tibble of the rows appended (zero rows if none / on failure)
sync_nab_from_v2 <- function(v1_path = "nab_business_confidence_raw.csv",
                             v2_path = "../nowcasting_v2/data_raw/nab_conf.csv",
                             quiet = FALSE) {
  say <- function(...) if (!quiet) message(...)
  none <- tibble(date = as.Date(character()), value = numeric())

  say("  → Syncing NAB confidence from the v2 scrape...")

  # A missing/unreadable v2 file must not be fatal here. If this leaves v1
  # stale, check_nab_data_freshness() in 03c is what decides that's an error —
  # we don't want two competing failure modes for the same condition.
  if (!file.exists(v2_path)) {
    warning(glue::glue("v2 NAB source not found at '{v2_path}' — v1 CSV left as-is."))
    say("    v2 source missing; nothing synced.")
    return(none)
  }

  v2 <- tryCatch(
    read_csv(v2_path, show_col_types = FALSE) |>
      mutate(date = ymd(date), value = as.numeric(value)) |>
      filter(!is.na(date), !is.na(value)),
    error = function(e) {
      warning(glue::glue("Could not read v2 NAB source: {conditionMessage(e)}"))
      NULL
    }
  )
  if (is.null(v2) || nrow(v2) == 0) {
    say("    v2 source unreadable or empty; nothing synced.")
    return(none)
  }

  if (!file.exists(v1_path)) {
    stop(glue::glue("v1 NAB CSV not found at: {v1_path}"))
  }
  v1 <- read_csv(v1_path, show_col_types = FALSE) |>
    mutate(date = ymd(date), value = as.numeric(value))

  if (nrow(v1) == 0) stop("v1 NAB CSV is empty — refusing to seed it from v2.")

  cutoff <- max(v1$date, na.rm = TRUE)
  new_rows <- v2 |>
    filter(date > cutoff) |>
    arrange(date) |>
    select(date, value)

  if (nrow(new_rows) == 0) {
    say(glue::glue("    Already current (v1 latest: {format(cutoff, '%B %Y')}); nothing to add."))
    return(none)
  }

  # Append in the file's existing shape: date,value / first-of-month / ascending.
  write_csv(new_rows, v1_path, append = TRUE, col_names = FALSE)

  say(glue::glue(
    "    Appended {nrow(new_rows)} month(s) from v2: {paste(format(new_rows$date, '%b %Y'), collapse = ', ')}"
  ))
  new_rows
}
