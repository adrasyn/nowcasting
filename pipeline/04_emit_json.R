#### Emit JSON artifacts for the website ####
# Writes the 5 JSON files consumed by the Next.js site at nowcast.wlsn.me.
#
# Contract (must match src/lib/types.ts):
#   - latest.json       — headline
#   - gdp.json          — historical GDP actuals
#   - nowcasts.json     — every weekly vintage ever saved
#   - indicators.json   — 12 monthly indicator series
#   - performance.json  — accuracy scorecard
#
# Called from run_complete_nowcast.R after the nowcast + vintage save.

library(jsonlite)
library(dplyr)
library(lubridate)
library(readr)
library(tidyr)

# Bias-aware empirical CI bands (replaces the old hardcoded +/-0.7%/+/-1.4%).
source(if (file.exists("ci_bands.R")) "ci_bands.R" else "pipeline/ci_bands.R")

#### Indicator name mapping (R wide-column → website JSON id) ####
# The R pipeline uses one naming convention; the JSON contract uses another.
# Keep this in lock-step with src/lib/types.ts and data/indicators.json.
INDICATOR_ID_MAP <- c(
  employment    = "employment",
  unemp_rate    = "unemp_rate",
  participation = "part_rate",
  hours_worked  = "hours_worked",
  household_spending = "household_spending",
  cons_conf     = "cons_conf",
  building_app  = "building_approvals",
  bus_conf      = "bus_conf",
  exports_goods = "goods_exp",
  exports_servs = "services_exp",
  imports_goods = "goods_imp",
  imports_servs = "services_imp"
)

INDICATOR_GROUPS <- list(
  Labour   = c("employment", "unemp_rate", "part_rate", "hours_worked"),
  Consumer = c("household_spending", "cons_conf"),
  Business = c("building_approvals", "bus_conf"),
  External = c("goods_exp", "services_exp", "goods_imp", "services_imp")
)

INDICATOR_META <- list(
  employment         = list(name = "Employment",            unit = "persons",           source = "ABS Labour Force Survey"),
  unemp_rate         = list(name = "Unemployment Rate",     unit = "percent",           source = "ABS Labour Force Survey"),
  part_rate          = list(name = "Participation Rate",    unit = "percent",           source = "ABS Labour Force Survey"),
  hours_worked       = list(name = "Hours Worked",          unit = "hours (thousands)", source = "ABS Labour Force Survey"),
  household_spending = list(name = "Household Spending",    unit = "$ millions",        source = "ABS Monthly Household Spending Indicator"),
  cons_conf          = list(name = "Consumer Confidence",   unit = "index",             source = "OECD via FRED"),
  building_approvals = list(name = "Building Approvals",    unit = "count",             source = "ABS Building Approvals"),
  bus_conf           = list(name = "Business Confidence",   unit = "index",             source = "NAB Monthly Business Survey"),
  goods_exp          = list(name = "Goods Exports",         unit = "$ millions",        source = "ABS International Trade"),
  services_exp       = list(name = "Services Exports",      unit = "$ millions",        source = "ABS International Trade"),
  goods_imp          = list(name = "Goods Imports",         unit = "$ millions",        source = "ABS International Trade"),
  services_imp       = list(name = "Services Imports",      unit = "$ millions",        source = "ABS International Trade")
)

# Per-indicator release-date rule. Used as a fallback when the ABS
# latest-release scrape (04b_release_calendar_fetch.R) can't reach the page.
# Each rule yields the expected release date for a given reference period:
#
#   month_offset : how many months past the reference period the release
#                  falls (Labour Force = N+1; MHSI = N+2; quarterly BoP/GDP
#                  use the quarter-end month as N).
#   weekday      : 1=Mon, 2=Tue, 3=Wed, 4=Thu, 5=Fri (NA → use lag_days).
#   occurrence   : nth occurrence of that weekday in the offset month.
#   lag_days     : fallback for non-ABS indicators where the publisher
#                  doesn't lock to a weekday (cons_conf via FRED).
#
# These match the ABS calendar at the time of writing (May 2026); ABS shifts
# dates around public holidays and operational tweaks, so the scrape in
# 04b_release_calendar_fetch.R is preferred — this rule is only the fallback.
INDICATOR_RELEASE_RULE <- list(
  employment         = list(month_offset = 1, weekday = 4, occurrence = 3),  # 3rd Thu of N+1
  unemp_rate         = list(month_offset = 1, weekday = 4, occurrence = 3),
  part_rate          = list(month_offset = 1, weekday = 4, occurrence = 3),
  hours_worked       = list(month_offset = 1, weekday = 4, occurrence = 3),
  household_spending = list(month_offset = 2, weekday = 2, occurrence = 1),  # 1st Tue of N+2
  cons_conf          = list(month_offset = 1, weekday = NA, lag_days = 5),    # FRED — variable
  building_approvals = list(month_offset = 2, weekday = 1, occurrence = 1),  # 1st Mon of N+2 (approx)
  bus_conf           = list(month_offset = 1, weekday = 2, occurrence = 2),  # NAB 2nd Tue of N+1
  goods_exp          = list(month_offset = 2, weekday = 4, occurrence = 1),  # 1st Thu of N+2
  goods_imp          = list(month_offset = 2, weekday = 4, occurrence = 1),
  services_exp       = list(month_offset = 3, weekday = 2, occurrence = 1, anchor = "quarter_end"),
  services_imp       = list(month_offset = 3, weekday = 2, occurrence = 1, anchor = "quarter_end")
)

# Frequency per indicator — used to compute "next release" spacing (monthly
# series → +1 month; quarterly series → +3 months).
INDICATOR_FREQUENCY <- c(
  employment         = "monthly",
  unemp_rate         = "monthly",
  part_rate          = "monthly",
  hours_worked       = "monthly",
  household_spending = "monthly",
  cons_conf          = "monthly",
  building_approvals = "monthly",
  bus_conf           = "monthly",
  goods_exp          = "monthly",
  services_exp       = "quarterly",
  goods_imp          = "monthly",
  services_imp       = "quarterly"
)

#### Release-date calculation ####
# ABS releases quarterly GDP on the first Wednesday of the month 3 months after
# the quarter ends. e.g. Q1 ends Mar → release in Jun; Q4 ends Dec → release in Mar (of following year).
gdp_release_date <- function(quarter_str) {
  parts <- strsplit(quarter_str, " Q", fixed = TRUE)[[1]]
  if (length(parts) != 2) return(NA)
  yr <- suppressWarnings(as.integer(parts[1]))
  q  <- suppressWarnings(as.integer(parts[2]))
  if (is.na(yr) || is.na(q) || !(q %in% 1:4)) return(NA)
  quarter_end_month <- q * 3L          # Q1→3, Q2→6, Q3→9, Q4→12
  release_month <- quarter_end_month + 3L
  release_year  <- yr
  if (release_month > 12L) {
    release_month <- release_month - 12L
    release_year  <- yr + 1L
  }
  month_start <- as.Date(sprintf("%d-%02d-01", release_year, release_month))
  first_dow   <- as.numeric(format(month_start, "%w"))  # 0=Sun, 3=Wed
  days_to_wed <- (3L - first_dow) %% 7L
  month_start + days_to_wed
}

date_to_quarter <- function(d) sprintf("%d Q%d", year(d), quarter(d))

# Source the ABS release-calendar scraper (sibling file). Tolerate being
# called from either repo root or the pipeline/ directory.
local({
  candidates <- c(
    "pipeline/04b_release_calendar_fetch.R",
    "04b_release_calendar_fetch.R"
  )
  hit <- candidates[file.exists(candidates)][1]
  if (!is.na(hit)) source(hit, local = FALSE)
})

#' nth occurrence of a given weekday in a given month.
#' @param weekday 1=Mon, 2=Tue, ..., 7=Sun (ISO).
nth_weekday_of_month <- function(year, month, weekday, occurrence) {
  month_start <- as.Date(sprintf("%d-%02d-01", year, month))
  # `as.POSIXlt(d)$wday` is 0=Sun..6=Sat. Convert to ISO 1=Mon..7=Sun.
  iso_dow <- function(d) { w <- as.POSIXlt(d)$wday; if (w == 0) 7L else as.integer(w) }
  first_dow <- iso_dow(month_start)
  offset_to_first <- (weekday - first_dow) %% 7
  month_start + offset_to_first + 7 * (occurrence - 1)
}

#' Apply the per-indicator weekday rule to compute an expected release date.
#' Returns Date or NA. Does not handle public-holiday shifts — that's why
#' the scraped calendar is preferred.
release_date_from_rule <- function(json_id, ref_year, ref_month) {
  rule <- INDICATOR_RELEASE_RULE[[json_id]]
  if (is.null(rule)) return(as.Date(NA))
  rel_month <- ref_month + rule$month_offset
  rel_year  <- ref_year
  while (rel_month > 12L) { rel_month <- rel_month - 12L; rel_year <- rel_year + 1L }

  if (is.null(rule$weekday) || is.na(rule$weekday)) {
    # Fallback: lag_days from end of reference month.
    ref_end <- ceiling_date(as.Date(sprintf("%d-%02d-01", ref_year, ref_month)),
                            "month") - days(1)
    return(ref_end + days(rule$lag_days))
  }
  nth_weekday_of_month(rel_year, rel_month, rule$weekday, rule$occurrence)
}

#' Compute (last_release_date, next_release_estimate) for a given indicator.
#'
#' Preference order:
#'   1. Scraped ABS calendar (if a row is present and dates are non-NA).
#'   2. Per-indicator weekday rule applied to the latest reference period
#'      (and the next reference period for `next_release_estimate`).
#'   3. NA.
#'
#' If the rule-derived `next_release_estimate` is already in the past
#' (because we haven't yet ingested the data ABS has already published),
#' ratchet it forward one period at a time until it is in the future.
compute_release_dates <- function(json_id, last_ref_month, abs_calendar = NULL) {
  scraped <- if (!is.null(abs_calendar)) {
    abs_calendar |> filter(json_id == !!json_id) |> head(1)
  } else NULL

  scraped_last <- if (!is.null(scraped) && nrow(scraped) == 1) scraped$last_release_date else as.Date(NA)
  scraped_next <- if (!is.null(scraped) && nrow(scraped) == 1) scraped$next_release_estimate else as.Date(NA)

  if (is.na(last_ref_month)) {
    return(list(
      last  = if (!is.na(scraped_last)) format(scraped_last, "%Y-%m-%d") else NA_character_,
      next_ = if (!is.na(scraped_next)) format(scraped_next, "%Y-%m-%d") else NA_character_
    ))
  }

  parts <- strsplit(last_ref_month, "-", fixed = TRUE)[[1]]
  y <- as.integer(parts[1]); m <- as.integer(parts[2])

  rule_last <- release_date_from_rule(json_id, y, m)

  step_months <- if (!is.null(INDICATOR_FREQUENCY[[json_id]]) &&
                     INDICATOR_FREQUENCY[[json_id]] == "quarterly") 3L else 1L
  next_y <- y; next_m <- m + step_months
  while (next_m > 12L) { next_m <- next_m - 12L; next_y <- next_y + 1L }
  rule_next <- release_date_from_rule(json_id, next_y, next_m)

  # Ratchet rule_next forward if it's already in the past.
  today <- Sys.Date()
  while (!is.na(rule_next) && rule_next < today) {
    next_m <- next_m + step_months
    while (next_m > 12L) { next_m <- next_m - 12L; next_y <- next_y + 1L }
    rule_next <- release_date_from_rule(json_id, next_y, next_m)
    if (is.na(rule_next)) break
  }

  final_last <- if (!is.na(scraped_last)) scraped_last else rule_last
  final_next <- if (!is.na(scraped_next)) scraped_next else rule_next

  list(
    last  = if (!is.na(final_last)) format(final_last, "%Y-%m-%d") else NA_character_,
    next_ = if (!is.na(final_next)) format(final_next, "%Y-%m-%d") else NA_character_
  )
}

#### Main emitter ####
#' Write the 5 JSON artifacts consumed by the Next.js site.
#'
#' @param target_dir Destination directory (e.g. "../data" when called from
#'   pipeline/).
#' @param nowcast    Output of `generate_nowcast()` — a list with
#'   `target_quarter`, `nowcast_value`, `qoq_growth`, `yoy_growth`,
#'   `latest_actual_quarter`, `latest_actual_value`.
#' @param master     Output of `build_master_dataset()` — list with `$wide`
#'   and `$long` tibbles.
#' @param vintage_info Output of `save_vintage()` — list containing
#'   `vintage_id` and `file_path`. Used to locate `vintage_tracking.csv`.
#' @return invisible(NULL). Side effect: writes 5 .json files to target_dir.
emit_json <- function(target_dir, nowcast, master, vintage_info) {
  dir.create(target_dir, showWarnings = FALSE, recursive = TRUE)

  # Read the vintage tracking CSV FIRST. The most recent row is the canonical
  # "latest nowcast" — it's what the pipeline most recently produced.
  # We fall back to the passed-in `nowcast` arg only if no vintages exist yet.
  vintage_csv <- file.path(VINTAGE_BASE_DIR, "vintage_tracking.csv")
  latest_vintage <- if (file.exists(vintage_csv)) {
    vraw_all <- read_csv(vintage_csv, show_col_types = FALSE)
    if (nrow(vraw_all) > 0) {
      vraw_all |>
        mutate(run_timestamp_dt = as.POSIXct(run_timestamp, tz = "UTC")) |>
        arrange(desc(run_timestamp_dt)) |>
        slice(1)
    } else NULL
  } else NULL

  # Use the latest vintage if we have one; otherwise the legacy RDS.
  if (!is.null(latest_vintage)) {
    target_quarter        <- as.character(latest_vintage$target_quarter)
    point_value           <- round(as.numeric(latest_vintage$nowcast_value))
    qoq_growth_pct        <- round(as.numeric(latest_vintage$qoq_growth), 2)
    yoy_growth_pct        <- round(as.numeric(latest_vintage$yoy_growth), 2)
    latest_actual_value   <- round(as.numeric(latest_vintage$latest_actual_value))
    data_through_date     <- as.Date(latest_vintage$data_as_of_date)
  } else {
    target_quarter        <- nowcast$target_quarter
    point_value           <- round(as.numeric(nowcast$nowcast_value))
    qoq_growth_pct        <- round(as.numeric(nowcast$qoq_growth), 2)
    yoy_growth_pct        <- round(as.numeric(nowcast$yoy_growth), 2)
    latest_actual_value   <- round(as.numeric(nowcast$latest_actual_value))
    data_through_date     <- max(master$wide$date, na.rm = TRUE)
  }

  next_release <- gdp_release_date(target_quarter)

  # Build a tidy GDP series from master$wide (for gdp.json, the headline reference,
  # and performance actuals).
  gdp_wide <- master$wide |>
    select(date, value = gdp_quarterly) |>
    filter(!is.na(value)) |>
    arrange(date) |>
    mutate(
      qoq_pct = (value / lag(value) - 1) * 100,
      yoy_pct = (value / lag(value, 4) - 1) * 100,
      quarter = vapply(date, date_to_quarter, character(1))
    )

  # Derive the latest actual's quarter + QoQ from the most recent published GDP row.
  latest_actual_row <- if (nrow(gdp_wide) > 0) tail(gdp_wide, 1) else NULL
  latest_actual_quarter <- if (!is.null(latest_actual_row)) latest_actual_row$quarter else nowcast$latest_actual_quarter
  latest_actual_qoq <- if (!is.null(latest_actual_row)) latest_actual_row$qoq_pct else NA_real_

  # "Released days before next release" is a negative number; e.g. if Q4 was released
  # 92 days before Q1's scheduled release, this field reads -92.
  prev_release <- gdp_release_date(latest_actual_quarter)
  released_days_before_next <- if (!is.na(prev_release) && !is.na(next_release)) {
    as.integer(as.numeric(difftime(prev_release, next_release, units = "days")))
  } else NA_integer_

  # Bias-aware empirical CI bands from the latest validated backtest.
  ci <- load_ci_params()
  prev_level_now <- ci_prev_level(point_value, qoq_growth_pct)
  b68 <- ci_level_band(qoq_growth_pct, prev_level_now, ci$qoq_bias_pp, ci$qoq_sd_pp, ci$z_68)
  b95 <- ci_level_band(qoq_growth_pct, prev_level_now, ci$qoq_bias_pp, ci$qoq_sd_pp, ci$z_95)

  # --- 1. latest.json ---
  latest_obj <- list(
    generated_at          = format(Sys.time(), "%Y-%m-%dT%H:%M:%SZ", tz = "UTC"),
    target_quarter        = target_quarter,
    data_through          = format(data_through_date, "%Y-%m"),
    next_gdp_release_date = format(next_release, "%Y-%m-%d"),
    nowcast = list(
      gdp_chain_volume_millions = point_value,
      qoq_growth_pct            = qoq_growth_pct,
      yoy_growth_pct            = yoy_growth_pct,
      ci_68_low                 = b68$low,
      ci_68_high                = b68$high,
      ci_95_low                 = b95$low,
      ci_95_high                = b95$high
    ),
    latest_actual = list(
      quarter                   = latest_actual_quarter,
      gdp_chain_volume_millions = latest_actual_value,
      qoq_growth_pct            = round(latest_actual_qoq, 2),
      released_days_before_next = released_days_before_next
    )
  )
  write(
    toJSON(latest_obj, auto_unbox = TRUE, pretty = TRUE, digits = NA, na = "null"),
    file.path(target_dir, "latest.json")
  )

  # --- 2. gdp.json ---
  gdp_series <- gdp_wide |>
    transmute(
      quarter = quarter,
      value   = round(value),
      qoq_pct = round(qoq_pct, 2),
      yoy_pct = round(yoy_pct, 2)
    )
  write(
    toJSON(list(series = gdp_series), auto_unbox = TRUE, pretty = TRUE, na = "null"),
    file.path(target_dir, "gdp.json")
  )

  # --- 3. nowcasts.json ---
  # Reuse vraw_all read at top of function.
  vintages_out <- if (exists("vraw_all") && !is.null(vraw_all) && nrow(vraw_all) > 0) {
    vraw_all |>
      mutate(
        run_date_d    = as.Date(run_timestamp),
        release_d     = as.Date(vapply(target_quarter, function(q) {
          rd <- gdp_release_date(q)
          if (inherits(rd, "Date")) as.character(rd) else NA_character_
        }, character(1))),
        days_until_release = as.integer(as.numeric(difftime(run_date_d, release_d, units = "days"))),
        qg_v     = as.numeric(qoq_growth),
        prev_lvl = ci_prev_level(as.numeric(nowcast_value), qg_v)
      ) |>
      transmute(
        run_date          = format(run_date_d, "%Y-%m-%d"),
        target_quarter,
        point             = round(as.numeric(nowcast_value)),
        qoq_growth_pct    = round(qg_v, 2),
        ci_68_low         = ci_level_band(qg_v, prev_lvl, ci$qoq_bias_pp, ci$qoq_sd_pp, ci$z_68)$low,
        ci_68_high        = ci_level_band(qg_v, prev_lvl, ci$qoq_bias_pp, ci$qoq_sd_pp, ci$z_68)$high,
        ci_95_low         = ci_level_band(qg_v, prev_lvl, ci$qoq_bias_pp, ci$qoq_sd_pp, ci$z_95)$low,
        ci_95_high        = ci_level_band(qg_v, prev_lvl, ci$qoq_bias_pp, ci$qoq_sd_pp, ci$z_95)$high,
        data_through      = format(as.Date(data_as_of_date), "%Y-%m"),
        days_until_release
      )
  } else {
    tibble(
      run_date = character(), target_quarter = character(),
      point = integer(), qoq_growth_pct = double(),
      ci_68_low = integer(), ci_68_high = integer(),
      ci_95_low = integer(), ci_95_high = integer(),
      data_through = character(), days_until_release = integer()
    )
  }
  write(
    toJSON(list(vintages = vintages_out), auto_unbox = TRUE, pretty = TRUE, na = "null"),
    file.path(target_dir, "nowcasts.json")
  )

  # --- 4. indicators.json ---
  # Pull the actual release dates published on each ABS latest-release page
  # once per emit. Failures (offline runner, page-structure change) leave the
  # tibble's dates NA and the caller falls back to a per-indicator weekday
  # rule. Non-ABS indicators (cons_conf, bus_conf) are always rule-driven.
  abs_calendar <- tryCatch(
    fetch_abs_release_calendar(),
    error = function(e) {
      message("ABS release-calendar fetch failed: ", conditionMessage(e))
      NULL
    }
  )

  long_df <- master$long
  indicators_list <- lapply(names(INDICATOR_ID_MAP), function(r_id) {
    json_id <- unname(INDICATOR_ID_MAP[[r_id]])
    meta    <- INDICATOR_META[[json_id]]
    group   <- Find(function(g) json_id %in% INDICATOR_GROUPS[[g]], names(INDICATOR_GROUPS))

    series_df <- long_df |>
      filter(indicator_id == r_id) |>
      arrange(date) |>
      transmute(
        date  = format(date, "%Y-%m"),
        value = round(value, 3)
      )

    last_ref_month <- if (nrow(series_df) > 0) tail(series_df$date, 1) else NA_character_
    release_dates  <- compute_release_dates(json_id, last_ref_month, abs_calendar)

    list(
      id                    = json_id,
      name                  = meta$name,
      group                 = group,
      unit                  = meta$unit,
      source                = meta$source,
      series                = series_df,
      last_release_date     = release_dates$last,
      next_release_estimate = release_dates$next_
    )
  })
  write(
    toJSON(list(indicators = indicators_list), auto_unbox = TRUE, pretty = TRUE, na = "null"),
    file.path(target_dir, "indicators.json")
  )

  # --- 5. performance.json ---
  # For each target quarter with both a final nowcast AND a published actual,
  # compute level-error, percent-error, and year-ended-growth error. Aggregate
  # to MAE / bias / (optional) RBA edge using the SoMP forecast CSV.
  perf_empty <- list(
    mae_millions = 0, mae_pct = 0,
    bias_millions = 0, bias_pct = 0,
    rba_comparison = list(n = 0L, avg_edge_pp = NA),
    errors = list()
  )
  minus_4q <- function(q) {
    parts <- strsplit(q, " Q", fixed = TRUE)[[1]]
    paste0(as.integer(parts[1]) - 1L, " Q", parts[2])
  }
  # SoMP CSV lives alongside the pipeline scripts. Try a few candidate locations
  # to tolerate being called from either repo root or `pipeline/`.
  somp_candidates <- c(
    "pipeline/rba_somp_forecasts.csv",
    "rba_somp_forecasts.csv",
    file.path(dirname(target_dir), "pipeline", "rba_somp_forecasts.csv")
  )
  somp_path <- somp_candidates[file.exists(somp_candidates)][1]
  # Fall back to the same directory as the fetcher script if nothing exists yet.
  if (is.na(somp_path) || !nzchar(somp_path)) {
    somp_path <- "pipeline/rba_somp_forecasts.csv"
  }
  # Source the SoMP fetcher from an adjacent file.
  somp_fetcher_candidates <- c(
    "pipeline/04a_fetch_somp.R",
    "04a_fetch_somp.R",
    file.path(dirname(target_dir), "pipeline", "04a_fetch_somp.R")
  )
  somp_fetcher <- somp_fetcher_candidates[file.exists(somp_fetcher_candidates)][1]
  if (!is.na(somp_fetcher)) source(somp_fetcher, local = TRUE)

  perf_obj <- local({
    if (nrow(vintages_out) == 0 || nrow(gdp_wide) == 0) return(perf_empty)

    finals <- vintages_out |>
      group_by(target_quarter) |>
      slice_max(run_date, n = 1, with_ties = FALSE) |>
      ungroup()

    gdp_match <- gdp_wide |>
      transmute(target_quarter = quarter, actual = value,
                actual_qoq = qoq_pct, actual_yoy = yoy_pct)

    paired <- finals |> inner_join(gdp_match, by = "target_quarter")
    if (nrow(paired) == 0) return(perf_empty)

    # Refresh SoMP cache for any paired target quarters not yet seen. Fetcher
    # handles 404s (SoMP not yet published) and Q1/Q3 targets (no match) by
    # simply not appending a row.
    somp_df <- if (exists("ensure_somp_cache")) {
      tryCatch(
        ensure_somp_cache(paired$target_quarter, somp_path),
        error = function(e) {
          message(sprintf("[somp] cache refresh failed: %s", conditionMessage(e)))
          if (file.exists(somp_path)) {
            suppressWarnings(read_csv(somp_path, show_col_types = FALSE))
          } else {
            tibble::tibble(target_quarter = character(), somp_release = character(),
                           yoy_forecast_pct = numeric(), source_url = character())
          }
        }
      )
    } else if (file.exists(somp_path)) {
      suppressWarnings(read_csv(somp_path, show_col_types = FALSE))
    } else {
      tibble::tibble(target_quarter = character(), somp_release = character(),
                     yoy_forecast_pct = numeric(), source_url = character())
    }

    # Year-ended nowcast: point / GDP at (target − 4 quarters) − 1.
    ref_lookup <- gdp_wide |> transmute(ref_quarter = quarter, ref_value = value)
    paired <- paired |>
      mutate(ref_quarter = vapply(target_quarter, minus_4q, character(1))) |>
      left_join(ref_lookup, by = "ref_quarter") |>
      mutate(
        error_millions = point - actual,
        error_pct      = (point - actual) / actual * 100,
        yoy_nowcast    = ifelse(is.na(ref_value), NA_real_,
                                (point / ref_value - 1) * 100)
      ) |>
      left_join(
        somp_df |> transmute(
          target_quarter,
          somp_release,
          yoy_rba = yoy_forecast_pct
        ),
        by = "target_quarter"
      ) |>
      mutate(
        edge_pp = ifelse(
          is.na(yoy_rba) | is.na(yoy_nowcast) | is.na(actual_yoy),
          NA_real_,
          abs(yoy_nowcast - actual_yoy) - abs(yoy_rba - actual_yoy)
        )
      ) |>
      arrange(target_quarter)

    errors_df <- paired |>
      transmute(
        target_quarter,
        final_nowcast  = round(point),
        actual         = round(actual),
        error_millions = round(error_millions),
        error_pct      = round(error_pct, 2),
        yoy_nowcast    = ifelse(is.na(yoy_nowcast), NA_real_, round(yoy_nowcast, 2)),
        yoy_actual     = ifelse(is.na(actual_yoy), NA_real_, round(actual_yoy, 2)),
        yoy_rba        = ifelse(is.na(yoy_rba), NA_real_, round(yoy_rba, 2)),
        somp_release   = ifelse(is.na(somp_release), NA_character_, somp_release),
        edge_pp        = ifelse(is.na(edge_pp), NA_real_, round(edge_pp, 2))
      )

    edge_vec <- paired$edge_pp[!is.na(paired$edge_pp)]
    rba_block <- list(
      n = length(edge_vec),
      avg_edge_pp = if (length(edge_vec) > 0) round(mean(edge_vec), 2) else NA_real_
    )

    list(
      mae_millions   = round(mean(abs(paired$error_millions))),
      mae_pct        = round(mean(abs(paired$error_pct)), 2),
      bias_millions  = round(mean(paired$error_millions)),
      bias_pct       = round(mean(paired$error_pct), 2),
      rba_comparison = rba_block,
      errors         = errors_df
    )
  })
  write(
    toJSON(perf_obj, auto_unbox = TRUE, pretty = TRUE, na = "null"),
    file.path(target_dir, "performance.json")
  )

  message(sprintf("✓ Emitted 5 JSON files to %s", normalizePath(target_dir)))
  invisible(NULL)
}
