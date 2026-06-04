####################################################################################################
# RDP 2024-04: Nowcasting Quarterly GDP Growth Using A Monthly Activity Indicator
####################################################################################################
# Luke Hartigan, 20-06-2023
####################################################################################################

# Clear the workspace
rm(list = ls(all = TRUE))

# Set directories
d_location <- "Data/"
f_location <- "Code/methods/"
r_location <- "Results/"

# Source required functions
source(paste0(f_location, "qmle_dfm_methods.R"))    # Lag of factor(s) in measurement eqn
source(paste0(f_location, "mai_utils.R"))           # helper functions
source(paste0(f_location, "misc_methods.R"))        # long_run_var()

# Set up a few options
options(digits = 4)

# What are we doing?
cat("MAI COVID-19 robustness analysis...\n")

####################################################################################################
# Read in the data -- already transformed and conditionally standardised (tfs)
####################################################################################################

# Monthly indicator name
idx_name <- "MAI"
idx_long_name <- "Monthly Activity Indicator"

# Date format
date_fmt <- "%Y-%m-%d"

# Set some time series values
ts_end_str <- "2020-02-01" # before COVID-19
ts_freq_str <- "month"
ts_freq <- 12

# Estimation options used to estimate monthly indicator -- manually determined
q <- 1L # no. dynamic factors
s <- 2L # no. dynamic loadings in filter
p <- 1L # no. AR terms in VAR

# Load the previously estimated monthly indicator series
x_infile <- sprintf("rt_%s_q_%d_s_%d_p_%d_rdp.csv", tolower(idx_name), q, s, p) # real-time mai
x_data <- read.csv(paste0(d_location, x_infile), header = TRUE, sep = ',')
x_seq <- as.Date(x = x_data[, 1L], format = date_fmt)
x <- x_data[, -1L] # drop dates column
nx <- length(x)

# Numerical starting and ending times
ts_begin <- get_year_month(x = x_seq[1L])
ts_end <- get_year_month(x = ts_end_str)

# Load transformed (tf) and conditionally standardised (s) dataset
data_file <- sprintf("%s_data_tfs.csv", tolower(idx_name))
mai_data <- read.csv(paste0(d_location, data_file), header = TRUE, sep = ',')
ts_seq <- as.Date(x = mai_data[, 1L], format = date_fmt)
panel <- mai_data[, -1L, drop = FALSE] # drop dates column

# Targeted Predictors (tp) list
tp_file <- sprintf("%s_tp_list.csv", tolower(idx_name))
tp_series <- scan(file = paste0(d_location, tp_file),
                  what = "character", quiet = TRUE)

# Get targeted predictor series -- new panel
y <- panel[, tp_series, drop = FALSE]

# Category codes
info <- read.csv(paste0(d_location,
                 sprintf("%s_info.csv", tolower(idx_name))),
                 header = TRUE, sep = ',', row.names = 1L)

tgroup <- info["tgroup", tp_series, drop = FALSE]

# Convert to a 'ts' object so we can use window() later on
x <- ts(data = x, start = ts_begin, frequency = ts_freq)
y <- ts(data = y, start = ts_begin, frequency = ts_freq)

# Remove COVID-19 period
y_t <- window(x = y, start = NULL, end = ts_end)

####################################################################################################
# Setup QMLE-DFM model
####################################################################################################

# How to handle NAs in the dataset?
na_opt <- "exclude"

# QMLE-DFM estimation options
q <- 1L                 # Number of dynamic factors
s <- 2L                 # Number of lags in the loadings filter
p <- 1L                 # Number of lags in the factor VAR
id_opt <- "DFM2"        # The q x q block of L is lower triangular with 1s on the
scale_opt <- FALSE      # Already standardised
sign_opt <- FALSE       # Shouldn't be needed if named factor id is working right
max_iter <- 500L
threshold <- 1E-4       # Not too strict!!
check_increased <- TRUE
verbose <- TRUE

# MAI -- QMLE-DFM Estimation -- Pre-COVID-19
dfm <- qmle_dfm(x = y_t, q = q, s = s, p = p,
                id_opt = id_opt, scale_opt = scale_opt, na_opt = na_opt,
                sign_opt = sign_opt, max_iter = max_iter, threshold = threshold,
                check_increased = check_increased, verbose = verbose)

# Real-time factor estimate -- Full sample but using pre-COVID-19 parmaeter estimates
rt_dfm <- real_time_factor(x = y, q = q, s = s, p = p,
                           params = dfm$parameters, scale_opt = scale_opt)

# Get real-time MAI
rt_mai <- rt_dfm$factors[, 1L, drop = FALSE]

# Convert to 'ts' objects
rt_mai <- ts(data = rt_mai, start = start(y), frequency = frequency(y))

# Give the series row and column names
rownames(rt_mai) <- as.character(x_seq)
colnames(rt_mai) <- paste("RT", idx_name, sep = '_')

# Compute differential
err <- x - rt_mai

# Convert to a 'ts' object so we can use window() later on
err <- ts(data = err, start = ts_begin, frequency = ts_freq)

# Remove COVID-19 period
err_t <- window(x = err, start = NULL, end = ts_end)

# Compute RMSE of the difference between MAI using full sample params and MAI using Pre-COVID-19 params
delta_fs <- rmse(x = err)
delta_pc <- rmse(x = err_t)

# Print result to the console
cat("Difference between MAI using parameters estimated from full sample and \nMAI using parameters estimated from pre-COVID-19 sample\n")
cat(sprintf("The RMSE between the two MAIs (Full sample) is %g\n", delta_fs))
cat(sprintf("The RMSE between the two MAIs (Pre-COVID) is %g\n", delta_pc))
cat('\n')

# Is the MSE (FS) statistically significantly different from zero?
er_sq <- err * err
mx <- mean(er_sq)
vx <- long_run_var(x = (er_sq - mx), nlag = 1L)
dmt <- mx / sqrt(vx)
pval <- 2.0 * pnorm(q = abs(dmt), lower.tail = FALSE)

cat("MSE (FS) test of statistical significance:\n")
cat(sprintf("Statistic: %g\tp-value: %g\n\n", dmt, pval))

####################################################################################################
# Write results to .csv files
####################################################################################################

# Alternative Real-time MAI estimated with parameters using pre-COVID-19 sample
write.table(x = rt_mai,
            file = paste0(r_location, sprintf("rt_%s_pre_covid", tolower(idx_name)), ".csv"),
            append = FALSE, quote = FALSE, sep = ',', row.names = TRUE, col.names = NA)

cat(sprintf("All files written to: %s\n", r_location))

# EOF
