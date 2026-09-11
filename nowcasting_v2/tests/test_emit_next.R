# test_emit_next.R -- the next-quarter horizon in the v2 emit path (2026-09-12)
#
# Two things are checked, and deliberately nothing else:
#
#   1. ci_params_for_stage() reads the right block. The next horizon has its own
#      calibration (`next` in the params, one entry per information stage) and
#      must never silently borrow the current quarter's, EXCEPT on params written
#      before the next block existed, where the documented fallback is the
#      current-quarter pooled figures labelled "pooled-current".
#
#   2. The current horizon is untouched. Every current-quarter lookup is compared
#      against the JSON file read directly, so a regression in the new `horizon`
#      argument cannot move a published band without failing here.
#
# Not a model run: emit_v2_json() builds the panel and the MAI for every Monday
# in the cadence and writes into data/, which is not something a test should do.
# The next-quarter nowcast itself is pinned in test_nowcast_midas.R.
#
# Run from nowcasting_v2/:  Rscript tests/test_emit_next.R

suppressMessages({ library(jsonlite) })
source(file.path("..", "pipeline", "ci_bands.R"))

CI_PATH <- file.path("..", "pipeline", "seed", "ci_params_v2.json")

pass <- TRUE
check <- function(cond, msg) {
  cat(sprintf("[%s] %s\n", if (isTRUE(cond)) "PASS" else "FAIL", msg))
  if (!isTRUE(cond)) pass <<- FALSE
}

ci  <- load_ci_params(CI_PATH)
raw <- jsonlite::fromJSON(CI_PATH, simplifyVector = FALSE)

# ---- the params carry a next block --------------------------------------------
nx <- raw[["next"]]
check(!is.null(nx), "ci_params_v2.json carries a top-level `next` block")
check(!is.null(nx$pooled$qoq_sd_pp) && is.finite(nx$pooled$qoq_sd_pp) && nx$pooled$qoq_sd_pp > 0,
      sprintf("next$pooled sd is finite and positive (%.4f, n=%d)",
              nx$pooled$qoq_sd_pp, nx$pooled$n))

# jt = 0 cannot occur on this horizon (nowcast_midas refuses it) and jt = 3 needs
# a late ABS print, so the calibrated stages are 1 and 2.
check(identical(sort(names(nx$by_jt)), c("1", "2")),
      sprintf("next$by_jt has exactly the stages that occur: %s",
              paste(sort(names(nx$by_jt)), collapse = ", ")))

# ---- the next horizon reads the next block ------------------------------------
for (j in 1:2) {
  p <- ci_params_for_stage(ci, j, "next")
  want <- nx$by_jt[[as.character(j)]]
  check(is.finite(p$sd_pp) && p$sd_pp > 0,
        sprintf("next, jt=%d: sd is finite and positive (%.4f)", j, p$sd_pp))
  check(identical(p$stage, as.character(j)),
        sprintf("next, jt=%d: stage is labelled '%s'", j, p$stage))
  check(isTRUE(all.equal(p$sd_pp, want$qoq_sd_pp)) &&
          isTRUE(all.equal(p$n, want$n)) &&
          isTRUE(all.equal(p$z_68, want$t_68)) &&
          isTRUE(all.equal(p$z_95, want$t_95)),
        sprintf("next, jt=%d: every field comes from next$by_jt$`%d`", j, j))
  check(!isTRUE(all.equal(p$sd_pp, raw$pooled$qoq_sd_pp)),
        sprintf("next, jt=%d: sd is NOT the current-quarter pooled sd", j))
}

# A stage the next horizon was never calibrated at falls back to ITS pooled block,
# not the current quarter's.
p3 <- ci_params_for_stage(ci, 3L, "next")
check(identical(p3$stage, "pooled") && isTRUE(all.equal(p3$sd_pp, nx$pooled$qoq_sd_pp)),
      "next, an uncalibrated stage falls back to next$pooled")

# ---- the current horizon is bit-unchanged -------------------------------------
for (j in c(2L, 3L)) {
  p    <- ci_params_for_stage(ci, j)              # default horizon
  ph   <- ci_params_for_stage(ci, j, "current")   # explicit
  want <- raw$by_jt[[as.character(j)]]
  check(identical(p, ph), sprintf("current, jt=%d: the default horizon is 'current'", j))
  check(isTRUE(all.equal(p$sd_pp, want$qoq_sd_pp)) &&
          isTRUE(all.equal(p$bias_pp, want$qoq_bias_applied_pp)) &&
          isTRUE(all.equal(p$bias_measured_pp, want$qoq_bias_pp)) &&
          isTRUE(all.equal(p$mae_pp, want$qoq_mae_pp)) &&
          isTRUE(all.equal(p$n, want$n)) &&
          isTRUE(all.equal(p$z_68, want$t_68)) &&
          isTRUE(all.equal(p$z_95, want$t_95)) &&
          identical(p$stage, as.character(j)),
        sprintf("current, jt=%d: every field still matches by_jt$`%d` in the JSON", j, j))
}
p_pool <- ci_params_for_stage(ci, 0L)
check(identical(p_pool$stage, "pooled") && isTRUE(all.equal(p_pool$sd_pp, raw$pooled$qoq_sd_pp)),
      "current, an uncalibrated stage still falls back to pooled")

# ---- params with no next block --------------------------------------------------
old <- ci
old[["next"]] <- NULL
p_old <- ci_params_for_stage(old, 2L, "next")
check(identical(p_old$stage, "pooled-current") &&
        isTRUE(all.equal(p_old$sd_pp, raw$pooled$qoq_sd_pp)),
      "params with no `next` block fall back to the current pooled params, labelled 'pooled-current'")

# ---- the published payload, if it carries a next quarter -----------------------
lj <- tryCatch(jsonlite::fromJSON(file.path("..", "data", "latest_v2.json"), simplifyVector = FALSE),
               error = function(e) NULL)
if (!is.null(lj)) {
  nq <- lj$models$next_quarter
  if (is.null(nq)) {
    cat("[SKIP] data/latest_v2.json carries no next_quarter block (no MAI month past the current quarter)\n")
  } else {
    check(identical(nq$horizon, "next"), "payload: next_quarter is labelled horizon 'next'")
    check(identical(nq$current_quarter, lj$models$headline$target_quarter),
          "payload: next_quarter names the headline's quarter as its current quarter")
    check(!identical(nq$target_quarter, lj$models$headline$target_quarter),
          "payload: next_quarter targets a different quarter from the headline")
  }
  # Every row is labelled, and only with a horizon the schema knows. An unlabelled
  # row predates 2026-09-12 and is a current-quarter row.
  check(all(vapply(lj$vintages, function(v)
    is.null(v$horizon) || v$horizon %in% c("current", "next"), logical(1))),
    "payload: every vintage row is unlabelled, 'current' or 'next'")

  # A next-quarter row OUTLIVES its horizon: after the ABS prints, the quarter it
  # targeted becomes the current one. So selecting on target_quarter alone is not
  # enough to get the current-quarter path, and /v2 drops horizon == "next"
  # explicitly (src/app/v2/page.tsx). This pins that the two selections differ, so
  # the filter cannot be dropped as redundant without failing here.
  hq <- lj$models$headline$target_quarter
  by_quarter <- Filter(function(v) identical(v$target_quarter, hq), lj$vintages)
  drawn <- Filter(function(v) !identical(v$horizon, "next"), by_quarter)
  check(length(drawn) > 0L, sprintf("payload: %d current-horizon row(s) for the headline quarter %s",
                                    length(drawn), hq))
  cat(sprintf("      (%d of %d rows targeting %s were made at the next horizon)\n",
              length(by_quarter) - length(drawn), length(by_quarter), hq))
}

cat(sprintf("\n==> test_emit_next: %s\n", if (pass) "PASS" else "FAIL"))
if (!pass) quit(status = 1L)
