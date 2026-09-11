#### Per-information-stage CI params for v2 ####
#
# Turns a WEEKLY (Monday-cadence) backtest CSV into interval parameters that vary
# by within-quarter information stage `jt` (= n_months_in_quarter).
#
# Why per-stage -- and how much it actually turned out to matter.
#
# The old params were calibrated on quarter-end as-ofs only, where jt == 2 for
# every single observation, then applied to every Monday the site publishes. That
# is structurally wrong, and RDP 2024-04 Table 3 reports accuracy separately by
# stage (FC 0.87 / M1 0.70 / M2 0.78 / M3 0.88) for exactly that reason.
#
# Having measured it on a weekly grid, two things came out differently from the
# expectation, and both are worth knowing before anyone invests further here:
#
#  * jt = 0 does not occur, and structurally cannot. GDP releases ~60 days after
#    quarter-end, i.e. two months into the next quarter, so a quarter always has
#    at least two months of data by the time it becomes the target. The jt = 0
#    random-walk fallback in nowcast_midas() is effectively dead code in
#    production. Observed stages are 2 and 3, with jt = 1 rare and thin.
#
#  * jt = 2 and jt = 3 are NOT significantly different: sd 0.5377 vs 0.5398 on
#    n = 17 each, var.test F = 0.89, p = 0.697. So per-stage calibration is the
#    right structure but, on current evidence, does not change the published band.
#    It is kept because it is measured rather than assumed, and because it will
#    apply the correct band if the stages ever do diverge.
#
# Two deliberate departures from the old compute_ci_params.R:
#
#  1. BIAS IS MEASURED AND REPORTED, BUT NEVER APPLIED. RDP 2024-04 does not
#     bias-correct: the word "bias" does not appear in the paper, its replication
#     code applies no adjustment to its forecasts, and it evaluates purely on RMSE
#     -- a loss that already penalises bias and variance jointly. Subtracting the
#     mean error afterwards would publish a number that none of our RMSE figures
#     describe, and would be a deviation from the paper dressed up as fidelity.
#
#     So `qoq_bias_applied_pp` is always 0. The measured bias and its t-statistic
#     are still emitted (`qoq_bias_pp`, `bias_t`, `bias_significant`) so the site
#     can DISCLOSE a systematic tendency rather than silently correct for it --
#     which is also more useful to a reader.
#
#     This matters: at alpha = 0.10 the measured bias is +0.34pp with t = 4.7.
#     Applying it would have moved the published Q2 nowcast from +0.47% to +0.13%
#     and turned most of the evolution chart negative.
#
#     CONSEQUENCE, measured 2026-08-08. Because the errors are not centred on
#     zero, an interval centred on the raw output and spanned by z*sd does not
#     have the coverage its label claims: the 68% band contained the eventual
#     figure in 7 of 17 quarters (41%), at BOTH stages. The 95% band is roughly
#     right (94% / 88%) only because it is wide enough to absorb the bias. This is
#     not a calculation error -- "+/- 1 sd" and "68% confident" are simply
#     different objects once the mean error is non-zero.
#
#     The site's response is to STOP PUBLISHING AN INTERVAL and disclose the track
#     record instead (qoq_mae_pp and qoq_bias_pp), which is what the Atlanta Fed's
#     GDPNow does -- it publishes no confidence band at all, only its MAE and RMSE
#     -- and what RDP 2024-04 does, evaluating purely on RMSE. The band fields are
#     still emitted for the record; nothing in the UI renders them as a
#     probability. Do not re-label these as a confidence interval without first
#     re-measuring coverage.
#
#  2. t(df), NOT the normal. sd is estimated, not known. At n=17 the old z=1.96
#     made the 95% band 8.2% too narrow.
#
#  3. ONE OBSERVATION PER (target_quarter, jt). A weekly grid gives ~3-4 Mondays
#     inside the same quarter at the same stage, and those share almost the same
#     information set -- counting them as independent would inflate n and shrink
#     the interval spuriously. We keep the LAST (most informed) Monday in each
#     cell, so n per stage is the number of quarters, not the number of Mondays.
#
# TWO HORIZONS (2026-09-12). The backtest now also records a NEXT-quarter figure
# (`qoq_growth_forecast_next`, scored against `qoq_actual_next` at stage
# `n_months_in_next_quarter`). That estimator lags one further quarter into the
# future off the same MAI, so it is a different estimator again and gets its own
# calibration, written to a top-level `next` block with the same {pooled, by_jt}
# shape. Everything about the method is identical: post-CALIB_FROM target
# quarters, one observation per (target quarter, stage), MIN_N fallback -- only
# the columns differ. The current-quarter block is byte-unchanged by this: the
# two are computed by the same function over different columns.
#
# Observed next-quarter stages are 1 and 2 only. 0 cannot occur (nowcast_midas()
# refuses the next horizon when the MAI has no month past the current quarter)
# and 3 needs a late ABS print. A stage that never occurs simply has no entry and
# would fall back to `next$pooled`.
#
# Usage (from nowcasting_v2/):
#   Rscript R/compute_ci_params_v2.R <backtest.csv> <out.json> [model_label]

suppressMessages({ library(jsonlite) })

args  <- commandArgs(trailingOnly = TRUE)
src   <- if (length(args) >= 1) args[[1]] else stop("need a backtest csv")
out   <- if (length(args) >= 2) args[[2]] else stop("need an output json path")
label <- if (length(args) >= 3) args[[3]] else basename(src)

MIN_N     <- 12L    # below this a per-stage sd is too noisy to publish; fall back to pooled
BIAS_ALPHA <- 0.05  # two-sided significance required before we subtract a bias

# Calibrate on post-COVID target quarters only, as the original compute_ci_params.R
# did. This was re-tested rather than inherited, and the data backs it:
#
#   pre-2020  n=85  sd=0.3382
#   post-2021 n=38  sd=0.5824
#   var.test  F=2.97  p<0.0001  -> the regimes genuinely differ
#
# So pooling the full history (or merely excising the 2020-21 pandemic quarters
# and keeping 2012-2019) would understate current uncertainty by ~40%. The
# pre-COVID era was simply an easier forecasting environment for this model.
#
# The pandemic quarters themselves are excluded by construction: they fall before
# CALIB_FROM. Leaving them in would triple the apparent sd (jt=2: 1.225 raw vs
# 0.412 robust) on the strength of four quarters carrying +6.5, -3.8, -2.7, -2.6pp.
#
# Judgement call worth revisiting: these bands describe accuracy in ordinary
# post-pandemic quarters. Another COVID-scale shock is not in them.
CALIB_FROM <- as.Date("2022-01-01")

raw <- read.csv(src, stringsAsFactors = FALSE)

stats_for <- function(e) {
  n <- length(e)
  if (n < 3L) return(NULL)
  bias <- mean(e); sdv <- sd(e); rmse <- sqrt(mean(e^2))
  tstat <- bias / (sdv / sqrt(n))
  sig   <- abs(tstat) > qt(1 - BIAS_ALPHA / 2, n - 1L)
  list(n = n,
       # Measured and reported for disclosure; NEVER applied -- see note above.
       qoq_bias_pp        = round(bias, 4),
       bias_t             = round(tstat, 3),
       bias_significant   = sig,
       qoq_bias_applied_pp = 0,
       qoq_sd_pp          = round(sdv, 4),
       qoq_rmse_pp        = round(rmse, 4),
       # Mean absolute error: the "typical miss" the site publishes in place of an
       # interval (see the disclosure note in the header). MAE rather than RMSE
       # because it is the one a reader can interpret without further explanation
       # -- it is literally the average size of the miss.
       qoq_mae_pp         = round(mean(abs(e)), 4),
       t_68               = round(qt(0.84134, n - 1L), 4),   # one-sd-equivalent quantile
       t_95               = round(qt(0.975,   n - 1L), 4))
}

# Calibrate ONE horizon: `err`, `stage` and `qdate` are the three columns that
# define it, `as_of` breaks the within-cell tie. Returns list(pooled, by_jt).
# Run over (qoq_error, n_months_in_quarter, target_quarter_date) this reproduces
# exactly what this script did before the next horizon existed.
calibrate <- function(d, err, stage, qdate, tag) {
  d <- data.frame(err = as.numeric(err), stage = as.numeric(stage),
                  qdate = as.Date(qdate), as_of = as.Date(d$as_of))
  d <- d[!is.na(d$err) & !is.na(d$stage) & !is.na(d$qdate), ]
  if (!nrow(d)) stop("no usable ", tag, " rows in ", src)

  n_all <- nrow(d)
  d     <- d[d$qdate >= CALIB_FROM, ]
  cat(sprintf("%s [%s]: kept %d of %d rows (target quarter >= %s)\n",
              label, tag, nrow(d), n_all, CALIB_FROM))
  if (!nrow(d)) stop("no ", tag, " rows at or after CALIB_FROM ", CALIB_FROM)

  # --- one row per (target quarter, stage): keep the last as-of in each cell ----
  d <- d[order(d$qdate, d$stage, d$as_of), ]
  key <- paste(d$qdate, d$stage, sep = "|")
  d <- d[!duplicated(key, fromLast = TRUE), ]
  cat(sprintf("%s [%s]: %d independent (quarter, stage) observations\n",
              label, tag, nrow(d)))

  pooled <- stats_for(d$err)
  if (is.null(pooled)) stop("not enough ", tag, " observations to calibrate")

  by_jt <- list()
  for (j in sort(unique(d$stage))) {
    e <- d$err[d$stage == j]
    s <- stats_for(e)
    if (is.null(s) || s$n < MIN_N) {
      cat(sprintf("  [%s] jt=%d: n=%d < %d -- will fall back to pooled\n",
                  tag, j, length(e), MIN_N))
      next
    }
    s$stage <- j
    by_jt[[as.character(j)]] <- s
    cat(sprintf("  [%s] jt=%d: n=%2d  bias %+0.4f (t=%+.2f%s)  sd %.4f  t95 %.3f\n",
                tag, j, s$n, s$qoq_bias_pp, s$bias_t,
                if (s$bias_significant) ", SIGNIFICANT but not applied" else ", n.s.",
                s$qoq_sd_pp, s$t_95))
  }
  list(pooled = pooled, by_jt = by_jt)
}

cur <- calibrate(raw, raw$qoq_error, raw$n_months_in_quarter,
                 raw$target_quarter_date, "current")
pooled <- cur$pooled
by_jt  <- cur$by_jt

# The next horizon exists only in backtests run after 2026-09-12. An older CSV
# simply produces no `next` block, and ci_params_for_stage() then falls back to
# the current-quarter pooled params.
has_next <- all(c("qoq_growth_forecast_next", "qoq_actual_next",
                  "n_months_in_next_quarter", "next_target_quarter_date") %in% names(raw))
nxt <- if (has_next && any(!is.na(raw$qoq_growth_forecast_next) & !is.na(raw$qoq_actual_next))) {
  calibrate(raw, raw$qoq_growth_forecast_next - raw$qoq_actual_next,
            raw$n_months_in_next_quarter, raw$next_target_quarter_date, "next")
} else {
  cat(sprintf("%s: no next-quarter columns -- writing no `next` block\n", label))
  NULL
}

params <- list(
  schema      = "v2-ci-by-stage-1",
  basis       = sprintf(paste("empirical pseudo-out-of-sample error dispersion, by within-quarter",
                              "information stage (jt = n_months_in_quarter); post-COVID target quarters",
                              "only (>= %s). Pre-2020 errors are significantly tighter (F=2.97, p<0.0001)",
                              "so pooling them would understate current uncertainty."), CALIB_FROM),
  calibrated_from = as.character(CALIB_FROM),
  method      = paste("interval = point +/- t(df) * sd, centred on the model's raw output.",
                      "The measured bias is reported (qoq_bias_pp, bias_t) but NOT applied:",
                      "RDP 2024-04 does not bias-correct and evaluates on RMSE, which already",
                      "penalises bias. Stages with fewer than MIN_N observations fall back to `pooled`.",
                      "The top-level `next` block is the same calculation for the nowcast of the",
                      "quarter AFTER the current one, at its own information stage."),
  min_n       = MIN_N,
  bias_alpha  = BIAS_ALPHA,
  pooled      = pooled,
  by_jt       = by_jt,
  # Same shape, one quarter further out: the nowcast for the quarter AFTER the
  # current one, at its own information stage. Absent when the backtest CSV has
  # no next-quarter columns. `next` is an R keyword, so read it as p[["next"]].
  "next"      = nxt,
  model       = label,
  source      = src,
  computed_at = format(Sys.time(), "%Y-%m-%dT%H:%M:%SZ", tz = "UTC")
)

write_json(params, out, auto_unbox = TRUE, pretty = TRUE, digits = 6)
cat(sprintf("wrote %s  (pooled n=%d, sd=%.4f; %d per-stage entries)\n",
            out, pooled$n, pooled$qoq_sd_pp, length(by_jt)))
if (!is.null(nxt))
  cat(sprintf("  next: pooled n=%d, sd=%.4f; %d per-stage entries\n",
              nxt$pooled$n, nxt$pooled$qoq_sd_pp, length(nxt$by_jt)))
