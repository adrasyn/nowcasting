# diag_consumption.R -- C1 diagnostic.
# Compute pre-COVID corr of each consumption-proxy candidate's growth transform
# (t2 + log, RBA-style, quarter-averaged of within-quarter monthly growth) with
# quarterly GDP growth. Compares current rt (A3348585R) vs household_spending
# (A130200584T). Uses the SAME transform math as transform_panel (transform_series).

here <- "R"
source(file.path(here, "_setup.R"))
source(file.path(here, "methods", "misc_methods.R"))
suppressMessages({ library(readr) })

PRECOVID_END <- as.Date("2019-12-01")

gdp <- read_csv("data_raw/rt_dgdp_qtr.csv", show_col_types = FALSE)
gdp$date <- as.Date(gdp$date)

# Quarter-average a monthly series of growth onto ABS quarter-end label.
qtr_avg <- function(d, val) {
  yr <- as.integer(format(d, "%Y")); mo <- as.integer(format(d, "%m"))
  qi <- (mo - 1L) %/% 3L; qend_mo <- qi*3L + 3L
  ql <- as.Date(sprintf("%04d-%02d-01", yr, qend_mo))
  agg <- tapply(val, ql, function(v) if (sum(!is.na(v))==3L) mean(v, na.rm=TRUE) else NA_real_)
  data.frame(date = as.Date(names(agg)), value = as.numeric(agg))
}

precovid_corr_of_growth <- function(csv, tcode = "t2", tlog = TRUE) {
  d <- read_csv(csv, show_col_types = FALSE)
  d$date <- as.Date(d$date); d <- d[order(d$date), ]
  tx <- as.numeric(transform_series(x = d$value, take_log = tlog, tcode = tcode))
  # transform_series drops 1 leading obs for t2
  dt <- d$date[(nrow(d) - length(tx) + 1L):nrow(d)]
  qa <- qtr_avg(dt, tx)
  m <- merge(qa, gdp, by = "date", suffixes = c("_x","_g"))
  m <- m[m$date <= PRECOVID_END & complete.cases(m), ]
  mfull <- merge(qa, gdp, by="date", suffixes=c("_x","_g")); mfull <- mfull[complete.cases(mfull),]
  list(precovid = cor(m$value_x, m$value_g), n_pre = nrow(m),
       full = cor(mfull$value_x, mfull$value_g), n_full = nrow(mfull),
       range = range(dt))
}

cat("=== C1 consumption-proxy diagnostic ===\n")
for (cand in list(
  c(id="rt (A3348585R retail turnover)", csv="data_raw/rt.csv"),
  c(id="household_spending (A130200584T MHSI)", csv="data_raw/household_spending.csv")
)) {
  if (!file.exists(cand["csv"])) { cat(sprintf("%-42s : (no csv yet)\n", cand["id"])); next }
  r <- precovid_corr_of_growth(cand["csv"])
  cat(sprintf("%-42s : pre-COVID corr=%+.3f (n=%d) | full=%+.3f (n=%d) | %s..%s\n",
              cand["id"], r$precovid, r$n_pre, r$full, r$n_full,
              as.character(r$range[1]), as.character(r$range[2])))
}

# Also test building_app while we are here (sanity that the new series correlate)
if (file.exists("data_raw/building_app.csv")) {
  r <- precovid_corr_of_growth("data_raw/building_app.csv")
  cat(sprintf("%-42s : pre-COVID corr=%+.3f (n=%d) | full=%+.3f (n=%d)\n",
              "building_app (A422070J approvals)", r$precovid, r$n_pre, r$full, r$n_full))
}
