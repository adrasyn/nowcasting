####################################################################################################
# RDP 2024-04: Nowcasting Quarterly GDP Growth Using A Monthly Activity Indicator
####################################################################################################
# Luke Hartigan, 27-04-2023
####################################################################################################

# Clear the workspace
rm(list = ls(all = TRUE))

# Set directories
d_location <- "Data/"
f_location <- "Code/methods/"
r_location <- "Results/"

# Source required functions
source(paste0(f_location, "mai_utils.R"))        # helper function
source(paste0(f_location, "misc_methods.R"))     # mixed freq lags

# Load the required libraries
suppressMessages(library("zoo"))
suppressMessages(library("midasr"))

# Set up a few options
options(digits = 4)
print_opt <- TRUE

# What are we doing?
cat("Determining the best MIDAS specification for modelling quarterly GDP growth using a monthly activity indicator...\n")

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

# Numerical estimation starting and ending times
m_begin <- get_year_month(x = m_begin_str)
m_end <- get_year_month(x = ts_end_str)

q_begin <- get_year_quarter(x = q_begin_str)
q_end <- get_year_quarter(x = ts_end_str)

# Adjust both series to be of comparable lengths for MIDAS regression
x_t <- window(x = x, start = m_begin, end = m_end)
y_t <- window(x = y, start = q_begin, end = q_end)

nxt <- length(x_t)
nyt <- length(y_t)

# Check length(y_t) == 3*length(x_t)
if (nxt / nyt != mt) {
    stop(sprintf("Error: length(x_t) = %d not a multiple of length(y_t) = %d\n", nxt, nyt), call. = FALSE)
}

####################################################################################################
# Setup MIDAS regression models
####################################################################################################

# Functional constraint and number of parameters selection based on information criterion
mt <- x_freq / y_freq
nealmon2 <- nealmon # 2 params
nealmon3 <- nealmon # 3 params
opt_fn <- "optim"
opt_meth <- "BFGS"
ic_opt <- "BIC"
test_opt <- "hAhr_test"

# Set of different functional constraints to evaluate
set_x <- expand_weights_lags(weights = c("nealmon2", "nealmon3", "nbeta"),
                             from = 0L, to = c(2L, 5L), m = 1L,
                             start = list(nealmon2 = c(1.0, -1.0),
                                          nealmon3 = c(1.7, 0.5, -1.0),
                                          nbeta = c(1.7, 1.0, 2.0)))

# Determine the optimal MIDAS model specification
mods <- midas_r_ic_table(y_t ~ mls(x_t, 0L, mt),
                         data = list(y_t = y_t, x_t = x_t),
                         table = list(x_t = set_x),
                         IC = c(ic_opt), test = c(test_opt),
                         Ofunction = opt_fn, method = opt_meth)

# Get models and IC (restricted and unrestricted) to save to disk
mod_ic <- mods$table

# Best model based on Information Criterion
cat("Restricted MIDAS Models:\n")
mdr_ic <- modsel(x = mods, IC = ic_opt, type = "restricted")     # R-MIDAS
cat('\n')

cat("Unrestricted MIDAS Models:\n")
mdu_ic <- modsel(x = mods, IC = ic_opt, type = "unrestricted")   # U-MIDAS
cat('\n')

# Estimate 'best' MIDAS model based on IC and get fitted values
# R-MIDAS model options based on BIC
kr1 <- 0L # begin lag
kr2 <- 2L # end lag based on IC for restricted MIDAS
wts_fn <- nealmon
wts_grad <- nealmon_gradient
wts_params <- c(1.0, -1.0) # with 3 lags BIC suggests 2 params is optimal

# Restricted MIDAS model (mdr)
mdr <- midas_r(y_t ~ mls(x_t, kr1:kr2, mt, wts_fn),
               start = list(x_t = wts_params),
               weight_gradients = list(wts_fn = wts_grad),
               data = list(y_t = y_t, x_t = x_t),
               Ofunction = opt_fn, method = opt_meth)

# U-MIDAS model options based on BIC
ku1 <- 0L
ku2 <- 4L

# Unrestricted MIDAS model (mdu)
mdu <- midas_r(y_t ~ mls(x_t, ku1:ku2, mt), start = NULL,
               data = list(y_t = y_t, x_t = x_t))

# Fitted values
y_r <- as.matrix(predict(mdr))
y_u <- as.matrix(predict(mdu))

missr <- length(y_t) - length(y_r)
missu <- length(y_t) - length(y_u)

# Convert to ts objects
y_rt <- ts(data = as.matrix(x = c(rep_len(NA_real_, length.out = missr), y_r)),
           end = q_end, frequency = y_freq)
y_ut <- ts(data = as.matrix(x = c(rep_len(NA_real_, length.out = missu), y_u)),
           end = q_end, frequency = y_freq)

# Set the row and column names
rownames(y_rt) <- as.character(seq(from = as.Date(q_begin_str),
                                   to = as.Date(ts_end_str), by = y_freq_str))
colnames(y_rt) <- paste0(idx_name, "_RM")

rownames(y_ut) <- as.character(seq(from = as.Date(q_begin_str),
                                   to = as.Date(ts_end_str), by = y_freq_str))
colnames(y_ut) <- paste0(idx_name, "_UM")

# Compute R-squared statistic and root mean squared error
rsq_r <- rsq(y_rt, y_t)
rsq_u <- rsq(y_ut, y_t)

rmse_r <- rmse(y_t - y_rt)
rmse_u <- rmse(y_t - y_ut)

####################################################################################################
# Print estimation results to the console
####################################################################################################

if (print_opt) {

    # Which is fit is more accurate (on average)?
    cat("\n------------------------------------------\n")
    cat("GDP Nowcast Historical Accuracy Comparison\n\n")
    cat(sprintf("Sample period: %d:Q%d -- %d:Q%d\n\n", q_begin[1L], q_begin[2L], q_end[1L], q_end[2L]))
    cat("Root Mean Squared Error\n")
    cat(sprintf("%s (R-MIDAS):                        %2.2f\n", idx_name, rmse_r))
    cat(sprintf("%s (U-MIDAS):                        %2.2f\n\n", idx_name, rmse_u))
    cat("R-squared Statistic\n")
    cat(sprintf("%s (R-MIDAS):                        %2.2f\n", idx_name, rsq_r))
    cat(sprintf("%s (U-MIDAS):                        %2.2f\n", idx_name, rsq_u))
    cat("------------------------------------------\n\n")

}

####################################################################################################
# Write results to .csv files
####################################################################################################

# Model ICs
write.table(x = mod_ic,
            file = paste0(r_location,
            sprintf("midas_model_list_ic_%s_tp", ic_opt), ".csv"),
            append = FALSE, quote = FALSE, sep = ',',
            row.names = TRUE, col.names = NA)

# Fitted quarterly activity indicator -- R-MIDAS
write.table(x = y_rt,
            file = paste0(r_location,
            sprintf("y_rm_q_%d_s_%d_p_%d_tp", q, s, p), ".csv"),
            append = FALSE, quote = FALSE, sep = ',',
            row.names = TRUE, col.names = NA)

# Fitted quarterly activity indicator -- U-MIDAS
write.table(x = y_ut,
            file = paste0(r_location,
            sprintf("y_um_q_%d_s_%d_p_%d_tp", q, s, p), ".csv"),
            append = FALSE, quote = FALSE, sep = ',',
            row.names = TRUE, col.names = NA)

cat(sprintf("All files written to: %s\n", r_location))

# EOF
