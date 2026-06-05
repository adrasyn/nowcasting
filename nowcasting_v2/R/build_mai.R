# build_mai.R
# Phase 3.3 -- build the live Monthly Activity Indicator (MAI).
#
# (a) Targeted-predictor selection (adapts Targeted_Predictor_MAI_Dataset.R):
#     regress quarterly GDP growth on each candidate's 3 within-quarter monthly
#     lags (via mf_lag) + COVID impulse dummies, HAC OLS (lm_hac), and Wald-test
#     that the candidate's 3 coefficients are jointly zero. Keep series whose
#     Wald stat exceeds the chi-square(df=3, alpha=0.1) threshold.
# (b) Single dynamic factor on the selected transformed panel:
#     pc_factor() init then qmle_dfm(q=1, s=2, p=1) (per Estimate_and_Analyse_TP_MAI.R).
# (c) The first factor is the MAI -> data_raw/mai.csv + cache/mai.rds.
#
# Reuses the RBA estimation math verbatim; this file is glue + windowing/IO only.

suppressWarnings(suppressMessages({
  here <- tryCatch(dirname(sys.frame(1)$ofile), error = function(e) NA)
}))
if (is.na(here) || !nzchar(here)) here <- "R"
source(file.path(here, "_setup.R"))
source(file.path(here, "methods", "misc_methods.R"))
source(file.path(here, "methods", "lm_hac_methods.R"))
source(file.path(here, "methods", "qmle_dfm_methods.R"))
source(file.path(here, "methods", "mai_utils.R"))
source(file.path(here, "transform_panel.R"))

suppressMessages({
  library(dplyr)
  library(readr)
})

# --- helpers --------------------------------------------------------------

# COVID impulse dummies, one column per quarter in [2020Q1, 2021Q4] (RBA window).
.covid_dummies <- function(qdates) {
  covid_q <- seq(as.Date("2020-03-01"), as.Date("2021-12-01"), by = "3 months")
  covid_q <- covid_q[covid_q >= min(qdates) & covid_q <= max(qdates)]
  D <- sapply(covid_q, function(cq) as.numeric(qdates == cq))
  if (length(covid_q) == 0L) return(matrix(numeric(0), nrow = length(qdates), ncol = 0))
  matrix(D, nrow = length(qdates))
}

# --- main -----------------------------------------------------------------

build_mai <- function(tfs           = NULL,
                      panel_info_csv = "seed/panel_info.csv",
                      gdp_csv        = "data_raw/rt_dgdp_qtr.csv",
                      out_csv        = "data_raw/mai.csv",
                      out_rds        = "cache/mai.rds",
                      sel_alpha      = 0.10,    # selection threshold (RBA)
                      iis_alpha      = 0.01,    # COVID dummy significance (RBA)
                      exclude_ids    = character(0),
                      force_selected = NULL,    # if non-NULL, skip Wald selection and
                                                # use these ids (intersected w/ available)
                      verbose_dfm    = FALSE) {

  if (is.null(tfs)) {
    wide <- readRDS("cache/panel_vintage_latest.rds")
    tfs  <- transform_panel(wide, panel_info_csv)
  }
  info <- readr::read_csv(panel_info_csv, show_col_types = FALSE)

  ids <- setdiff(names(tfs), "date")
  if (length(exclude_ids)) ids <- setdiff(ids, exclude_ids)

  # ---- GDP target (quarterly growth) ----
  gdp <- readr::read_csv(gdp_csv, show_col_types = FALSE)
  gdp$date <- as.Date(gdp$date)
  gdp <- gdp[order(gdp$date), ]

  mt <- 3L  # months per quarter

  # ---- Common window honouring the data contract ----
  # Monthly span: start at the first month of a quarter (Jan/Apr/Jul/Oct), end at
  # the last complete quarter. Quarterly GDP windowed to the same quarters.
  spine <- tfs$date
  # First month that is a quarter start AND >= first spine date
  qmonths <- c(1, 4, 7, 10)
  ms <- spine[ as.integer(format(spine, "%m")) %in% qmonths ]
  m_start <- min(ms)
  # GDP quarter end: align quarter labels. ABS quarterly GDP dates are first-of-quarter
  # months (Mar/Jun/Sep/Dec -> labelled 03/06/09/12-01). Map to quarter index.
  # We need full quarters: monthly data through end of a quarter (month 3,6,9,12).
  m_end_candidates <- spine[ as.integer(format(spine, "%m")) %in% c(3,6,9,12) ]
  # also need GDP available for that quarter
  q_dates <- gdp$date
  # Build quarter-end month for each quarter-start in our monthly window
  m_end <- max(m_end_candidates)
  # Full monthly window for the DFM/MAI emission: [m_start, last AVAILABLE month].
  # This INCLUDES 1-2 trailing partial-quarter months so the emitted MAI carries
  # the ragged edge that nowcast_midas needs (jt>0). The DFM estimation itself is
  # unchanged -- qmle_dfm (na_opt="exclude") tolerates the ragged tail and simply
  # produces factor values for the partial-quarter months as well.
  m_last <- max(spine)
  msel_full <- spine >= m_start & spine <= m_last
  Xm_full   <- as.matrix(tfs[msel_full, ids, drop = FALSE])
  mdates_full <- spine[msel_full]

  # Complete-quarter block for the targeted-predictor SELECTION + GDP alignment
  # (the y/x Wald regression must use whole quarters only -> data contract).
  msel <- spine >= m_start & spine <= m_end
  Xm   <- as.matrix(tfs[msel, ids, drop = FALSE])
  mdates <- spine[msel]
  nxt  <- nrow(Xm)
  if (nxt %% mt != 0L) {
    # drop trailing partial quarter
    drop <- nxt %% mt
    Xm <- Xm[seq_len(nxt - drop), , drop = FALSE]
    mdates <- mdates[seq_len(nxt - drop)]
    nxt <- nrow(Xm)
  }

  # Quarter-label dates for the monthly window: each quarter labelled by its
  # last month's first-of-quarter ABS convention (Mar/Jun/Sep/Dec).
  q_label <- mdates[seq(mt, nxt, by = mt)]   # 3rd month of each quarter (e.g. 03-01)
  # Align GDP onto these quarter labels
  y_full <- gdp$value[match(q_label, gdp$date)]
  nyt <- length(q_label)
  if (nyt != nxt / mt) stop("build_mai(): contract violation nxt != 3*nyt.\n")

  # COVID dummies aligned to q_label
  Dcov <- .covid_dummies(q_label)

  # ---- (a) Targeted-predictor selection ----
  k1 <- 0L; k2 <- 2L
  jn <- length(k1:k2)                         # 3 monthly lags per series
  qvec <- matrix(0.0, nrow = jn, ncol = 1L)

  int <- TRUE; kern <- "QS"; res <- "EH"; dbw <- FALSE; dft <- TRUE

  # IIS: which COVID dummies are individually significant (on full-sample y)
  ix <- integer(0)
  if (ncol(Dcov) > 0L) {
    ok0 <- complete.cases(y_full, Dcov)
    ism <- lm_hac(y = y_full[ok0], x = Dcov[ok0, , drop = FALSE],
                  intercept = int, kern_opt = kern, res_opt = res,
                  dbw_opt = dbw, df_correct = dft)
    ix <- as.integer(which(ism$pvalue[-1L] < iis_alpha))  # exclude intercept
  }
  Dsig <- if (length(ix)) Dcov[, ix, drop = FALSE] else NULL

  # Wald restriction matrix: zero out the jn series coefs (after intercept).
  # Columns: [intercept, series(jn), sig-dummies]. wald_test uses full nvar width.
  ndsig <- if (is.null(Dsig)) 0L else ncol(Dsig)
  rmat <- cbind(matrix(0, jn, 1L), diag(1, jn),
                matrix(0, jn, ndsig))

  results <- matrix(NA_real_, nrow = length(ids), ncol = 3L,
                    dimnames = list(ids, c("Stat", "Pval", "Rsq")))

  for (i in seq_along(ids)) {
    xm <- mf_lag(x = Xm[, i], k = k1:k2, m = mt)   # nyt x 3 (M3,M2,M1)
    Xreg <- if (is.null(Dsig)) xm else cbind(xm, Dsig)
    ok <- complete.cases(y_full, Xreg)
    if (sum(ok) < (jn + ndsig + 5L)) next          # not enough obs to identify
    mod <- tryCatch(
      lm_hac(y = y_full[ok], x = Xreg[ok, , drop = FALSE], intercept = int,
             kern_opt = kern, res_opt = res, dbw_opt = dbw, df_correct = dft),
      error = function(e) NULL)
    if (is.null(mod)) next
    wt <- tryCatch(wald_test(x = mod, rmat = rmat, qvec = qvec),
                   error = function(e) NULL)
    if (is.null(wt)) next
    results[i, ] <- c(wt$statistic, wt$pvalue, mod$rsq)
  }

  threshold <- qchisq(p = sel_alpha, df = jn, lower.tail = FALSE)
  keep <- !is.na(results[, "Stat"]) & results[, "Stat"] >= threshold
  selected <- rownames(results)[keep]
  ranked <- results[order(results[, "Stat"], decreasing = TRUE), , drop = FALSE]
  ranked_sel <- ranked[rownames(ranked) %in% selected, , drop = FALSE]

  # ---- Pseudo-real-time override: fix the targeted-predictor selection ----
  # When force_selected is supplied (backtest harness), bypass the recursive
  # Wald selection and use a pre-determined selection (typically the full-sample
  # selection). Intersect with the ids actually available in this (truncated)
  # panel so an as-of date that predates a series simply drops it. The Wald
  # ranks above are still computed and returned for diagnostics.
  if (!is.null(force_selected)) {
    forced <- intersect(force_selected, ids)
    if (length(forced) < 2L) {
      stop(sprintf("build_mai(): force_selected leaves only %d available series.\n",
                   length(forced)), call. = FALSE)
    }
    selected <- forced
  }

  if (length(selected) < 2L) {
    stop(sprintf("build_mai(): only %d series selected (threshold=%.2f); cannot estimate a factor.\n",
                 length(selected), threshold), call. = FALSE)
  }

  # ---- (b) Single dynamic factor on selected transformed panel ----
  # Estimate the DFM on the FULL monthly window (Xm_full) so the emitted MAI runs
  # through the last available month (ragged edge included). The DFM estimation is
  # unchanged from before -- only its input window now keeps the trailing 1-2
  # partial-quarter months instead of discarding them.
  ybegin <- c(as.integer(format(mdates_full[1], "%Y")), as.integer(format(mdates_full[1], "%m")))
  Ysel <- ts(Xm_full[, selected, drop = FALSE], start = ybegin, frequency = 12)

  # PC init (drop NA rows the way the RBA does) -- diagnostic / sign reference
  yna <- remove_na_values(x = Ysel, na_opt = "exclude")
  pc <- tryCatch(pc_factor(x = yna, r = 1L, norm_opt = "LN",
                           scale_opt = FALSE, sign_opt = TRUE, vardec_opt = FALSE),
                 error = function(e) NULL)

  # QMLE DFM (EM tolerates ragged NAs)
  dfm <- qmle_dfm(x = Ysel, q = 1L, s = 2L, p = 1L,
                  id_opt = "DFM2", na_opt = "exclude", scale_opt = FALSE,
                  sign_opt = FALSE, max_iter = 500L, threshold = 1E-4,
                  check_increased = TRUE, verbose = verbose_dfm)

  fac <- dfm$factors[, 1L]
  # Orient the factor so it co-moves positively with mean of selected panel
  ref <- rowMeans(Xm_full[, selected, drop = FALSE], na.rm = TRUE)
  if (suppressWarnings(cor(fac, ref, use = "complete.obs")) < 0) fac <- -fac

  mai <- data.frame(date = mdates_full, value = as.numeric(fac))

  # % variance explained by the single factor (PC-based, on balanced block)
  var_explained <- NA_real_
  if (!is.null(pc) && !is.null(pc$loadings)) {
    # share of total variance captured by factor 1 in the balanced PC block
    f <- pc$factors[, 1L]; L <- pc$loadings[, 1L]
    fit <- outer(f, L)
    var_explained <- sum(fit^2) / sum(yna^2)
  }

  diagnostics <- list(
    selected      = selected,
    ranked_all    = ranked,
    ranked_sel    = ranked_sel,
    threshold     = threshold,
    n_candidates  = length(ids),
    n_selected    = length(selected),
    covid_dummies_significant = ix,
    dfm_aic       = dfm$aic,
    dfm_loglik    = dfm$loglik,
    dfm_niter     = dfm$niter,
    pc_var_explained = var_explained,
    window_month  = range(mdates_full),
    excluded_ids  = exclude_ids
  )

  out <- list(mai = mai, loadings = dfm$loadings, diagnostics = diagnostics,
              factor_se = dfm$factor_se[, 1L])

  if (!is.null(out_csv)) {
    dir.create(dirname(out_csv), showWarnings = FALSE, recursive = TRUE)
    write.csv(mai, out_csv, row.names = FALSE)
  }
  if (!is.null(out_rds)) {
    dir.create(dirname(out_rds), showWarnings = FALSE, recursive = TRUE)
    saveRDS(out, out_rds)
  }

  cat(sprintf("build_mai(): %d candidates -> %d selected; MAI %s..%s (n=%d); DFM aic=%.1f\n",
              length(ids), length(selected),
              as.character(min(mdates_full)), as.character(max(mdates_full)), nrow(mai),
              dfm$aic))
  invisible(out)
}

if (sys.nframe() == 0L) {
  res <- build_mai(verbose_dfm = FALSE)
  cat("\nSelected (ranked by Wald):\n")
  print(round(res$diagnostics$ranked_sel, 2))
  cat(sprintf("\nCOVID dummies significant (idx): %s\n",
              paste(res$diagnostics$covid_dummies_significant, collapse = ", ")))
  cat(sprintf("PC var explained (factor 1): %.3f\n", res$diagnostics$pc_var_explained))
}
