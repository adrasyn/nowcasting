####################################################################################################
# Phase 1 Parity Check: reproduced RBA MIDAS results vs RDP 2024-04 published benchmarks
#
# Compares the CSVs produced by the RBA replication scripts (run from
# nowcasting_v2/rba_paper/content/) against the numbers published in the paper
# (rdp2024-04.pdf, Table 3 + Table 4).
#
# This is a PARITY GATE: if reproduced numbers match the paper within tolerance,
# the gate passes; otherwise it reports MISMATCH with both sets of numbers.
####################################################################################################

####################################################################################################
# (a) Paper target constants (extracted from rdp2024-04.pdf via pdftools::pdf_text)
####################################################################################################

# Table 4 -- MSE-F Test of Equal Prediction Accuracy.
# In the RBA scripts the rownames are "COVID" (= the FULL sample, incl. COVID) and
# "Pre-COVID" (sample excluding the COVID period). Column "MAI-QA" is the
# quarter-average model = paper column "QA".
paper_msef <- list(
    # Full-sample (script row "COVID")
    full_QA_stat = 135.34,
    full_QA_pval = 0.00,
    full_FC_stat = 36.43,
    full_M1_stat = 132.87,
    full_M2_stat = 80.47,
    full_M3_stat = 34.86,
    full_AR1_stat = -7.12,
    # Pre-COVID (script row "Pre-COVID")
    pc_QA_stat   = 11.47,
    pc_QA_pval   = 0.00,
    pc_FC_stat   = -19.77,
    pc_M1_stat   = -14.29,
    pc_M2_stat   = -11.53,
    pc_M3_stat   = -7.71,
    pc_AR1_stat  = -0.20
)

# Table 3 -- "All" horizon Root Mean Squared Error (full sample, incl. COVID),
# columns Sample mean, AR(1), FC, M1, M2, M3, QA.
paper_rmse_all_full <- c(
    Mean = 0.98, `AR(1)` = 1.01, `MAI-UM-FC` = 0.87,
    `MAI-UM-M1` = 0.70, `MAI-UM-M2` = 0.78, `MAI-UM-M3` = 0.88, `MAI-QA` = 0.70
)

# Table 3 -- "All" horizon RMSE, pre-COVID sample.
paper_rmse_all_pc <- c(
    Mean = 0.59, `AR(1)` = 0.59, `MAI-UM-FC` = 0.64,
    `MAI-UM-M1` = 0.62, `MAI-UM-M2` = 0.61, `MAI-UM-M3` = 0.60, `MAI-QA` = 0.56
)

####################################################################################################
# (b) Read the results our run produced in Results/
####################################################################################################

read_replication_results <- function(results_dir) {

    msef_file      <- file.path(results_dir, "msef_gdp_q_1_s_2_p_1.csv")
    msef_pval_file <- file.path(results_dir, "msef_pval_gdp_q_1_s_2_p_1.csv")
    rmse_file      <- file.path(results_dir, "rmse_gdp_q_1_s_2_p_1.csv")
    rmse_pc_file   <- file.path(results_dir, "rmse_pc_gdp_q_1_s_2_p_1.csv")

    for (f in c(msef_file, msef_pval_file, rmse_file, rmse_pc_file)) {
        if (!file.exists(f)) {
            stop(sprintf("Expected results file missing: %s\n(Did all three replication scripts run?)", f),
                 call. = FALSE)
        }
    }

    # MSE-F statistics: first column = rowname ("COVID"/"Pre-COVID")
    msef <- read.csv(msef_file, header = TRUE, check.names = FALSE)
    rownames(msef) <- msef[[1L]]; msef[[1L]] <- NULL

    msef_pval <- read.csv(msef_pval_file, header = TRUE, check.names = FALSE)
    rownames(msef_pval) <- msef_pval[[1L]]; msef_pval[[1L]] <- NULL

    # RMSE: rownames are horizon labels; "Full sample" is the All-horizon row.
    rmse <- read.csv(rmse_file, header = TRUE, check.names = FALSE)
    rownames(rmse) <- rmse[[1L]]; rmse[[1L]] <- NULL

    rmse_pc <- read.csv(rmse_pc_file, header = TRUE, check.names = FALSE)
    rownames(rmse_pc) <- rmse_pc[[1L]]; rmse_pc[[1L]] <- NULL

    list(msef = msef, msef_pval = msef_pval, rmse = rmse, rmse_pc = rmse_pc)
}

####################################################################################################
# (c) Comparison: print matched / mismatched with relative error
####################################################################################################

# Relative error; for tiny / zero denominators fall back to absolute error.
rel_err <- function(reproduced, paper) {
    if (is.na(reproduced) || is.na(paper)) return(NA_real_)
    if (abs(paper) < 1e-8) return(abs(reproduced - paper))
    abs(reproduced - paper) / abs(paper)
}

compare_parity <- function(results_dir, tol = 0.05, verbose = TRUE) {

    res <- read_replication_results(results_dir)

    rows <- list()
    add <- function(label, reproduced, paper, tol_use = tol, is_pval = FALSE) {
        re <- rel_err(reproduced, paper)
        if (is_pval) {
            # p-value parity = both below 0.05 (paper reports 0.00)
            ok <- (!is.na(reproduced) && reproduced < 0.05 && paper < 0.05)
        } else {
            ok <- (!is.na(re) && re <= tol_use)
        }
        rows[[length(rows) + 1L]] <<- data.frame(
            metric = label, reproduced = reproduced, paper = paper,
            rel_err = re, match = ok, stringsAsFactors = FALSE)
    }

    # --- Table 4 headline gate: full-sample QA MSE-F stat + p-value ---
    add("MSE-F QA full-sample (stat)", res$msef["COVID", "MAI-QA"],     paper_msef$full_QA_stat)
    add("MSE-F QA full-sample (pval)", res$msef_pval["COVID", "MAI-QA"], paper_msef$full_QA_pval, is_pval = TRUE)
    add("MSE-F QA pre-COVID (stat)",   res$msef["Pre-COVID", "MAI-QA"], paper_msef$pc_QA_stat)
    add("MSE-F QA pre-COVID (pval)",   res$msef_pval["Pre-COVID", "MAI-QA"], paper_msef$pc_QA_pval, is_pval = TRUE)

    # --- Other Table 4 statistics (full sample) ---
    add("MSE-F FC full-sample (stat)", res$msef["COVID", "MAI-UM-FC"], paper_msef$full_FC_stat)
    add("MSE-F M1 full-sample (stat)", res$msef["COVID", "MAI-UM-M1"], paper_msef$full_M1_stat)
    add("MSE-F M2 full-sample (stat)", res$msef["COVID", "MAI-UM-M2"], paper_msef$full_M2_stat)
    add("MSE-F M3 full-sample (stat)", res$msef["COVID", "MAI-UM-M3"], paper_msef$full_M3_stat)

    # --- Table 3 "All" horizon RMSE (full sample). Paper rounded to 2 dp,
    #     so use an absolute-style tolerance of 0.01 on a 2dp comparison. ---
    for (m in names(paper_rmse_all_full)) {
        add(sprintf("RMSE All full-sample [%s]", m),
            round(res$rmse["Full sample", m], 2), paper_rmse_all_full[[m]], tol_use = 0.02)
    }
    for (m in names(paper_rmse_all_pc)) {
        add(sprintf("RMSE All pre-COVID [%s]", m),
            round(res$rmse_pc["Full sample", m], 2), paper_rmse_all_pc[[m]], tol_use = 0.02)
    }

    tab <- do.call(rbind, rows)

    if (verbose) {
        cat("####################################################################\n")
        cat("# Phase 1 Parity Check: reproduced vs RDP 2024-04 published numbers\n")
        cat(sprintf("# Tolerance (MSE-F stats): %.0f%% relative error\n", tol * 100))
        cat("####################################################################\n\n")
        out <- tab
        out$reproduced <- round(out$reproduced, 4)
        out$rel_err    <- round(out$rel_err, 4)
        out$match      <- ifelse(out$match, "MATCH", "MISMATCH")
        print(out, row.names = FALSE)
        cat("\n")
    }

    # Gate verdict driven by the headline full-sample QA stat + p-value.
    qa_stat_row <- tab[tab$metric == "MSE-F QA full-sample (stat)", ]
    qa_pval_row <- tab[tab$metric == "MSE-F QA full-sample (pval)", ]
    gate_pass <- isTRUE(qa_stat_row$match) && isTRUE(qa_pval_row$match)

    if (verbose) {
        cat(sprintf("Headline QA MSE-F: reproduced = %.2f vs paper = %.2f (rel err %.2f%%)\n",
                    qa_stat_row$reproduced, qa_stat_row$paper, qa_stat_row$rel_err * 100))
        cat(sprintf("Headline QA p-value: reproduced = %.3f (paper 0.00; gate needs < 0.05)\n",
                    qa_pval_row$reproduced))
        cat(sprintf("\n==> PARITY GATE: %s\n", if (gate_pass) "PASS" else "MISMATCH"))
    }

    invisible(list(table = tab, gate_pass = gate_pass))
}

# Auto-run only when this file is the script passed to Rscript (not when sourced
# from the test harness). Detect via the --file= command arg matching this file.
.parity_is_main <- {
    a <- commandArgs(trailingOnly = FALSE)
    f <- sub("^--file=", "", a[grep("^--file=", a)])
    length(f) == 1L && grepl("check_replication_parity\\.R$", f)
}
if (.parity_is_main) {
    .results_dir <- if (exists(".parity_results_dir")) .parity_results_dir else "nowcasting_v2/rba_paper/content/Results"
    compare_parity(.results_dir)
}

# EOF
