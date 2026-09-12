# fetch_rt_gdp.R
# Build the GDP regressand for v2: quarterly q/q growth (%) in
# data_raw/rt_dgdp_qtr.csv (date,value), where `date` is the first day of the
# quarter's last month.
#
# "rt" = real-time, and since 2026-09 it finally means what the RBA meant by it.
# RDP 2024-04 estimates and evaluates on the ABS's INITIAL estimate of each
# quarter -- the number that was actually published at the time -- not the
# later-revised series. v2 used the latest vintage until now, and that choice
# was most of its error: retrained on the initial estimates, its bias against
# the print falls +0.31 -> +0.10pp and its MAE 0.33 -> 0.17pp
# (docs/measurements/2026-09-11-v2-first-print-ab.md).
#
# So the series is assembled in two parts:
#
#   1. The first-release history, maintained by the v3 pipeline in
#      nowcasting_v3/data/gdp_first_release.csv (1959Q4 onward; the v3 weekly
#      job appends the new print on the Monday after each ABS release).
#      Override the path with NOWCAST_FIRST_RELEASE_CSV if you need to.
#
#   2. Any quarter NEWER than that file, taken from a live ABS fetch of the
#      latest vintage (series A2304402X). This matters on exactly one day a
#      quarter: the v2 step of the weekly workflow runs at 19:00 UTC Sunday
#      (05:00 AEST Monday) and the v3 job that appends the print runs at 20:30
#      UTC (06:30 AEST Monday), so on a print Monday the
#      first-release file is one quarter short. For a just-printed quarter the
#      latest vintage IS the initial estimate, so appending it is exact, not an
#      approximation -- and it stops being used the moment v3 writes the row.
#
# If the live fetch fails we still write the first-release history alone (with a
# warning). Writing nothing would leave v2 nowcasting against a stale file,
# which is the failure mode nowcast_midas() warns about.
#
# The file feeds targeted-predictor selection (Phase 3) and the MIDAS
# regressions (Phase 4).

suppressWarnings(suppressMessages({
  here <- tryCatch(dirname(sys.frame(1)$ofile), error = function(e) NA)
}))
if (is.na(here) || !nzchar(here)) here <- "R"
source(file.path(here, "_setup.R"))

suppressMessages({
  library(dplyr)
})

DEFAULT_FIRST_RELEASE_CSV <- "../nowcasting_v3/data/gdp_first_release.csv"

# "2026Q2" -> 2026-06-01 (first day of the quarter's last month, the labelling
# every other v2 GDP consumer already assumes).
.quarter_label_to_date <- function(lab) {
  lab <- trimws(as.character(lab))
  m <- regmatches(lab, regexec("^([0-9]{4})[Qq]([1-4])$", lab))
  yr <- vapply(m, function(x) if (length(x) == 3L) x[[2]] else NA_character_, "")
  qt <- vapply(m, function(x) if (length(x) == 3L) x[[3]] else NA_character_, "")
  bad <- is.na(yr)
  if (any(bad)) {
    stop(sprintf("fetch_rt_gdp(): unparseable quarter label(s): %s\n",
                 paste(utils::head(lab[bad], 5L), collapse = ", ")), call. = FALSE)
  }
  as.Date(sprintf("%s-%02d-01", yr, 3L * as.integer(qt)))
}

# The first-release history, as date/value.
.read_first_release <- function(csv) {
  if (!file.exists(csv)) {
    stop(sprintf("fetch_rt_gdp(): first-release file not found: %s\n", csv), call. = FALSE)
  }
  fr <- utils::read.csv(csv, stringsAsFactors = FALSE)
  need <- c("quarter", "qoq_pct")
  if (!all(need %in% names(fr))) {
    stop(sprintf("fetch_rt_gdp(): %s needs columns %s; has %s\n",
                 csv, paste(need, collapse = ", "), paste(names(fr), collapse = ", ")),
         call. = FALSE)
  }
  out <- data.frame(date  = .quarter_label_to_date(fr$quarter),
                    value = as.numeric(fr$qoq_pct))
  out <- out[!is.na(out$value), , drop = FALSE]
  out[order(out$date), , drop = FALSE]
}

# Latest-vintage ABS levels -> q/q growth (%). Returns NULL (with a message) if
# readabs is unavailable or the download fails; the caller decides what that means.
.fetch_live_growth <- function(series_id) {
  if (!requireNamespace("readabs", quietly = TRUE)) {
    message("fetch_rt_gdp(): readabs is not installed -- skipping the live ABS fetch.")
    return(NULL)
  }
  raw <- tryCatch({
    # Cache ABS downloads in a temp dir so we don't pollute the repo
    Sys.setenv(R_READABS_PATH = tempdir())
    readabs::read_abs_series(series_id)
  }, error = function(e) {
    message(sprintf("fetch_rt_gdp(): live ABS fetch failed (%s).", conditionMessage(e)))
    NULL
  })
  if (is.null(raw) || nrow(raw) == 0L) return(NULL)

  lev <- raw %>%
    dplyr::select(date, value) %>%
    dplyr::arrange(date) %>%
    dplyr::filter(!is.na(value))
  if (nrow(lev) < 2L) return(NULL)

  g <- 100.0 * (lev$value / dplyr::lag(lev$value) - 1.0)
  out <- data.frame(date = as.Date(lev$date), value = g)
  out[!is.na(out$value), , drop = FALSE]
}

fetch_rt_gdp <- function(out_csv = "data_raw/rt_dgdp_qtr.csv",
                         series_id = "A2304402X",
                         first_release_csv = NULL) {
  if (is.null(first_release_csv)) {
    first_release_csv <- Sys.getenv("NOWCAST_FIRST_RELEASE_CSV", unset = "")
    if (!nzchar(first_release_csv)) first_release_csv <- DEFAULT_FIRST_RELEASE_CSV
  }

  out <- .read_first_release(first_release_csv)
  cat(sprintf("fetch_rt_gdp(): %d initial-estimate obs (%s..%s) from %s\n",
              nrow(out), as.character(min(out$date)), as.character(max(out$date)),
              first_release_csv))

  live <- .fetch_live_growth(series_id)
  if (is.null(live)) {
    warning(sprintf(paste("fetch_rt_gdp(): no live ABS data for %s -- writing the",
                          "first-release history alone. If an ABS release has just",
                          "landed, the newest quarter is missing until the v3 job",
                          "appends it."), series_id), call. = FALSE)
  } else {
    add <- live[live$date > max(out$date), , drop = FALSE]
    if (nrow(add) > 1L) {
      # One missing quarter is the print-Monday case and the appended value is
      # the initial estimate. Two or more means the v3 job has stopped
      # appending: only the NEWEST of these is an initial estimate, the older
      # ones are revised figures, so the target is wrong until v3 catches up.
      warning(sprintf(paste("fetch_rt_gdp(): the first-release file is %d quarters",
                            "behind the ABS; only the newest appended quarter is an",
                            "initial estimate. Check the v3 weekly job."), nrow(add)),
              call. = FALSE)
    }
    if (nrow(add) > 0L) {
      out <- rbind(out, add)
      out <- out[order(out$date), , drop = FALSE]
      cat(sprintf("fetch_rt_gdp(): appended %d quarter(s) from the live ABS fetch: %s\n",
                  nrow(add),
                  paste(sprintf("%s = %.4f", as.character(add$date), add$value),
                        collapse = ", ")))
    } else {
      cat("fetch_rt_gdp(): live ABS fetch adds no quarter beyond the first-release file.\n")
    }
  }

  if (nrow(out) < 40L) {
    stop(sprintf("fetch_rt_gdp(): only %d growth obs, expected hundreds.\n",
                 nrow(out)), call. = FALSE)
  }
  if (anyDuplicated(out$date)) {
    stop("fetch_rt_gdp(): duplicate quarter dates in the assembled series.\n", call. = FALSE)
  }

  dir.create(dirname(out_csv), showWarnings = FALSE, recursive = TRUE)
  write.csv(out, file = out_csv, row.names = FALSE)
  cat(sprintf("fetch_rt_gdp(): wrote %d quarterly GDP growth obs (%s..%s) to %s\n",
              nrow(out), as.character(min(out$date)), as.character(max(out$date)),
              out_csv))
  invisible(out)
}

if (sys.nframe() == 0L) {
  fetch_rt_gdp()
}
