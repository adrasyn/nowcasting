# test_transform_panel.R
# Confirms: (a) a transformed column is ~zero-mean / unit-variance over its
# observed span; (b) the differencing matches the series' tcode (t2 drops the
# first obs vs the raw observed span; t1 keeps all).
here <- "R"
source(file.path(here, "_setup.R"))
source(file.path(here, "build_panel.R"))
source(file.path(here, "transform_panel.R"))
suppressMessages(library(readr))

fail <- function(msg) { cat("FAIL:", msg, "\n"); quit(status = 1L) }

wide <- build_panel()
info <- read_csv("seed/panel_info.csv", show_col_types = FALSE)
tfs  <- transform_panel(wide, info)

# (a) zero-mean / unit-variance for a clean t2/tlog series (emp) over observed span
v <- tfs[["emp"]]; v <- v[!is.na(v)]
if (abs(mean(v)) > 0.05) fail(sprintf("emp transformed mean %.3f not ~0", mean(v)))
if (abs(sd(v) - 1) > 1e-6) fail(sprintf("emp transformed sd %.4f not 1", sd(v)))

# (b) tcode differencing: emp is t2 -> transformed observed count = raw count - 1
raw_emp <- wide[["emp"]]; raw_n <- sum(!is.na(raw_emp))
tf_n <- sum(!is.na(tfs[["emp"]]))
if (tf_n != raw_n - 1L) fail(sprintf("emp t2: expected %d obs, got %d", raw_n-1L, tf_n))

# t1 level series (nab_conf) keeps all observed obs
raw_nc <- sum(!is.na(wide[["nab_conf"]])); tf_nc <- sum(!is.na(tfs[["nab_conf"]]))
if (tf_nc != raw_nc) fail(sprintf("nab_conf t1: expected %d obs, got %d", raw_nc, tf_nc))

# firmmbab90 (t1? no -> t2 level-rate diff) unit variance check too
vf <- tfs[["firmmbab90"]]; vf <- vf[!is.na(vf)]
if (abs(sd(vf) - 1) > 1e-6) fail("firmmbab90 not unit variance")

cat("PASS test_transform_panel: zero-mean/unit-var + tcode differencing verified\n")
