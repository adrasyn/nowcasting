####################################################################################################
# RDP 2024-04: Nowcasting Quarterly GDP Growth Using A Monthly Activity Indicator
####################################################################################################
# Luke Hartigan, 26-06-2023
####################################################################################################

# Clear the workspace
rm(list = ls(all = TRUE))

# Set directories
d_location <- "Data/"
f_location <- "Code/methods/"
r_location <- "Results/"

# Source required functions
source(paste0(f_location, "mai_utils.R"))       # helper functions
source(paste0(f_location, "misc_methods.R"))    # cssfed()

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

# Numerical starting and ending times
x_begin <- get_year_month(x = mth_seq[1L])
x_end <- get_year_month(x = mth_seq[nx])

y_begin <- get_year_quarter(x = qtr_seq[1L])
y_end <- get_year_quarter(x = qtr_seq[ny])

# Convert both x and y to 'ts' objects so we can use window() later on
x <- ts(data = x, start = x_begin, frequency = x_freq)
y <- ts(data = y, start = y_begin, frequency = y_freq)

# String estimation starting and ending times -- manually determined
m_begin_str <- "1978-04-01" # i.e. 1978:M4 (first month in Q2)
q_begin_str <- "1978-06-01" # i.e. 1978:Q2
ts_end_str <- qtr_seq[ny] # common ending point

pre_covid_str <- "2019-12-01"
covid_impact_str <- "2020-06-01"

# Numerical estimation starting and ending times
m_begin <- get_year_month(x = m_begin_str)
m_end <- get_year_month(x = ts_end_str)

q_begin <- get_year_quarter(x = q_begin_str)
q_end <- get_year_quarter(x = ts_end_str)

pre_covid <- get_year_quarter(x = pre_covid_str)
covid_impact <- get_year_quarter(x = covid_impact_str)

# Adjust both series to be of comparable lengths for MIDAS regression
x_t <- window(x = x, start = m_begin, end = m_end)
y_t <- window(x = y, start = q_begin, end = q_end)

nxt <- length(x_t)
nyt <- length(y_t)

# Check length(x_t) == 3 * length(y_t)
if (nxt / nyt != mt) {
    stop(sprintf("Error: length(x_t) = %d not a multiple of length(y_t) = %d\n", nxt, nyt), call. = FALSE)
}

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
npath <- 500L
meth_opt <- "static"
info_opt <- FALSE
set.seed(1025879)

####################################################################################################
# Recursively nowcast quarterly GDP growth
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

est_end_it <- 40L # i.e. ten years
it_seq <- seq(from = est_end_it, to = (nyt - ht), by = 1L)
it_len <- length(it_seq)

# Date sequences for recursive forecast / nowcast -- quarterly
q_fc_seq <- tail(x = q_est_seq, n = it_len)

# Results storage
sh <- 3L    # short-term horizon
md <- 10L   # medium-term horizon
fc_hor <- c(sprintf("Past %d-years", sh), sprintf("Past %d-years", md), "Full sample")
fc_mds <- c("Actual", "Mean", "AR(1)", "MAI-UM-FC", "MAI-UM-M1",
            "MAI-UM-M2", "MAI-UM-M3", "MAI-QA")
nfh <- length(fc_hor)
nmd <- length(fc_mds)
fc_mat <- matrix(data = NA_real_, nrow = it_len, ncol = nmd)
er_mat <- matrix(data = NA_real_, nrow = it_len, ncol = (nmd - 1L))

# Start recursive forecasting exercise...
cat("Starting Recursive Forecastinf / Nowcasting Exercise...\n")

for (it in it_seq) {

    # Get indice for array access
    id <- (it - est_end_it) + 1L

    # Print to the console what we are doing
    cat(sprintf("Forecasting / Nowcasting period: %s\n", q_fc_seq[id]))

    # Get estimate end point
    m_est_end <- get_year_month(m_est_seq[it * mt])
    q_est_end <- get_year_quarter(q_est_seq[it])

    # Get estimate x_t -- only 'end' gets extended
    x_est <- window(x = x_t, start = m_begin, end = m_est_end)

    # Get estimate y_t -- only 'end' gets extended
    y_est <- window(x = y_t, start = q_begin, end = q_est_end)

    # Get actual y -- using indexing
    y_act <- as.numeric(y_t[seq(from = length(y_est) + 1L,
                                to = length(y_est) + ht, length.out = 1L)])

    fc_mat[id, 1L] <- y_act

    # Constant model (i.e. 'mean' model)
    int_md <- lm(formula = y_est ~ 1.0)
    int_fc <- predict(object = int_md,
                      newdata = data.frame(rep_len(x = ct, length.out = ht)))
    fc1 <- as.numeric(int_fc)

    fc_mat[id, 2L] <- fc1

    # AR(1) model -- using base R
    ar_md <- ar(x = y_est, aic = FALSE, order.max = 1L,
                method = "ols", demean = FALSE, intercept = TRUE)
    ar_fc <- predict(object = ar_md, n.ahead = ht)
    fc2 <- as.numeric(ar_fc$pred)

    fc_mat[id, 3L] <- fc2

    # U-MIDAS forecast / nowcasting
    for (jt in 0L:mt) {

        um_md <- midas_r(formula = y_est ~ mls(x = x_est,
                         k = (k1 - jt):k2, m = mt), start = NULL) # U-MIDAS

        # Get actual x to use in nowcasting -- using indexing
        x_new <- x_t[seq(from = length(x_est) + 1L,
                         to = length(x_est) + jt, length.out = jt)]

        um_fc <- forecast(object = um_md,
                          newdata = list(x_est = c(x_new, rep_len(x = NA_real_, length.out = (mt - jt)))),
                          se = se_opt, level = nlevel, fan = fan_opt, npaths = npath, method = meth_opt, add_ts_info = info_opt)
        fc4 <- as.numeric(um_fc$mean)

        fc_mat[id, 4L + jt] <- fc4

    }

    # Quarter-average MAI model -- add a lag of xm to make it similar to the U-MIDAS model with 0L:5L lags (same as U-MIDAS but with equal/flat coefficients)
    xm_est <- rowMeans(mls(x = x_est, k = 0L:2L, m = mt), na.rm = TRUE)
    qa_md <- midas_r(formula = y_est ~ mls(x = xm_est, k = 0L:1L, m = 1L),
                     data = list(y_est = y_est, xm_est = xm_est), start = NULL)
    nxm <- mean(x_new, na.rm = TRUE)
    qa_fc <- forecast(object = qa_md, newdata = list(xm_est = c(nxm)),
                      se = se_opt, level = nlevel, fan = fan_opt,
                      npaths = npath, method = meth_opt, add_ts_info = info_opt)
    fc5 <- as.numeric(qa_fc$mean)

    fc_mat[id, nmd] <- fc5

}

# Finished nowcasting
cat("...Finished Forecasting / Nowcasting Exercise.\n")

# Convert to a 'ts' object
fc_mat <- ts(data = fc_mat,
             start = get_year_quarter(q_fc_seq[1L]), frequency = y_freq)

# Set the row and column names
rownames(fc_mat) <- as.character(q_fc_seq)
colnames(fc_mat) <- fc_mds

# Compute forecast error of each model: y_f - y_t
for (kt in 2L:nmd) {

    er_mat[, kt - 1L] <- as.numeric(fc_mat[, kt] - fc_mat[, 1L])

}

# Convert to a 'ts' object so we can use window()
er_mat <- ts(data = er_mat, start = start(fc_mat), frequency = y_freq)

# Set the row and column names
rownames(er_mat) <- rownames(fc_mat)
colnames(er_mat) <- colnames(fc_mat)[-1L] # Drop actual y_t

# Exclude COVID-19 period
er_mat_pc <- window(x = er_mat, start = NULL, end = pre_covid)

# COVID-19 forecast / nowcast error
covid_err <- er_mat[covid_impact_str, ]
covid_gdp <- as.numeric(window(x = y_t, start = covid_impact, end = covid_impact))
rel_covid_err <- abs(covid_err / covid_gdp)

# Compute rmses for various time periods -- includes COVID period
rmse_sh <- apply(X = tail(x = er_mat[, seq_len(nmd - 1L)], n = (sh * y_freq)),
                 MARGIN = 2L, FUN = rmse, na.rm = TRUE)

rmse_md <- apply(X = tail(er_mat[, seq_len(nmd - 1L)], n = (md * y_freq)),
                 MARGIN = 2L, FUN = rmse, na.rm = TRUE)

rmse_all <- apply(X = er_mat, MARGIN = 2L, FUN = rmse, na.rm = TRUE)

# Compute rmses for various time periods -- excludes COVID period
rmse_sh_pc <- apply(X = tail(x = er_mat_pc[, seq_len(nmd - 1L)], n = (sh * y_freq)),
                    MARGIN = 2L, FUN = rmse, na.rm = TRUE)

rmse_md_pc <- apply(X = tail(er_mat_pc[, seq_len(nmd - 1L)], n = (md * y_freq)),
                    MARGIN = 2L, FUN = rmse, na.rm = TRUE)

rmse_all_pc <- apply(X = er_mat_pc, MARGIN = 2L, FUN = rmse, na.rm = TRUE)

# Collect results into matrices for easy comparison
rmse_mat <- rbind(rmse_sh, rmse_md, rmse_all)
rmse_mat_pc <- rbind(rmse_sh_pc, rmse_md_pc, rmse_all_pc)

# Relative rmses
rel_rmse_mat <- rbind(rmse_sh[-1L] / rmse_sh[1L], rmse_md[-1L] / rmse_md[1L], rmse_all[-1L] / rmse_all[1L])
rel_rmse_mat_pc <- rbind(rmse_sh_pc[-1L] / rmse_sh_pc[1L], rmse_md_pc[-1L] / rmse_md_pc[1L], rmse_all_pc[-1L] / rmse_all_pc[1L])

# Set the row names
rownames(rmse_mat) <- rownames(rmse_mat_pc) <- rownames(rel_rmse_mat) <- rownames(rel_rmse_mat_pc) <- fc_hor

# Cumulated Sum of Squared FC Errors
min_er <- arrayInd(ind = which.min(x = rmse_mat), .dim = dim(rmse_mat))[2L] # column
max_er <- arrayInd(ind = which.max(x = rmse_mat), .dim = dim(rmse_mat))[2L] # column
cfer <- cssfed(e1 = er_mat[, max_er], e2 = er_mat[, min_er])

# Convert to a 'ts' object so we can use window()
cfer <- ts(data = cfer, start = start(er_mat), frequency = y_freq)

####################################################################################################
# Print estimation results to the console
####################################################################################################

if (print_opt) {

     # Print RMSE and relative RMSE to the console
     cat("RMSEs for forecast / nowcasts -- Include COVID-19\n")
     print(rmse_mat)
     cat('\n')
     cat("RMSEs for forecast / nowcasts -- Pre-COVID-19\n")
     print(rmse_mat_pc)
     cat('\n')
     cat(sprintf("Relative RMSEs for forecast / nowcasts (relative to \'%s\' model) -- Include COVID-19\n", colnames(rmse_mat)[1L]))
     print(rel_rmse_mat)
     cat('\n')
     cat(sprintf("Relative RMSEs for forecast / nowcasts (relative to \'%s\' model) -- Pre-COVID-19\n", colnames(rmse_mat_pc)[1L]))
     print(rel_rmse_mat_pc)
     cat('\n')

}

####################################################################################################
# Write results to .csv files
####################################################################################################

# Forecast/Nowcasts
write.table(x = fc_mat,
            file = paste0(r_location,
            sprintf("fc_nc_gdp_q_%d_s_%d_p_%d", q, s, p), ".csv"),
            append = FALSE, quote = FALSE, sep = ',',
            row.names = TRUE, col.names = NA)

# Forecast/Nowcast errors
write.table(x = er_mat,
            file = paste0(r_location,
            sprintf("er_gdp_q_%d_s_%d_p_%d", q, s, p), ".csv"),
            append = FALSE, quote = FALSE, sep = ',',
            row.names = TRUE, col.names = NA)

# Forecast/Nowcast errors -- Pre-COVID
write.table(x = er_mat_pc,
            file = paste0(r_location,
            sprintf("er_pc_gdp_q_%d_s_%d_p_%d", q, s, p), ".csv"),
            append = FALSE, quote = FALSE, sep = ',',
            row.names = TRUE, col.names = NA)

# Forecast/Nowcast error -- June 2020
write.table(x = covid_err,
            file = paste0(r_location,
            sprintf("covid_er_gdp_q_%d_s_%d_p_%d", q, s, p), ".csv"),
            append = FALSE, quote = FALSE, sep = ',',
            row.names = TRUE, col.names = NA)

# Relative Forecast/Nowcast error -- June 2020
write.table(x = rel_covid_err,
            file = paste0(r_location,
            sprintf("rel_covid_er_gdp_q_%d_s_%d_p_%d", q, s, p), ".csv"),
            append = FALSE, quote = FALSE, sep = ',',
            row.names = TRUE, col.names = NA)

# RMSE estimates
write.table(x = rmse_mat,
            file = paste0(r_location,
            sprintf("rmse_gdp_q_%d_s_%d_p_%d", q, s, p), ".csv"),
            append = FALSE, quote = FALSE, sep = ',',
            row.names = TRUE, col.names = NA)

# RMSE estimates -- Pre-COVID
write.table(x = rmse_mat_pc,
            file = paste0(r_location,
            sprintf("rmse_pc_gdp_q_%d_s_%d_p_%d", q, s, p), ".csv"),
            append = FALSE, quote = FALSE, sep = ',',
            row.names = TRUE, col.names = NA)

# Relative RMSE estimates
write.table(x = rel_rmse_mat,
            file = paste0(r_location,
            sprintf("rel_rmse_gdp_q_%d_s_%d_p_%d", q, s, p), ".csv"),
            append = FALSE, quote = FALSE, sep = ',',
            row.names = TRUE, col.names = NA)

# Relative RMSE estimates -- Pre-COVID
write.table(x = rel_rmse_mat_pc,
            file = paste0(r_location,
            sprintf("rel_rmse_pc_gdp_q_%d_s_%d_p_%d", q, s, p), ".csv"),
            append = FALSE, quote = FALSE, sep = ',',
            row.names = TRUE, col.names = NA)

cat(sprintf("All files written to: %s\n", r_location))

# EOF
