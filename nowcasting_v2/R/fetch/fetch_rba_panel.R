# =============================================================================
# fetch_rba_panel.R  — Tier-1 RBA free-CSV predictors for nowcast v2
# =============================================================================
# Parses RBA statistical-table CSVs (https://www.rba.gov.au/statistics/tables/).
# Each RBA CSV has a metadata block, a row beginning "Series ID," giving the
# column codes, then dated data rows. Generic parser locates the "Series ID,"
# row and selects the target column by EXACT series_id confirmed from a fixture.
#
# Output contract: data_raw/<id>.csv with columns date,value (first-of-month).
# Each fetcher prints "<id>: N obs, MIN -> MAX".
#
# Series IDs CONFIRMED against fixtures (tests/fixtures/rba_*.csv):
#   credit          D2  col DLCACN   (Credit; Total, Original, $b)
#   credit_housing  D2  DLCACOHN + DLCACIHN (owner-occ + investor housing, $b)
#   credit_business D2  col DLCACBN  (Credit; Business, Original, $b)
#   fcmygbag3/5/10  F2.1 FCMYGBAG3/5/10 (AGS bond yields, monthly, % pa)
#   firmmbab90      F1.1 FIRMMBAB90  (3-mth BABs/BBSW, monthly, % pa)
#   scrigbag3/5/10  derived = AGS yield - BBSW (the RBA spread series)
#   credit_card     C1  CCCCSTPVSA  (Value of purchases, SA, $m)
#   asx200          MISSING — RBA no longer publishes a share price index CSV
#                   (current F7 = business lending rates); see panel_info notes.
# -----------------------------------------------------------------------------

.rba_setup <- local({
  cand <- c(file.path("nowcasting_v2", "R", "_setup.R"),
            file.path("R", "_setup.R"),
            file.path("..", "R", "_setup.R"),
            file.path("..", "..", "R", "_setup.R"))
  for (p in cand) if (file.exists(p)) return(normalizePath(dirname(dirname(p))))
  normalizePath(".")
})
source(file.path(.rba_setup, "R", "_setup.R"))

suppressMessages({
  library(dplyr)
  library(lubridate)
  library(readr)
})

.v2_root      <- .rba_setup
.data_raw_rba <- file.path(.v2_root, "data_raw")
.fixtures_rba <- file.path(.v2_root, "tests", "fixtures")
dir.create(.data_raw_rba, recursive = TRUE, showWarnings = FALSE)

RBA_BASE <- "https://www.rba.gov.au/statistics/tables/csv/"
RBA_TABLES <- c(
  d2   = "d2-data.csv",        # Lending and credit aggregates (monthly)
  f2_1 = "f2.1-data.csv",      # Capital market yields, govt bonds (monthly)
  f1_1 = "f1.1-data.csv",      # Interest rates & yields, money market (monthly)
  c1   = "c1-data.csv"         # Credit & charge cards, SA (monthly)
)

# -----------------------------------------------------------------------------
# Download an RBA CSV to a local path (with browser UA + retries).
# -----------------------------------------------------------------------------
download_rba_csv <- function(table_key, dest = NULL) {
  fname <- RBA_TABLES[[table_key]]
  if (is.null(fname)) stop("Unknown RBA table key: ", table_key)
  url <- paste0(RBA_BASE, fname)
  if (is.null(dest)) dest <- file.path(tempdir(), fname)
  ok <- FALSE
  for (attempt in 1:4) {
    res <- tryCatch(
      utils::download.file(url, dest, mode = "wb", quiet = TRUE,
                           headers = c("User-Agent" = "nowcasting/2.0 (+https://nowcast.wlsn.me)")),
      error = function(e) e
    )
    if (!inherits(res, "error") && file.exists(dest) && file.size(dest) > 1000) {
      # reject HTML error pages
      head_bytes <- readBin(dest, "raw", n = 32)
      if (!grepl("<!DOCTYPE|<html", rawToChar(head_bytes), ignore.case = TRUE)) {
        ok <- TRUE; break
      }
    }
    Sys.sleep(min(30, 3 * 2^(attempt - 1)))
  }
  if (!ok) stop(sprintf("RBA download failed for %s (%s)", table_key, url))
  dest
}

# -----------------------------------------------------------------------------
# Generic RBA-CSV parser. Reads raw lines, finds the "Series ID," row, then
# returns a long tibble date,value for the requested series_id column.
# Pure over a file path so it is unit-testable from a fixture.
# -----------------------------------------------------------------------------
parse_rba_csv <- function(path, series_id) {
  lines <- readr::read_lines(path)
  sid_row <- which(grepl("^Series ID,", lines))[1]
  if (is.na(sid_row)) stop("parse_rba_csv: no 'Series ID,' header row in ", basename(path))

  ids <- strsplit(lines[sid_row], ",", fixed = TRUE)[[1]]
  ids <- trimws(ids)
  col <- which(ids == series_id)
  if (length(col) == 0L) {
    stop(sprintf("parse_rba_csv: series_id '%s' not found in %s", series_id, basename(path)))
  }
  col <- col[1]

  data_lines <- lines[(sid_row + 1L):length(lines)]
  data_lines <- data_lines[grepl("^[0-9]", data_lines)]   # date rows only
  parts <- strsplit(data_lines, ",", fixed = TRUE)

  raw_date <- vapply(parts, function(p) if (length(p) >= 1) p[1] else NA_character_, "")
  raw_val  <- vapply(parts, function(p) if (length(p) >= col) p[col] else NA_character_, "")

  d <- .parse_rba_date(raw_date)
  v <- suppressWarnings(as.numeric(raw_val))

  out <- tibble(date = lubridate::floor_date(d, "month"), value = v) |>
    filter(!is.na(date), !is.na(value)) |>
    distinct(date, .keep_all = TRUE) |>
    arrange(date)
  if (nrow(out) == 0L) stop(sprintf("parse_rba_csv: no obs for '%s' in %s", series_id, basename(path)))
  out
}

# RBA dates appear as dd/mm/yyyy (D2,C1) or dd-Mon-yyyy (F2.1,F1.1).
.parse_rba_date <- function(x) {
  d <- as.Date(rep(NA, length(x)))
  slash <- grepl("/", x, fixed = TRUE)
  if (any(slash))  d[slash]  <- as.Date(x[slash],  format = "%d/%m/%Y")
  if (any(!slash)) d[!slash] <- as.Date(x[!slash], format = "%d-%b-%Y")
  d
}

.write_series_rba <- function(tbl, id) {
  path <- file.path(.data_raw_rba, paste0(id, ".csv"))
  readr::write_csv(tbl, path)
  cat(sprintf("%s: %d obs, %s -> %s\n",
              id, nrow(tbl),
              format(min(tbl$date), "%Y-%m-%d"),
              format(max(tbl$date), "%Y-%m-%d")))
  invisible(path)
}

# -----------------------------------------------------------------------------
# Series fetchers. `src` lets tests/offline runs point at a fixture file.
# -----------------------------------------------------------------------------
.get_d2   <- function(src) if (is.null(src)) download_rba_csv("d2")   else src
.get_f2_1 <- function(src) if (is.null(src)) download_rba_csv("f2_1") else src
.get_f1_1 <- function(src) if (is.null(src)) download_rba_csv("f1_1") else src
.get_c1   <- function(src) if (is.null(src)) download_rba_csv("c1")   else src

# D2 had a definitional break in 2019-07: the "excluding financial businesses"
# columns (DLCAC*N) stop at 2019-06 and are succeeded by the "including select
# financial businesses" columns (DLCACSF*N) from 2019-07. We splice old->new at
# the break so each level series is current AND retains its long history.
.splice_d2 <- function(p, old_id, new_id, break_date = as.Date("2019-07-01")) {
  old <- parse_rba_csv(p, old_id) |> filter(date <  break_date)
  new <- parse_rba_csv(p, new_id) |> filter(date >= break_date)
  bind_rows(old, new) |> arrange(date) |> distinct(date, .keep_all = TRUE)
}

fetch_credit <- function(src = NULL, write = TRUE) {
  tbl <- .splice_d2(.get_d2(src), "DLCACN", "DLCACSFN")  # Credit; Total (Original)
  if (write) .write_series_rba(tbl, "credit"); tbl
}

fetch_credit_housing <- function(src = NULL, write = TRUE) {
  p <- .get_d2(src)
  oo  <- parse_rba_csv(p, "DLCACOHN")                   # owner-occupier housing
  inv <- parse_rba_csv(p, "DLCACIHN")                   # investor housing
  tbl <- dplyr::inner_join(oo, inv, by = "date", suffix = c("_oo", "_inv")) |>
    transmute(date, value = value_oo + value_inv) |>
    arrange(date)
  if (write) .write_series_rba(tbl, "credit_housing"); tbl
}

fetch_credit_business <- function(src = NULL, write = TRUE) {
  tbl <- .splice_d2(.get_d2(src), "DLCACBN", "DLCACSFBN")  # Credit; Business (Original)
  if (write) .write_series_rba(tbl, "credit_business"); tbl
}

fetch_fcmygbag3  <- function(src = NULL, write = TRUE) {
  tbl <- parse_rba_csv(.get_f2_1(src), "FCMYGBAG3")
  if (write) .write_series_rba(tbl, "fcmygbag3"); tbl
}
fetch_fcmygbag5  <- function(src = NULL, write = TRUE) {
  tbl <- parse_rba_csv(.get_f2_1(src), "FCMYGBAG5")
  if (write) .write_series_rba(tbl, "fcmygbag5"); tbl
}
fetch_fcmygbag10 <- function(src = NULL, write = TRUE) {
  tbl <- parse_rba_csv(.get_f2_1(src), "FCMYGBAG10")
  if (write) .write_series_rba(tbl, "fcmygbag10"); tbl
}

fetch_firmmbab90 <- function(src = NULL, write = TRUE) {
  tbl <- parse_rba_csv(.get_f1_1(src), "FIRMMBAB90")    # 3-mth BABs/BBSW
  if (write) .write_series_rba(tbl, "firmmbab90"); tbl
}

# Spread = AGS yield - BBSW (the RBA scrigbag* series). Inner-join on month.
.fetch_spread <- function(id, yield_id, f2src, f1src, write) {
  y   <- parse_rba_csv(.get_f2_1(f2src), yield_id)
  bbsw <- parse_rba_csv(.get_f1_1(f1src), "FIRMMBAB90")
  tbl <- dplyr::inner_join(y, bbsw, by = "date", suffix = c("_y", "_b")) |>
    transmute(date, value = value_y - value_b) |>
    arrange(date)
  if (write) .write_series_rba(tbl, id); tbl
}
fetch_scrigbag3  <- function(f2src=NULL, f1src=NULL, write=TRUE) .fetch_spread("scrigbag3",  "FCMYGBAG3",  f2src, f1src, write)
fetch_scrigbag5  <- function(f2src=NULL, f1src=NULL, write=TRUE) .fetch_spread("scrigbag5",  "FCMYGBAG5",  f2src, f1src, write)
fetch_scrigbag10 <- function(f2src=NULL, f1src=NULL, write=TRUE) .fetch_spread("scrigbag10", "FCMYGBAG10", f2src, f1src, write)

fetch_credit_card <- function(src = NULL, write = TRUE) {
  tbl <- parse_rba_csv(.get_c1(src), "CCCCSTPVSA")      # Value of purchases (SA)
  if (write) .write_series_rba(tbl, "credit_card"); tbl
}

# asx200: no free RBA-CSV source (current F7 = business lending rates; the old
# share-price index table was discontinued). Recorded MISSING in panel_info.
# Stooq/Yahoo require an API key or are not stable for automation -> Tier-2.

fetch_rba_panel <- function() {
  fns <- list(
    credit = fetch_credit, credit_housing = fetch_credit_housing,
    credit_business = fetch_credit_business,
    fcmygbag3 = fetch_fcmygbag3, fcmygbag5 = fetch_fcmygbag5, fcmygbag10 = fetch_fcmygbag10,
    firmmbab90 = fetch_firmmbab90,
    scrigbag3 = function() fetch_scrigbag3(), scrigbag5 = function() fetch_scrigbag5(),
    scrigbag10 = function() fetch_scrigbag10(),
    credit_card = fetch_credit_card
  )
  res <- list()
  for (id in names(fns)) {
    res[[id]] <- tryCatch(fns[[id]](),
      error = function(e) { message(sprintf("  !! %s FAILED: %s", id, conditionMessage(e))); NULL })
  }
  invisible(res)
}

if (sys.nframe() == 0L && !interactive()) {
  fetch_rba_panel()
}
