# nowcast_midas.R
# Phase 4.1 -- Stage 2 of nowcast v2: the U-MIDAS GDP nowcast driven by OUR live MAI.
#
# Reuses the RBA RDP 2024-04 MIDAS engine (validated in Phase 1). The headline
# model is QA (quarter-average U-MIDAS): regress quarterly GDP growth on the
# quarter-average of the monthly MAI via midas_r, then nowcast the current quarter
# from whatever within-quarter MAI months are available so far.
#
# This file is GLUE ONLY. The math is the RBA's:
#   - QA fit + forecast: lines 226-233 of Recursive_Nowcast_GDP_UMIDAS_TP.R
#   - mls()/midas_r() from midasr
# The only adaptation is the INPUT: we drive the engine with our live MAI/GDP CSVs
# and select the target quarter as the first quarter that has MAI data but no
# released GDP yet (RBA ran a fixed recursive backtest; we want the live edge).

suppressWarnings(suppressMessages({
  here <- tryCatch(dirname(sys.frame(1)$ofile), error = function(e) NA)
}))
if (is.na(here) || !nzchar(here)) here <- "R"
source(file.path(here, "_setup.R"))
source(file.path(here, "methods", "mai_utils.R"))   # get_year_month/quarter, rmse, rsq

suppressMessages({
  library(zoo)
  library(midasr)
})

# Coerce a (date,value) data.frame OR a ts to a (date,value) data.frame.
.as_dv <- function(x, freq) {
  if (is.data.frame(x)) {
    stopifnot(all(c("date", "value") %in% names(x)))
    d <- data.frame(date = as.Date(x$date), value = as.numeric(x$value))
    d <- d[order(d$date), ]
    return(d[!is.na(d$value), , drop = FALSE])
  }
  stop(".as_dv(): expected a data.frame with date,value columns.\n", call. = FALSE)
}

# Quarter-end label (first-of-month of the quarter's last month: 03/06/09/12-01)
# for an arbitrary first-of-month date.
.quarter_label <- function(d) {
  yr <- as.integer(format(d, "%Y"))
  mo <- as.integer(format(d, "%m"))
  qi <- (mo - 1L) %/% 3L            # 0..3
  as.Date(sprintf("%04d-%02d-01", yr, qi * 3L + 3L))
}

# "2026 Q2" style label from a quarter-end first-of-month date.
.quarter_name <- function(qend) {
  yr <- as.integer(format(qend, "%Y"))
  q  <- as.integer(format(qend, "%m")) / 3L
  sprintf("%d Q%d", yr, q)
}

####################################################################################################
# nowcast_midas
#
#   mai          : data.frame(date, value) -- monthly MAI (freq 12), first-of-month dates.
#   gdp_growth   : data.frame(date, value) -- quarterly GDP QoQ growth %, ABS quarter-end labels.
#   as_of        : optional Date. If given, only MAI months <= as_of and GDP quarters whose data
#                  would be available by then are used (lets the test pin a historical slice).
#                  Default NULL = use everything in the inputs.
#   prev_level   : optional numeric. The released GDP chain-volume LEVEL of the quarter
#                  immediately BEFORE the target quarter, used to express the growth nowcast as a
#                  level. If NULL, nowcast_level is returned NA (growth is still produced).
#                  For horizon = "next" the quarter before the target IS the current quarter,
#                  whose level is itself a nowcast: the caller chains it (pass the headline
#                  nowcast's `nowcast_level`), this function never invents it.
#   horizon      : "current" (default) = the first quarter with MAI data but no released GDP,
#                  i.e. exactly the behaviour this file has always had. "next" = the quarter
#                  AFTER that one, nowcast from its partial MAI months as soon as it has any.
#
# The next-quarter horizon needs NO unpublished GDP. The U-MIDAS regression has no lagged-GDP
# regressor: it maps monthly MAI onto quarterly growth, so a quarter can be nowcast from its own
# partial months plus the months before them, whether or not the preceding quarter has printed.
# The subtlety is that the lags k = (3 - jt):5 reach up to five months back from the target
# quarter's last month, i.e. into the CURRENT quarter, which sits AFTER the estimation sample.
# So the forecast newdata carries the current quarter's three months ahead of the next quarter's
# partial months, `forecast()` returns two quarters, and we take the LAST one.
#
# Returns a list:
#   target_quarter, qoq_growth, nowcast_level, model, n_obs,
#   plus n_months_in_quarter (jt), prev_level, horizon and current_quarter for transparency.
####################################################################################################
nowcast_midas <- function(mai, gdp_growth, as_of = NULL, prev_level = NULL,
                          model = c("qa", "umidas"),
                          qa_lag = 0L:1L,     # QA quarterly lag (sweep knob; 0:1 = default)
                          horizon = c("current", "next")) {
  model   <- match.arg(model)
  horizon <- match.arg(horizon)

  mt <- 3L                          # months per quarter (high-freq ratio)

  m <- .as_dv(mai)                  # monthly MAI
  y <- .as_dv(gdp_growth)           # quarterly GDP growth

  if (!is.null(as_of)) {
    as_of <- as.Date(as_of)
    m <- m[m$date <= as_of, , drop = FALSE]
    # GDP for a quarter is released ~ the quarter after it ends; keep it simple and
    # faithful to the recursive contract: only use GDP quarters whose quarter-end is
    # strictly before the target's quarter (computed below). Pre-trim to <= as_of.
    y <- y[y$date <= as_of, , drop = FALSE]
  }

  if (nrow(m) < mt) stop("nowcast_midas(): need at least one quarter of MAI.\n", call. = FALSE)
  if (nrow(y) < 41L) stop("nowcast_midas(): need a long GDP history to fit MIDAS.\n", call. = FALSE)

  # ---- Determine target quarter = first quarter with MAI but no released GDP ----
  last_gdp_q <- max(y$date)                       # last released GDP quarter (quarter-end label)
  # Quarter-end label of the latest MAI month:
  last_mai_q <- .quarter_label(max(m$date))

  # The target is ALWAYS the quarter after the last released GDP -- that is what
  # "first quarter with MAI data but no released GDP" means, and it does not depend
  # on how far the MAI happens to reach.
  #
  # The previous implementation took `last_mai_q` whenever the MAI edge ran past
  # released GDP. That silently skipped a whole quarter: the MAI crosses into a new
  # quarter as soon as ONE selected series publishes a single month (the yield block
  # has a 2-day lag), which happens roughly four weeks BEFORE the previous quarter's
  # GDP is released. The model would abandon the complete-but-unreleased quarter,
  # publish a 1-month nowcast of the quarter after it, and never nowcast the skipped
  # quarter again -- so it also never got a final vintage for the track record.
  #
  # MAI months beyond the target quarter are simply not used: `target_months` below
  # filters to the target quarter, so a longer MAI raises nothing but jt's ceiling.
  target_q <- seq(last_gdp_q, by = "3 months", length.out = 2L)[2L]

  # If the MAI runs more than one quarter past the target, the GDP series is almost
  # certainly stale rather than the MAI being early -- e.g. fetch_rt_gdp.R did not
  # run, so we are nowcasting a quarter whose GDP was released some time ago.
  if (last_mai_q > seq(target_q, by = "3 months", length.out = 2L)[2L]) {
    warning(sprintf(paste("nowcast_midas(): MAI reaches %s but target quarter is %s --",
                          "released GDP ends %s. Is data_raw/rt_dgdp_qtr.csv stale?"),
                    as.character(last_mai_q), as.character(target_q),
                    as.character(last_gdp_q)), call. = FALSE)
  }

  # `target_q` as computed above is the CURRENT quarter: the first with MAI data but no
  # released GDP. The "next" horizon moves the target one quarter on and keeps the current
  # quarter's three months as the lag block the U-MIDAS newdata needs (see the header).
  current_q  <- target_q
  cur_months <- m[.quarter_label(m$date) == current_q, , drop = FALSE]
  if (horizon == "next") target_q <- seq(current_q, by = "3 months", length.out = 2L)[2L]

  # MAI months belonging to the target quarter (the "x_new" partial months).
  target_months <- m[.quarter_label(m$date) == target_q, , drop = FALSE]
  if (horizon == "next") {
    # Order matters. "No month beyond the current quarter" is the normal state for the
    # first weeks after a print and the caller treats it as "not yet", so it is tested
    # FIRST. Only once a month past the current quarter exists is a short current
    # quarter a real anomaly: with a contiguous MAI it cannot happen, so the second
    # check is an assertion, not an expected refusal. Testing it first would turn every
    # ordinary "not yet" into a hard error and lose the as-of's headline row too.
    if (nrow(target_months) == 0L)
      stop(sprintf("nowcast_midas(): no MAI month beyond the current quarter %s yet\n",
                   .quarter_name(current_q)), call. = FALSE)
    if (nrow(cur_months) < mt)
      stop(sprintf(paste("nowcast_midas(): current quarter incomplete -- %s has %d of %d MAI",
                         "months, yet the MAI already reaches %s. Non-contiguous MAI?\n"),
                   .quarter_name(current_q), nrow(cur_months), mt,
                   .quarter_name(target_q)), call. = FALSE)
  }
  jt <- nrow(target_months)
  if (jt > mt) stop("nowcast_midas(): more than 3 MAI months in target quarter (bad alignment).\n",
                    call. = FALSE)
  # jt == 0 is the brief post-GDP-release / pre-new-monthly-data window. It is
  # handled by the paper's FC model (U-MIDAS with no within-quarter input), which
  # per-stage dispatch now routes to -- the previous random-walk substitution into
  # the QA regression was an unbacktested adaptation and has been removed.
  # In production jt is only ever 2 or 3: ABS releases GDP ~60 days after
  # quarter-end, i.e. two months into the next quarter, so a target quarter always
  # has >= 2 months of MAI by the time it becomes the target. Verified across 678
  # backtest nowcasts, zero at jt = 0.

  # ---- Build the estimation sample honouring the data contract ----
  # Estimation must use only COMPLETE quarters that also have released GDP. Drop the
  # target quarter's (partial) months from the in-sample monthly block.
  # The sample is the months strictly before the CURRENT quarter for BOTH horizons. For
  # "current" that is today's behaviour verbatim (current_q == target_q). For "next" it is
  # also what the GDP contiguity trim below would produce anyway -- `y` has no row for the
  # current quarter by construction -- but making it explicit keeps the two horizons on one
  # estimation sample, so the next-quarter figure never sees a quarter the headline did not.
  m_est_src <- m[m$date < current_q, , drop = FALSE]     # months strictly before current quarter

  # Align monthly block: first month must be a quarter's first month (Jan/Apr/Jul/Oct),
  # length a multiple of 3, and matched 1:3 with the GDP quarters we hold.
  qstart_mo <- c(1L, 4L, 7L, 10L)
  fm <- m_est_src$date[as.integer(format(m_est_src$date, "%m")) %in% qstart_mo]
  m_start <- min(fm)
  m_est_src <- m_est_src[m_est_src$date >= m_start, , drop = FALSE]
  nme <- nrow(m_est_src)
  drop <- nme %% mt
  if (drop > 0L) m_est_src <- m_est_src[seq_len(nme - drop), , drop = FALSE]

  # Quarter labels for the estimation monthly block (3rd month of each quarter).
  mdates <- m_est_src$date
  nxt    <- length(mdates)
  q_label <- mdates[seq(mt, nxt, by = mt)]

  # GDP aligned onto those quarter labels (complete quarters only).
  y_full <- y$value[match(q_label, y$date)]
  ok <- !is.na(y_full)
  if (!all(ok)) {
    # Trim to the contiguous span where both x (always present) and GDP exist.
    # Keep the longest leading run with GDP (GDP history is contiguous in practice).
    keep_q <- which(ok)
    # require contiguity from the first usable quarter to the last
    first_q <- min(keep_q); last_q <- max(keep_q)
    if (any(!ok[first_q:last_q]))
      stop("nowcast_midas(): GDP has interior gaps over the estimation span.\n", call. = FALSE)
    q_sel <- first_q:last_q
    q_label <- q_label[q_sel]
    y_full  <- y_full[q_sel]
    # corresponding months
    m_sel <- unlist(lapply(q_sel, function(qq) ((qq - 1L) * mt + 1L):(qq * mt)))
    mdates <- mdates[m_sel]
    m_est_src <- m_est_src[m_sel, , drop = FALSE]
    nxt <- length(mdates)
  }
  nyt <- length(q_label)
  if (nxt != mt * nyt) stop("nowcast_midas(): contract violation nxt != 3*nyt.\n", call. = FALSE)

  # ---- ts objects per the contract ----
  x_begin <- get_year_month(mdates[1L])
  q_begin <- get_year_quarter(q_label[1L])
  x_est <- ts(data = m_est_src$value, start = x_begin, frequency = 12)
  y_est <- ts(data = y_full,          start = q_begin, frequency = 4)

  if (length(x_est) != mt * length(y_est))
    stop("nowcast_midas(): length(x_est) != 3*length(y_est) after windowing.\n", call. = FALSE)

  # PER-STAGE DISPATCH (RBA Recursive_Nowcast_GDP_UMIDAS_TP.R:206-233).
  #
  # The paper builds FIVE models, one per within-quarter information stage: FC/M1/
  # M2/M3 are unrestricted U-MIDAS at k = (k1 - jt):k2, and QA is a flat-weighted
  # quarter average. Its QA block runs AFTER the jt loop, so x_new is the jt=3
  # vector -- QA is only ever evaluated on a COMPLETE quarter, and the paper calls
  # it "similar to M3".
  #
  # v2 used QA at every stage, feeding a 1-2 month mean into coefficients fitted
  # exclusively on 3-month means (xm_est below). Measured at jt=2 (post-COVID,
  # n=17): QA RMSE 0.6009 / bias +0.4509 against U-MIDAS 0.5025 / +0.3821 -- 16%
  # and 15% better. Paired test p=0.10, so suggestive rather than conclusive on
  # this n, but consistent in direction, and at jt=3 the two are near-identical
  # (0.4464 vs 0.4309) exactly as the paper implies. Fidelity and accuracy agree,
  # so `model = "qa"` now means "the paper's QA when the quarter is complete,
  # its per-stage U-MIDAS otherwise".
  #
  # `model = "umidas"` still forces U-MIDAS at every stage, for sweeps.
  use_qa <- identical(model, "qa") && jt >= mt

  if (use_qa) {
    # ---- QA U-MIDAS: fit + nowcast (RBA Recursive_Nowcast lines 226-233) ----
    # In-sample quarter-averages of the MAI, with one lag (k=0:1) to mirror a
    # U-MIDAS with flat coefficients over the within-quarter months.
    xm_est <- rowMeans(mls(x = x_est, k = 0L:2L, m = mt), na.rm = TRUE)
    qa_md <- midas_r(formula = y_est ~ mls(x = xm_est, k = qa_lag, m = 1L),
                     data = list(y_est = y_est, xm_est = xm_est), start = NULL)

    # jt == mt here by construction (see the dispatch note above), so this is the
    # complete-quarter average the paper's QA expects -- never a partial mean.
    nxm <- mean(target_months$value, na.rm = TRUE)

    # For horizon = "next" the target quarter sits one quarter past the estimation sample,
    # so the newdata has to step through the current quarter first and we take the LAST
    # forecast. (jt == 3 on the next quarter only happens if the ABS is late with a print.)
    nxm_block <- if (horizon == "next") c(mean(cur_months$value, na.rm = TRUE), nxm) else c(nxm)

    qa_fc <- forecast(object = qa_md, newdata = list(xm_est = nxm_block),
                      se = FALSE, method = "static", add_ts_info = FALSE)
    qoq_growth <- as.numeric(tail(qa_fc$mean, 1L))
    fit_md <- qa_md
    model_name <- "QA-UMIDAS"
  } else {
    # ---- Full unrestricted U-MIDAS (RBA Recursive_Nowcast lines 206-221) ----
    # Separate within-quarter monthly coefficients + lags. RBA spec: k = (k1-jt):k2
    # with k1=3 (begin lag), k2=5 (end lag). jt = within-quarter MAI months known.
    # x_new = the partial-quarter monthly MAI values, padded to 3 with NA.
    k1 <- 3L; k2 <- 5L
    jtf <- if (jt >= 1L) jt else 0L
    um_md <- midas_r(formula = y_est ~ mls(x = x_est, k = (k1 - jtf):k2, m = mt),
                     start = NULL)
    if (jtf >= 1L) {
      x_new <- as.numeric(target_months$value)
    } else {
      # jt==0: no within-quarter data. This is the paper's FC model -- k = k1:k2
      # uses only PRIOR-quarter MAI months, so the three contemporaneous slots are
      # all NA and nothing is extrapolated into them.
      x_new <- numeric(0)
      cat(sprintf("nowcast_midas(): jt=0 (no MAI months yet for %s); U-MIDAS uses k=(k1):k2 with no within-quarter input (1-step-ahead).\n",
                  .quarter_name(target_q)))
    }
    # The lags k = (3 - jt):5 reach up to five months back from the target quarter's last
    # month. For horizon = "next" that reaches into the CURRENT quarter, which is itself
    # past the estimation sample, so the newdata block leads with the current quarter's
    # three months and forecast() returns TWO quarters -- the next quarter is the last one.
    lead_block <- if (horizon == "next") as.numeric(cur_months$value) else numeric(0)
    um_fc <- forecast(object = um_md,
                      newdata = list(x_est = c(lead_block, x_new,
                                     rep_len(NA_real_, mt - jtf))),
                      se = FALSE, method = "static", add_ts_info = FALSE)
    qoq_growth <- as.numeric(tail(um_fc$mean, 1L))
    fit_md <- um_md
    model_name <- "UMIDAS-full"
  }

  if (!is.finite(qoq_growth))
    stop("nowcast_midas(): nowcast is not finite.\n", call. = FALSE)

  n_obs <- length(na.omit(predict(fit_md)))

  # ---- Implied level ----
  nowcast_level <- if (!is.null(prev_level) && is.finite(prev_level)) {
    prev_level * (1 + qoq_growth / 100)
  } else {
    NA_real_
  }

  list(
    target_quarter      = .quarter_name(target_q),
    qoq_growth          = qoq_growth,
    nowcast_level       = nowcast_level,
    model               = model_name,
    n_obs               = n_obs,
    n_months_in_quarter = jt,
    horizon             = horizon,
    current_quarter     = .quarter_name(current_q),
    prev_level          = if (is.null(prev_level)) NA_real_ else prev_level,
    sample_start        = .quarter_name(.quarter_label(q_label[1L])),
    sample_end          = .quarter_name(q_label[nyt])
  )
}

if (sys.nframe() == 0L) {
  mai <- read.csv("data_raw/mai.csv")
  gdp <- read.csv("data_raw/rt_dgdp_qtr.csv")
  res <- nowcast_midas(mai, gdp)
  cat(sprintf("Target quarter : %s\n", res$target_quarter))
  cat(sprintf("QoQ growth     : %+.3f%%\n", res$qoq_growth))
  cat(sprintf("Implied level  : %s\n",
              if (is.na(res$nowcast_level)) "NA (no prev_level)" else sprintf("%.0f", res$nowcast_level)))
  cat(sprintf("Model          : %s\n", res$model))
  cat(sprintf("n_obs in fit   : %d\n", res$n_obs))
  cat(sprintf("MAI months in target quarter (jt): %d\n", res$n_months_in_quarter))
  cat(sprintf("Fit sample     : %s .. %s\n", res$sample_start, res$sample_end))
}
