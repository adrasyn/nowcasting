####################################################################################################
# RDP 2024-04: Nowcasting Quarterly GDP Growth Using A Monthly Activity Indicator
####################################################################################################
# Luke Hartigan, 13-03-2023
####################################################################################################

# Set directories
d_location <- "Data/"
f_location <- "Code/methods/"
r_location <- "Results/"

# Source required functions
source(paste0(f_location, "misc_methods.R"))

# Set up a few options
options(digits = 4)

# What are we doing?
cat("Pre-processing the monthly activity indicator dataset...\n")

####################################################################################################
# Read in the data
####################################################################################################

# Monthly indicator name
idx_name <- "MAI"
idx_long_name <- "Monthly Activity Indicator"

# Date format
date_fmt <- "%d/%m/%Y"

# Set some time series values
ts_freq_str <- "month"
ts_freq <- 12

# Load monthly partial indicator dataset
data_file <- sprintf("%s_panel.csv", tolower(idx_name))
mai_data <- read.csv(paste0(d_location, data_file), header = TRUE, sep = ',')
ts_seq <- as.Date(x = mai_data[, 1L], format = date_fmt)
panel <- mai_data[, -1L, drop = FALSE] # drop dates column

info_file <- sprintf("%s_info.csv", tolower(idx_name))
info <- read.csv(paste0(d_location, info_file),
                 header = TRUE, sep = ',', row.names = 1L)

# ID codes for operating on the panel
tcode <- info["tcode", , drop = FALSE]
tlog <- info["tlog", , drop = FALSE]

# Rolling window length -- 20 years
wind <- 20L
rdx <- wind * as.integer(ts_freq) # Monthly frequency

####################################################################################################
# Transform the data before extracting the factors
####################################################################################################

# Notes:
# tcode == "t1" => No difference, i.e., Level (default)
# tcode == "t2" => 1st Difference, i.e., (1 - B)y

# Levels
ylv <- panel[, which(tlog == FALSE & tcode == "t1"), drop = FALSE]

# First difference
dylv <- apply(X = panel[, which(tlog == FALSE & tcode == "t2"), drop = FALSE],
              MARGIN = 2L, FUN = transform_series, take_log = FALSE, tcode = "t2")

# Log difference (compounded growth)
dyln <- apply(X = panel[, which(tlog == TRUE & tcode == "t2"), drop = FALSE],
              MARGIN = 2L, FUN = transform_series, take_log = TRUE, tcode = "t2")

# Fix the differing series lengths
nx <- nrow(ylv) - nrow(dyln)
ylv <- trim_row(x = ylv, a = nx, b = 0)

# Combine data into a dataframe
paneltf <- data.frame(cbind(ylv, dylv, dyln))

# Sort to be as originally ordered in 'mai_panel'
paneltf <- paneltf[, colnames(panel), drop = FALSE]

# NB: We allow for a structural break in the mean in 1993:Q1 due to the introduction of inflation targeting
paneltfs <- rolling_scale(x = paneltf, roll_len = rdx, center = TRUE, scale = FALSE)

# Scale the panel to have unit variance over the full sample
paneltfs <- scale(x = paneltfs, center = FALSE, scale = TRUE)

# Give the rows useful names
rownames(paneltfs) <- as.character(ts_seq[-seq_len(nx)])
rownames(paneltf) <- as.character(ts_seq[-seq_len(nx)])

####################################################################################################
# Save data to an .csv file for future use
####################################################################################################

# Transformed and conditionally standardised (tfs) panel -- .csv file
write.table(x = paneltfs,
            file = paste0(d_location, sprintf("%s_data_tfs_censored", tolower(idx_name)), ".csv"),
            append = FALSE, quote = FALSE, sep = ',', na = "",
            row.names = TRUE, col.names = NA)

cat(sprintf("All files written to: %s\n", d_location))

# EOF
