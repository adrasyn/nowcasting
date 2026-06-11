####################################################################################################
# RDP 2024-04: Nowcasting Quarterly GDP Growth Using A Monthly Activity Indicator
# Replication files
####################################################################################################
# Luke Hartigan, 02-05-2024
####################################################################################################

# Clear the workspace
graphics.off()
rm(list = ls(all = TRUE))
gc()
cat("\014")

p_name <- "a Monthly Activity Indicator Useful for Nowcasting Quarterly GDP Growth"

# What are we doing?
cat(sprintf("Replication files for: \n\'%s\'...\n\n", p_name))

cat("Main analysis:\n")

# Transform data
source("Code/Transform_MAI_Data.R")
cat('\n')

# Targeted predictor dataset
#source("Code/Targeted_Predictor_MAI_Dataset.R") # Note: fails due to censored dataset
#cat('\n')

# Determine some DFM estimation options
#source("Code/Determine_TP_MAI_Estimation_Options.R") # Note: fails due to censored dataset
#cat('\n')

# Estimate and analysis the MAI
#source("Code/Estimate_and_Analyse_TP_MAI.R") # Note: fails due to censored dataset
#cat('\n')

# COVID-19 robustness analysis
#source("Code/MAI_COVID_Robustness_Analysis.R") # Note: Fails due to censored dataset
#cat('\n')

# MIDAS model specification analysis
source("Code/Modelling_GDP_MIDAS_TP.R")
cat('\n')

# Out-of-sample recursive prediction evaluation
source("Code/Recursive_Nowcast_GDP_UMIDAS_TP.R")
cat('\n')

# Empiricial p-value computation
source("Code/Recursive_Nowcast_GDP_UMIDAS_TP_MSEF_BOOTSTRAP.R")
cat('\n')

cat("Auxiliary analysis:\n")

# Correlogram for Australian quarterly GDP growth
source("Code/GDP_Dependence_Analysis.R")
cat('\n')

# MIDAS weight functions
source("Code/MIDAS_Polynomial_Weight_Functions.R")
cat('\n')

cat("...replication completed!\n\n")

# EOF
