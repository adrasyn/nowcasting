#### Empirical confidence bands ####
# Replaces the old hardcoded +/-0.7% (68%) / +/-1.4% (95%) multiplicative bands
# with intervals derived from the model's actual POOS backtest error.
#
# Backtest error is defined as `forecast - actual`, so a positive mean error =>
# the model OVER-predicts. The interval for the *actual* is centred on
# (qoq - bias) and spanned by z * sd, where sd is the dispersion of errors about
# their mean. For v2, bias is always 0 -- see the note below -- so the band is
# simply qoq +/- z * sd.
#
# NOTE on sd: this comment used to say sd = sqrt(rmse^2 - bias^2). That is the
# population identity; the generators actually use the sample sd() (n-1 divisor),
# which is what you want when sd is estimated from a modest number of quarters.
# The two differ by the n/(n-1) factor. Do not "fix" the code to match the old
# comment.
#
# NOTE on the bias term: v2 no longer applies one. compute_ci_params_v2.R sets
# qoq_bias_applied_pp = 0 always, so v2's bands are centred on the model's raw
# output. RDP 2024-04 does not bias-correct: the word does not appear in the
# paper, its replication code applies no ex-post adjustment to forecasts, its
# MIDAS regression already fits an intercept (which absorbs a constant offset
# in-sample), and it evaluates on RMSE -- a loss that penalises bias and variance
# jointly. Subtracting the mean error afterwards therefore double-counts, and
# publishes a number that none of our RMSE figures describe. The measured bias is
# still reported (qoq_bias_pp, bias_t) so the site can disclose it.
# v1's flat seed/ci_params.json still applies its bias unconditionally.
#
# Params (qoq_bias_pp, qoq_sd_pp, z_68, z_95) come from seed/ci_params.json,
# regenerated from a backtest by compute_ci_params.R. Functions are vectorised
# so they serve both latest.json (scalar) and nowcasts.json (per-vintage).

#' QoQ-growth band edges (percentage points) for a forecast.
ci_qoq_band <- function(qoq_point, bias_pp, sd_pp, z) {
  center <- qoq_point - bias_pp
  list(low = center - z * sd_pp, high = center + z * sd_pp)
}

#' Level ($M) of the prior quarter implied by a point level + its QoQ growth.
ci_prev_level <- function(point_level, qoq_point) point_level / (1 + qoq_point / 100)

#' Level ($M) band edges for a forecast, via the QoQ band + the prior level.
ci_level_band <- function(qoq_point, prev_level, bias_pp, sd_pp, z) {
  b <- ci_qoq_band(qoq_point, bias_pp, sd_pp, z)
  list(low  = round(prev_level * (1 + b$low  / 100)),
       high = round(prev_level * (1 + b$high / 100)))
}

#' Load + validate the CI params produced by compute_ci_params.R (flat, v1) or
#' compute_ci_params_v2.R (per-information-stage, schema "v2-ci-by-stage-1").
load_ci_params <- function(path = "seed/ci_params.json") {
  if (!file.exists(path)) {
    stop(sprintf("CI params not found at '%s'. Regenerate with: Rscript compute_ci_params.R", path))
  }
  p <- jsonlite::fromJSON(path)

  if (!is.null(p$schema) && p$schema == "v2-ci-by-stage-1") {
    if (is.null(p$pooled) || !is.numeric(p$pooled$qoq_sd_pp) || p$pooled$qoq_sd_pp <= 0) {
      stop(sprintf("%s: pooled$qoq_sd_pp missing or invalid", path))
    }
    return(p)
  }

  if (!is.numeric(p$qoq_bias_pp) || !is.numeric(p$qoq_sd_pp) ||
      is.na(p$qoq_bias_pp) || is.na(p$qoq_sd_pp) || p$qoq_sd_pp <= 0) {
    stop("ci_params.json: qoq_bias_pp / qoq_sd_pp missing or invalid")
  }
  if (is.null(p$z_68)) p$z_68 <- 1.0
  if (is.null(p$z_95)) p$z_95 <- 1.96
  p
}

#' Resolve the interval parameters that apply at a given within-quarter
#' information stage.
#'
#' A nowcast made with 0 months of target-quarter data is a different estimator
#' from one made with 3, so it does not get the same interval. For per-stage
#' params we look up `jt`; if that stage was too thin to calibrate (or `jt` is
#' unknown) we fall back to the pooled figures. Flat/legacy params ignore `jt`.
#'
#' `horizon` picks WHICH estimator's calibration to read. "current" is the
#' quarter the ABS has not printed yet; "next" is the one after it, nowcast off
#' the same MAI a quarter further out, and it has its own error dispersion in the
#' params' top-level `next` block. Params written before 2026-09-12 have no such
#' block: rather than refuse, we fall back to the current-quarter POOLED figures
#' and label the stage "pooled-current" so the caller can see the substitution.
#'
#' Returns list(bias_pp, sd_pp, z_68, z_95, n, stage) where `stage` is the stage
#' actually used ("pooled" when falling back) so callers can surface it.
ci_params_for_stage <- function(p, jt = NULL, horizon = c("current", "next")) {
  horizon <- match.arg(horizon)
  # `bias_pp` is the bias APPLIED to the interval centre (always 0 for v2).
  # `bias_measured_pp` and `mae_pp` are the track-record figures the site
  # publishes INSTEAD of a probability interval -- see compute_ci_params_v2.R.
  # Keep the two strictly separate: one moves numbers, the other only describes
  # them.
  flat <- function(bias, sd, z68, z95, n, stage, bias_measured = NA_real_, mae = NA_real_) {
    list(bias_pp = bias, sd_pp = sd, z_68 = z68, z_95 = z95, n = n, stage = stage,
         bias_measured_pp = bias_measured, mae_pp = mae)
  }

  if (is.null(p$schema) || p$schema != "v2-ci-by-stage-1") {
    # v1's flat params apply their bias, and carry no MAE.
    return(flat(p$qoq_bias_pp, p$qoq_sd_pp, p$z_68, p$z_95, p$n, "flat",
                bias_measured = p$qoq_bias_pp))
  }

  # `next` is an R keyword, so the block is only reachable as p[["next"]].
  blk <- p
  fallback_stage <- "pooled"
  if (horizon == "next") {
    nx <- p[["next"]]
    if (is.null(nx)) {
      blk <- list(pooled = p$pooled, by_jt = NULL)
      fallback_stage <- "pooled-current"
    } else {
      blk <- nx
    }
  }

  s <- NULL
  if (!is.null(jt) && !is.na(jt) && !is.null(blk$by_jt)) {
    s <- blk$by_jt[[as.character(jt)]]
  }
  stage <- as.character(jt)
  if (is.null(s)) {
    s <- blk$pooled
    stage <- fallback_stage
  }
  # qoq_mae_pp is absent from params generated before 2026-08-08; NA is handled
  # downstream by omitting the disclosure rather than printing a blank.
  mae <- if (is.null(s$qoq_mae_pp)) NA_real_ else s$qoq_mae_pp
  flat(s$qoq_bias_applied_pp, s$qoq_sd_pp, s$t_68, s$t_95, s$n, stage,
       bias_measured = s$qoq_bias_pp, mae = mae)
}
