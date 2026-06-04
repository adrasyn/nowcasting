####################################################################################################
# RDP 2024-04: Nowcasting Quarterly GDP Growth Using A Monthly Activity Indicator
####################################################################################################
# Luke Hartigan, 22-06-2023
####################################################################################################

# Clear the workspace
rm(list = ls(all = TRUE))

# Set directories
d_location <- "Data/"
f_location <- "Code/methods/"
r_location <- "Results/"

# Source required functions
source(paste0(f_location, "mai_utils.R")) # helper functions

# Load the required libraries
suppressMessages(library("midasr")) # nealmon(); nbeta()

# Set up a few options
options(digits = 4)

# What are we doing?
cat("Normalised Exponential Almon and Normalised Beta Lag MIDAS Coefficients...\n")

####################################################################################################
# Preliminary stuff
####################################################################################################

# Normalised Exponential Almon and Normalised Beta options -- all weights sum to 1!
p2 <- c(1.0, -0.5)
p3 <- c(1.0, 0.5, -0.1)
pb <- c(1.0, 3.5, 7.5) # NB: has a '0' added as passed to nbetaMT()
d <- 16L
w1 <- nealmon(p = p2, d = d)
w2 <- nealmon(p = p3, d = d)
w3 <- nbeta(p = pb, d = d)
x <- seq_len(d) - 1L

# Collect together and give row and column names
wts <- cbind(w1, w2, w3)
rownames(wts) <- x
colnames(wts) <- c("nealmon_p2", "nealmon_p3", "nbeta")

####################################################################################################
# Write results to .csv files
####################################################################################################

# Save Normalised Exponential Almon and Normalised Beta Weights to disc
write.table(x = wts,
            file = paste0(r_location,"midas_poly_wts", ".csv"),
            append = FALSE, quote = FALSE, sep = ',',
            row.names = TRUE, col.names = NA)

cat(sprintf("All files written to: %s\n", r_location))

# EOF
