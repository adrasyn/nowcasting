####################################################################################################
# RDP 2024-04: Nowcasting Quarterly GDP Growth Using A Monthly Activity Indicator
####################################################################################################
# Luke Hartigan, 28-04-2023
####################################################################################################

# Clear the workspace
rm(list = ls(all = TRUE))

# Set directories
d_location <- "Data/"
f_location <- "Code/methods/"
r_location <- "Results/"

# Source required functions
source(paste0(f_location, "misc_methods.R"))     # mixed freq lags
source(paste0(f_location, "mai_utils.R"))        # helper functions

# Set up a few options
options(digits = 4)
print_opt <- TRUE

# What are we doing?
cat("Quarterly GDP growth time series properties...\n")

####################################################################################################
# Helper function
####################################################################################################

# # Gets confidence interval data from acf object `x`
# Source: https://stackoverflow.com/questions/14266333/extract-confidence-interval-values-from-acf-correlogram
get_acf_ci <- function(x, ci = 0.95, ci.type = c("white", "ma"))
{
    # Preliminary checks
    if (class(x) != "acf") {
        stop("get_acf_ci(): object \'x'\ not of  class \'acf\'\n", call. = FALSE)
    }

    # Get the c.i. type
    ci.type = match.arg(ci.type)

    # iid value
    ci0 <- qnorm(p = (1 + ci) * 0.5) / sqrt(x$n.used)

    if (ci.type == "ma") {
        ci <- ci0 * sqrt(cumsum(c(1, 2 * drop(x$acf)[-1L]^2)))
        ci <- ci[-length(ci)]
    } else {
        ci <- ci0
    }

    return (ci)

}

####################################################################################################
# Read in all data for analysis
####################################################################################################

# Date format
ydate_fmt <- "%d/%m/%Y"

# Set some time series values
y_freq_str <- "quarter"
y_freq <- 4

# Read in 'Real-time' GDP series (already a quarterly growth rate)
qtr_infile <- "rt_dgdp_qtr.csv"
qtr_data <- read.csv(paste0(d_location, qtr_infile), header = TRUE, sep = ',')
qtr_seq <- as.Date(x = qtr_data[, 1L], format = ydate_fmt)
y <- qtr_data[, -1L] # drop dates column
ny <- length(y)

# Numerical starting and ending times
y_begin <- get_year_quarter(x = qtr_seq[1L])
y_end <- get_year_quarter(x = qtr_seq[ny])

# Convert all series to 'ts' objects so we can use window() later on
y <- ts(data = y, start = y_begin, frequency = y_freq)

# String time series for common starting and ending times
q_begin_str <- "1978-03-01" # i.e. 1978:Q1 (using one lag will give us 1978:Q2)
q_end_str <- qtr_seq[ny] # common ending point

# Numerical estimation starting and ending times
q_begin <- get_year_quarter(x = q_begin_str)
q_end <- get_year_quarter(x = q_end_str)

# Date sequences for recursive estimation -- quarterly
ts_seq <- seq(from = as.Date(q_begin_str),
              to = as.Date(q_end_str), by = y_freq_str)

# Adjust all series to be of comparable lengths for OLS using mf_lag()
y_t <- window(x = y, start = q_begin, end = q_end)

####################################################################################################
# Setup recursive regression models
####################################################################################################

# Setup data
p <- 1L
yyt <- embed(x = y_t, dimension = (1L + p))

nobs <- dim(yyt)[1L]
nvar <- dim(yyt)[2L]

# ACF/PACF for qaurterly GDP Growth
nlag <- 12L

acf_y <- acf(x = yyt[, 2L], lag.max = nlag, plot = FALSE)
pacf_y <- pacf(x = yyt[, 2L], lag.max = nlag, plot = FALSE)

# Get actual values
acf_val <- drop(acf_y$acf)[-1L] # drop first acf which is 1 by definition
pacf_val <- drop(pacf_y$acf)

# Get confidence intervals
ci_opt <- 0.95
ci_type <- "white"

acf_ci <- get_acf_ci(x = acf_y, ci = ci_opt, ci.type = ci_type)
pacf_ci <- get_acf_ci(x = pacf_y, ci = ci_opt, ci.type = ci_type)

# Collect results for saving to disk

acf_data <- cbind(acf_val, -acf_ci, acf_ci)
rownames(acf_data) <- seq_len(nlag)
colnames(acf_data) <- c("ACF", "LB", "UB.")

pacf_data <- cbind(pacf_val, -pacf_ci, pacf_ci)
rownames(pacf_data) <- seq_len(nlag)
colnames(pacf_data) <- c("PACF", "LB", "UB.")

####################################################################################################
# Write results to .csv files
####################################################################################################

# ACF -- GDP
write.table(x = acf_data,
            file = paste0(r_location, "acf_gdp", ".csv"),
            append = FALSE, quote = FALSE, sep = ',',
            row.names = TRUE, col.names = NA)

# PACF -- GDP
write.table(x = pacf_data,
            file = paste0(r_location, "pacf_gdp", ".csv"),
            append = FALSE, quote = FALSE, sep = ',',
            row.names = TRUE, col.names = NA)

cat(sprintf("All files written to: %s\n", r_location))

# EOF
