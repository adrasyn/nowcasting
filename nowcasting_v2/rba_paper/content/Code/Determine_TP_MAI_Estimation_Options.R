####################################################################################################
# RDP 2024-04: Nowcasting Quarterly GDP Growth Using A Monthly Activity Indicator
####################################################################################################
# Luke Hartigan, 30-05-2023
####################################################################################################

# Clear the workspace
rm(list = ls(all = TRUE))

# Set directories
d_location <- "Data/"
f_location <- "Code/methods/"
r_location <- "Results/"

# Source required functions
source(paste0(f_location, "var_methods.R")) 	 # Determine optimal VAR(p) order
source(paste0(f_location, "ndfm_methods.R"))     # Estimate the number of dyn facs (q)
source(paste0(f_location, "qmle_dfm_methods.R")) # remove_na_values()
source(paste0(f_location, "mai_utils.R"))        # helper functions

# Set up a few options
options(digits = 4)

# What are we doing?
cat("Determining the DFM estimation options for constructing the MAI...\n")

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

# Get extended series -- full panel (for comparison)
z <- panel

# Convert to a 'ts' object so we can use window() later on
y <- ts(data = y, start = ts_begin, frequency = ts_freq)
z <- ts(data = z, start = ts_begin, frequency = ts_freq)

####################################################################################################
# Set up various options for determining 'q', 's' and 'p'
####################################################################################################

# How to handle NAs?
na_opt <- "exclude"     # Remove NAs
yna <- remove_na_values(x = y, na_opt = na_opt)
zna <- remove_na_values(x = z, na_opt = na_opt)

# Set up a few options for the log IC procedure
# using the Hallin and Liska (2007) log IC
q_max <- 8L
nbck <- 10L
stp <- 1.0
c_max <- 3.0
penalty <- "p3"
cf <- 1000.0
m <- 12L
h <- m
scale_opt <- TRUE
plot_opt <- TRUE

## Determine the number of dynamic factors 'q'

# q_est is the value of q_c in the second 'stability region' in the plot
ndf <- num_dyn_factors(x = yna, q_max = q_max, nbck = nbck, stp = stp,
                       c_max = c_max, penalty = penalty, cf = cf,
                       m = m, h = h, scale_opt = scale_opt, plot_opt = plot_opt)

# Collect the results to save to disk
ndf_results <- cbind(ndf$nfactor, ndf$v_nfactor, ndf$cr)
colnames(ndf_results) <- c("qc", "sc", "cr")

## Determine the lag length of the loadings filter 's'

# Dynamic eigenvalues options (some come from above)
nv <- 10L

# Dynamic eigenvalues for targeted predictor panel
dn <- dyn_eig(x = yna, q = nv, m = m, h = h)
rsq_dpc <- dn$vardec[seq_len(nv), 2L]

# Dynamic eigenvalues for extended panel
dn_ex <- dyn_eig(x = zna, q = nv, m = m, h = h)
rsq_dpc_ex <- dn_ex$vardec[seq_len(nv), 2L]

# Collection explained variance in TP and EX panels to save to disk
dpc_var_comp <- rbind(rsq_dpc, rsq_dpc_ex)
rownames(dpc_var_comp) <- c("TP", "EX")
colnames(dpc_var_comp) <- as.character(seq_len(nv))
cat("Explained variation (DPC) -- Targeted Predictors vs. Extended Panel\n")
print(dpc_var_comp)
cat('\n')

# Determine the number of static factors
nsf <- mod_bnic(x = yna, kmax = q_max, scale_opt = scale_opt)
cat("Modified Bai and Ng information criteria\n")
print(nsf)
cat('\n')

# PC Factor estimation options
r <- 3L                 # Number of static factors (based on estimate of q)
norm_opt <- "LN"
scale_opt <- FALSE      # Already standardised
sign_opt <- TRUE
vardec_opt <- TRUE      # We want the explained variation of each factor

# Static factor model
sfm <- pc_factor(x = yna, r = r, norm_opt = norm_opt, scale_opt = scale_opt,
                 sign_opt = sign_opt, vardec_opt = vardec_opt)

fac_pc <- sfm$factors
rsq_pc <- sfm$vardec[seq_len(nv), 2L]

# Collection explained variance to save to disk: r = q(s = 1) => s = (r - q)/q
var_comp <- rbind(rsq_dpc, rsq_pc)
rownames(var_comp) <- c("Dynamic", "Static")
colnames(var_comp) <- as.character(seq_len(nv))
cat("Explained variation -- Dynamic vs. Static\n")
print(var_comp)
cat('\n')

## Determine the lag order for the estimated factor 'p'

# Using information criterion
max_lag <- 4L
min_lag_fac_pc <- var_order(y = fac_pc, max_lags = max_lag)
cat("Minimum AR lag order (PC-Factor)\n")
print(min_lag_fac_pc)
cat('\n')

# Using ACF/PACF plots
def.par <- par(no.readonly = TRUE) # save default, for resetting...

layout(matrix(data = seq_len(2L * r), nrow = r, ncol = 2L, byrow = TRUE))

acf(x = fac_pc[,1L], lag.max = max_lag, main = sprintf("PC-Factor \U2013 %d", 1L))
pacf(x = fac_pc[,1L], lag.max = max_lag, main = sprintf("PC-Factor \U2013 %d", 1L))

acf(x = fac_pc[,2L], lag.max = max_lag, main = sprintf("PC-Factor \U2013 %d", 2L))
pacf(x = fac_pc[,2L], lag.max = max_lag, main = sprintf("PC-Factor \U2013 %d", 2L))

acf(x = fac_pc[,3L], lag.max = max_lag, main = sprintf("PC-Factor \U2013 %d", 3L))
pacf(x = fac_pc[,3L], lag.max = max_lag, main = sprintf("PC-Factor \U2013 %d", 3L))

par(def.par) # ...reset to default

####################################################################################################
# Write results to .csv files
####################################################################################################

# Number of dynamic factors results
write.table(x = ndf_results,
            file = paste0(r_location, "ndf_results_tp.csv"),
            append = FALSE, quote = FALSE, sep = ',',
            row.names = TRUE, col.names = NA)

# Variance explained in TP and EX panels by the dynamic eigenvalues
write.table(x = dpc_var_comp,
            file = paste0(r_location, "explvar_comparison_tp_ex.csv"),
            append = FALSE, quote = FALSE, sep = ',',
            row.names = TRUE, col.names = NA)

# Variance explained by the dynamic and static eigenvalues
write.table(x = var_comp,
            file = paste0(r_location, "explvar_comparison_tp.csv"),
            append = FALSE, quote = FALSE, sep = ',',
            row.names = TRUE, col.names = NA)

cat(sprintf("All files written to: %s\n", r_location))

# EOF
