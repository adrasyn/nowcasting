#### Tier-2 scraper: NAB Business Survey — FULL sub-index suite ####
# Extends the recovered panel-expansion scraper (scrape_nab_survey_v1.R, which
# handled conditions + capacity only) to ALL monthly NAB sub-indices used by the
# RBA RDP 2024-04 MAI panel:
#
#   nab_conf     Business confidence       (net balance)
#   nab_cond     Business conditions       (net balance)
#   nab_trade    Trading conditions        (net balance)
#   nab_profit   Profitability             (net balance)
#   nab_emp      Employment (NAB)          (net balance)
#   nab_forward  Forward orders            (net balance)
#   nab_stocks   Stocks                    (net balance)
#   nab_cu       Capacity utilisation      (per cent)
#
# PRIME DIRECTIVE: never fabricate. Every emitted value traces to a fixture/live
# PDF. Implausible parses are dropped (range-checked), not invented. A documented
# gap is success.
#
# SOURCES (two layouts, both observed in the cached fixtures):
#   (A) QUARTERLY "Data Appendix" — the cleanest, most stable structured source.
#       Identical layout 2023q2 .. 2026q1. Each block has a "...Monthly..." header
#       line with five YYYYmM columns, then labelled rows. The LAST 5 numbers on a
#       row are the five monthly values. Rows we read (first match only — the
#       expectations blocks repeat some labels with forecast quarters):
#         Confidence, Conditions, Trading, Profitability, Employment,
#         Orders (=forward orders), Stocks current, Capacity utilis.
#       5 monthly obs per quarterly PDF, all eight series.
#   (B) MONTHLY "Table 1: Key Monthly Business Survey Statistics" — present as
#       selectable text in 2025+ PDFs (clean), three month columns. The 2023 PDF
#       has this table letter-spaced ("B usiness co nfidence", "8 4 .5") so it is
#       NOT reliably parseable; for those we fall back to the (sparse) bullets via
#       v1's parser. Newer monthly tables give the freshest 1-3 obs.
#
# REVISIONS: NAB revises. Per (series,date) we keep the value from the most
# authoritative/recent source. Priority: quarterly appendix (1) > monthly table
# (2) > monthly bullet (3). Logged.

suppressMessages({
  library(pdftools)
  library(stringr)
  library(dplyr)
  library(readr)
  library(lubridate)
  library(tibble)
})

# Reuse v1's helpers (.nab_title_month, parse_nab_monthly bullet parser, download)
# without re-defining them: source the recovered file from the same dir.
local({
  here <- tryCatch(dirname(sys.frame(1)$ofile), error = function(e) NA_character_)
  cand <- c(
    if (!is.na(here)) file.path(here, "scrape_nab_survey_v1.R"),
    "R/fetch/scrape_nab_survey_v1.R",
    "nowcasting_v2/R/fetch/scrape_nab_survey_v1.R"
  )
  for (p in cand) if (!is.null(p) && file.exists(p)) { sys.source(p, envir = topenv()); break }
})

MONTH_ABBR <- c(Jan = 1, Feb = 2, Mar = 3, Apr = 4, May = 5, Jun = 6,
                Jul = 7, Aug = 8, Sep = 9, Oct = 10, Nov = 11, Dec = 12)

# Series catalogue: id -> plausibility range. net-balance indices can be deeply
# negative post-COVID; capacity is a percentage.
NAB_SERIES <- list(
  nab_conf    = list(range = c(-70, 50), unit = "net"),
  nab_cond    = list(range = c(-70, 50), unit = "net"),
  nab_trade   = list(range = c(-70, 60), unit = "net"),
  nab_profit  = list(range = c(-70, 60), unit = "net"),
  nab_emp     = list(range = c(-70, 50), unit = "net"),
  nab_forward = list(range = c(-70, 50), unit = "net"),
  nab_stocks  = list(range = c(-50, 50), unit = "net"),
  nab_cu      = list(range = c(60, 95),  unit = "pct")
)

.in_range <- function(id, v) {
  r <- NAB_SERIES[[id]]$range
  !is.na(v) & v >= r[1] & v <= r[2]
}

#' Extract the last `n` numeric tokens of a text line (NA-aware: literal "NA"
#' tokens are preserved as NA so column alignment is not corrupted).
.last_n_nums <- function(ln, n = 5) {
  nums <- str_extract_all(ln, "(?:NA|[-+]?\\d+\\.?\\d*)")[[1]]
  nums <- suppressWarnings(as.numeric(nums))
  if (length(nums) < n) return(NULL)
  tail(nums, n)
}

#' Parse the QUARTERLY Data Appendix for ALL eight sub-indices.
#'
#' Strategy: scan every page that has YYYYmM headers. For each labelled data row
#' we want, find the nearest preceding "...Monthly..." header (5 YYYYmM tokens)
#' and take the last 5 numbers of the row. We take only the FIRST occurrence of
#' each label per page-region to avoid the expectations/forecast duplicate rows
#' ("Conds. next 3m", "Orders next 3m", "Stocks next 3m", "Empl next 3m").
#'
#' @return tibble(date, id, value)
parse_nab_quarterly_full <- function(path) {
  empty <- tibble(date = as.Date(character()), id = character(), value = numeric())
  txt <- tryCatch(pdf_text(path), error = function(e) NULL)
  if (is.null(txt)) return(empty)

  # Row label regexes (anchored at line start after optional spaces / pipe).
  # Each maps to a series id. Order matters only for documentation.
  row_rx <- c(
    nab_conf    = "^\\s*Confidence\\b",
    nab_cond    = "^\\s*Conditions\\b",
    nab_trade   = "^\\s*Trading\\b",
    nab_profit  = "^\\s*Profitability\\b",
    nab_emp     = "^\\s*Employment\\b",
    nab_forward = "^\\s*Orders\\b",          # forward orders (current row)
    nab_stocks  = "^\\s*Stocks current\\b",
    nab_cu      = "^\\s*Capacity utilis"
  )

  parse_month_hdr <- function(ln) {
    mm <- str_match_all(ln, "(\\d{4})m(\\d{1,2})")[[1]]
    if (nrow(mm) < 5) return(NULL)
    tail(make_date(as.integer(mm[, 2]), as.integer(mm[, 3]), 1), 5)
  }

  results <- list()
  for (p in seq_along(txt)) {
    if (!str_detect(txt[p], "\\d{4}m\\d")) next
    lines <- str_split(txt[p], "\n")[[1]]

    hdr_dates_for <- function(row_i) {
      for (j in seq(row_i - 1, max(1, row_i - 8))) {
        dd <- parse_month_hdr(lines[j])
        if (!is.null(dd)) return(dd)
      }
      NULL
    }

    for (id in names(row_rx)) {
      ri <- which(str_detect(lines, row_rx[[id]]))
      if (length(ri) == 0) next
      i <- ri[1]                              # FIRST match only (data appendix proper)
      dd <- hdr_dates_for(i); if (is.null(dd)) next
      vv <- .last_n_nums(lines[i], 5); if (is.null(vv)) next
      # The forward-orders ("Orders") row sometimes carries a stray leading
      # column number before the quarterly block; last-5 still isolates monthly.
      results[[length(results) + 1]] <- tibble(date = dd, id = id, value = vv)
    }
  }

  if (length(results) == 0) return(empty)
  out <- bind_rows(results) |>
    filter(!is.na(value)) |>
    distinct(date, id, .keep_all = TRUE)
  out[mapply(.in_range, out$id, out$value), , drop = FALSE]
}

#' Parse the MONTHLY "Table 1" for ALL eight sub-indices, when present as clean
#' selectable text (2025+ PDFs). Returns 0 rows if the table is letter-spaced /
#' rasterised (older PDFs) — caller falls back to bullets.
#'
#' @return tibble(date, id, value)
parse_nab_monthly_full <- function(path) {
  empty <- tibble(date = as.Date(character()), id = character(), value = numeric())
  txt <- tryCatch(pdf_text(path), error = function(e) NULL)
  if (is.null(txt)) return(empty)
  page1 <- txt[1]
  lines <- str_split(page1, "\n")[[1]]

  # Three-month header e.g. "Feb-26   Mar-26   Apr-26" (clean tables only).
  hdr_idx <- which(str_detect(
    lines, "([A-Z][a-z]{2}-\\d{2})\\s+([A-Z][a-z]{2}-\\d{2})\\s+([A-Z][a-z]{2}-\\d{2})"
  ))
  if (length(hdr_idx) == 0) return(empty)
  hm <- str_match_all(lines[hdr_idx[1]], "([A-Z][a-z]{2})-(\\d{2})")[[1]]
  if (nrow(hm) != 3) return(empty)
  dates <- make_date(2000 + as.integer(hm[, 3]), MONTH_ABBR[hm[, 2]], 1)
  if (length(dates) != 3 || any(is.na(dates))) return(empty)

  # Row label -> id. Each table row ends in exactly 3 trailing numbers (the month
  # columns) at the RIGHT edge; prose text often wraps onto the same physical line
  # to the LEFT (e.g. "...a distinct change from the March survey.   Trading 12 11
  # 7"). So we DON'T anchor at line-start; instead we require the label to be
  # immediately followed by the 3 month numbers and nothing after them. last-3
  # then isolates the month columns regardless of any leading prose numbers.
  # "Forw ard Orders" carries an OCR space; "Trading"/"Profitability" rows are the
  # sub-indented conditions components.
  num3 <- "\\s+[-+]?\\d+\\.?\\d*\\s+[-+]?\\d+\\.?\\d*\\s+[-+]?\\d+\\.?\\d*\\s*$"
  row_rx <- c(
    nab_conf    = paste0("Business confidence", num3),
    nab_cond    = paste0("Business conditions", num3),
    nab_trade   = paste0("\\bTrading", num3),
    nab_profit  = paste0("\\bProfitability", num3),
    nab_emp     = paste0("\\bEmployment", num3),
    nab_forward = paste0("Forw\\s?ard Orders", num3),
    nab_stocks  = paste0("\\bStocks", num3),
    nab_cu      = paste0("Capacity utilisation rate", num3)
  )

  results <- list()
  for (id in names(row_rx)) {
    ri <- which(str_detect(lines, row_rx[[id]]))
    if (length(ri) == 0) next
    # Extract the matched label+3numbers tail, then take its last 3 numbers (so
    # any prose numbers to the left of the label are excluded).
    seg <- str_extract(lines[ri[1]], row_rx[[id]])
    vv <- .last_n_nums(seg, 3)
    if (is.null(vv)) next
    results[[length(results) + 1]] <- tibble(date = dates, id = id, value = vv)
  }
  if (length(results) == 0) return(empty)
  out <- bind_rows(results) |> filter(!is.na(value))
  out[mapply(.in_range, out$id, out$value), , drop = FALSE]
}

#' Assemble all eight NAB sub-indices from fixture (and optionally live) PDFs.
#' Priority per (series,date): quarterly(1) > monthly-table(2) > monthly-bullet(3).
#'
#' @return list(series = named list of tibble(date,value), log = character)
assemble_nab_full <- function(monthly_paths = character(),
                              quarterly_paths = character(),
                              live = FALSE) {
  log <- character()
  add_log <- function(...) log[[length(log) + 1]] <<- sprintf(...)

  if (live) {
    # Reuse v1's live URL seeds + downloader (best-effort; failures logged).
    for (u in get0("NAB_QUARTERLY_PDFS", ifnotfound = character())) {
      p <- .nab_download(u)
      if (is.na(p)) add_log("DOWNLOAD FAIL (quarterly): %s", u) else quarterly_paths <- c(quarterly_paths, p)
    }
    for (u in get0("NAB_MONTHLY_PDFS", ifnotfound = character())) {
      p <- .nab_download(u)
      if (is.na(p)) add_log("DOWNLOAD FAIL (monthly): %s", u) else monthly_paths <- c(monthly_paths, p)
    }
  }

  rows <- list()
  push <- function(tbl, prio, src) {
    if (is.null(tbl) || nrow(tbl) == 0) return(invisible())
    rows[[length(rows) + 1]] <<- tbl |> mutate(prio = prio, src = src)
  }

  for (p in quarterly_paths) {
    q <- tryCatch(parse_nab_quarterly_full(p), error = function(e) {
      add_log("PARSE FAIL (quarterly %s): %s", basename(p), conditionMessage(e)); NULL })
    if (!is.null(q) && nrow(q) > 0) {
      push(q, 1L, basename(p))
      add_log("quarterly %s: %d obs (%s), %s..%s", basename(p), nrow(q),
              paste(sort(unique(q$id)), collapse = ","), format(min(q$date)), format(max(q$date)))
    } else add_log("quarterly %s: 0 obs", basename(p))
  }
  for (p in monthly_paths) {
    tb <- tryCatch(parse_nab_monthly_full(p), error = function(e) {
      add_log("PARSE FAIL (monthly-table %s): %s", basename(p), conditionMessage(e)); NULL })
    if (!is.null(tb) && nrow(tb) > 0) {
      push(tb, 2L, basename(p))
      add_log("monthly-table %s: %d obs (%s)", basename(p), nrow(tb),
              paste(sort(unique(tb$id)), collapse = ","))
    } else {
      # Letter-spaced / rasterised table: fall back to the v1 bullet parser for
      # the two series it reliably extracts (conditions + capacity only).
      bl <- tryCatch(parse_nab_monthly(p), error = function(e) NULL)
      if (!is.null(bl) && !is.na(bl$date)) {
        bt <- bind_rows(
          if (!is.na(bl$conditions)) tibble(date = bl$date, id = "nab_cond", value = bl$conditions),
          if (!is.na(bl$capacity))   tibble(date = bl$date, id = "nab_cu",   value = bl$capacity)
        )
        push(bt, 3L, basename(p))
        add_log("monthly-bullet %s: date=%s cond=%s cap=%s (table not parseable)",
                basename(p), format(bl$date), bl$conditions, bl$capacity)
      } else add_log("monthly %s: NO parseable table or bullets", basename(p))
    }
  }

  if (length(rows) == 0) {
    add_log("NO DATA parsed from any source.")
    return(list(series = setNames(vector("list", length(NAB_SERIES)), names(NAB_SERIES)),
                log = log))
  }

  all <- bind_rows(rows)
  best <- all |>
    arrange(id, date, prio) |>
    group_by(id, date) |>
    slice(1) |>
    ungroup()

  series <- list()
  for (id in names(NAB_SERIES)) {
    df <- best |> filter(id == !!id) |> transmute(date, value) |>
      arrange(date) |> distinct(date, .keep_all = TRUE)
    series[[id]] <- df
    if (nrow(df) == 0) { add_log("%s: EMPTY", id); next }
    full <- seq(min(df$date), max(df$date), by = "month")
    gaps <- full[!full %in% df$date]
    add_log("%s: %d obs, %s -> %s, last=%s", id, nrow(df),
            format(min(df$date)), format(max(df$date)), tail(df$value, 1))
    if (length(gaps) == 0) add_log("  %s gaps: NONE", id)
    else add_log("  %s gaps (%d): %s", id, length(gaps),
                 paste(format(gaps, "%Y-%m"), collapse = ", "))
  }

  list(series = series, log = log)
}

#' Top-level: assemble from fixtures (+ live if reachable) and write 8 CSVs.
fetch_nab_full <- function(dest_dir = "data_raw",
                           fixtures_dir = "tests/fixtures/nab",
                           live = TRUE) {
  mp <- list.files(fixtures_dir, pattern = "^nab_monthly_.*\\.pdf$", full.names = TRUE)
  qp <- list.files(fixtures_dir, pattern = "^nab_quarterly_.*\\.pdf$", full.names = TRUE)
  res <- assemble_nab_full(monthly_paths = mp, quarterly_paths = qp, live = live)
  cat(paste(res$log, collapse = "\n"), "\n")
  dir.create(dest_dir, recursive = TRUE, showWarnings = FALSE)
  for (id in names(res$series)) {
    df <- res$series[[id]]
    if (!is.null(df) && nrow(df) > 0)
      write_csv(df, file.path(dest_dir, paste0(id, ".csv")))
  }
  invisible(res)
}

if (sys.nframe() == 0 && !interactive()) {
  fetch_nab_full()
}
