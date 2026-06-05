#### Experimental scraper: NAB Business Survey (conditions + capacity utilisation) ####
# Sub-track 1B. Produces two tidy monthly CSVs:
#   experimental/data_raw/nab_conditions.csv (date,value)  business CONDITIONS net balance
#   experimental/data_raw/nab_capacity.csv   (date,value)  capacity utilisation %
#
# DATA SOURCES (all discovered from listing pages / search, never templated):
#   * MONTHLY Business Survey PDF  — page 1 has:
#       - a "Survey Details" bullet list with the headline month's conditions & capacity
#         (e.g. "Business conditions remained at +6 index points",
#               "Capacity utilisation rose to 83.1%")
#       - SOMETIMES a selectable "Table 1: Key Monthly Business Survey Statistics"
#         giving the last 3 months as columns. When the table is rasterised (older /
#         some months) only the caption leaks through as text, so we fall back to
#         the bullets. Both paths are implemented; the table is preferred when present.
#   * QUARTERLY Business Survey PDF — has a numeric "appendix" page whose national
#       "Conditions" and "Capacity utilis." rows carry the LAST 5 MONTHLY values
#       (columns like 2025m2 ... 2025m6). Cleanest structured backfill, 5 obs/PDF.
#
# IMPORTANT (data quality): NAB REVISES prior months. The first-print bullet value in
# a given month's PDF often differs from the same month re-published (revised) in a
# later monthly Table 1 or in a quarterly appendix. For the assembled series we prefer,
# per date, the value from the MOST RECENTLY PUBLISHED source (revised wins). This is
# logged. We never invent values; every number traces to a fixture PDF.

suppressMessages({
  library(pdftools)
  library(stringr)
  library(dplyr)
  library(readr)
  library(lubridate)
  library(tibble)
})

MONTH_ABBR <- c(Jan = 1, Feb = 2, Mar = 3, Apr = 4, May = 5, Jun = 6,
                Jul = 7, Aug = 8, Sep = 9, Oct = 10, Nov = 11, Dec = 12)

# Plausibility ranges (used to reject garbage parses, never to fabricate).
COND_RANGE <- c(-60, 40)    # net balance
CAP_RANGE  <- c(60, 90)     # per cent

#' Infer the headline (latest) month of a monthly survey PDF from its title line,
#' e.g. "NAB Monthly Business Survey Apr-26" -> 2026-04-01.
.nab_title_month <- function(page1) {
  m <- str_match(page1, "Monthly Business Survey\\s+([A-Z][a-z]{2})[a-z]*[ -]?(\\d{2})\\b")
  if (is.na(m[1, 1])) return(NA_Date_)
  mon <- MONTH_ABBR[[m[1, 2]]]
  yr  <- 2000 + as.integer(m[1, 3])
  if (is.na(mon) || is.na(yr)) return(NA_Date_)
  make_date(yr, mon, 1)
}

#' Parse the Survey Details BULLETS of a monthly NAB PDF.
#' Tolerant of wording variants: "rose to", "fell to", "remained at",
#' "was flat at", "rose X pts to", "(unrounded)", optional sign, "index points"/"%".
#'
#' @param path Path to a monthly NAB Business Survey PDF.
#' @return list(date=Date, conditions=numeric|NA, capacity=numeric|NA)
parse_nab_monthly <- function(path) {
  page1 <- pdf_text(path)[1]
  d <- .nab_title_month(page1)
  flat <- str_replace_all(page1, "\\s+", " ")

  # --- Business conditions (net balance, integer, signed) ---
  # Grab the bullet sentence starting at "Business conditions" up to the first
  # "index point" mention, then pull the integer immediately before it.
  cond <- NA_real_
  cm <- str_match(
    flat,
    "Business conditions\\b[^.]*?\\(?([+-]?\\d{1,3})\\)?\\s*index point"
  )
  if (!is.na(cm[1, 2])) cond <- as.numeric(cm[1, 2])

  # --- Capacity utilisation (per cent, one decimal) ---
  cap <- NA_real_
  pm <- str_match(
    flat,
    "Capacity utilisation\\b[^.]*?(\\d{2}\\.\\d)\\s*%"
  )
  if (!is.na(pm[1, 2])) cap <- as.numeric(pm[1, 2])

  # Range sanity (drop implausible parses rather than emit junk).
  if (!is.na(cond) && (cond < COND_RANGE[1] || cond > COND_RANGE[2])) cond <- NA_real_
  if (!is.na(cap)  && (cap  < CAP_RANGE[1]  || cap  > CAP_RANGE[2]))  cap  <- NA_real_

  list(date = d, conditions = cond, capacity = cap)
}

#' Parse the selectable "Table 1: Key Monthly Business Survey Statistics" of a
#' monthly NAB PDF, when present (newer PDFs embed it as text). Returns the last
#' 3 months for both series. If the table is rasterised this returns 0 rows.
#'
#' @param path Path to a monthly NAB Business Survey PDF.
#' @return tibble(date, series in {conditions,capacity}, value)
parse_nab_monthly_table <- function(path) {
  page1 <- pdf_text(path)[1]
  lines <- str_split(page1, "\n")[[1]]

  # Header row with three month labels like "Feb-26   Mar-26   Apr-26"
  hdr_idx <- which(str_detect(
    lines, "([A-Z][a-z]{2}-\\d{2})\\s+([A-Z][a-z]{2}-\\d{2})\\s+([A-Z][a-z]{2}-\\d{2})"
  ))
  if (length(hdr_idx) == 0) return(tibble(date = as.Date(character()),
                                          series = character(), value = numeric()))
  hm <- str_match_all(lines[hdr_idx[1]], "([A-Z][a-z]{2})-(\\d{2})")[[1]]
  dates <- make_date(2000 + as.integer(hm[, 3]), MONTH_ABBR[hm[, 2]], 1)
  if (length(dates) != 3) return(tibble(date = as.Date(character()),
                                        series = character(), value = numeric()))

  pull_row <- function(label_rx) {
    ri <- which(str_detect(lines, label_rx))
    if (length(ri) == 0) return(rep(NA_real_, 3))
    # take the LAST 3 numbers on the matched line (the 3 month columns sit at the
    # right edge; any leading prose numbers are to the left)
    nums <- str_extract_all(lines[ri[1]], "[-+]?\\d+\\.?\\d*")[[1]]
    nums <- suppressWarnings(as.numeric(nums))
    nums <- nums[!is.na(nums)]
    if (length(nums) < 3) return(rep(NA_real_, 3))
    tail(nums, 3)
  }

  # The table "Business conditions" row may share a physical line with wrapped
  # prose to its left; identify it as "Business conditions" followed by exactly
  # 3 trailing numbers (and nothing else). Bullet sentences have words after
  # "conditions", so they won't match.
  cond_vals <- pull_row(
    "Business conditions\\s+[-+]?\\d+\\s+[-+]?\\d+\\s+[-+]?\\d+\\s*$"
  )
  cap_vals  <- pull_row("Capacity utilisation rate\\b")

  out <- bind_rows(
    tibble(date = dates, series = "conditions", value = cond_vals),
    tibble(date = dates, series = "capacity",   value = cap_vals)
  ) |>
    filter(!is.na(value))

  # Range sanity
  out <- out |>
    filter(
      (series == "conditions" & value >= COND_RANGE[1] & value <= COND_RANGE[2]) |
      (series == "capacity"   & value >= CAP_RANGE[1]  & value <= CAP_RANGE[2])
    )
  out
}

#' Parse the numeric appendix of a QUARTERLY NAB PDF: the national "Conditions"
#' and "Capacity utilis." rows, returning their LAST 5 MONTHLY values (columns
#' like 2025m2 ... 2025m6). Quarterly columns (YYYYqN) are ignored.
#'
#' @param path Path to a quarterly NAB Business Survey PDF.
#' @return tibble(date, series in {conditions,capacity}, value)
parse_nab_quarterly <- function(path) {
  txt <- pdf_text(path)
  empty <- tibble(date = as.Date(character()), series = character(), value = numeric())

  # Find any page carrying the national Conditions row and/or the Capacity row
  # alongside YYYYmM monthly column headers. (Older vintages split these across
  # pages, so we require EITHER series, not both, and parse each independently.)
  page_has <- function(p) {
    str_detect(p, "\\d{4}m\\d") &&
      (str_detect(p, "\\bCapacity utilis") || str_detect(p, "(?m)^\\s*Conditions\\b"))
  }
  pidx <- which(vapply(txt, page_has, logical(1)))
  if (length(pidx) == 0) return(empty)

  results <- list()
  for (p in pidx) {
    lines <- str_split(txt[p], "\n")[[1]]

    # A monthly header line: contains >=5 tokens of the form YYYYmM
    parse_month_hdr <- function(ln) {
      mm <- str_match_all(ln, "(\\d{4})m(\\d{1,2})")[[1]]
      if (nrow(mm) < 5) return(NULL)
      tail(make_date(as.integer(mm[, 2]), as.integer(mm[, 3]), 1), 5)
    }

    # For a data row, take its LAST 5 numbers (the monthly columns sit rightmost,
    # after the quarterly columns).
    last5 <- function(ln) {
      nums <- str_extract_all(ln, "(?:NA|[-+]?\\d+\\.?\\d*)")[[1]]
      nums <- suppressWarnings(as.numeric(nums))   # "NA" -> NA
      if (length(nums) < 5) return(NULL)
      tail(nums, 5)
    }

    # Find the nearest preceding month-header for a given data-row index.
    hdr_dates_for <- function(row_i) {
      for (j in seq(row_i - 1, max(1, row_i - 6))) {
        dd <- parse_month_hdr(lines[j])
        if (!is.null(dd)) return(dd)
      }
      NULL
    }

    # national Conditions row: line starting (after optional spaces/pipe) with
    # "Conditions" but NOT "Conds." (those are the next-3m/12m forecast rows)
    cond_i <- which(str_detect(lines, "^\\s*Conditions\\b"))
    for (i in cond_i) {
      dd <- hdr_dates_for(i); if (is.null(dd)) next
      vv <- last5(lines[i]);  if (is.null(vv)) next
      results[[length(results) + 1]] <-
        tibble(date = dd, series = "conditions", value = vv)
    }

    cap_i <- which(str_detect(lines, "Capacity utilis"))
    for (i in cap_i) {
      dd <- hdr_dates_for(i); if (is.null(dd)) next
      vv <- last5(lines[i]);  if (is.null(vv)) next
      results[[length(results) + 1]] <-
        tibble(date = dd, series = "capacity", value = vv)
    }
  }

  if (length(results) == 0) return(empty)
  out <- bind_rows(results) |>
    filter(!is.na(value)) |>
    distinct(date, series, .keep_all = TRUE)

  out <- out |>
    filter(
      (series == "conditions" & value >= COND_RANGE[1] & value <= COND_RANGE[2]) |
      (series == "capacity"   & value >= CAP_RANGE[1]  & value <= CAP_RANGE[2])
    )
  out
}

#### ---- Discovery + assembly (live) ---------------------------------------- ####

# FIXTURE PROVENANCE (every saved PDF -> exact source URL, all returned HTTP 200
# application/pdf and were hand-spot-checked against their human-readable text).
# Live NAB hosting (content/dam) only serves ~mid-2025+; older PDFs were recovered
# from the Internet Archive at their REAL archived paths (found via the Wayback
# CDX index, not guessed) — a 200 snapshot proves the file genuinely existed there.
#
#   nab_monthly_2023_07.pdf  web.archive.org/.../business.nab.com.au/wp-content/uploads/2023/08/NAB-Monthly-Business-Survey-July-2023.pdf
#   nab_monthly_2025_06.pdf  news.nab.com.au/content/dam/nab-news/documents/economics/nab-monthly-business-survey-june-2025.pdf
#   nab_monthly_2025_07.pdf  news.nab.com.au/content/dam/nab-news/documents/economics/2025m07-nab-monthly-business-survey.pdf
#   nab_monthly_2025_08.pdf  news.nab.com.au/content/dam/nab-news/documents/economics/nab-monthly-business-survey-august-2025.pdf
#   nab_monthly_2025_09.pdf  news.nab.com.au/content/dam/nab-news/documents/economics/2025m09%20NAB%20Monthly%20Business%20Survey.pdf
#   nab_monthly_2025_10.pdf  news.nab.com.au/content/dam/nab-news/documents/economics/nab-monthly-business-survey-oct-2025.pdf
#   nab_monthly_2025_12.pdf  www.nab.com.au/content/dam/nab-email-composer/nabmarketsresearchembargo/economics/pdf/2025m12%20NAB%20Monthly%20Business%20Survey-ewtgerb.pdf
#   nab_monthly_2026_02.pdf  news.nab.com.au/content/dam/nab-news/documents/economics/NAB%20Monthly%20Business%20Survey%20Feb%202026.pdf
#   nab_monthly_2026_03.pdf  news.nab.com.au/content/dam/nab-news/documents/economics/202603%20NAB%20Monthly%20Business%20Survey%20March.pdf
#   nab_monthly_2026_04.pdf  news.nab.com.au/content/dam/nab-news/documents/economics/202604%20NAB%20Monthly%20Business%20Survey%20April.pdf
#   nab_quarterly_2023q2.pdf web.archive.org/.../wp-content/uploads/2023/07/NAB-Quarterly-Business-Survey-Q2-2023.pdf
#   nab_quarterly_2023q3.pdf web.archive.org/.../wp-content/uploads/2023/10/NAB-Quarterly-Business-Survey-Q3-2023.pdf  (cond only; appendix has no monthly capacity row)
#   nab_quarterly_2023q4.pdf web.archive.org/.../wp-content/uploads/2024/02/NAB-Quarterly-Business-Survey-Q4-2023.pdf
#   nab_quarterly_2024q1.pdf web.archive.org/.../wp-content/uploads/2024/04/NAB-Quarterly-Business-Survey-Q1-2024.pdf
#   nab_quarterly_2024q2.pdf web.archive.org/.../wp-content/uploads/2024/07/NAB-Quarterly-Business-Survey-Q2-2024.pdf
#   nab_quarterly_2024q3.pdf web.archive.org/.../wp-content/uploads/2024/10/NAB-Quarterly-Business-Survey-Q3-2024.pdf
#   nab_quarterly_2024q4.pdf web.archive.org/.../wp-content/uploads/2025/02/NAB-Quarterly-Business-Survey-Q4-2024-1.pdf
#   nab_quarterly_2025q1.pdf business.nab.com.au/content/dam/nab-business/document/NAB-Quarterly-Business-Survey-Q1-2025.pdf
#   nab_quarterly_2025q2.pdf business.nab.com.au/content/dam/nab-business/document/NAB-Quarterly-Business-Survey-Q2-2025.pdf
#   nab_quarterly_2025q3.pdf news.nab.com.au/content/dam/nab-news/documents/economics/2025q3%20NAB%20Qtly%20Business%20Survey.pdf
#   nab_quarterly_2026q1.pdf news.nab.com.au/content/dam/nab-news/documents/economics/NAB%20Qtly%20Business%20Survey%20-%20Q1%202026.pdf
#
# DISCOVERY METHOD (reproducible): resolve a news.nab.com.au article page (e.g.
# news.nab.com.au/tag/economic-market/<slug>) and grep its raw HTML for
# /content/dam/.../economics/*.pdf — the link is in the server-rendered markup.
# (business.nab.com.au/tag/business-survey is JS-rendered and exposes no links
# in raw HTML, so prefer the news.nab.com.au tag pages.)
#
# Seed list of live (non-archive) monthly/quarterly URLs used by live downloads.
NAB_MONTHLY_PDFS <- c(
  "2026m04" = "https://news.nab.com.au/content/dam/nab-news/documents/economics/202604%20NAB%20Monthly%20Business%20Survey%20April.pdf",
  "2026m03" = "https://news.nab.com.au/content/dam/nab-news/documents/economics/202603%20NAB%20Monthly%20Business%20Survey%20March.pdf",
  "2026m02" = "https://news.nab.com.au/content/dam/nab-news/documents/economics/NAB%20Monthly%20Business%20Survey%20Feb%202026.pdf"
)
NAB_QUARTERLY_PDFS <- c(
  "2025q2" = "https://business.nab.com.au/content/dam/nab-business/document/NAB-Quarterly-Business-Survey-Q2-2025.pdf"
)

#' Download a URL to a temp file; returns path or NA on failure (never stops the
#' whole run — a single dead link is logged and skipped, not fabricated).
.nab_download <- function(url, tries = 3) {
  for (k in seq_len(tries)) {
    tmp <- tempfile(fileext = ".pdf")
    ok <- tryCatch(
      utils::download.file(url, tmp, mode = "wb", quiet = TRUE,
                           method = "libcurl",
                           headers = c("User-Agent" = "Mozilla/5.0")),
      error = function(e) 1L
    )
    if (ok == 0 && file.exists(tmp) && file.info(tmp)$size > 5000) {
      # confirm it's really a PDF, not an HTML 404 page
      hdr <- readBin(tmp, "raw", 5)
      if (rawToChar(hdr) == "%PDF-") return(tmp)
    }
    Sys.sleep(1)
  }
  NA_character_
}

#' Assemble the two series from a set of local PDF paths (fixtures) and/or live
#' downloads. Priority per date (revised wins): quarterly appendix > monthly
#' Table 1 > monthly bullet. Returns list(conditions=tibble, capacity=tibble, log=character).
assemble_nab <- function(monthly_paths = character(), quarterly_paths = character(),
                         monthly_urls = NAB_MONTHLY_PDFS,
                         quarterly_urls = NAB_QUARTERLY_PDFS,
                         live = FALSE) {
  log <- character()
  add_log <- function(...) log[[length(log) + 1]] <<- sprintf(...)

  # Resolve live downloads if requested.
  if (live) {
    for (u in quarterly_urls) {
      p <- .nab_download(u)
      if (is.na(p)) { add_log("DOWNLOAD FAIL (quarterly): %s", u) }
      else quarterly_paths <- c(quarterly_paths, p)
    }
    for (u in monthly_urls) {
      p <- .nab_download(u)
      if (is.na(p)) { add_log("DOWNLOAD FAIL (monthly): %s", u) }
      else monthly_paths <- c(monthly_paths, p)
    }
  }

  # Collect with a priority rank: 1=quarterly, 2=monthly table, 3=monthly bullet.
  rows <- list()
  push <- function(tbl, prio, src) {
    if (nrow(tbl) == 0) return(invisible())
    rows[[length(rows) + 1]] <<- tbl |> mutate(prio = prio, src = src)
  }

  for (p in quarterly_paths) {
    q <- tryCatch(parse_nab_quarterly(p), error = function(e) {
      add_log("PARSE FAIL (quarterly %s): %s", basename(p), conditionMessage(e)); NULL })
    if (!is.null(q)) {
      push(q, 1L, basename(p))
      add_log("quarterly %s: %d obs (%s..%s)", basename(p), nrow(q),
              format(min(q$date)), format(max(q$date)))
    }
  }
  for (p in monthly_paths) {
    tb <- tryCatch(parse_nab_monthly_table(p), error = function(e) {
      add_log("PARSE FAIL (monthly-table %s): %s", basename(p), conditionMessage(e)); NULL })
    if (!is.null(tb) && nrow(tb) > 0) {
      push(tb, 2L, basename(p))
      add_log("monthly-table %s: %d obs", basename(p), nrow(tb))
    }
    bl <- tryCatch(parse_nab_monthly(p), error = function(e) {
      add_log("PARSE FAIL (monthly-bullet %s): %s", basename(p), conditionMessage(e)); NULL })
    if (!is.null(bl) && !is.na(bl$date)) {
      bt <- bind_rows(
        if (!is.na(bl$conditions)) tibble(date = bl$date, series = "conditions", value = bl$conditions),
        if (!is.na(bl$capacity))   tibble(date = bl$date, series = "capacity",   value = bl$capacity)
      )
      push(bt, 3L, basename(p))
      add_log("monthly-bullet %s: date=%s cond=%s cap=%s", basename(p),
              format(bl$date), bl$conditions, bl$capacity)
    }
  }

  if (length(rows) == 0) {
    add_log("NO DATA parsed from any source.")
    return(list(conditions = tibble(date = as.Date(character()), value = numeric()),
                capacity   = tibble(date = as.Date(character()), value = numeric()),
                log = log))
  }

  all <- bind_rows(rows)

  # Per (series,date) keep the highest-priority (lowest prio number) source.
  best <- all |>
    arrange(series, date, prio) |>
    group_by(series, date) |>
    slice(1) |>
    ungroup()

  mk <- function(s) {
    best |> filter(series == s) |>
      transmute(date, value) |> arrange(date) |>
      distinct(date, .keep_all = TRUE)
  }
  cond <- mk("conditions")
  cap  <- mk("capacity")

  # Coverage + gap logging.
  describe <- function(name, df) {
    if (nrow(df) == 0) { add_log("%s: EMPTY", name); return(invisible()) }
    full <- seq(min(df$date), max(df$date), by = "month")
    gaps <- full[!full %in% df$date]
    add_log("%s: %d obs, %s -> %s, last=%s", name, nrow(df),
            format(min(df$date)), format(max(df$date)), tail(df$value, 1))
    if (length(gaps) == 0) add_log("%s gaps: NONE", name)
    else add_log("%s gaps (%d): %s", name, length(gaps),
                 paste(format(gaps, "%Y-%m"), collapse = ", "))
  }
  describe("conditions", cond)
  describe("capacity", cap)

  list(conditions = cond, capacity = cap, log = log)
}

#' Top-level: assemble (live by default) and write the two CSVs.
fetch_nab_survey <- function(dest_dir = "experimental/data_raw",
                             fixtures_dir = "experimental/tests/fixtures/nab",
                             live = TRUE) {
  # Always include local fixtures (reproducible), plus live if reachable.
  mp <- list.files(fixtures_dir, pattern = "^nab_monthly_.*\\.pdf$", full.names = TRUE)
  qp <- list.files(fixtures_dir, pattern = "^nab_quarterly_.*\\.pdf$", full.names = TRUE)

  res <- assemble_nab(monthly_paths = mp, quarterly_paths = qp, live = live)
  cat(paste(res$log, collapse = "\n"), "\n")

  dir.create(dest_dir, recursive = TRUE, showWarnings = FALSE)
  if (nrow(res$conditions) > 0)
    write_csv(res$conditions, file.path(dest_dir, "nab_conditions.csv"))
  if (nrow(res$capacity) > 0)
    write_csv(res$capacity, file.path(dest_dir, "nab_capacity.csv"))

  invisible(res)
}

if (sys.nframe() == 0 && !interactive()) {
  fetch_nab_survey()
}
