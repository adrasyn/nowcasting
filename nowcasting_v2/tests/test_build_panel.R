# test_build_panel.R -- shape / monthly-date / no-all-NA checks for build_panel()
here <- "R"
source(file.path(here, "_setup.R"))
source(file.path(here, "build_panel.R"))
suppressMessages(library(readr))

fail <- function(msg) { cat("FAIL:", msg, "\n"); quit(status = 1L) }

w <- build_panel()

info <- read_csv("seed/panel_info.csv", show_col_types = FALSE)
hc <- info$has_csv; if (is.character(hc)) hc <- toupper(hc) %in% c("TRUE","T")
expected_ids <- info$id[hc %in% TRUE]

# 1. wide shape: one column per has_csv id + date
ids <- setdiff(names(w), "date")
if (!setequal(ids, expected_ids)) fail("column set != has_csv ids")
if (!"date" %in% names(w)) fail("no date column")

# 2. monthly first-of-month dates, strictly increasing, no gaps
d <- w$date
if (any(as.integer(format(d, "%d")) != 1L)) fail("dates not first-of-month")
gaps <- as.integer(round(diff(as.numeric(d)) / 30.4))
# every consecutive pair should be ~1 month apart
mdiff <- mapply(function(a, b) length(seq(a, b, by = "month")) - 1L, head(d, -1), tail(d, -1))
if (any(mdiff != 1L)) fail("monthly spine has gaps")

# 3. no all-NA columns
allna <- vapply(w[, ids], function(x) all(is.na(x)), logical(1))
if (any(allna)) fail(paste("all-NA columns:", paste(ids[allna], collapse=",")))

cat(sprintf("PASS test_build_panel: %d series x %d months, monthly spine, no all-NA cols\n",
            length(ids), nrow(w)))
