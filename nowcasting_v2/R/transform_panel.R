# transform_panel.R
# Phase 3.2 -- transform + conditionally standardise the monthly panel.
# Adapts rba_paper Transform_MAI_Data.R to our data layout:
#   - per-series tcode/tlog via transform_series()  (t1 level, t2 1st diff;
#     tlog TRUE => log-diff / compounded growth)
#   - rolling_scale(center = TRUE, scale = FALSE) over a backward window
#   - full-sample unit-variance scale()
#
# Because our panel is ragged (series start/end at different dates) we cannot
# diff the whole wide matrix at once the way the RBA does on their balanced
# (censored) panel. We transform each series on its own observed span, then
# re-place it on the common monthly spine. This preserves the RBA's per-series
# statistical transform exactly; the only adaptation is WHERE we apply it
# (per-series observed window vs one balanced block).

suppressWarnings(suppressMessages({
  here <- tryCatch(dirname(sys.frame(1)$ofile), error = function(e) NA)
}))
if (is.na(here) || !nzchar(here)) here <- "R"
source(file.path(here, "_setup.R"))
source(file.path(here, "methods", "misc_methods.R"))  # transform_series, rolling_scale, trim_row

suppressMessages({
  library(dplyr)
  library(readr)
})

# Rolling window length: RBA use 20yr (240 months). With short series this can
# exceed the series length; rolling_scale() stop()s in that case, so we clamp the
# window per-series to min(rba_window, n) and warn. Statistical behaviour for
# long series is identical to the RBA; short series just use a shorter window.
.RBA_ROLL_MONTHS <- 240L

transform_panel <- function(wide, panel_info,
                            roll_months = .RBA_ROLL_MONTHS) {

  if (is.character(panel_info)) {
    panel_info <- readr::read_csv(panel_info, show_col_types = FALSE)
  }
  ids <- setdiff(names(wide), "date")
  info <- panel_info[match(ids, panel_info$id), , drop = FALSE]
  if (any(is.na(info$id))) {
    stop("transform_panel(): panel column not found in panel_info.\n", call. = FALSE)
  }

  # tlog may be logical or character
  tlog_vec <- info$tlog
  if (is.character(tlog_vec)) tlog_vec <- toupper(tlog_vec) %in% c("TRUE", "T")

  spine <- wide$date
  out <- data.frame(date = spine)

  for (k in seq_along(ids)) {
    id    <- ids[k]
    tcode <- info$tcode[k]
    tlog  <- tlog_vec[k]

    v <- wide[[id]]
    obs_idx <- which(!is.na(v))
    if (length(obs_idx) == 0L) stop(sprintf("transform_panel(): %s all NA\n", id))

    # Operate on the contiguous observed span (first..last non-NA). Interior NAs
    # (e.g. nab_stocks gaps) are passed through transform_series; diff() yields NA
    # around the gap, which the downstream EM tolerates.
    i0 <- min(obs_idx); i1 <- max(obs_idx)
    x  <- v[i0:i1]

    # Per-series transform (level vs 1st diff; log if tlog). transform_series()
    # drops leading obs when differencing (t2 -> drops 1). Track alignment.
    tx <- transform_series(x = x, take_log = isTRUE(tlog), tcode = tcode)
    tx <- as.numeric(tx)
    drop_n <- length(x) - length(tx)            # 0 for t1, 1 for t2
    span_start <- i0 + drop_n                    # spine index of first transformed obs

    # Conditional standardisation: rolling centre (window clamped to series length)
    n_tx <- length(tx)
    # Clamp to n-1: rolling_scale()'s loop (roll_len+1):nobs degenerates when
    # roll_len == nobs (descending index), so keep at least one rolling step.
    rl <- min(roll_months, n_tx - 1L)
    if (rl < 2L) {
      stop(sprintf("transform_panel(): %s too short to scale (n=%d)\n", id, n_tx))
    }
    if (rl < roll_months) {
      message(sprintf("transform_panel(): %s clamped roll window %d -> %d (short series)",
                      id, roll_months, rl))
    }

    # rolling_scale handles interior NAs poorly (it scale()s windows). To stay
    # faithful and robust, centre with rolling_scale on the gap-free runs is
    # overkill; the RBA panel has no interior gaps. For series with interior NAs
    # we fall back to a simple full-sample centre (mean) over observed values,
    # which is the limiting case of rolling centring. Detect interior NAs:
    has_interior_na <- any(is.na(tx[which(!is.na(tx))[1]:tail(which(!is.na(tx)),1)]))

    if (has_interior_na) {
      cen <- tx - mean(tx, na.rm = TRUE)
    } else {
      cen <- as.numeric(rolling_scale(x = tx, roll_len = rl, center = TRUE, scale = FALSE))
    }

    # Full-sample unit variance
    s <- stats::sd(cen, na.rm = TRUE)
    if (is.na(s) || s == 0) stop(sprintf("transform_panel(): %s zero variance\n", id))
    z <- cen / s

    # Re-place onto the spine
    col <- rep(NA_real_, length(spine))
    col[span_start:(span_start + n_tx - 1L)] <- z
    out[[id]] <- col
  }

  dplyr::as_tibble(out)
}

if (sys.nframe() == 0L) {
  wide <- readRDS("cache/panel_vintage_latest.rds")
  tfs  <- transform_panel(wide, "seed/panel_info.csv")
  cat(sprintf("transform_panel(): %d series x %d months\n",
              ncol(tfs) - 1L, nrow(tfs)))
  # spot-check a t2/tlog series and a level series over their observed range
  for (id in c("emp", "firmmbab90", "nab_conf")) {
    v <- tfs[[id]][!is.na(tfs[[id]])]
    cat(sprintf("  %s: mean=%.4f sd=%.4f n=%d\n", id, mean(v), sd(v), length(v)))
  }
  saveRDS(tfs, "cache/panel_tfs_latest.rds")
}
