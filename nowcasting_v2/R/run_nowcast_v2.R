# run_nowcast_v2.R
# Phase 4.2 -- end-to-end nowcast v2 driver.
#
# Chains the two stages:
#   Stage 1 (MAI):    build_panel() -> transform_panel() -> build_mai()
#   Stage 2 (nowcast): nowcast_midas()  (QA U-MIDAS, RBA RDP 2024-04 engine)
#
# Flags:
#   --no-fetch   Reuse the cached panel vintage (cache/panel_vintage_latest.rds)
#                and cached GDP/MAI CSVs instead of re-fetching from ABS/RBA.
#                build_panel() reads the already-downloaded data_raw/*.csv, so the
#                chain runs fully offline on cached data.
#
# Prints the current-quarter nowcast (target quarter, QoQ %, implied level) and
# the MAI tail. Fail loud on any stage error.

suppressWarnings(suppressMessages({
  here <- tryCatch(dirname(sys.frame(1)$ofile), error = function(e) NA)
}))
if (is.na(here) || !nzchar(here)) here <- "R"
source(file.path(here, "_setup.R"))
source(file.path(here, "build_panel.R"))
source(file.path(here, "transform_panel.R"))
source(file.path(here, "build_mai.R"))
source(file.path(here, "nowcast_midas.R"))

suppressMessages({ library(readr) })

# Latest released GDP chain-volume LEVEL (millions). Used only to express the
# growth nowcast as a level (prev_level = level of the quarter before target).
# Source order:
#   (1) fetch ABS series A2304402X live (unless --no-fetch),
#   (2) cache/rt_gdp_level.rds (written on a previous fetch),
#   (3) v1 output data/latest.json (READ ONLY) -- nowcast.gdp_chain_volume_millions
#       is the most recent quarter's level v1 carries; latest_actual is one prior.
# Returns list(level, date, source) or NULL.
get_prev_level <- function(no_fetch, repo_root) {
  cache_rds <- "cache/rt_gdp_level.rds"

  if (!no_fetch) {
    lev <- tryCatch({
      suppressMessages(library(readabs)); suppressMessages(library(dplyr))
      Sys.setenv(R_READABS_PATH = tempdir())
      raw <- read_abs_series("A2304402X")
      d <- raw %>% dplyr::select(date, value) %>%
        dplyr::filter(!is.na(value)) %>% dplyr::arrange(date)
      d
    }, error = function(e) { message("get_prev_level(): ABS fetch failed: ", conditionMessage(e)); NULL })
    if (!is.null(lev) && nrow(lev) > 0L) {
      dir.create("cache", showWarnings = FALSE, recursive = TRUE)
      saveRDS(lev, cache_rds)
      return(list(level = tail(lev$value, 1L), date = tail(lev$date, 1L), source = "ABS A2304402X (live)"))
    }
  }

  if (file.exists(cache_rds)) {
    lev <- readRDS(cache_rds)
    return(list(level = tail(lev$value, 1L), date = tail(lev$date, 1L), source = "cache/rt_gdp_level.rds"))
  }

  # Fallback: v1 latest.json
  lj <- file.path(repo_root, "data", "latest.json")
  if (file.exists(lj)) {
    txt <- paste(readLines(lj, warn = FALSE), collapse = "\n")
    m <- regmatches(txt, regexpr('"nowcast"\\s*:\\s*\\{[^}]*"gdp_chain_volume_millions"\\s*:\\s*[0-9.]+', txt))
    if (length(m) == 1L) {
      val <- as.numeric(sub('.*"gdp_chain_volume_millions"\\s*:\\s*', '', m))
      return(list(level = val, date = NA, source = "v1 data/latest.json (nowcast level)"))
    }
  }
  NULL
}

run_nowcast_v2 <- function(no_fetch = TRUE, repo_root = "..") {

  cat("############################################################\n")
  cat("# nowcast v2 -- end-to-end run", if (no_fetch) "(--no-fetch: cached data)" else "(live fetch)", "\n")
  cat("############################################################\n\n")

  # ---- Stage 1: MAI ----
  if (no_fetch && file.exists("cache/panel_vintage_latest.rds")) {
    cat("[1/4] build_panel: reusing cached vintage cache/panel_vintage_latest.rds\n")
    wide <- readRDS("cache/panel_vintage_latest.rds")
  } else {
    cat("[1/4] build_panel: assembling panel from data_raw/*.csv\n")
    wide <- build_panel()
  }

  cat("[2/4] transform_panel\n")
  tfs <- transform_panel(wide, "seed/panel_info.csv")

  cat("[3/4] build_mai\n")
  mai_out <- build_mai(tfs = tfs, out_csv = "data_raw/mai.csv", out_rds = "cache/mai.rds")
  mai <- mai_out$mai

  # ---- Stage 2: nowcast ----
  cat("[4/4] nowcast_midas (QA U-MIDAS)\n")
  gdp <- read.csv("data_raw/rt_dgdp_qtr.csv")

  pl <- get_prev_level(no_fetch = no_fetch, repo_root = repo_root)
  prev_level <- if (is.null(pl)) NULL else pl$level

  nc <- nowcast_midas(mai, gdp, prev_level = prev_level)

  # ---- Report ----
  cat("\n------------------------------------------------------------\n")
  cat("CURRENT-QUARTER NOWCAST (nowcast v2)\n")
  cat("------------------------------------------------------------\n")
  cat(sprintf("  Target quarter      : %s\n", nc$target_quarter))
  cat(sprintf("  QoQ growth          : %+.3f%%\n", nc$qoq_growth))
  if (is.na(nc$nowcast_level)) {
    cat("  Implied level        : NA (no prev_level available)\n")
  } else {
    cat(sprintf("  Implied level (m$)  : %.0f\n", nc$nowcast_level))
    cat(sprintf("  prev quarter level  : %.0f  [%s]\n", pl$level, pl$source))
  }
  cat(sprintf("  Model               : %s\n", nc$model))
  cat(sprintf("  Fit sample          : %s .. %s (n_obs = %d)\n",
              nc$sample_start, nc$sample_end, nc$n_obs))
  cat(sprintf("  MAI months in target: %d\n", nc$n_months_in_quarter))

  cat("\nMAI tail (last 6 months):\n")
  print(tail(mai, 6))
  cat("\n")

  invisible(list(nowcast = nc, mai = mai, prev_level = pl))
}

if (sys.nframe() == 0L) {
  args <- commandArgs(trailingOnly = TRUE)
  no_fetch <- "--no-fetch" %in% args
  run_nowcast_v2(no_fetch = no_fetch)
}
