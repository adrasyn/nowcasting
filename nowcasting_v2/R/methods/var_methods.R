####################################################################################################
# Vector Autoregression Models Estimated by OLS
# Luke Hartigan, 2019
####################################################################################################
# Helper functions
####################################################################################################

# Compute the inverse of a matrix using the Cholesky factorisation
chol_inv <- function(x)
{
    return (chol2inv(x = chol(x = x)))
}

# R emulation of MATLAB eye(N)
eye <- function(n)
{
    return (diag(x = 1.0, nrow = n))
}

# Compute the log of the determinant of a matrix using the LU decomposition
log_det <- function(x)
{
    ld <- unlist(determinant(x = x, logarithm = TRUE))
    return (as.numeric(ld[1L] * ld[2L]))
}

# R emulation of MATLAB reshape(A, M, N, ...)
mreshape <- function(data, ...)
{
    dim(data) <- c(...)
    return (data)
}

# R emulation of MATLAB ones()
ones <- function(...)
{
    return (array(data = 1.0, dim = c(...)))
}

# R emulation of MATLAB repmat(A, M, N)
repmat <- function(mat, m, n)
{
    return (kronecker(matrix(data = 1, nrow = m, ncol = n), mat))
}

# Compute the square of variable/elements of 'x'
square <- function(x)
{
    return (x * x)
}

# R emulation of MATLAB zeros()
zeros <- function(...)
{
    return (array(data = 0.0, dim = c(...)))
}

####################################################################################################
# Compute lag matrix with dimensions (T - p, N x p)
# NB: stats::embed() is an alternative method
####################################################################################################

lag_mat <- function(x, nlags)
{
    # Preliminary stuff
    x <- as.matrix(x)
    nobs <- dim(x)[1L]
    nvar <- dim(x)[2L]

    # Storage for the matrix of lagged variables
    xlags <- matrix(data = NA_real_, nrow = nobs - nlags, ncol = nvar * nlags)

    # Construct the matrix of lagged variables
    for (i in seq_len(nlags)) {
        xlags[, (nvar*i - nvar + 1L):(nvar*i)] <- x[((nlags + 1L) - i):(nobs - i), ]
    }

    # Return the matrix of lagged variables
    return (xlags)
}

####################################################################################################
# Construct the companion matrix given the coefficient matrix 'params'
####################################################################################################

companion <- function(params, intercept = TRUE)
{
    # Drop coefficients related to the intercept if present
    if (intercept) {
        params <- params[-1L, , drop = FALSE]
    }

    # Compute some useful values
    m <- dim(params)[1L]
    n <- dim(params)[2L]

    # Pre-allocate storage for the results
    companion <- zeros(m, m)
    companion[seq_len(n), ] <- t(params)

    if (m > n) {
        companion[(n + 1L):m, 1L:(m - n)] <- eye(m - n)
    }

    # Return the companion matrix
    return (companion)
}

####################################################################################################
# foo <- ols_var(y, plag, intercept, het, get_companion)
#
# PURPOSE:
#   Estimate a reduced form VAR using OLS
#
# INPUTS:
#   y = Endogenous variables (vector: T x N)
#   plag = Number of lags of y to include in the VAR
#   intercept options:
#     intercept == TRUE (intercept) *Default*
#     intercept == FALSE (no intercept)
#   het options:
#     het == TRUE (heteroskedasticity consistent vcov matrix)
#     het == FALSE (homoskedasticity consistent vcov matrix)
#   get_companion options:
#     get_companion == TRUE (return companion matrix) *Default*
#     get_companion == FALSE (no companion matrix)
#
# OUTPUTS: (list object, class "olsvar")
#   coefficients = VAR coefficients (each column has the coefficients for a single equation)
#   residuals = VAR innovations
#   omega = Innovation covariance matrix
#   vcov = VAR coefficient covariance matrix
#   nobs = Number of observations used in estimation
#   nvar = Number of regressors used in estimation (including lags)
#	kvar = Number of endogenous variables
#   aic = Akaike's Information Criterion
#   sic = Schwarz's Information Criterion
#   has_intercept = TRUE if intercept included in VAR model else FALSE
#   companion = companion matrix if requested
#
# DEPENDENCIES:
#   lag_mat()
#   companion()
#
# REFERENCES:
#   Hamilton, J. D., (1994), "Time Series Analysis".
#
#   Luthkephol, H., (2005), "New Introduction to Multivariate Time Series Analysis"
#
# AUTHOR:
#   Luke Hartigan (2018)
####################################################################################################

ols_var <- function(y, plag, intercept = TRUE, het = TRUE, get_companion = TRUE)
{
    # Preliminary stuff
    y <- as.matrix(y)
    yp <- y[-seq_len(plag), , drop = FALSE]         # cut away first p lags
    nobs <- dim(y)[1L] - plag                       # adjusted time series length

    # Compute matrix of lagged y values
    ylags <- lag_mat(x = y, nlag = plag)

    # Include an intercept if requested
    if (intercept) {
        ylags <- cbind(1.0, ylags)
    }

    # Compute the QR decomposition of the lagged dependent matrix
    qr_xmat <- qr(x = ylags)

    # Compute the VAR coefficients
    coefficients <- qr.coef(qr = qr_xmat, y = yp)

    # Compute the VAR innovations
    residuals <- qr.resid(qr = qr_xmat, y = yp)

    # Compute the innovation and VAR coefficient covariance matrices
    nvar <- dim(coefficients)[1L]
    kvar <- dim(coefficients)[2L]
    omega <- crossprod(x = residuals, y = NULL) / nobs # MLE version
    xxi <- chol2inv(qr.R(qr = qr_xmat, complete = FALSE))

    if (het) {
        vcov <- zeros(nvar * kvar, nvar)
        for (i in seq_len(kvar)) {
            j <- (i - 1L) * nvar
            vcov[(j + 1L):(j + nvar), ] <- tcrossprod(x = xxi, y = ylags) %*% residuals[, i]
        }
    } else {
        vcov <- kronecker(X = omega, Y = xxi)
    }

    # Compute information criterion
    aic <- log_det(omega) + (2.0 * nvar^2.0 * plag) / nobs
    sic <- log_det(omega) + (log(nobs) * nvar^2.0 * plag) / nobs

    # Collect results as a list object
    results <- list()
    results$coefficients <- coefficients
    results$residuals <- residuals
    results$omega <- omega
    results$vcov <- vcov
    results$nobs <- nobs
    results$nvar <- nvar
    results$kvar <- kvar
    results$aic <- aic
    results$sic <- sic
    results$has_intercept <- intercept

    # Construct the companion matrix if requested
    if (get_companion) {
        companion <- companion(params = coefficients, intercept = intercept)
        results$companion <- companion
    }

    # Return results with class "ols_var"
    results$call <- match.call()
    class(results) <- "ols_var"
    return (results)
}

####################################################################################################
# Get the optimal number of lags as suggested by the AIC and SIC
####################################################################################################

# VAR model
var_order <- function(y, max_lags = 10L, intercept = TRUE)
{
    # Preliminary stuff
    ic_mat <- zeros(max_lags, 2L)
    colnames(ic_mat) <- c("AIC", "SIC")

    for (i in seq_len(max_lags)) {

        # Estimate the VAR for each lag i and save the information criterion
        tmp <- ols_var(y = y, plag = i, intercept = intercept, 
            het = FALSE, get_companion = FALSE)
        ic_mat[i, 1L] <- tmp$aic
        ic_mat[i, 2L] <- tmp$sic

    }

    # Compute the minimum ic
    min_ic <- apply(X = ic_mat, MARGIN = 2L, FUN = which.min)
    
    # Return results as a list object with class 'var_order'
    results <- list()
    results$call <- match.call()
    results$ic <- min_ic
    class(results) <- "var_order"
    return (results)
}

# Print method for 'var_order' and 'varx_order'
print.var_order <- function(x, digits = 4L, print.gap = 3L, right = TRUE, ...)
{
    # Specify row and column labels
    ic <- matrix(data = x$ic, nrow = 1L, ncol = 2L)
    rownames(ic) <- "Lags"
    colnames(ic) <- c("AIC", "SIC")
    # Print results
    cat("\nCall: ", paste(deparse(x$call), sep = '\n', collapse = '\n'), '\n', sep = "")
    cat("\nMinimum VAR lag order\n\n")
    print.default(x = x$ic, digits = digits, print.gap = print.gap, right = right, ...)
    cat('\n')
}

# EOF
