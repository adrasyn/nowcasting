# sweep_v2.R
# Overnight go-wide backtest sweep for the survey-data integration experiment.
# (spec: docs/superpowers/specs/2026-06-09-survey-data-integration-design.md)
#
# HARNESS GLUE ONLY. All estimation math is the unchanged v2/RBA code reached via
# backtest_v2() (which threads exclude_ids/sel_alpha/dfm_q/qa_lag into build_mai +
# nowcast_midas). This file just (a) defines the variant grid, (b) runs each variant
# through backtest_v2(), (c) scores RMSE over full / post-COVID / last-8q-OOS windows
# vs latest-vintage GDP, and (d) writes per-variant CSVs + a master summary.
#
# Staging (controls combinatorics + overfitting):
#   Stage A: panel variants B0..B4a at default hyperparameters.
#   Stage B: hyperparameter grid on the best Stage-A variant(s).
# The best Stage-A variant is chosen automatically (min post-COVID RMSE, tie-break
# full-sample RMSE); Stage B then sweeps model/sel_alpha/dfm_q/qa_lag on it.

suppressWarnings(suppressMessages({
  here <- tryCatch(dirname(sys.frame(1)$ofile), error = function(e) NA)
}))
if (is.na(here) || !nzchar(here)) here <- "R"
source(file.path(here, "backtest_v2.R"))

suppressMessages({ library(dplyr); library(readr) })

OUT_DIR        <- "cache/sweep_v2"
POSTCOVID_FROM <- as.Date("2022-01-01")
OOS_N_QUARTERS <- 8L   # held-out tail window for the overfitting guard
dir.create(OUT_DIR, showWarnings = FALSE, recursive = TRUE)

# ---- metrics over a results frame (mirrors analyze_v2_vs_v1.R definitions) ----
.metrics <- function(res) {
  res <- res[!is.na(res$qoq_error), , drop = FALSE]
  res$tqd <- as.Date(res$target_quarter_date)
  res <- res[order(res$tqd), ]
  pc  <- res[res$tqd >= POSTCOVID_FROM, , drop = FALSE]
  oos <- if (nrow(res) >= OOS_N_QUARTERS) tail(res, OOS_N_QUARTERS) else res
  rmse <- function(d) if (nrow(d)) sqrt(mean(d$qoq_error^2)) else NA_real_
  hit  <- function(d) if (nrow(d)) mean(d$direction_correct, na.rm = TRUE) * 100 else NA_real_
  list(
    n_full       = nrow(res),  rmse_full = rmse(res),  hit_full = hit(res),
    n_pc         = nrow(pc),   rmse_pc   = rmse(pc),    hit_pc   = hit(pc),
    n_oos        = nrow(oos),  rmse_oos  = rmse(oos),   hit_oos  = hit(oos),
    oos_from     = if (nrow(oos)) as.character(min(oos$tqd)) else NA_character_
  )
}

# ---- build a summary row from metrics + variant metadata ----
.summary_row <- function(v, m, n_skipped, runtime_min, fixed_selection) {
  data.frame(
    variant = v$id, stage = v$stage, panel = basename(v$panel_rds),
    exclude = paste(v$exclude_ids, collapse="|"),
    model = v$model, sel_alpha = v$sel_alpha, dfm_q = v$dfm_q,
    qa_lag = paste(range(v$qa_lag), collapse=":"),
    n_full = m$n_full, rmse_full = m$rmse_full, hit_full = m$hit_full,
    n_pc = m$n_pc, rmse_pc = m$rmse_pc, hit_pc = m$hit_pc,
    n_oos = m$n_oos, rmse_oos = m$rmse_oos, hit_oos = m$hit_oos, oos_from = m$oos_from,
    n_skipped = n_skipped, runtime_min = runtime_min,
    fixed_selection = fixed_selection,
    stringsAsFactors = FALSE
  )
}

# ---- run one variant -> writes its results CSV, returns a summary row ----
# Resume-safe: if the variant's results CSV already exists, read it back and
# recompute metrics instead of re-running the (slow) backtest.
run_variant <- function(v) {
  cat(sprintf("\n========== VARIANT %s ==========\n", v$id))
  cat(sprintf("panel=%s | exclude={%s} | model=%s alpha=%.2f q=%d qa_lag=%s\n",
              basename(v$panel_rds), paste(v$exclude_ids, collapse=","),
              v$model, v$sel_alpha, v$dfm_q, paste(range(v$qa_lag), collapse=":")))
  out_csv <- file.path(OUT_DIR, paste0(v$id, ".csv"))
  if (file.exists(out_csv)) {
    cached <- readr::read_csv(out_csv, show_col_types = FALSE)
    m <- .metrics(cached)
    cat(sprintf(">>> %s: CACHED (read back) full RMSE=%.4f (n=%d) | postCOVID RMSE=%.4f (n=%d) | OOS8 RMSE=%.4f\n",
                v$id, m$rmse_full, m$n_full, m$rmse_pc, m$n_pc, m$rmse_oos))
    return(.summary_row(v, m, NA_integer_, 0, "(cached)"))
  }
  t0 <- Sys.time()
  bt <- backtest_v2(panel_rds   = v$panel_rds,
                    panel_info_csv = v$panel_info_csv,
                    out_csv     = file.path(OUT_DIR, paste0(v$id, ".csv")),
                    model       = v$model,
                    exclude_ids = v$exclude_ids,
                    sel_alpha   = v$sel_alpha,
                    dfm_q       = v$dfm_q,
                    qa_lag      = v$qa_lag,
                    verbose     = FALSE)
  el <- as.numeric(difftime(Sys.time(), t0, units = "mins"))
  m  <- .metrics(bt$results)
  cat(sprintf(">>> %s: full RMSE=%.4f (n=%d) | postCOVID RMSE=%.4f (n=%d) | OOS8 RMSE=%.4f | %.1f min\n",
              v$id, m$rmse_full, m$n_full, m$rmse_pc, m$n_pc, m$rmse_oos, el))
  .summary_row(v, m, nrow(bt$skipped), round(el, 2),
               paste(bt$fixed_selection, collapse="|"))
}

# ===========================================================================
# Variant definitions
# ===========================================================================
PANEL_ORIG <- "cache/panel_vintage_ORIG_baseline.rds"   # pre-integration (old short NAB, no AiG/Westpac)
PANEL_NEW  <- "cache/panel_vintage_sweep.rds"           # new data, wmi 2008+
PANEL_WMIF <- "cache/panel_vintage_sweep_wmifull.rds"   # new data, wmi 1988+
INFO       <- "seed/panel_info.csv"
AIG <- c("aig_pmi","aig_pci","aig_psi")
WMI <- "wmi_sent"

.def <- function(id, stage, panel, exclude, model="qa", sel_alpha=0.10, dfm_q=1L, qa_lag=0L:1L,
                 info=INFO)
  list(id=id, stage=stage, panel_rds=panel, panel_info_csv=info, exclude_ids=exclude,
       model=model, sel_alpha=sel_alpha, dfm_q=dfm_q, qa_lag=qa_lag)

stageA <- list(
  .def("B0_baseline",  "A", PANEL_ORIG, character(0)),          # current v2 (old NAB, no new series)
  .def("B1_nabhist",   "A", PANEL_NEW,  c(AIG, WMI)),           # extended NAB history only
  .def("B2_nab_aig",   "A", PANEL_NEW,  WMI),                   # + AiG block
  .def("B3_nab_wmi",   "A", PANEL_NEW,  AIG),                   # + Westpac sentiment (2008+)
  .def("B4_all",       "A", PANEL_NEW,  character(0)),          # full new panel
  .def("B4a_all_wmifull","A", PANEL_WMIF, character(0))         # full new panel, Westpac 1988+
)

# ---- Stage B grid built on the chosen best Stage-A variant ----
build_stageB <- function(best) {
  grid <- list()
  alphas <- c(0.05, 0.10, 0.20)
  qs     <- c(1L, 2L)
  for (md in c("qa","umidas")) {
    lags <- if (md == "qa") list(0L:1L, 0L:2L) else list(0L:1L)  # qa_lag inert for umidas
    for (al in alphas) for (q in qs) for (lg in lags) {
      # skip the exact default (already run in Stage A as `best`)
      if (md=="qa" && al==0.10 && q==1L && identical(lg,0L:1L)) next
      tag <- sprintf("%s_%s_a%02d_q%d_l%s", best$id, md, round(al*100), q,
                     paste(range(lg), collapse=""))
      grid[[length(grid)+1L]] <- .def(tag, "B", best$panel_rds, best$exclude_ids,
                                       model=md, sel_alpha=al, dfm_q=q, qa_lag=lg,
                                       info=best$panel_info_csv)
    }
  }
  grid
}

# ===========================================================================
# Main
# ===========================================================================
if (sys.nframe() == 0L) {
  args <- commandArgs(trailingOnly = TRUE)
  stage_arg <- if (length(args)) args[[1]] else "all"   # "A" | "B" | "all"

  rows <- list()

  # ---- Stage A ----
  if (stage_arg %in% c("A","all")) {
    for (v in stageA) rows[[length(rows)+1L]] <- run_variant(v)
    sumA <- do.call(rbind, rows)
    readr::write_csv(sumA, file.path(OUT_DIR, "summary_stageA.csv"))
    cat("\n--- Stage A summary ---\n"); print(sumA[, c("variant","rmse_full","rmse_pc","rmse_oos","hit_pc")])
  }

  # ---- choose best Stage-A variant (exclude B0; we want a NEW-data winner; but
  #      record if nothing beats B0). Best = min rmse_pc, tie-break rmse_full. ----
  if (stage_arg %in% c("B","all")) {
    sumA <- readr::read_csv(file.path(OUT_DIR, "summary_stageA.csv"), show_col_types = FALSE)
    cand <- sumA[sumA$variant != "B0_baseline", , drop = FALSE]
    cand <- cand[order(cand$rmse_pc, cand$rmse_full), ]
    best_id <- cand$variant[1]
    bestdef <- Filter(function(v) v$id == best_id, stageA)[[1]]
    cat(sprintf("\n>>> Best Stage-A new-data variant: %s (postCOVID RMSE %.4f)\n",
                best_id, cand$rmse_pc[1]))

    stageB <- build_stageB(bestdef)
    cat(sprintf(">>> Stage B: %d hyperparameter variants on %s\n", length(stageB), best_id))
    rowsB <- list()
    for (v in stageB) rowsB[[length(rowsB)+1L]] <- tryCatch(run_variant(v),
      error = function(e) { cat(sprintf("  [VARIANT FAIL] %s: %s\n", v$id, conditionMessage(e))); NULL })
    rowsB <- Filter(Negate(is.null), rowsB)
    sumB <- do.call(rbind, rowsB)
    readr::write_csv(sumB, file.path(OUT_DIR, "summary_stageB.csv"))

    # master summary = A + B. Coerce oos_from to character on both sides:
    # read-back sumA parses it as <date>, fresh sumB builds it as <character>,
    # and bind_rows refuses to combine the two types.
    sumA$oos_from <- as.character(sumA$oos_from)
    sumB$oos_from <- as.character(sumB$oos_from)
    sumAll <- dplyr::bind_rows(sumA, sumB)
    readr::write_csv(sumAll, file.path(OUT_DIR, "summary.csv"))
    cat("\n--- FULL summary (sorted by postCOVID RMSE) ---\n")
    print(sumAll[order(sumAll$rmse_pc), c("variant","stage","rmse_full","rmse_pc","rmse_oos","hit_pc")])
  }
}
