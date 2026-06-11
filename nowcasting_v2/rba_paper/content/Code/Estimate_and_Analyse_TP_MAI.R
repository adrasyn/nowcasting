####################################################################################################
# RDP 2024-04: Nowcasting Quarterly GDP Growth Using A Monthly Activity Indicator
####################################################################################################
# Luke Hartigan, 19-06-2023
####################################################################################################

# Clear the workspace
rm(list = ls(all = TRUE))

# Set directories
d_location <- "Data/"
f_location <- "Code/methods/"
r_location <- "Results/"

# Source required functions
source(paste0(f_location, "qmle_dfm_methods.R")) # Lag of factor(s) in measurement eqn
source(paste0(f_location, "mai_utils.R"))        # helper functions

# Set up a few options
options(digits = 4)

# What are we doing?
cat("Estimate and Analyse the Monthly Composite Activity Indicator for Australia...\n")

####################################################################################################
# Read in the data -- already transformed and conditionally standardised (tfs)
####################################################################################################

# Monthly indicator name
idx_name <- "MAI"
idx_long_name <- "Monthly Activity Indicator"

# Date format
date_fmt <- "%d/%m/%Y"

# Set some time series values
ts_freq_str <- "month"
ts_freq <- 12

# Load transformed (tf) and conditionally standardised (s) dataset
data_file <- sprintf("%s_data_tfs.csv", tolower(idx_name))
mai_data <- read.csv(paste0(d_location, data_file), header = TRUE, sep = ',')
ts_seq <- as.Date(x = mai_data[, 1L], format = date_fmt)
panel <- mai_data[, -1L, drop = FALSE] # drop dates column

# Numerical starting time
ts_begin <- get_year_month(x = ts_seq[1L])

# Targeted Predictors (tp) list
tp_file <- sprintf("%s_tp_list.csv", tolower(idx_name))
tp_series <- scan(file = paste0(d_location, tp_file),
                  what = "character", quiet = TRUE)

# Get targeted predictor series -- new panel
y <- panel[, tp_series, drop = FALSE]

# Convert y to a 'ts' object so we can use window() later on
y <- ts(data = y, start = ts_begin, frequency = ts_freq)

# Category codes
info <- read.csv(paste0(d_location,
                 sprintf("%s_info.csv", tolower(idx_name))),
                 header = TRUE, sep = ',', row.names = 1L)

tgroup <- info["tgroup", tp_series, drop = FALSE]

# Long names
long_names <- info["longname", tp_series, drop = FALSE]

####################################################################################################
# Dataset by main category
####################################################################################################

# Compute the number of series for each category
group_names <- c('H', 'S', 'F')
long_group_names <- c("Hard", "Soft", "Financial")
ngroups <- length(group_names)
series_counts <- !is.na(y)

# Results storage
num_series_cat <- zeros(dim(y)[1L], ngroups)

for (i in seq_len(ngroups)) {
    num_series_cat[,i] <- as.matrix(rowSums(x = series_counts[, which(tgroup == group_names[i]), drop = FALSE]))
}

# Give the rows and columns useful names
colnames(num_series_cat) <- long_group_names
rownames(num_series_cat) <- as.character(ts_seq)

####################################################################################################
# Setup factor models
####################################################################################################

# MAI -- Cross-sectional mean
fac_mu <- rowMeans(x = y, na.rm = TRUE)

# How to handle NAs in the dataset?
na_opt <- "exclude"     # Remove NAs

# Remove NA and estimate the number of factors in the panel using the modified Bai & Ng (2002) IC
yna <- remove_na_values(x = y, na_opt = na_opt)

# PC Factor estimation options
r <- 1L
norm_opt <- "LN"
scale_opt <- FALSE      # Already standardised
sign_opt <- TRUE
vardec_opt <- FALSE     # We don't want the explained variation of each factor

# MAI -- PC Estimation
sfm <- pc_factor(x = yna, r = r, norm_opt = norm_opt, scale_opt = scale_opt,
                 sign_opt = sign_opt, vardec_opt = vardec_opt)

#fac_pc <- sfm$factors
na_end <- max(apply(X = y, MARGIN = 2,
                    FUN = function(x, n) { sum(is.na(tail(x, n))) }, n = 10L)) # Should not be more than 10!
fac_pc <- as.matrix(x = c(rep_len(x = NA_real_, length.out = (dim(y)[1L] - dim(yna)[1L] - na_end)),
                          sfm$factors, rep_len(x = NA_real_, length.out = na_end)), ncol = 1L) # Accounts for missing obs, *** manually determined ***
lam_pc <- sfm$loadings

# QMLE-DFM estimation options
q <- 1L                 # Number of dynamic factors
s <- 2L                 # Number of lags in the loadings filter
p <- 1L                 # Number of lags in the factor VAR
id_opt <- "DFM2"        # The q x q block of L is an Identity matrix
sign_opt <- FALSE       # Shouldn't be needed if named factor id is working right
max_iter <- 500L
threshold <- 1E-4       # Not too strict!!
check_increased <- TRUE
verbose <- TRUE

# MAI -- QMLE-DFM Estimation
dfm <- qmle_dfm(x = y, q = q, s = s, p = p,
                id_opt = id_opt, scale_opt = scale_opt, na_opt = na_opt,
                sign_opt = sign_opt, max_iter = max_iter, threshold = threshold,
                check_increased = check_increased, verbose = verbose)

# AIC for model comparison
aic <- dfm$aic
cat(sprintf("The AIC for the DFM (q = %d; s = %d; p = %d) is %g\n",
            q, s, p, aic))

# Extract dfm outputs
fac_em <- dfm$factors
fac_se <- dfm$factor_se
lam_em <- dfm$loadings

# Real-time factor estimate
rt_dfm <- real_time_factor(x = y, q = q, s = s, p = p,
                           params = dfm$parameters, scale_opt = scale_opt)
rt_fac <- rt_dfm$factors
rt_fac_se <- rt_dfm$factor_se

# Compute the decomposition of the MAI by data category
decomp <- factor_decomposition(x = y, q = q, s = s, p = p, params = dfm$parameters,
                               scale_opt = scale_opt)[, , 1L] # First slice only

# Decomposition and cross-section standard deviation results storage
decomp_by_cat <- zeros(dim(y)[1L], ngroups)
sd_by_cat <- zeros(dim(y)[1L], ngroups)

for (i in seq_len(ngroups)) {

    decomp_by_cat[, i] <- as.matrix(x = rowSums(x = decomp[, which(tgroup == group_names[i]), drop = FALSE],
                                    na.rm = TRUE))
    sd_by_cat[, i] <- as.matrix(x = apply(X = y[, which(tgroup == group_names[i]), drop = FALSE],
                                MARGIN = 1L, FUN = sd, na.rm = TRUE))

}

# Get the aggregate for all categories
decomp_total <- rowSums(x = decomp_by_cat, na.rm = TRUE)
sd_total <- as.matrix(x = apply(X = y, MARGIN = 1L, FUN = sd, na.rm = TRUE))

# Convert to 'ts' objects
fac_mu <- ts(data = fac_mu, start = start(y), frequency = frequency(y))
fac_pc <- ts(data = fac_pc, start = start(y), frequency = frequency(y))
fac_em <- ts(data = fac_em, start = start(y), frequency = frequency(y))
rt_fac <- ts(data = rt_fac, start = start(y), frequency = frequency(y))

# Get MAI -- Cross-sectional mean (robustness check)
mai_mu <- as.matrix(fac_mu)
rownames(mai_mu) <- as.character(ts_seq)
colnames(mai_mu) <- paste(idx_name, "MU", sep = '_')

# Get MAI -- SFM (i.e. PCA)
mai_pc <- fac_pc
rownames(mai_pc) <- as.character(ts_seq)
colnames(mai_pc) <- paste(idx_name, "PC", sep = '_')

# Get MAI -- DFM
mai <- fac_em[, 1L, drop = FALSE]
rownames(mai) <- as.character(ts_seq)
colnames(mai) <- idx_name

mai_se <- fac_se[, 1L, drop = FALSE]
rownames(mai_se) <- as.character(ts_seq)
colnames(mai_se) <- paste(idx_name, "SE", sep = '_')

# Get real-time MAI
rt_mai <- rt_fac[, 1L, drop = FALSE]
rownames(rt_mai) <- as.character(ts_seq)
colnames(rt_mai) <- paste("RT", idx_name, sep = '_')

rt_mai_se <- rt_fac_se[, 1L, drop = FALSE]
rownames(rt_mai_se) <- as.character(ts_seq)
colnames(rt_mai_se) <- paste("RT", idx_name, "SE", sep = '_')

# Get MAI variable weights (factor loadings)
mai_wts <- cbind(lam_em, rowSums(lam_em))
ttl <- "Total"
colnames(mai_wts) <- c(colnames(lam_em), ttl)

# Get the MAI decomposition/contribution by data category
mai_decomp <- cbind(decomp_total, decomp_by_cat)
mai_decomp <- ts(data = mai_decomp, start = start(y), frequency = frequency(y))
rownames(mai_decomp) <- as.character(ts_seq)
colnames(mai_decomp) <- c(ttl, long_group_names)

# Get the cross-sectional standard deviation by data category
mai_cs_sd <- cbind(sd_total, sd_by_cat)
mai_cs_sd <- ts(data = mai_cs_sd, start = start(y), frequency = frequency(y))
rownames(mai_cs_sd) <- as.character(ts_seq)
colnames(mai_cs_sd) <- c(ttl, long_group_names)

####################################################################################################
# Write results to .csv files
####################################################################################################

# Number of series by data category
write.table(x = num_series_cat,
            file = paste0(r_location,
            sprintf("%s_num_series_cat_tp", tolower(idx_name)), ".csv"),
            append = FALSE, quote = FALSE, sep = ',', row.names = TRUE, col.names = NA)

# DFM MAI estimate
write.table(x = mai,
            file = paste0(r_location,
            sprintf("%s_q_%d_s_%d_p_%d_tp", tolower(idx_name), q, s, p), ".csv"),
            append = FALSE, quote = FALSE, sep = ',', row.names = TRUE, col.names = NA)

# MAI standard error estimate
write.table(x = mai_se,
            file = paste0(r_location,
            sprintf("%s_se_q_%d_s_%d_p_%d_tp", tolower(idx_name), q, s, p), ".csv"),
            append = FALSE, quote = FALSE, sep = ',', row.names = TRUE, col.names = NA)

# MAI loadings
write.table(x = mai_wts,
            file = paste0(r_location,
            sprintf("%s_loadings_q_%d_s_%d_p_%d_tp", tolower(idx_name), q, s, p), ".csv"),
            append = FALSE, quote = FALSE, sep = ',', row.names = TRUE, col.names = NA)

# MAI decomposition by data category
write.table(x = mai_decomp,
            file = paste0(r_location,
            sprintf("%s_decomp_q_%d_s_%d_p_%d_tp", tolower(idx_name), q, s, p), ".csv"),
            append = FALSE, quote = FALSE, sep = ',', row.names = TRUE, col.names = NA)

# MAI cross-sectional standard deviation by data category
write.table(x = mai_cs_sd,
            file = paste0(r_location,
            sprintf("%s_cs_sd_q_%d_s_%d_p_%d_tp", tolower(idx_name), q, s, p), ".csv"),
            append = FALSE, quote = FALSE, sep = ',', row.names = TRUE, col.names = NA)

# Real-time MAI estimate
write.table(x = rt_mai,
            file = paste0(r_location,
            sprintf("rt_%s_q_%d_s_%d_p_%d_tp", tolower(idx_name), q, s, p), ".csv"),
            append = FALSE, quote = FALSE, sep = ',', row.names = TRUE, col.names = NA)

# Real-time MAI standard errors estimate
write.table(x = rt_mai_se,
            file = paste0(r_location,
            sprintf("rt_%s_se_q_%d_s_%d_p_%d_tp", tolower(idx_name), q, s, p), ".csv"),
            append = FALSE, quote = FALSE, sep = ',', row.names = TRUE, col.names = NA)

cat(sprintf("All files written to: %s\n", r_location))

# EOF
