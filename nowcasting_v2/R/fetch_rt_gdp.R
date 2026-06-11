# fetch_rt_gdp.R
# Fetch real GDP chain-volume (ABS series A2304402X), compute QoQ growth (%),
# save quarterly growth to data_raw/rt_dgdp_qtr.csv (date,value).
# This is the GDP target used for targeted-predictor selection (Phase 3) and
# the MIDAS regressions (Phase 4). "rt" = real-time in the RBA naming; here we
# use the latest vintage (a real-time vintage substitution is a later refinement).

suppressWarnings(suppressMessages({
  here <- tryCatch(dirname(sys.frame(1)$ofile), error = function(e) NA)
}))
if (is.na(here) || !nzchar(here)) here <- "R"
source(file.path(here, "_setup.R"))

suppressMessages({
  library(readabs)
  library(dplyr)
})

fetch_rt_gdp <- function(out_csv = "data_raw/rt_dgdp_qtr.csv",
                         series_id = "A2304402X") {
  # Cache ABS downloads in a temp dir so we don't pollute the repo
  Sys.setenv(R_READABS_PATH = tempdir())

  raw <- read_abs_series(series_id)
  if (is.null(raw) || nrow(raw) == 0L) {
    stop(sprintf("fetch_rt_gdp(): no data returned for series %s\n", series_id),
         call. = FALSE)
  }

  lev <- raw %>%
    dplyr::select(date, value) %>%
    dplyr::arrange(date) %>%
    dplyr::filter(!is.na(value))

  # QoQ growth in per cent
  g <- 100.0 * (lev$value / dplyr::lag(lev$value) - 1.0)
  out <- data.frame(date = lev$date, value = g)
  out <- out[!is.na(out$value), , drop = FALSE]

  if (nrow(out) < 40L) {
    stop(sprintf("fetch_rt_gdp(): only %d growth obs, expected hundreds.\n",
                 nrow(out)), call. = FALSE)
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
