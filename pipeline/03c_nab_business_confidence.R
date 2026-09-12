#### Australian GDP Nowcasting - NAB Business Confidence Integration ####
# Purpose: Manage NAB Business Confidence data (manual updates)
# Author: James Wilson
# Date: 2026-01-01

#### Load dependencies ####
library(dplyr)
library(readr)
library(tibble)
library(lubridate)
library(glue)

#### NAB Business Confidence Functions ####

#' Load NAB Business Confidence data from CSV
#'
#' @param start_date Start date for filtering (default: "2000-01-01")
#' @param skip_freshness_check Skip data freshness validation (for backtesting)
#' @param grace_period_days Days after 2nd Tuesday before expecting data (default: 0)
#' @return Tibble with standardized columns: date, value, series_id, series_name
#' @details NAB releases data on the 2nd Tuesday of each month for the PREVIOUS month.
#'          Function will error if data is stale and skip_freshness_check = FALSE.
# SIX DAYS OF GRACE, NOT ZERO. NAB publishes on the second Tuesday, and the
# scheduled laptop routine that scrapes it (docs/cowork-weekly-refresh.md) runs
# on Sunday. With no grace, any run between the Tuesday and that Sunday -- a
# manual dispatch, or a quarter-month Tuesday-evening run that lands on the
# second Tuesday -- demanded data nobody had fetched yet and halted the whole
# job, v2 emit included (2026-09-12). Tuesday plus six is the following Monday,
# so the weekly Monday run still insists on the fresh month.
NAB_GRACE_PERIOD_DAYS <- 6L

load_nab_business_confidence <- function(start_date = "2000-01-01",
                                         skip_freshness_check = FALSE,
                                         grace_period_days = NAB_GRACE_PERIOD_DAYS) {
  message("Loading NAB Business Confidence data...")

  # Read the CSV file
  csv_path <- "nab_business_confidence_raw.csv"

  if (!file.exists(csv_path)) {
    stop(glue("NAB data file not found at: {csv_path}"))
  }

  # Read and standardize data
  data <- read_csv(csv_path, show_col_types = FALSE) |>
    mutate(
      date = ymd(date),
      value = as.numeric(value),
      series_id = "NAB_BUS_CONF",
      series_name = "NAB Business Confidence",
      unit = "Index",
      series_type = "NAB",
      indicator_id = "bus_conf",
      component_id = "I_priv",  # Business investment
      frequency = "monthly"
    ) |>
    filter(
      date >= ymd(start_date),
      !is.na(value)
    ) |>
    arrange(date)

  message(glue("  → Loaded {nrow(data)} observations from {min(data$date)} to {max(data$date)}"))
  message(glue("  → Latest value: {tail(data$value, 1)} ({tail(data$date, 1)})"))

  # Check data freshness
  check_nab_data_freshness(
    data = data,
    as_of_date = Sys.Date(),
    grace_period_days = grace_period_days,
    skip_check = skip_freshness_check
  )

  return(data)
}

#' Determine expected latest NAB data month based on release schedule
#'
#' @param as_of_date Date to check against (default: today)
#' @param grace_period_days Days after 2nd Tuesday before expecting data (default: 0)
#' @return List with expected_data_month, next_release_date, is_past_release
get_expected_nab_data_month <- function(as_of_date = Sys.Date(),
                                        grace_period_days = 0) {
  # NAB releases data on 2nd Tuesday of month for PREVIOUS month
  # Example: Jan 14 (2nd Tue of Jan) releases December data
  
  as_of_date <- ymd(as_of_date)
  current_year <- year(as_of_date)
  current_month <- month(as_of_date)
  
  # Calculate 2nd Tuesday of current month
  second_tuesday <- get_second_tuesday(current_year, current_month)
  
  # Add grace period
  release_cutoff <- second_tuesday + days(grace_period_days)
  
  if (as_of_date >= release_cutoff) {
    # We are past the 2nd Tuesday (+ grace), so previous month data should be available
    expected_data_month <- floor_date(as_of_date, "month") - months(1)
  } else {
    # We have not reached 2nd Tuesday yet, so TWO months ago should be latest
    expected_data_month <- floor_date(as_of_date, "month") - months(2)
  }
  
  return(list(
    expected_data_month = expected_data_month,
    next_release_date = second_tuesday,
    is_past_release = as_of_date >= release_cutoff
  ))
}

#' Check if NAB data is up to date based on release schedule
#'
#' @param data NAB data tibble with date column
#' @param as_of_date Date to check against (default: today)
#' @param grace_period_days Days after 2nd Tuesday before expecting data (default: 0)
#' @param skip_check Skip the freshness check (for backtesting)
#' @return invisible(TRUE) on success, stops with error if data is stale
check_nab_data_freshness <- function(data,
                                     as_of_date = Sys.Date(),
                                     grace_period_days = 0,
                                     skip_check = FALSE) {
  if (skip_check) {
    message("  → Data freshness check SKIPPED (skip_check = TRUE)")
    return(invisible(TRUE))
  }

  # Check if data is empty
  if (nrow(data) == 0) {
    stop("NAB data is empty")
  }

  # Get expected data availability
  expected <- get_expected_nab_data_month(
    as_of_date = as_of_date,
    grace_period_days = grace_period_days
  )

  # Get actual latest data month
  latest_data_date <- max(data$date, na.rm = TRUE)
  latest_data_month <- floor_date(latest_data_date, "month")

  # Check if data is fresh
  if (latest_data_month < expected$expected_data_month) {
    # DATA IS STALE!
    missing_months <- interval(latest_data_month, expected$expected_data_month) %/% months(1)

    # Format months for error message
    missing_month_list <- seq.Date(
      from = latest_data_month + months(1),
      to = expected$expected_data_month,
      by = "month"
    )
    missing_formatted <- paste(format(missing_month_list, "%B %Y"), collapse = ", ")

    stop(glue("
NAB Business Confidence data is OUT OF DATE!

Latest available data: {format(latest_data_date, '%B %Y')}
Expected latest data:  {format(expected$expected_data_month, '%B %Y')}
Missing {missing_months} month(s): {missing_formatted}

NAB releases data on the 2nd Tuesday of each month for the PREVIOUS month.
The 2nd Tuesday of {format(as_of_date, '%B %Y')} was {format(expected$next_release_date, '%B %d, %Y')}.

To update the data:
  1. Visit NAB Business Survey: https://business.nab.com.au/nab-monthly-business-survey/
  2. Find the Business Confidence Index value for {format(expected$expected_data_month, '%B %Y')}
  3. Update using: update_nab_data('{format(expected$expected_data_month, '%Y-%m-01')}', [VALUE])

To skip this check (e.g., for backtesting):
  load_nab_business_confidence(skip_freshness_check = TRUE)
    "))
  }

  # Data is fresh!
  message(glue("  → Data is UP TO DATE (latest: {format(latest_data_date, '%B %Y')})"))
  return(invisible(TRUE))
}

#' Calculate the second Tuesday of a given month
#'
#' @param year Year (numeric)
#' @param month Month (numeric, 1-12)
#' @return Date object for the second Tuesday
get_second_tuesday <- function(year, month) {
  # Get first day of the month
  first_day <- ymd(glue("{year}-{month}-01"))
  
  # Find day of week (1=Sunday, 2=Monday, 3=Tuesday, ..., 7=Saturday)
  first_dow <- wday(first_day)
  
  # Calculate days until first Tuesday
  days_to_first_tuesday <- (3 - first_dow) %% 7
  
  # First Tuesday + 7 days = Second Tuesday
  second_tuesday <- first_day + days(days_to_first_tuesday + 7)
  
  return(second_tuesday)
}

#' Update NAB Business Confidence with new data
#'
#' @param new_date Date of new observation (e.g., "2025-12-01")
#' @param new_value Value of business confidence
#' @return Updated dataset
update_nab_data <- function(new_date, new_value) {
  csv_path <- "nab_business_confidence_raw.csv"

  # Load existing data
  existing <- read_csv(csv_path, show_col_types = FALSE)

  # Create new row
  new_row <- tibble(
    date = ymd(new_date),
    value = as.numeric(new_value)
  )

  # Check if date already exists
  if (new_row$date %in% existing$date) {
    message(glue("Updating existing value for {new_date}"))
    existing <- existing |>
      filter(date != new_row$date)
  } else {
    message(glue("Adding new observation for {new_date}"))
  }

  # Combine and sort
  updated <- bind_rows(existing, new_row) |>
    arrange(date)

  # Save back to CSV
  write_csv(updated, csv_path)
  message(glue("  → Saved to {csv_path}"))
  message(glue("  → Total observations: {nrow(updated)}"))

  return(updated)
}

#' Fetch all manual indicators (NAB Business Confidence)
#'
#' @param start_date Start date for historical data
#' @param skip_freshness_check Skip data freshness validation (for backtesting)
#' @return List of data tibbles by indicator_id
fetch_all_manual_indicators <- function(start_date = "2000-01-01",
                                        skip_freshness_check = FALSE) {
  message("\n=== Loading Manual Indicators ===\n")

  manual_data <- list()

  # Load NAB Business Confidence
  message("[1/1] NAB Business Confidence")
  nab_data <- load_nab_business_confidence(
    start_date = start_date,
    skip_freshness_check = skip_freshness_check
  )
  manual_data[["bus_conf"]] <- nab_data

  message(glue("\n✓ Loaded {length(manual_data)} manual indicators"))

  return(manual_data)
}

#### Example Usage ####

if (FALSE) {
  # Load NAB data (with freshness check)
  nab_data <- load_nab_business_confidence()

  # Load NAB data for backtesting (skip freshness check)
  nab_data <- load_nab_business_confidence(skip_freshness_check = TRUE)

  # Update with new observation
  # (When NAB releases new data on 2nd Tuesday, run this:)
  update_nab_data(new_date = "2025-12-01", new_value = 1)

  # Test date calculation helpers
  get_second_tuesday(2026, 1)  # Returns 2026-01-14
  get_expected_nab_data_month("2026-01-15")  # Returns info about expected data

  # Combine with other data sources
  source("03_data_ingestion.R")
  source("03b_fetch_fred_data.R")

  abs_data <- fetch_all_abs_indicators(use_cache = TRUE)
  fred_data <- fetch_all_fred_indicators(use_cache = TRUE)
  manual_data <- fetch_all_manual_indicators()

  # Combine all three sources
  all_indicators <- c(abs_data, fred_data, manual_data)

  # Build master dataset
  master <- build_master_dataset(all_indicators)
  saveRDS(master, ".cache/processed/master_dataset_complete.rds")
}

message("\n=== NAB Business Confidence Integration Ready ===\n")
message("Functions available:")
message("  - load_nab_business_confidence() - Load NAB data from CSV")
message("  - update_nab_data() - Add new monthly observation")
message("  - fetch_all_manual_indicators() - Load all manual data sources")
message("\nData file:")
message("  - pipeline/nab_business_confidence_raw.csv")
message("\nTo update when NAB releases new data:")
message("  update_nab_data('2026-01-01', 5)  # Example: Jan 2026 = 5")
message("\nNAB releases: 2nd Tuesday of each month for PREVIOUS month")
message("  Example: December 2025 data released on Jan 14, 2026")
