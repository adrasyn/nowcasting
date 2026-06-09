# test_build_mai_ragged_edge.R
# Regression: build_mai() must not crash when the panel SPINE extends past every
# SELECTED series (a trailing month with zero observed selected series). This
# happens once long survey series (e.g. wmi_sent -> 2026-06) join the panel but
# are excluded from / not selected into the factor: max(spine) then sits on an
# all-NA-among-selected row, which previously desynced the Kalman gain/mask dims
# in rts_smoother -> "Kt %*% C : non-conformable arguments".
#
# Root cause + fix: build_mai trims trailing months with zero observed selected
# series before the DFM (windowing only; estimation math unchanged).
here <- "R"
source(file.path(here, "transform_panel.R"))
source(file.path(here, "build_mai.R"))
suppressMessages(library(readr))

fail <- function(msg) { cat("FAIL:", msg, "\n"); quit(status = 1L) }

panel_rds <- "cache/panel_vintage_sweep.rds"
if (!file.exists(panel_rds)) {
  cat("SKIP: %s not present (build sweep panel first)\n")
  quit(status = 0L)
}

wide <- readRDS(panel_rds)
tfs  <- transform_panel(wide, "seed/panel_info.csv")

# Sanity: the spine must actually extend past the non-wmi series for this test to
# exercise the bug (otherwise it proves nothing).
sp_max <- max(tfs$date)
wmi_max <- max(tfs$date[!is.na(tfs$wmi_sent)])
if (wmi_max < sp_max) fail(sprintf("test precondition: wmi_sent (%s) is not the spine max (%s)",
                                    wmi_max, sp_max))

# Excluding wmi_sent leaves a trailing spine month with zero selected obs -> the
# regression case. Must NOT error.
res <- tryCatch(
  build_mai(tfs = tfs, exclude_ids = c("aig_pmi","aig_pci","aig_psi","wmi_sent"),
            out_csv = NULL, out_rds = NULL, verbose_dfm = FALSE),
  error = function(e) { fail(sprintf("build_mai errored on ragged edge: %s", conditionMessage(e))); NULL })

# MAI must be produced and must END before the all-NA spine tail (i.e. trimmed).
if (is.null(res) || is.null(res$mai)) fail("no MAI returned")
mai_end <- max(res$mai$date)
if (mai_end >= sp_max) fail(sprintf("MAI end %s not trimmed below spine max %s", mai_end, sp_max))

# And the factor must be finite throughout.
if (any(!is.finite(res$mai$value))) fail("MAI has non-finite values")

cat(sprintf("PASS: ragged-edge build_mai ok (%d selected; MAI ends %s; spine max %s)\n",
            length(res$diagnostics$selected), as.character(mai_end), as.character(sp_max)))
