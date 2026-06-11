####################################################################################################
# RDP 2024-04: Nowcasting Quarterly GDP Growth Using A Monthly Activity Indicator
####################################################################################################
# Luke Hartigan, 28-03-2023
####################################################################################################

# Clear the workspace
rm(list = ls(all = TRUE))

# Set directories
d_location <- "Data/"
f_location <- "Code/methods/"
r_location <- "Results/"

# Source required functions
source(paste0(f_location, "mai_utils.R"))     # helper functions
source(paste0(f_location, "misc_methods.R"))

# Load the required libraries
suppressMessages(library("zoo"))
suppressMessages(library("midasr"))

# Set up a few options
options(digits = 4)
print_opt <- TRUE

# What are we doing?
cat("Nowcasting quarterly GDP growth using a monthly activity indicator and various models in a recursive exercise...\n")

####################################################################################################
# Read in the data for the analysis
####################################################################################################

# Monthly indicator name
idx_name <- "MAI"
idx_long_name <- "Monthly Activity Indicator"

# Date format
xdate_fmt <- "%Y-%m-%d"
ydate_fmt <- "%d/%m/%Y"

# Set some time series values
x_freq_str <- "month"
y_freq_str <- "quarter"

x_freq <- 12
y_freq <- 4

# High frequency ratio
mt <- x_freq / y_freq

# Estimation options used to estimate monthly indicator -- manually determined
q <- 1L # no. dynamic factors
s <- 2L # no. dynamic loadings in filter
p <- 1L # no. AR terms in VAR

# Load the previously estimated monthly indicator series
mth_infile <- sprintf("rt_%s_q_%d_s_%d_p_%d_rdp.csv", tolower(idx_name), q, s, p) # real-time mai
mth_data <- read.csv(paste0(d_location, mth_infile), header = TRUE, sep = ',')
mth_seq <- as.Date(x = mth_data[, 1L], format = xdate_fmt)
x <- mth_data[, -1L] # drop dates column
nx <- length(x)

# Read in 'Real-time' GDP series (NB: already a quarterly growth rate)
qtr_infile <- "rt_dgdp_qtr.csv"
qtr_data <- read.csv(paste0(d_location, qtr_infile), header = TRUE, sep = ',')
qtr_seq <- as.Date(x = qtr_data[, 1L], format = ydate_fmt)
y <- qtr_data[, -1L] # drop dates column
ny <- length(y)

# Read in previously estimated forecast/nowcast errors
er_infile <- sprintf("er_gdp_q_%d_s_%d_p_%d.csv", q, s, p)
er_data <- read.csv(paste0(r_location, er_infile), header = TRUE, sep = ',')
er_seq <- as.Date(x = er_data[, 1L], format = xdate_fmt)
er_mat <- er_data[, -1L, drop = FALSE] # drop dates column

# Numerical starting and ending times
x_begin <- get_year_month(x = mth_seq[1L])
x_end <- get_year_month(x = mth_seq[nx])

y_begin <- get_year_quarter(x = qtr_seq[1L])
y_end <- get_year_quarter(x = qtr_seq[ny])

er_begin <- get_year_quarter(x = er_seq[1L])

# Convert 'ts' objects so we can use window() later on
x <- ts(data = x, start = x_begin, frequency = x_freq)
y <- ts(data = y, start = y_begin, frequency = y_freq)

er_mat <- ts(data = er_mat, start = er_begin, frequency = y_freq)

# String estimation starting and ending times -- *** Manaully determined ***
m_begin_str <- "1978-04-01" # i.e. 1978:M4 (first month in Q2)
q_begin_str <- "1978-06-01" # i.e. 1978:Q2
ts_end_str <- qtr_seq[ny] # common ending point

pre_covid_str <- "2019-12-01"

# Numerical estimation starting and ending times
m_begin <- get_year_month(x = m_begin_str)
m_end <- get_year_month(x = ts_end_str)

q_begin <- get_year_quarter(x = q_begin_str)
q_end <- get_year_quarter(x = ts_end_str)

pre_covid <- get_year_quarter(x = pre_covid_str)

# Adjust both series to be of comparable lengths for MIDAS regression
x_t <- window(x = x, start = m_begin, end = m_end)
y_t <- window(x = y, start = q_begin, end = q_end)

nxt <- length(x_t)
nyt <- length(y_t)

# Check length(x_t) == 3 * length(y_t)
if (nxt / nyt != mt) {
    stop(sprintf("Error: length(x_t) = %d not a multiple of length(y_t) = %d\n",
                 nxt, nyt), call. = FALSE)
}

# Exclude COVID-19 period
er_mat_pc <- window(x = er_mat, start = NULL, end = pre_covid)

# Combine into a list so we can loop over them later
er_lst <- list(er_mat, er_mat_pc)

####################################################################################################
# Setup MIDAS regression model
####################################################################################################

# U-MIDAS regression options
k1 <- 3L # begin lag
k2 <- 5L # end lag

# U-MIDAS forecast options
se_opt <- TRUE
nlevel <- 95
fan_opt <- FALSE
npath <- 100L
meth_opt <- "static"
info_opt <- FALSE
set.seed(1025879)

####################################################################################################
# MSE-F Test Statistic
####################################################################################################

# Date sequences for recursive estimation -- monthly
m_est_seq <- seq(from = as.Date(m_begin_str),
                 to = as.Date(ts_end_str), by = x_freq_str)

# Date sequences for recursive estimation -- quarterly
q_est_seq <- seq(from = as.Date(q_begin_str),
                 to = as.Date(ts_end_str), by = y_freq_str)

# Compute a few things outside the loop
ht <- 1L
ct <- 1.0

est_end_it <- 40L
it_seq <- seq(from = est_end_it, to = (nyt - ht), by = 1L)
it_len <- length(it_seq)

# Date sequences for recursive forecast / nowcast -- quarterly
q_fc_seq <- tail(x = q_est_seq, n = it_len)

# Modelling options
fc_mds <- c("Mean", "AR(1)", "MAI-UM-FC", "MAI-UM-M1",
            "MAI-UM-M2", "MAI-UM-M3", "MAI-QA")
ht_vec <- c(dim(er_mat)[1L], dim(er_mat_pc)[1L])
nmd <- length(fc_mds)
nhv <- length(ht_vec)

# Compute the MSE-F statistic -- baseline model: Mean
msef_act <- matrix(data = NA_real_, nrow = nhv, ncol = (nmd - 1L))

for (kt in 2L:nmd) {

    for (lt in seq_len(nhv)) {

        msef_act[lt, kt - 1L] <- ht_vec[lt] * rel_mse(f1 = tail(x = er_lst[[lt]][, kt],
                                                                n = ht_vec[lt]),
                                                      f2 = tail(x = er_lst[[lt]][, 1L],
                                                                n = ht_vec[lt]))

    }

}

# Set the row and column names
rownames(msef_act) <- c("COVID","Pre-COVID")
colnames(msef_act) <- fc_mds[-1L]

####################################################################################################
# Bootstrap p-values for MSE-F test
####################################################################################################

# Estimate null model for the full sample
int_md_all <- lm(formula = y_t ~ 1.0)
mx <- as.numeric(coef(object = int_md_all))
sx <- as.numeric(sd(resid(object = int_md_all)))

# Bootstrap options
nrep <- 1000L
msef_sim <- array(data = NA_real_, dim = c(nrep, nmd - 1L, nhv))

# Start timer...
ptm <- proc.time()

# Start bootstrap procedure...
cat("Starting bootstrap procedure to compute MSE-F empirical p-values...\n")

for (bt in seq_len(nrep)) {

    # Generate dependent variable using baseline model paramaters
    y_sim <- rnorm(n = nyt, mean = mx, sd = sx)

    # Convert to a 'ts' object so we can use window() later
    y_sim <- ts(data = y_sim, start = q_begin, frequency = y_freq)

    # Results storage
    er_mat_sim <- matrix(data = NA_real_, nrow = it_len, ncol = nmd)

    for (it in it_seq) {

        # Get indice for array access
        id <- (it - est_end_it) + 1L

        # Get estimate end point
        m_est_end <- get_year_month(m_est_seq[it * mt])
        q_est_end <- get_year_quarter(q_est_seq[it])

        # Get estimate x_t -- only 'end' gets extended
        x_est <- window(x = x_t, start = m_begin, end = m_est_end)

        # Get estimate y_sim -- only 'end' gets extended
        y_est <- window(x = y_sim, start = q_begin, end = q_est_end)

        # Get actual y -- using indexing
        y_act <- as.numeric(y_sim[seq(from = length(y_est) + 1L,
                                      to = length(y_est) + ht, length.out = 1L)])

        # Constant model (i.e. 'mean' model)
        int_md <- lm(formula = y_est ~ 1.0)
        int_fc <- predict(object = int_md,
                          newdata = data.frame(rep_len(x = ct, length.out = ht)))

        er_mat_sim[id, 1L] <- as.numeric(int_fc) - y_act

        # AR(1) model -- using base R
        ar_md <- ar(x = y_est, aic = FALSE, order.max = 1L,
                    method = "ols", demean = FALSE, intercept = TRUE)
        ar_fc <- predict(object = ar_md, n.ahead = ht)

        er_mat_sim[id, 2L] <- as.numeric(ar_fc$pred) - y_act

        # U-MIDAS forecast / nowcasting
        for (jt in 0L:mt) {

            um_md <- midas_r(formula = y_est ~ mls(x = x_est,
                             k = (k1 - jt):k2, m = mt), start = NULL) # U-MIDAS

            # Get actual x to use in nowcasting -- easier using indexing
            x_new <- x_t[seq(from = length(x_est) + 1L,
                             to = length(x_est) + jt, length.out = jt)]

            um_fc <- forecast(object = um_md,
                              newdata = list(x_est = c(x_new, rep_len(x = NA_real_, length.out = (mt - jt)))),
                              se = se_opt, level = nlevel, fan = fan_opt, npaths = npath, method = meth_opt, add_ts_info = info_opt)

            er_mat_sim[id, 3L + jt] <- as.numeric(um_fc$mean) - y_act

        }

        # Quarter-average MAI model
        xm_est <- rowMeans(mls(x = x_est, k = 0L:2L, m = mt), na.rm = TRUE)
        qa_md <- midas_r(formula = y_est ~ mls(x = xm_est, k = 0L:1L, m = 1L),
                         data = list(y_est = y_est, xm_est = xm_est), start = NULL)
        nxm <- mean(x_new, na.rm = TRUE)
        qa_fc <- forecast(object = qa_md, newdata = list(xm_est = c(nxm)),
                          se = se_opt, level = nlevel, fan = fan_opt,
                          npaths = npath, method = meth_opt, add_ts_info = info_opt)

        er_mat_sim[id, nmd] <- as.numeric(qa_fc$mean) - y_act

    }

    # Compute the simulated MSE-F statistic under the null hypothesis
    for (kt in 2L:nmd) {

        for (lt in seq_len(nhv)) {

            msef_sim[bt, kt - 1L, lt] <- ht_vec[lt] * rel_mse(f1 = tail(x = er_mat_sim[, kt],
                                                                        n = ht_vec[lt]),
                                                              f2 = tail(x = er_mat_sim[, 1L],
                                                                        n = ht_vec[lt]))
        }

    }

    if (as.double(bt) %% 100.0 == 0) {
        cat(sprintf("   Progress: -- %3.0f%% completed -- \b \r", (as.double(bt) / nrep) * 100.0))
    }

}

# Finished bootstrap procedure
cat("...Finished bootstrap procedure.\n")

# ...stop timer
fin_time <- proc.time() - ptm

cat(sprintf("Elapsed time: %3.2f minutes\n", fin_time[3L] / 60.0))

# Set array dimension names
dimnames(msef_sim) <- list(seq_len(nrep), colnames(msef_act), rownames(msef_act))

# Compute the empirical p-values -- percentage of trials in which the empirical test statistic exceeds the actual test statistic
msef_pval <- matrix(data = NA_real_, nrow = nhv, ncol = nmd - 1L)

for (it in seq_len(nhv)) {

    for (jt in seq_len(nmd - 1L)) {

        msef_pval[it, jt] <- sum(as.integer(msef_sim[ , jt, it] > msef_act[it, jt])) / nrep

    }


}

# Set the row and column names
rownames(msef_pval) <- rownames(msef_act)
colnames(msef_pval) <- colnames(msef_act)

####################################################################################################
# Print results to the console
####################################################################################################

if (print_opt) {

    # Print MSE-F to the console
    cat(sprintf("Actual MSE-F for forecast / nowcasts -- baseline model: \'%s\'\n\n", fc_mds[1L]))
    print(msef_act)
    cat('\n')

    # Print MSE-F empirical p-values to the console
    cat(sprintf("Actual MSE-F empirical p-values for forecast / nowcasts -- baseline model: \'%s\'\n\n", fc_mds[1L]))
    print(msef_pval)
    cat("\n\n")

}

####################################################################################################
# Write results to .csv files
####################################################################################################

# MSE-F test results
write.table(x = msef_act,
            file = paste0(r_location,
            sprintf("msef_gdp_q_%d_s_%d_p_%d", q, s, p), ".csv"),
            append = FALSE, quote = FALSE, sep = ',',
            row.names = TRUE, col.names = NA)

# MSE-F test empirical p-value results
write.table(x = msef_pval,
            file = paste0(r_location,
            sprintf("msef_pval_gdp_q_%d_s_%d_p_%d", q, s, p), ".csv"),
            append = FALSE, quote = FALSE, sep = ',',
            row.names = TRUE, col.names = NA)

cat(sprintf("All files written to: %s\n", r_location))

# EOF
