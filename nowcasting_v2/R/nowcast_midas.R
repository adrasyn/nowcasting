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
#
# Returns a list:
#   target_quarter, qoq_growth, nowcast_level, model, n_obs,
#   plus n_months_in_quarter (jt) and prev_level for transparency.
####################################################################################################
nowcast_midas <- function(mai, gdp_growth, as_of = NULL, prev_level = NULL,
                          model = c("qa", "umidas"),
                          qa_lag = 0L:1L) {   # QA quarterly lag (sweep knob; 0:1 = default)
  model <- match.arg(model)

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

  if (last_mai_q <= last_gdp_q) {
    # MAI doesn't yet reach beyond released GDP. Target the quarter AFTER last GDP
    # and rely on whatever (possibly zero) MAI months exist for it; if none, fail loud.
    target_q <- seq(last_gdp_q, by = "3 months", length.out = 2L)[2L]
  } else {
    target_q <- last_mai_q
  }

  # MAI months belonging to the target quarter (the "x_new" partial months).
  target_months <- m[.quarter_label(m$date) == target_q, , drop = FALSE]
  jt <- nrow(target_months)
  if (jt > mt) stop("nowcast_midas(): more than 3 MAI months in target quarter (bad alignment).\n",
                    call. = FALSE)
  # jt == 0 is the brief post-GDP-release / pre-new-monthly-data window (MAI and
  # released GDP end on the same quarter). We still nowcast the NEXT quarter as a
  # pure 1-step-ahead forecast: with no within-quarter MAI yet, the QA model's
  # contemporaneous quarter-average is set to the LAST OBSERVED quarter-average
  # (random-walk-in-level extrapolation of the MAI). This is the only adaptation
  # of the RBA QA path; logged below and surfaced via n_months_in_quarter = 0.

  # ---- Build the estimation sample honouring the data contract ----
  # Estimation must use only COMPLETE quarters that also have released GDP. Drop the
  # target quarter's (partial) months from the in-sample monthly block.
  m_est_src <- m[m$date < target_q, , drop = FALSE]      # months strictly before target quarter

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

  if (identical(model, "qa")) {
    # ---- QA U-MIDAS: fit + nowcast (RBA Recursive_Nowcast lines 226-233) ----
    # In-sample quarter-averages of the MAI, with one lag (k=0:1) to mirror a
    # U-MIDAS with flat coefficients over the within-quarter months.
    xm_est <- rowMeans(mls(x = x_est, k = 0L:2L, m = mt), na.rm = TRUE)
    qa_md <- midas_r(formula = y_est ~ mls(x = xm_est, k = qa_lag, m = 1L),
                     data = list(y_est = y_est, xm_est = xm_est), start = NULL)

    # Partial-quarter average for the target quarter (the live edge). When jt == 0
    # there is no within-quarter MAI yet, so extrapolate with the last observed
    # quarter-average (random-walk-in-level); see note above.
    if (jt >= 1L) {
      nxm <- mean(target_months$value, na.rm = TRUE)
    } else {
      nxm <- as.numeric(tail(xm_est, 1L))
      cat(sprintf("nowcast_midas(): jt=0 (no MAI months yet for %s); using last observed quarter-average %.4f as contemporaneous input (random-walk extrapolation).\n",
                  .quarter_name(target_q), nxm))
    }
    qa_fc <- forecast(object = qa_md, newdata = list(xm_est = c(nxm)),
                      se = FALSE, method = "static", add_ts_info = FALSE)
    qoq_growth <- as.numeric(qa_fc$mean)
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
      # jt==0: no within-quarter data; pure 1-step-ahead. RW-extrapolate the
      # contemporaneous month from the last observed monthly MAI value.
      x_new <- numeric(0)
      cat(sprintf("nowcast_midas(): jt=0 (no MAI months yet for %s); U-MIDAS uses k=(k1):k2 with no within-quarter input (1-step-ahead).\n",
                  .quarter_name(target_q)))
    }
    um_fc <- forecast(object = um_md,
                      newdata = list(x_est = c(x_new,
                                     rep_len(NA_real_, mt - jtf))),
                      se = FALSE, method = "static", add_ts_info = FALSE)
    qoq_growth <- as.numeric(um_fc$mean)
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
