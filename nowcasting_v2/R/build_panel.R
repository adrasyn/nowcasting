# build_panel.R
# Phase 3.1 -- assemble the monthly partial-indicator panel.
# Reads every has_csv==TRUE series from data_raw/<id>.csv (date,value),
# left-joins onto a monthly spine (min->max date across all series), returns a
# wide tibble keyed on first-of-month `date` (one column per id).
# Fails loud if a has_csv id has no CSV.

suppressWarnings(suppressMessages({
  here <- tryCatch(dirname(sys.frame(1)$ofile), error = function(e) NA)
}))
if (is.na(here) || !nzchar(here)) here <- "R"
source(file.path(here, "_setup.R"))

suppressMessages({
  library(dplyr)
  library(tidyr)
  library(lubridate)
  library(readr)
})

# Floor a date to first-of-month
.first_of_month <- function(d) lubridate::floor_date(as.Date(d), unit = "month")

build_panel <- function(panel_info_csv = "seed/panel_info.csv",
                        data_raw_dir   = "data_raw",
                        out_rds        = "cache/panel_vintage_latest.rds") {

  info <- readr::read_csv(panel_info_csv, show_col_types = FALSE)

  # has_csv may be read as logical or character; normalise
  has_csv <- info$has_csv
  if (is.character(has_csv)) has_csv <- toupper(has_csv) %in% c("TRUE", "T")
  ids <- info$id[has_csv %in% TRUE]

  if (length(ids) == 0L) stop("build_panel(): no has_csv==TRUE rows in panel_info.\n", call. = FALSE)

  series_list <- vector("list", length(ids))
  names(series_list) <- ids

  for (id in ids) {
    f <- file.path(data_raw_dir, paste0(id, ".csv"))
    if (!file.exists(f)) {
      stop(sprintf("build_panel(): has_csv id '%s' has no CSV at %s\n", id, f),
           call. = FALSE)
    }
    d <- readr::read_csv(f, show_col_types = FALSE)
    if (!all(c("date", "value") %in% names(d))) {
      stop(sprintf("build_panel(): %s missing date/value columns\n", f), call. = FALSE)
    }
    d <- d %>%
      dplyr::transmute(date = .first_of_month(date),
                       value = as.numeric(value)) %>%
      dplyr::filter(!is.na(date)) %>%
      dplyr::arrange(date)
    # Collapse any duplicate months (keep last)
    d <- d %>% dplyr::group_by(date) %>% dplyr::summarise(value = dplyr::last(value),
                                                          .groups = "drop")
    names(d)[2] <- id
    series_list[[id]] <- d
  }

  # Monthly spine over min->max across all series
  all_dates <- do.call(c, lapply(series_list, function(x) x$date))
  spine <- data.frame(date = seq(min(all_dates), max(all_dates), by = "month"))

  wide <- spine
  for (id in ids) {
    wide <- dplyr::left_join(wide, series_list[[id]], by = "date")
  }
  wide <- dplyr::as_tibble(wide)

  # Sanity checks: monthly dates, no all-NA columns
  allna <- vapply(wide[ , ids, drop = FALSE], function(x) all(is.na(x)), logical(1))
  if (any(allna)) {
    stop(sprintf("build_panel(): all-NA column(s): %s\n",
                 paste(ids[allna], collapse = ", ")), call. = FALSE)
  }

  dir.create(dirname(out_rds), showWarnings = FALSE, recursive = TRUE)
  saveRDS(wide, out_rds)

  cat(sprintf("build_panel(): %d series x %d months (%s..%s) -> %s\n",
              length(ids), nrow(wide),
              as.character(min(wide$date)), as.character(max(wide$date)), out_rds))
  invisible(wide)
}

if (sys.nframe() == 0L) {
  w <- build_panel()
  # quick coverage summary
  ids <- setdiff(names(w), "date")
  cov <- sapply(ids, function(id) {
    v <- w[[id]]; nn <- which(!is.na(v))
    sprintf("%s: n=%d (%s..%s)", id, length(nn),
            as.character(w$date[min(nn)]), as.character(w$date[max(nn)]))
  })
  cat(paste(cov, collapse = "\n"), "\n")
}
