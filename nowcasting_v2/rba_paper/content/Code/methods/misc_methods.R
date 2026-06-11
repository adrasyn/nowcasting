####################################################################################################
# Misc R functions
# Luke Hartigan
####################################################################################################
# Prediction accuracy functions
####################################################################################################

# R emulation of MATLAB eye(N)
eye <- function(n)
{
    return (diag(x = 1, nrow = n))
}

# R emulation of MATLAB ones()
ones <- function(...)
{
    return (array(data = 1, dim = c(...)))
}

# Mean Absolute Error
mae <- function(x, na.rm = TRUE)
{
    return (mean(x = abs(x), na.rm = na.rm))
}

# Root Mean Absolute Error
rmae <- function(x, na.rm = TRUE)
{
    return (sqrt(mae(x = x, na.rm = na.rm)))
}

# Relative Root Mean Absolute Error
rel_rmae <- function(f1, f2)
{
    # Do some checks
    if (length(f1) != length(f2)) {
        stop("rel_rmae(): length 'f1' != length of 'f2'.\n", call. = FALSE)
    }

    rmae1 <- rmae(x = f1)
    rmae2 <- rmae(x = f2)
    rrmae <- (rmae2 - rmae1) / rmae1
    return (rrmae)
}

# Mean Squared Error
mse <- function(x, na.rm = TRUE)
{
    return (mean(x = (x * x), na.rm = na.rm))
}

# Root Mean Squared Error
rmse <- function(x, na.rm = TRUE)
{
    return (sqrt(mse(x = x, na.rm = na.rm)))
}

# Relative Mean Squared Error
rel_mse <- function(f1, f2)
{
    # Do some checks
    if (length(f1) != length(f2)) {
        stop("rel_mse(): length 'f1' != length of 'f2'.\n", call. = FALSE)
    }

    mse1 <- mse(x = f1)
    mse2 <- mse(x = f2)
    rmse <- (mse2 - mse1) / mse1
    return (rmse)
}

# Relative Root Mean Squared Error
rel_rmse <- function(f1, f2)
{
    # Do some checks
    if (length(f1) != length(f2)) {
        stop("rel_rmse(): length 'f1' != length of 'f2'.\n", call. = FALSE)
    }

    rmse1 <- rmse(x = f1)
    rmse2 <- rmse(x = f2)
    rrmse <- (rmse2 - rmse1) / rmse1
    return (rrmse)
}

# Compute the square of variable/elements of 'x'
square <- function(x)
{
    return (x * x)
}

# R emulation of MATLAB zeros()
zeros <- function(...)
{
    return (array(data = 0, dim = c(...)))
}

# Compute the fixed interval bandwidth which is a function of T
fixed_bw <- function(n)
{
    return (as.integer(floor(4.0 * (n / 100.0)^(2.0 / 9.0))))
}

# Compute the data-dependent bandwidth (Andrews 1991)
data_dependent_bw <- function(x)
{
    # Compute a few useful quantities
    x <- as.matrix(x)
    nobs <- dim(x)[1L]
    nvar <- dim(x)[2L]
    nobsm1 <- nobs - 1L

    rho <- zeros(nvar, 1L)
    s2 <- zeros(nvar, 1L)

    for (j in seq_len(nvar)) {
        zt <- x[2L:nobs, j, drop = FALSE]
        zt_1 <- x[1L:nobsm1, j, drop = FALSE]
        rho_j <- sum(zt_1 * zt) / sum(zt_1 * zt_1) # NB: using cov(x,y) / var(x) for speed
        ifelse(test = rho_j > 0.97, yes = 0.97, no = rho_j) # Cover cases of non-stationarity, see Andrews and Monahan (1992)
        rho[j] <- rho_j
        et <- zt - (rho_j * zt_1)
        s2[j] <- sum(et * et) / nobsm1
    }

    # Compute the bandwidth parameter
    num <- 0.0
    den <- 0.0

    for (k in seq_len(nvar)) {
        num <- num + 4.0 * rho[k]^2.0 * s2[k]^2.0 / (((1.0 - rho[k])^6.0) * (1.0 + rho[k])^2.0)
        den <- den + s2[k]^2.0 / (1.0 - rho[k])^4.0
    }

    # Compute bandwidth
    alpha <- num / den
    bw <- as.integer(ceiling(1.1447 * (alpha * nobs)^(1.0 / 3.0)))

    return (bw)
}

# Long run variance estimation
long_run_var <- function(x, nlag)
{
    # Get sum useful values
    n <- length(x)
    if (n < nlag) { stop("long_run_var(): number of obs < number of lags.\n", call. = FALSE) }

    # Demean the series
    u <- scale(x, center = TRUE, scale = FALSE)

    # Compute the long-run variance -- lag zero...
    gamma_0 <- crossprod(x = u, y = NULL)

    if (nlag > 0L) {
        nlagp1 <- nlag + 1L
        # ... remaining lags
        for (j in seq_len(nlag)) {
            wt <- 1.0 - (j / nlagp1)
            gamma_t <- crossprod(x = u[(j + 1L):n], y = u[1L:(n - j)])
            gamma_t <- gamma_t + gamma_t
            gamma_0 <- gamma_0 + (wt * gamma_t)
        }
    }

    gamma_0 <- drop(gamma_0) / n
    return (gamma_0)
}

# Cumulative Sum of Squared Forecast Error Difference
cssfed <- function(e1, e2)
{
    x <- cumsum(square(e1) - square(e2))
    return (x)
}

####################################################################################################
# Mixed-frequency functions
####################################################################################################

# Mixed frequency function for vectors
mf_lag <- function (x, k, m)
{
    # Compute some useful values
    nx <- length(x)
    n <- nx %/% m
    lk <- k
    k <- max(k) + 1L
    mk <- min(k)

    # Check arguments are sensible
    if (mk > 0L) {
        mk <- 0L
    }

    if ((nx %% m) != 0L) {
        stop("mf_lag(): Incomplete high frequency data.\n", call. = FALSE)
    }

    idx <- m * (((k - 1L) %/% m + 1L):(n - mk))
    #z <- lapply(mk:(k - 1L), function(hx) { x[idx - hx] })
    #z <- do.call("cbind", z)
    z <- do.call(what = "cbind",
                 args = lapply(X = mk:(k - 1L),
                               FUN = function(hx) { x[idx - hx] }))

    if (k == 1L) {
        z <- matrix(data = z, ncol = 1L)
    }

    # Get meaningful column names for the new data structure
    xname <- ifelse(test = is.null(colnames(x)), yes = 'x', no = colnames(x))
    colnames(z) <- paste0(xname, '_', (mk + 1L):k - 1L, '/', 'm')

    #pad <- matrix(data = NA_real_, nrow = n - dim(z)[1L], ncol = dim(z)[2L])
    #result <- rbind(pad, z)[ , lk + 1L, drop = FALSE]
    result <- rbind(matrix(data = NA_real_,
                           nrow = n - dim(z)[1L],
                           ncol = dim(z)[2L]), z)[ , lk + 1L, drop = FALSE]

    return (result)
}

# Mixed frequency function for matrices
mf_lag_mat <- function(x, k, m) {

    # Do some preliminary checks
    if(!is.matrix(x)) { x <- as.matrix(x) }

    # Number of variables in the dataset
    nv <- dim(yna)[2L]

    # Preallocate storage
    ldat <- vector(mode = "list", length = nv)

    # Create a list containing a lower frequency version of each column of 'x'
    for (i in seq_len(nv)) {
        ldat[[i]] <- mf_lag(x = yna[,i], k = k, m = m)
    }

    # lower frequency horizontally stacked dataset
    result <- do.call(what = "cbind", args = ldat)

    return (result)

}

####################################################################################################
# Scale a series relative to a backward rolling window 'roll_len'
####################################################################################################

rolling_scale <- function(x, roll_len = 40L, center = TRUE, scale = TRUE)
{
    # Preliminary stuff
    if (!is.matrix(x)) { x <- as.matrix(x) }
    nobs <- dim(x)[1L]
    nvar <- dim(x)[2L]
    roll_len_p1 <- roll_len + 1L
    roll_len_m1 <- roll_len - 1L

    # Check if colnames is NULL and if so set to "vi" for i = 1,...,nvar
    if (is.null(colnames(x))) {
        var_names <- paste0('v', seq_len(nvar))
    } else {
        var_names <- colnames(x)
    }

    if (roll_len > nobs) {
        stop(sprintf("Rolling window length \'%d\' greater than time series length \'%d\'\n",
            roll_len, nobs))
    }

    if (nvar > 1L) {

        # Allocate storage for the scaled series
        sx <- matrix(data = NA_real_, nrow = nobs, ncol = nvar)

        # Scale the initial part of the sample
        sx[seq_len(roll_len), ] <- scale(x = x[seq_len(roll_len), ], center = center, scale = scale)

        for (i in roll_len_p1:nobs) {
            sx[(i - roll_len_m1):i, ] <- scale(x = x[(i - roll_len_m1):i, ], center = center, scale = scale)
        }

    } else {

        # Allocate storage for the scaled series
        sx <- matrix(data = NA_real_, nrow = nobs, ncol = 1L)

        # Scale the initial part of the sample
        sx[seq_len(roll_len)] <- scale(x = x[seq_len(roll_len)], center = center, scale = scale)

        for (i in roll_len_p1:nobs) {
            sx[(i - roll_len_m1):i] <- scale(x = x[(i - roll_len_m1):i], center = center, scale = scale)
        }

    }

    # Assign colnames before returning sx
    colnames(sx) <- var_names

    return (sx)
}

####################################################################################################
# foo <- skewness(x, bias_fix)
#
# PURPOSE:
#   Function to calculate the skewness (3rd moment) of a variable.
#
# INPUTS:
#   x = data series to use
#   bias_fix options:
#       bias_fix == TRUE to correct for bias. (Default)
#       bias_fix == FALSE to not correct for bias.
#
# OUTPUTS:
#   skewness = estimate of the third moment of the data series x.
#
# DEPENDENCIES:
#   None.
#
# REFERENCES:
#   None.
#
# AUTHOR:
#   Luke Hartigan (2014)
####################################################################################################

skewness <- function(x, bias_fix = TRUE)
{
    # Preliminary stuff
    x <- as.matrix(x)
    n <- length(x)
    x0 <- x - mean(x, na.rm = TRUE)
    s2 <- mean(x0^2, na.rm = TRUE) # NB biased variance estimator

    # Bias corrected skewness
    if (bias_fix) {
        m3 <- mean(x0^3, na.rm = TRUE)
        s1 <- m3 / s2^1.5
        skewness <- s1 * sqrt((n - 1) / n) * n / (n - 2)
    } else {
        m3 <- mean(x0^3, na.rm = TRUE)
        skewness <- m3 / s2^1.5
    }

    # Return skewness
    return (skewness)

}

####################################################################################################
# foo <- kurtosis(x, bias_fx)
#
# PURPOSE:
#   Function to calculate the kurtosis (4th moment) of a variable.
#
# INPUTS:
#   x = data series to use
#   bias_fix options:
#       bias_fix == TRUE to correct for bias. (Default)
#       bias_fix == FALSE to not correct for bias.
#
# OUTPUTS:
#   kurtosis = estimate of the fourth moment of the data series x.
#
# DEPENDENCIES:
#   None.
#
# REFERENCES:
#   None.
#
# AUTHOR:
#   Luke Hartigan (2014)
####################################################################################################

kurtosis <- function(x, bias_fix = TRUE)
{
    # Preliminary stuff
    x <- as.matrix(x)
    n <- length(x)
    x0 <- x - mean(x, na.rm = TRUE)
    s2 <- mean(x0^2, na.rm = TRUE) # NB biased variance estimator

    # Bias corrected Kurtosis
    if (bias_fix) {
        m4 <- mean(x0^4, na.rm = TRUE)
        k1 <- m4 / s2^2
        kurtosis <- ((n + 1) * k1 - 3 * (n - 1)) * (n - 1) / ((n - 2) * (n - 3)) + 3
    } else {
        m4 <- mean(x0^4, na.rm = TRUE)
        kurtosis <- m4 / s2^2
    }

    # Return kurtosis
    return (kurtosis)

}

####################################################################################################
# foo <- jb_test(x)
#
# PURPOSE:
#   Function to calculate the Jarque-Bera test of normality. Under the null the data should have
#   skewness = 0 (symmetric) and have kurtosis = 3. The Jarque-Bera statistic is chi-square
#   distributed with 2 degrees of freedom.
#
# INPUTS:
#   x = data series to use
#
# OUTPUTS (List object with class "jb_test")
#   statistic = critical value of the Jarque-Bera test ~ chi-square(2)
#   pvalue = p value for the JB critical value.
#
# DEPENDENCIES:
#   None.
#
# REFERENCES:
#   Jarque, C. M., Bera, A. K. (1980) Efficient test for normality, homoscedasticity and
#       serial independence of residuals, Economic Letters, Vol. 6 Issue 3, 255-259.
#
# AUTHOR:
#   Luke Hartigan (2014)
####################################################################################################

jb_test <- function(x)
{
    # Preliminary settings
    x <- as.matrix(x)
    n <- length(x)
    x0 <- x - mean(x, na.rm = TRUE)
    s2 <- mean(x0^2, na.rm = TRUE) # NB biased variance estimator

    # Calculate sample skewness and excess kurtosis
    skew <- mean(x0^3, na.rm = TRUE) / s2^1.5
    kurt <- mean(x0^4, na.rm = TRUE) / s2^2 - 3

    # Calculate the test statistic
    statistic <- n * (skew * (skew / 6) + kurt * (kurt / 24))

    # Test results
    pvalue <- pchisq(q = statistic, df = 2, lower.tail = FALSE)

    # Collect results as a list object
    results <- list()
    results$statistic <- statistic
    results$pvalue <- pvalue

    # Return results with class "jb"
    results$call = match.call()
    class(results) <- "jb_test"
    return (results)

}

# Print method for "jb_test"
print.jb_test <- function(x, digits = max(3L, getOption("digits") - 3L), ...)
{
    cat("\nCall: ", paste(deparse(x$call), sep = '\n', collapse = '\n'), '\n', sep = "")
    cat("\nJarque & Bera (1980) test for normality:\n\n")
    cat("H0 : The process is \'normal\'\n\n")
    cat("Statistic  P-value\n")
    cat(sprintf("%9.4g  %7.4g\n", x$statistic, x$pvalue))
    cat('\n')
}

####################################################################################################
# foo <- transform_series(x, take_log, tcode, pcode)
#
# PURPOSE:
#   Function returns suitably transformed, lagged and/or differenced series.
#
# INPUTS:
# take_log = take the natural logarithm? Default is no (FALSE)
#
# tcode = option to specify how y is transformed:
#   tcode == "t1" [No difference, i.e., Level] -- Default --
#   tcode == "t2" [1st Difference, i.e., (1 - B)y]
#   tcode == "t3" [4th Difference, i.e., (1 - B^4)y, use with quarterly data]
#   tcode == "t4" [12th Difference, i.e., (1 - B^12)y, use with monthly data]
#   tcode == "t5" [2nd Difference, i.e., (1 - B)^2y, double difference]
#   tcode == "t6" [1st diff & seasonal diff for quaterly data, i.e., ((1 - B)(1 - B^4)y]
#   tcode == "t7" [1st diff & seasonal diff for monthly data, i.e., ((1 - B)(1 - B^12)y]
#
# pcode = option to specify if percentages are computed:
#   pcode == "p1" [no change] -- Default --
#   pcode == "p2" [multiply by 100]
#   pcode == "p3" [multiply by 400, annualised quarterly rate]
#   pcode == "p4" [multiply by 1200, annualised monthly rate]
#
# OUTPUTS:
#   y = transformed numeric vector x which is short than x if differencing is undertaken.
#
# DEPENDENCIES:
#	None.
#
# REFERENCES:
#   Adapted from the GAUSS procs of Stock and Watson (2005), 'Implications of Dynamic Factor
#     Models for VAR analysis', manuscript. link: http://www.princeton.edu/~mwatson/wp.html
#
# AUTHOR:
#   Luke Hartigan (2017)
####################################################################################################

transform_series <- function(x, take_log = FALSE,
                             tcode = c("t1", "t2", "t3", "t4", "t5", "t6", "t7"),
                             pcode = c("p1", "p2", "p3", "p4"))
{
    # Save 'ts' attributes if 'y' is a 'ts' object
    if (is.ts(x)) {
        x_ts <- TRUE
        endx <- end(x)
        freqx <- frequency(x)
    } else {
        x_ts <- FALSE
    }

    # Preliminary stuff
    tx <- as.matrix(x)

    # Log transformation
    if (take_log) {
        if (any(tx < 0, na.rm = TRUE)) {
            tx[which(tx < 0)] <- NaN
        }
        tx <- log(as.matrix(tx))
    }

    # Difference transform if requested
    tcode <- match.arg(tcode)

    switch (EXPR = tcode,
        "t1" = { tx }, # do nothing
        "t2" = { tx <- diff(x = tx, lag = 1L) },
        "t3" = { tx <- diff(x = tx, lag = 4L) },
        "t4" = { tx <- diff(x = tx, lag = 12L) },
        "t5" = { tx <- diff(diff(x = tx, lag = 1L), lag = 1L) },
        "t6" = { tx <- diff(diff(x = tx, lag = 1L), lag = 4L) },
        "t7" = { tx <- diff(diff(x = tx, lag = 1L), lag = 12L) }
    )

    # Convert to percentage if requested
    pcode <- match.arg(pcode)

    switch (EXPR = pcode,
        "p1" = { tx }, # do nothing
        "p2" = { tx <- tx * 100.0 },
        "p3" = { tx <- tx * 400.0 },
        "p4" = { tx <- tx * 1200.0 }
    )

    # Add 'ts' attribute to 'tx' if is a 'ts' object
    if (x_ts) {
        tx <- ts(tx, end = endx, frequency = freqx)
    }

    return (tx)
}

####################################################################################################
# foo <- trim_row(x, a, b)
#
# PURPOSE:
#   Function to remove specified rows from a matrix (or vector).
#
# INPUTS:
#   x = matrix or (vector) on dimension N x T
#   a = scalar value to trim nrow(x) from top of the matrix (or vector)
#   b = scale value to trim nrow(x) from bottom of the matrix (or vector)
#
# OUTPUTS:
#   x_adj = x[(a+1):(T-b), ]
#
# DEPENDENCIES:
#   None.
#
# REFERENCES:
#   Translation of GAUSS 'trimr' function.
#
# AUTHOR:
#   Luke Hartigan (2014)
####################################################################################################

trim_row <- function(x, a, b)
{
    # Preliminary stuff
    x <- as.matrix(x)
    mdim <- dim(x)[1L]
    ndim <- dim(x)[2L]

    # Do some checks on the dimensions of 'x' matrix
    if ((a < 0) || (b < 0)) {
        stop("trim_row(): Neither 'a' nor 'b' can be negative!!\n", call. = FALSE)
    }

    if ((a > mdim ) || (b > mdim)) {
        stop(sprintf("trim_row(): Length of 'a' or 'b' cannot exceed %d.\n", nrow(x)), call. = FALSE)
    }

    if ((a + b >= mdim)) {
        stop(sprintf("trim_row(): Length of 'a + b' cannot exceed %d.\n", nrow(x)), call. = FALSE)
    }

    x_adj <- x[(a + 1L):(mdim - b), , drop = FALSE]

    return (x_adj)
}

# EOF
