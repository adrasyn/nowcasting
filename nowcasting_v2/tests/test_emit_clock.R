# Run from nowcasting_v2/: Rscript tests/test_emit_clock.R
# Load only the calendar/cutoff helpers; no model fit or published-file writes.
suppressMessages(library(lubridate))
helpers <- c("GDP_LAG", ".LAG_ACC", ".lag_acc", ".truncate_acc", ".mondays_to_date")
for (expr in parse("R/emit_v2_json.R")) {
  if (is.call(expr) && identical(expr[[1]], as.name("<-")) &&
      as.character(expr[[2]]) %in% helpers) eval(expr)
}

Sys.setenv(TZ = "UTC") # setup-r overwrites the workflow's job-level timezone.
gdp <- data.frame(date = as.Date("2026-06-01"), value = 0.42)
boundary <- as.POSIXct("2026-10-04 19:00:00", tz = "UTC")
clock <- new.env(parent = environment(.mondays_to_date))
clock$Sys.time <- function() boundary
clock$Sys.Date <- function() as.Date(boundary, tz = "UTC")
cadence <- .mondays_to_date
environment(cadence) <- clock
mondays <- cadence(gdp)
stopifnot(tail(mondays, 1) == "2026-10-05")
# Also cover standard time and the instant before Sydney's Monday starts.
stopifnot(tail(.mondays_to_date(gdp, now = as.POSIXct("2026-09-27 19:00:00", tz = "UTC")), 1) == "2026-09-28")
stopifnot(tail(.mondays_to_date(gdp, now = as.POSIXct("2026-10-04 12:59:59", tz = "UTC")), 1) == "2026-09-28")
stopifnot(tail(.mondays_to_date(gdp, now = as.POSIXct("2026-10-12", tz = "UTC"), as_of = "2026-10-05"), 1) == "2026-10-05")
stopifnot(inherits(try(.mondays_to_date(gdp, now = boundary, as_of = "2026-10-06"), silent = TRUE), "try-error"))
stopifnot(inherits(try(.mondays_to_date(gdp, now = boundary, as_of = "2026-10-12"), silent = TRUE), "try-error"))

# The corrected Monday admits all eight observations masked by the old cutoff,
# while still excluding a September survey published after that Monday.
panel <- data.frame(date = as.Date(c("2026-08-01", "2026-09-01")),
                    export = c(47433, NA), building_app = c(16953, NA),
                    credit = c(4330.3, NA), credit_housing = c(2627.5, NA),
                    credit_business = c(1534.8, NA),
                    fcmygbag3 = c(NA, 4.91), fcmygbag5 = c(NA, 4.958),
                    fcmygbag10 = c(NA, 5.283), nab_cond = c(-1, 99))
old <- .truncate_acc(panel, "2026-09-28")
corrected <- .truncate_acc(panel, "2026-10-05")
for (id in c("export", "building_app", "credit", "credit_housing", "credit_business")) {
  stopifnot(is.na(old[[id]][1]), corrected[[id]][1] == panel[[id]][1])
}
for (id in c("fcmygbag3", "fcmygbag5", "fcmygbag10")) {
  stopifnot(is.na(old[[id]][2]), corrected[[id]][2] == panel[[id]][2])
}
stopifnot(is.na(corrected$nab_cond[2]))
cat("PASS: Sydney Monday cadence, pinned replay date, and publication cutoff\n")
