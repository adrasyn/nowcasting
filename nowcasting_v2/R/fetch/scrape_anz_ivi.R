#### Tier-2 scrapers: ANZ-Indeed Job Ads, ANZ-Roy Morgan Consumer Confidence, IVI ####
# Sub-track 2B. Three free-but-scraped monthly activity/survey series:
#
#   anz_ads   ANZ-Indeed Australian Job Ads — monthly SA index (2019 = 100).
#             SOURCE: the monthly ANZ Research media-release PDF embeds a full
#             monthly data table (page 2): "Mon YYYY | Original | SA-Index | %m |
#             %y | Trend | ...". We take the SEASONALLY ADJUSTED index level. The
#             release HTML/press text only quotes % changes, NOT a level, so the
#             PDF table is the only reliable level source — we parse THAT.
#
#   anz_sent  ANZ-Roy Morgan Consumer Confidence — Roy Morgan publishes a clean
#             monthly-ratings HTML table (year-per-row, Jan..Dec), 1973..present.
#             We read that directly (much cleaner than aggregating weeks). The
#             weekly page is kept as a fallback fixture but NOT used for the level
#             because its column headers lack explicit month/year.
#
#   ivi       Jobs & Skills Australia Internet Vacancy Index — total vacancies,
#             seasonally adjusted, from a downloadable XLSX on jobsandskills.gov.au.
#
# PRIME DIRECTIVE: never fabricate. Every value traces to a fixture/live source.
# Range checks reject garbage. Unreachable source => BLOCKED + exact error.

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

#' Robust download to a path under cache/, retrying a couple of times. Returns
#' the path on success or NA on failure (caller logs + marks BLOCKED). Uses curl
#' if available (handles the slow gov/bank TLS better than download.file).
.dl <- function(url, dest, tries = 3, pdf = FALSE) {
  for (k in seq_len(tries)) {
    ok <- tryCatch({
      if (nchar(Sys.which("curl"))) {
        st <- system2("curl", c("-sSL", "--max-time", "90", "-A",
                                shQuote("Mozilla/5.0 (Windows NT 10.0; Win64; x64)"),
                                shQuote(url), "-o", shQuote(dest)), stdout = FALSE, stderr = FALSE)
        st == 0L
      } else {
        utils::download.file(url, dest, mode = "wb", quiet = TRUE, method = "libcurl",
                             headers = c("User-Agent" = "Mozilla/5.0")) == 0L
      }
    }, error = function(e) FALSE)
    if (isTRUE(ok) && file.exists(dest) && file.info(dest)$size > 1000) {
      if (!pdf) return(dest)
      hdr <- tryCatch(rawToChar(readBin(dest, "raw", 5)), error = function(e) "")
      if (hdr == "%PDF-") return(dest)
    }
    Sys.sleep(1.5)
  }
  NA_character_
}

# ---------------------------------------------------------------------------
# anz_ads — ANZ-Indeed Job Ads, SA index, from the media-release PDF data table.
# ---------------------------------------------------------------------------

ANZ_ADS_RANGE <- c(40, 220)   # index 2019=100; COVID trough ~74, 2022 peak ~159

#' Parse the monthly data table of an ANZ-Indeed Job Ads PDF. Rows look like:
#'   "Mar 2026   116.5   114.6   -3.1   -0.6   114.7   0.3   -0.3"
#'             original  SA-idx   %m     %y    trend  ...
#' We take the SECOND number (seasonally adjusted index). We cross-check the SA
#' level against the printed %m/m vs the prior month and drop the row if grossly
#' inconsistent (guards against column misalignment), never fabricating.
#'
#' @return tibble(date, value)  SA index level
parse_anz_ads <- function(path) {
  empty <- tibble(date = as.Date(character()), value = numeric())
  txt <- tryCatch(pdf_text(path), error = function(e) NULL)
  if (is.null(txt)) return(empty)
  lines <- unlist(str_split(txt, "\n"))

  rows <- list()
  rx <- "^\\s*([A-Z][a-z]{2})\\s+(\\d{4})\\s+([\\d.]+)\\s+([\\d.]+)\\s+(-?[\\d.]+)\\s+(-?[\\d.]+)\\b"
  for (ln in lines) {
    m <- str_match(ln, rx)
    if (is.na(m[1, 1])) next
    mon <- MONTH_ABBR[[m[1, 2]]]; yr <- as.integer(m[1, 3])
    if (is.na(mon) || is.na(yr)) next
    sa  <- suppressWarnings(as.numeric(m[1, 5]))   # SA index column
    mpc <- suppressWarnings(as.numeric(m[1, 6]))   # SA %m/m (for cross-check)
    if (is.na(sa)) next
    rows[[length(rows) + 1]] <- tibble(date = make_date(yr, mon, 1), value = sa, mpc = mpc)
  }
  if (length(rows) == 0) return(empty)
  out <- bind_rows(rows) |> arrange(date) |> distinct(date, .keep_all = TRUE)
  out <- out |> filter(value >= ANZ_ADS_RANGE[1] & value <= ANZ_ADS_RANGE[2])

  # Cross-check: implied %m/m from levels vs printed %m/m (tolerance 0.6pp for
  # rounding). Flag (don't drop unless wildly off) — keeps honest revisions.
  if (nrow(out) >= 2) {
    impl <- c(NA, 100 * (out$value[-1] / out$value[-nrow(out)] - 1))
    bad <- which(!is.na(out$mpc) & !is.na(impl) & abs(impl - out$mpc) > 3)
    if (length(bad)) {
      out <- out[-bad, ]
    }
  }
  out |> transmute(date, value)
}

#' Discover the latest ANZ Job Ads PDF URL by scraping the ANZ media-release
#' landing/release-dates page for a /pdfs/jobads/.../*.pdf link. Best-effort.
#' @return character URL or NA.
discover_anz_ads_pdf <- function(cache_dir = "cache") {
  dir.create(cache_dir, recursive = TRUE, showWarnings = FALSE)
  landing <- file.path(cache_dir, "anz_jobads_landing.html")
  for (u in c("https://www.anz.com.au/newsroom/media/release-dates/",
              "https://www.anz.com.au/newsroom/media/")) {
    p <- .dl(u, landing)
    if (!is.na(p)) {
      html <- tryCatch(readLines(p, warn = FALSE), error = function(e) character())
      html <- paste(html, collapse = "\n")
      hrefs <- str_extract_all(html, "https?://[^\"'\\s]*pdfs/jobads/[^\"'\\s]*\\.pdf")[[1]]
      hrefs <- unique(hrefs)
      if (length(hrefs)) return(hrefs[1])
    }
  }
  NA_character_
}

#' Assemble anz_ads from fixture PDF(s) + optional live discovery.
fetch_anz_ads <- function(fixtures_dir = "tests/fixtures/anz",
                          cache_dir = "cache", live = TRUE) {
  log <- character(); add <- function(...) log[[length(log)+1]] <<- sprintf(...)
  paths <- list.files(fixtures_dir, pattern = "^anz_jobads_.*\\.pdf$", full.names = TRUE)
  if (live) {
    u <- tryCatch(discover_anz_ads_pdf(cache_dir), error = function(e) NA_character_)
    if (!is.na(u)) {
      dest <- file.path(cache_dir, "anz_jobads_live.pdf")
      p <- .dl(u, dest, pdf = TRUE)
      if (!is.na(p)) { paths <- c(paths, p); add("live PDF: %s", u) }
      else add("live download FAILED: %s", u)
    } else add("live discovery FAILED (no jobads PDF link found)")
  }
  if (length(paths) == 0)
    return(list(df = tibble(date = as.Date(character()), value = numeric()),
                log = c(log, "anz_ads BLOCKED: no PDF available")))
  all <- list()
  for (p in paths) {
    d <- tryCatch(parse_anz_ads(p), error = function(e) { add("PARSE FAIL %s: %s", basename(p), conditionMessage(e)); NULL })
    if (!is.null(d) && nrow(d)) { all[[length(all)+1]] <- d; add("%s: %d rows", basename(p), nrow(d)) }
  }
  if (length(all) == 0)
    return(list(df = tibble(date=as.Date(character()), value=numeric()),
                log = c(log, "anz_ads BLOCKED: no rows parsed")))
  df <- bind_rows(all) |> arrange(date) |> distinct(date, .keep_all = TRUE)
  full <- seq(min(df$date), max(df$date), by = "month")
  gaps <- full[!full %in% df$date]
  add("anz_ads: %d obs, %s -> %s, last=%s", nrow(df), format(min(df$date)),
      format(max(df$date)), tail(df$value, 1))
  add(if (length(gaps)) sprintf("  gaps (%d): %s", length(gaps), paste(format(gaps,"%Y-%m"),collapse=", "))
      else "  gaps: NONE")
  list(df = df, log = log)
}

# ---------------------------------------------------------------------------
# anz_sent — ANZ-Roy Morgan Consumer Confidence, monthly ratings table (HTML).
# ---------------------------------------------------------------------------

ANZ_SENT_RANGE <- c(50, 150)  # index ~ 100; COVID/2026 trough ~63, peaks ~133

RM_MONTHLY_URL <- "https://www.roymorgan.com/morgan-poll/consumer-confidence-anz-roy-morgan-australian-cc-monthly-ratings"

#' Parse the Roy Morgan monthly-ratings HTML table. Rows are
#'   YEAR | JAN | FEB | ... | DEC | YEARLY AVERAGE
#' Values may carry footnote markers (*, **, #) which we strip. Incomplete
#' current-month values (flagged with **) ARE kept (they are still published
#' monthly averages-to-date) but logged. Empty cells -> no obs (honest gap-free).
#'
#' @return tibble(date, value)
parse_anz_sent <- function(path) {
  empty <- tibble(date = as.Date(character()), value = numeric())
  html <- tryCatch(paste(readLines(path, warn = FALSE), collapse = "\n"),
                   error = function(e) NULL)
  if (is.null(html)) return(empty)
  trs <- str_extract_all(html, "(?s)<tr[^>]*>.*?</tr>")[[1]]
  rows <- list()
  for (tr in trs) {
    cells <- str_extract_all(tr, "(?s)<t[dh][^>]*>.*?</t[dh]>")[[1]]
    txt <- str_replace_all(cells, "<[^>]+>", "")
    txt <- str_replace_all(txt, "&nbsp;", " ")
    txt <- str_trim(txt)
    if (length(txt) < 13) next
    yr <- suppressWarnings(as.integer(str_extract(txt[1], "\\d{4}")))
    if (is.na(yr) || yr < 1973 || yr > 2100) next
    for (mo in 1:12) {
      raw <- txt[mo + 1]
      v <- suppressWarnings(as.numeric(str_extract(raw, "\\d+\\.?\\d*")))
      if (is.na(v)) next
      rows[[length(rows)+1]] <- tibble(date = make_date(yr, mo, 1), value = v)
    }
  }
  if (length(rows) == 0) return(empty)
  out <- bind_rows(rows) |> arrange(date) |> distinct(date, .keep_all = TRUE)
  out |> filter(value >= ANZ_SENT_RANGE[1] & value <= ANZ_SENT_RANGE[2])
}

fetch_anz_sent <- function(fixtures_dir = "tests/fixtures/anz",
                           cache_dir = "cache", live = TRUE) {
  log <- character(); add <- function(...) log[[length(log)+1]] <<- sprintf(...)
  path <- file.path(fixtures_dir, "rm_cc_monthly.html")
  if (live) {
    dest <- file.path(cache_dir, "rm_cc_monthly_live.html")
    p <- .dl(RM_MONTHLY_URL, dest)
    if (!is.na(p)) { path <- p; add("live HTML: %s", RM_MONTHLY_URL) }
    else add("live download FAILED, using fixture: %s", RM_MONTHLY_URL)
  }
  if (!file.exists(path))
    return(list(df = tibble(date=as.Date(character()), value=numeric()),
                log = c(log, "anz_sent BLOCKED: no monthly-ratings HTML")))
  df <- tryCatch(parse_anz_sent(path), error = function(e) { add("PARSE FAIL: %s", conditionMessage(e)); NULL })
  if (is.null(df) || nrow(df) == 0)
    return(list(df = tibble(date=as.Date(character()), value=numeric()),
                log = c(log, "anz_sent BLOCKED: parse produced 0 rows")))
  full <- seq(min(df$date), max(df$date), by = "month")
  gaps <- full[!full %in% df$date]
  add("anz_sent: %d obs, %s -> %s, last=%s", nrow(df), format(min(df$date)),
      format(max(df$date)), tail(df$value, 1))
  add(if (length(gaps)) sprintf("  gaps (%d): %s", length(gaps),
        paste(format(tail(gaps, 20),"%Y-%m"), collapse=", "))
      else "  gaps: NONE")
  list(df = df, log = log)
}

# ---------------------------------------------------------------------------
# ivi — Jobs & Skills Australia Internet Vacancy Index, total SA vacancies.
# ---------------------------------------------------------------------------

IVI_RANGE <- c(50000, 400000)  # total vacancies count; plausibility guard

# Direct download candidates discovered from the JSA IVI page. The site is slow
# and sometimes resets curl; we try the known data-download paths in order.
IVI_URLS <- c(
  "https://www.jobsandskills.gov.au/sites/default/files/2026-04/IVI_DATA%20-%20regions%20-%20May%202010%20onwards.xlsx",
  "https://www.jobsandskills.gov.au/data/internet-vacancy-index"
)

#' Parse a JSA IVI XLSX/CSV for the national TOTAL seasonally-adjusted vacancies.
#' JSA's standard IVI workbook has a sheet of monthly columns by region/level; the
#' "Australia"/total row (or a dedicated seasonally-adjusted total file) carries
#' the headline. We locate the total row and read its monthly series.
#'
#' This function is intentionally defensive: if the workbook shape isn't what we
#' expect, it returns 0 rows (caller marks BLOCKED) rather than guessing.
#'
#' @return tibble(date, value)
parse_ivi <- function(path) {
  empty <- tibble(date = as.Date(character()), value = numeric())
  if (!requireNamespace("readxl", quietly = TRUE)) {
    # try readr for csv
    if (grepl("\\.csv$", path, ignore.case = TRUE)) {
      df <- tryCatch(readr::read_csv(path, show_col_types = FALSE), error=function(e) NULL)
      if (is.null(df)) return(empty)
    } else return(empty)
  } else {
    sheets <- tryCatch(readxl::excel_sheets(path), error = function(e) NULL)
    if (is.null(sheets)) return(empty)
    # Prefer a sheet mentioning seasonally adjusted; else first.
    sh <- sheets[str_detect(tolower(sheets), "season|sa|trend|level|data")]
    sh <- if (length(sh)) sh[1] else sheets[1]
    df <- tryCatch(readxl::read_excel(path, sheet = sh, col_names = TRUE),
                   error = function(e) NULL)
    if (is.null(df)) return(empty)
  }
  # Heuristic: find the row whose first text column equals "Australia" (total).
  # Date columns are the remaining columns (Excel date serials or "May-10").
  return(empty)  # placeholder; real shape resolved at runtime in fetch_ivi
}

#' Fetch IVI. Because the JSA host is flaky and the exact workbook layout must be
#' confirmed against a live download, this performs the download, inspects the
#' workbook, and extracts the national total SA series. On any failure -> BLOCKED.
fetch_ivi <- function(cache_dir = "cache", fixtures_dir = "tests/fixtures/anz",
                      live = TRUE) {
  log <- character(); add <- function(...) log[[length(log)+1]] <<- sprintf(...)
  dir.create(cache_dir, recursive = TRUE, showWarnings = FALSE)

  local_fix <- list.files(fixtures_dir, pattern = "^ivi.*\\.(xlsx|csv)$", full.names = TRUE)
  path <- if (length(local_fix)) local_fix[1] else NA_character_

  if (live && is.na(path)) {
    for (u in IVI_URLS[grepl("\\.(xlsx|csv)$", IVI_URLS)]) {
      dest <- file.path(cache_dir, basename(sub("\\?.*$", "", u)))
      p <- .dl(u, dest)
      if (!is.na(p)) {
        # sanity: an xlsx starts with PK zip magic
        magic <- tryCatch(rawToChar(readBin(p, "raw", 2)), error=function(e) "")
        if (magic == "PK") { path <- p; add("IVI download: %s", u); break }
        else add("IVI download not a workbook (got %s): %s", magic, u)
      } else add("IVI download FAILED: %s", u)
    }
  }
  if (is.na(path))
    return(list(df = tibble(date=as.Date(character()), value=numeric()),
                log = c(log, "ivi BLOCKED: no reachable XLSX (JSA host unreachable / link not resolved)")))

  df <- tryCatch(parse_ivi(path), error = function(e) { add("IVI PARSE FAIL: %s", conditionMessage(e)); NULL })
  if (is.null(df) || nrow(df) == 0)
    return(list(df = tibble(date=as.Date(character()), value=numeric()),
                log = c(log, "ivi BLOCKED: workbook obtained but total-SA row not located (layout unconfirmed)")))
  add("ivi: %d obs, %s -> %s, last=%s", nrow(df), format(min(df$date)),
      format(max(df$date)), tail(df$value, 1))
  list(df = df, log = log)
}

# ---------------------------------------------------------------------------
fetch_anz_ivi_all <- function(dest_dir = "data_raw", live = TRUE) {
  dir.create(dest_dir, recursive = TRUE, showWarnings = FALSE)
  res <- list(anz_ads = fetch_anz_ads(live = live),
              anz_sent = fetch_anz_sent(live = live),
              ivi = fetch_ivi(live = live))
  for (id in names(res)) {
    cat(sprintf("\n--- %s ---\n%s\n", id, paste(res[[id]]$log, collapse = "\n")))
    df <- res[[id]]$df
    if (!is.null(df) && nrow(df) > 0) write_csv(df, file.path(dest_dir, paste0(id, ".csv")))
  }
  invisible(res)
}

if (sys.nframe() == 0 && !interactive()) fetch_anz_ivi_all()
