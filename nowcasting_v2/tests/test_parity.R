####################################################################################################
# Phase 1 PARITY GATE test (testthat)
#
# Asserts the reproduced RBA MIDAS replication matches RDP 2024-04 Table 4:
#   * full-sample QA MSE-F statistic == 135.34 within ~5% relative error
#   * full-sample QA empirical p-value < 0.05
#
# Run:
#   Rscript -e '.libPaths(c("<renv-lib>", .libPaths())); testthat::test_file("nowcasting_v2/tests/test_parity.R")'
####################################################################################################

library(testthat)

# Locate nowcasting_v2/ root robustly regardless of working dir.
# Priority: NOWCAST_V2_ROOT env var, then search upward from cwd for a dir
# that contains rba_paper/content/Results.
.find_v2_root <- function() {
    env <- Sys.getenv("NOWCAST_V2_ROOT", unset = "")
    if (nzchar(env) && dir.exists(file.path(env, "rba_paper"))) {
        return(normalizePath(env))
    }
    d <- normalizePath(getwd())
    for (i in seq_len(8L)) {
        cand <- file.path(d, "nowcasting_v2")
        if (dir.exists(file.path(cand, "rba_paper", "content", "Results"))) {
            return(normalizePath(cand))
        }
        if (dir.exists(file.path(d, "rba_paper", "content", "Results"))) {
            return(d)  # cwd already inside nowcasting_v2
        }
        parent <- dirname(d)
        if (identical(parent, d)) break
        d <- parent
    }
    stop("Could not locate nowcasting_v2 root; set NOWCAST_V2_ROOT.", call. = FALSE)
}
.v2_root <- .find_v2_root()

source(file.path(.v2_root, "R", "check_replication_parity.R"))
.results_dir <- file.path(.v2_root, "rba_paper", "content", "Results")

res <- read_replication_results(.results_dir)

test_that("full-sample QA MSE-F statistic matches paper (135.34) within 5%", {
    repro_stat <- res$msef["COVID", "MAI-QA"]
    expect_true(is.finite(repro_stat))
    expect_equal(repro_stat, 135.34, tolerance = 0.05)  # relative tolerance
})

test_that("full-sample QA empirical p-value is significant (< 0.05)", {
    repro_pval <- res$msef_pval["COVID", "MAI-QA"]
    expect_true(is.finite(repro_pval))
    expect_lt(repro_pval, 0.05)
})

test_that("pre-COVID QA MSE-F statistic matches paper (11.47) within 5%", {
    repro_stat <- res$msef["Pre-COVID", "MAI-QA"]
    expect_true(is.finite(repro_stat))
    expect_equal(repro_stat, 11.47, tolerance = 0.05)
})

# EOF
