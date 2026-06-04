###################################################################################################
# MAI Utility Functions used in the main scripts
###################################################################################################

# Add a legend at the bottom of the plot window
add_legend <- function(...)
{
    opar <- graphics::par(fig = c(0, 1, 0, 1), oma = c(0, 0, 0, 0), mar = c(0, 0, 0, 0), new = TRUE)
    on.exit(graphics::par(opar))
    graphics::plot(x = 0, y = 0, type = 'n', bty = 'n', xaxt = 'n', yaxt = 'n')
    graphics::legend(...)
}

# Get the year and month as numerical values
get_year_month <- function(x)
{
    date_str <- as.Date(x, format = "%Y-%m-%d")
    year <- as.numeric(substr(x = date_str, start = 1L, stop = 4L))
    month <- as.numeric(substr(x = date_str, start = 6L, stop = 7L))
    return (c(year, month))
}

# Get the year and quarter as numerical values
get_year_quarter <- function(x)
{
    date_str <- as.Date(x, format = "%Y-%m-%d")
    year <- as.numeric(substr(x = date_str, start = 1L, stop = 4L))
    quarter <- as.numeric(substr(x = date_str, start = 6L, stop = 7L)) / 3L
    return (c(year, quarter))
}

# Compute the percentage point (ppt) growth rate
ppt_growth <- function(x, nlag)
{
    if(!is.matrix(x)) { x <- as.matrix(x) }
    nobs <- dim(x)[1L]
    ppt <- (x[(1L + nlag):nobs, ] / x[1L:(nobs - nlag), ]) * 100.0 - 100.0
    return (ppt)
}

# Compute the Root Mean Squared Error (RMSE)
rmse <- function(x, na.rm = TRUE)
{
    return (sqrt(mean(x * x, na.rm = na.rm)))
}

# Compute the R-squared statistic
rsq <- function(yh, yt, na.rm = TRUE)
{
    return (sum(yh * yh, na.rm = na.rm) / sum(yt * yt, na.rm = na.rm))
}

# EOF
