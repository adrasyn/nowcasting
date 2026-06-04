####################################################################################################
# RDP 2023-0x: A Monthly Indicator Useful for Nowcasting Quarterly GDP Growth
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
source(paste0(f_location, "qmle_dfm_methods.R")) # Lag of factor(s) in measurement eqn
source(paste0(f_location, "lm_hac_methods.R"))   # Regression and Wald statistic
source(paste0(f_location, "mai_utils.R"))        # helper functions
source(paste0(f_location, "misc_methods.R"))     # mixed freq lags

# Set up a few options
options(digits = 4)
print_opt <- TRUE

# What are we doing?
cat("Constructing a dataset of targeted predictors...\n")

####################################################################################################
# Read in all data for analysis
####################################################################################################

# Monthly indicator name
idx_name <- "MAI"
idx_long_name <- "Monthly Activity Indicator"

# Date format
xdate_fmt <- "%d/%m/%Y"
ydate_fmt <- "%d/%m/%Y"

# Set some time series values
x_freq_str <- "month"
y_freq_str <- "quarter"

x_freq <- 12
y_freq <- 4

# High frequency ratio
mt <- x_freq / y_freq

# Load transformed (tf) and conditionally standardised (s) panel of monthly partial indicators
mth_infile <- sprintf("%s_data_tfs.csv", tolower(idx_name))
mth_data <- read.csv(paste0(d_location, mth_infile), header = TRUE, sep = ',')
mth_seq <- as.Date(x = mth_data[, 1L], format = xdate_fmt)
x <- mth_data[, -1L, drop = FALSE] # drop dates column
nx <- dim(x)[1L]

# Read in 'Real-time' GDP series (already a quarterly growth rate) to use in the MIDAS regressions
qtr_infile <- "rt_dgdp_qtr.csv"
qtr_data <- read.csv(paste0(d_location, qtr_infile), header = TRUE, sep = ',')
qtr_seq <- as.Date(x = qtr_data[, 1L], format = ydate_fmt)
y <- qtr_data[, -1L] # drop dates column
ny <- length(y)

# Read in quarterly intervention dummies
id_infile <- "qtr_int.csv"
id_data <- read.csv(paste0(d_location, id_infile), header = TRUE, sep = ',')
id_seq <- as.Date(x = id_data[, 1L], format = ydate_fmt)
id <- id_data[, -c(1L, 2L)] # drops dates and 'Target' columns
ni <- dim(id)[1L]

# Read in informaiton about dataset
info <- read.csv(paste0(d_location,
                 sprintf("%s_info.csv", tolower(idx_name))),
                 header = TRUE, sep = ',', row.names = 1L)

long_names <- info["longname", ]

# Numerical starting and ending times
x_begin <- get_year_month(x = mth_seq[1L])
x_end <- get_year_month(x = mth_seq[nx])

y_begin <- get_year_quarter(x = qtr_seq[1L])
y_end <- get_year_quarter(x = qtr_seq[ny])

i_begin <- get_year_quarter(x = id_seq[1L])
i_end <- get_year_quarter(x = id_seq[ni])

# Convert all series to 'ts' objects so we can use window() later on
x <- ts(data = x, start = x_begin, frequency = x_freq)
y <- ts(data = y, start = y_begin, frequency = y_freq)
id <- ts(data = id, start = i_begin, frequency = y_freq)

# String time series for common starting and ending times
m_begin_str <- "1978-04-01" # i.e. 1978:M4 (first month in Q2)
q_begin_str <- "1978-06-01" # i.e. 1978:Q2
ts_end_str <- qtr_seq[ny] # common ending point

# Numerical estimation starting and ending times
m_begin <- get_year_month(x = m_begin_str)
m_end <- get_year_month(x = ts_end_str)

q_begin <- get_year_quarter(x = q_begin_str)
q_end <- get_year_quarter(x = ts_end_str)

# Adjust all series to be of comparable lengths for OLS using mf_lag()
x_t <- window(x = x, start = m_begin, end = m_end)
y_t <- window(x = y, start = q_begin, end = q_end)
id_t <- window(x = id, start = q_begin, end = q_end)

nxt <- dim(x_t)[1L]
nyt <- length(y_t)
nit <- dim(id_t)[1L]

# Check length(y_t) == dim(id_t)[1L]
if (nyt != nit) {
    stop(sprintf("Error: length(id_t) = %d not equal to length(y_t) = %d\n", nit, nyt), call. = FALSE)
}

# Check dim(x_t)[1L] == 3 * length(y_t)
if (nxt / nyt != mt) {
    stop(sprintf("Error: length(x_t) = %d not a multiple of length(y_t) = %d\n", nxt, nyt), call. = FALSE)
}

####################################################################################################
# Setup OLS regression models
####################################################################################################

# lm_hac() estimation options -- Forecast error residuals
int <- TRUE
kern <- "QS"
res <- "EH"
dbw <- FALSE
dft <- TRUE

# mf_lag() options: 3 mths in current quarter
k1 <- 0L # begin lag
k2 <- 2L # end lag

# Impulse Indicator 'saturation' analysis of GDP growth for COVID-19 outlier(s)
# Find the indices for statistically significant impulse indicators
alpha <- 0.01

# Using 'lm_hac' and HAC standard errors
ism <- lm_hac(y = y_t, x = id_t,  intercept = int, kern_opt = kern,
              res_opt = res, dbw_opt = dbw, df_correct = dft)
ix <- as.integer(which(ism$pvalue[-1L] < alpha)) # exclude intercept

# Wald test options
jn <- length(k1:k2) # i.e. everything except the intercept and impulse indicators
qvec <- matrix(data = rep_len(x = 0.0, length.out = jn), nrow = jn)
rmat <- cbind(qvec, diag(x = 1.0, nrow = jn),
              repmat(mat = qvec, m = 1L, n = length(ix)))

# Results storage
nvars <- dim(x_t)[2L]
results <- zeros(nvars, 3L)
rownames(results) <- colnames(x_t)
colnames(results) <- c("Stat", "Pval", "Rsq") # No need to consider AIC as same number of params in each regression

# Loop over each variable...
for (i in seq_len(nvars)) {

    # ...Covert monthly series to 3 quarterly series with order: M3, M2, M1...
    xm_t <- mf_lag(x = x_t[, i], k = k1:k2, m = mt)

    # ...Find any missing observations...
    ok <- complete.cases(y_t, xm_t, id_t)

    # ...Estimate the model by OLS with HAC std errs...
    mod <- lm_hac(y = y_t[ok], x = cbind(xm_t[ok,], id_t[ok, ix]), intercept = int,
                  kern_opt = kern, res_opt = res, dbw_opt = dbw, df_correct = dft)

    # ...Conduct joint test that all coefficients related to ith series are zero...
    wt <- wald_test(x = mod, rmat = rmat, qvec = qvec)

    # ...Save estimation results for each series
    results[i, ] <- c(wt$statistic, wt$pvalue, mod$rsq)

}

# Metrics for ranking series in the panel
s1 <- colnames(results)[1L]
s2 <- colnames(results)[3L]

# Compute threshold value based on alpha for Chi-square[jn](alpha) distribution
alpha <- 0.1 # less restrictive value than used for IIS analysis
threshold <- qchisq(p = alpha, df = jn, lower.tail = FALSE)
tp <- results[, s1] >= threshold
ntp <- sum(as.integer(tp))

# Compute ordered indices based on the magintude of different metrics
iw <- order(x = results[, s1], decreasing = TRUE)
ir <- order(x = results[, s2], decreasing = TRUE)

# Compute ordered results based on the different metrics considered
ranked_ws <- results[iw, , drop = FALSE]
ranked_r2 <- results[ir, , drop = FALSE]

####################################################################################################
# Print list of targeted predictors to the console
####################################################################################################

if (print_opt) {

    # Print a message to the console
    cat("Targeted predictors:\n")
    cat(sprintf("Chi-squared[df = %d](alpha = %g) threshold = %g\n", jn, alpha, threshold))
    cat(sprintf("The number of series with Wald statistic greater than threshold = %d\n", ntp))
    cat("The series identified include:\n")
    print(rownames(results[tp, , drop = FALSE][seq_len(ntp), ]))
    cat('\n')

}

####################################################################################################
# Write results to .csv files
####################################################################################################

# MAI dataset sorted by Wald statistic
write.table(x = ranked_ws,
            file = paste0(r_location,
            sprintf("%s_ranked_data_ws", tolower(idx_name)), ".csv"),
            append = FALSE, quote = FALSE, sep = ',',
            row.names = TRUE, col.names = NA)

# MAI dataset sorted by R-squared statistic
write.table(x = ranked_r2,
            file = paste0(r_location,
            sprintf("%s_ranked_data_r2", tolower(idx_name)), ".csv"),
            append = FALSE, quote = FALSE, sep = ',',
            row.names = TRUE, col.names = NA)

# MAI targeted predictors variable list (sorted by Wald statistic)
write.table(x = rownames(ranked_ws)[seq_len(ntp)],
            file = paste0(r_location,
            sprintf("%s_tp_list", tolower(idx_name)), ".csv"),
            append = FALSE, quote = FALSE, sep = ',',
            row.names = FALSE, col.names = FALSE)

cat(sprintf("All files written to: %s\n", r_location))

# EOF
