####################################################################################################
# Methods to estimate Regression models with HAC Corrected Standard Errors
###################################################################################################
# These are codes to implement alternative HACCM estimators as described in the paper:
#
# Luke Hartigan (2018), "Alternative HAC Covariance Matrix Estimators with
#    Improved Finite Sample Properties", Computational Statistics & Data Analysis,
#    Vol. 119, March 2018, Pages 55-73. https://doi.org/10.1016/j.csda.2017.09.007
#
# Additional References:
#   Brown, R. L., J. Durbin and J. M. Evans, (1975), "Techniques for Testing the
#       Constancy of Regression Relationships over Time", Journal of the Royal
#       Statistical Society, Series B, 37, pp 149--192.
#
#   Kuan, C.-M. and Y.-W. Hsieh, (2008), "Improved HAC covariance matrix estimation
#       based on forecast errors", Economic Letters, 99, pp 89--92.
#
# Note: Automatic bandwidth code based on code from the 'Sandwich' R package by Zeileis (2004).
#
# Author:
#    Luke Hartigan, (2022)
####################################################################################################
# Helper functions used by the main functions below
####################################################################################################

# Compute the inverse of a matrix using the Cholesky factorisation
chol_inv <- function(x)
{
    return (chol2inv(x = chol(x = x)))
}

# Computes the matrix quadratic form: x'Ax for matrix 'A' and vector 'x'
qform <- function(mat, vec)
{
    # Preliminary stuff
    mat <- if(!is.matrix(mat)) { mat <- as.matrix(mat) }
    vec <- if(!is.matrix(vec)) { vec <- as.matrix(vec) }

    # Check argument dimensions are conformable
    if (dim(mat)[1L] != length(vec)) {
        stop("qform(): Non conformable dimension.\n", call. = FALSE)
    }

    # Calculate x'Ax using R's inbuilt matrix operations
    z <- as.numeric(crossprod(x = crossprod(x = mat, y = vec), y = vec))
    return (z)
}

# Computes the matrix quadratic inverse form: x'inv(A)x for matrix 'A' and vector 'x'
invqform <- function(mat, vec)
{
    # Preliminary stuff
    mat <- if(!is.matrix(mat)) { mat <- as.matrix(mat) }
    vec <- if(!is.matrix(vec)) { vec <- as.matrix(vec) }

    # Check argument dimensions are conformable
    if (dim(mat)[1L] != length(vec)) {
        stop("invqform(): Non conformable dimension.\n", call. = FALSE)
    }

    # Calculate x'inv(A)x using R's inbuilt matrix operations
    z <- as.numeric(crossprod(x = vec, qr.solve(a = mat, b = vec)))
    return (z)
}

# R emulation of MATLAB repmat(A, M, N)
repmat <- function(mat, m, n)
{
    return (kronecker(matrix(data = 1L, nrow = m, ncol = n), mat))
}

# Compute the square of variable/elements of 'x'
square <- function(x)
{
    return (x * x)
}

# Compute the p-value for the test statistic (two-sided test)
compute_p_value <- function(x)
{
    return (2.0 * stats::pnorm(q = abs(x),
        mean = 0.0, sd = 1.0, lower.tail = FALSE))
}

# Compute leverage measures from the 'Q' part of the QR decomposition
compute_leverage <- function(qr)
{
    if (!is.qr(x = qr)) {
        stop("compute_leverage(): Expected list object which inherits from \'qr\'.\n", call. = FALSE)
    }
    Q <- qr.Q(qr = qr, complete = FALSE)
    return (matrix(data = rowSums(square(Q)), nrow = dim(Q)[1L], ncol = 1L))
}

# Compute Recursive Residuals
recursive_resid <- function(y, x, intercept = TRUE, norm_opt = TRUE)
{
    # Do some preliminary things
    if (!is.matrix(y)) { y <- as.matrix(y) }
    if (!is.matrix(x)) { x <- as.matrix(x) }

    # Check data dimensions are conformable
    if (dim(y)[1L] != dim(x)[1L]) {
        stop("recursive_resid(): Non conformable dimension.\n", call. = FALSE)
    }

    # Include an intercept?
    if (intercept) {
        x <- cbind(1.0, x)
    }

    # Compute some useful values
    nobs <- dim(x)[1L]
    nvar <- dim(x)[2L]
    nvarp1 <- nvar + 1L

    # Set aside storage for the recursive residuals
    rresid <- matrix(data = NA_real_, nrow = (nobs - nvar), ncol = 1L)
    colnames(rresid) <- "rresid"

    # Initialise iXX_t and b_t for sample t = 1,...,nvar
    qr_xmat <- qr(x = x[seq_len(nvar), , drop = FALSE])
    iXX_t <- chol2inv(x = qr.R(qr = qr_xmat, complete = FALSE))
    b_t <- matrix(data = qr.coef(qr = qr_xmat,
                  y = y[seq_len(nvar), , drop = FALSE]), nrow = nvar, ncol = 1L)

    # Estimate the recursive residuals for t = nvar + 1,...,nobs
    for (i in nvarp1:nobs) {

        # Generate some useful values
        y_t <- y[i, , drop = FALSE]
        x_t <- x[i, , drop = FALSE]

        # Estimate the recursive residual
        e_t <- drop(y_t - (x_t %*% b_t))

        # Standardise the recursive residuals if specified
        rresid[i - nvar] <- ifelse(test = norm_opt,
                                   yes = e_t / sqrt(1.0 + drop(x_t %*% iXX_t %*% t(x_t))),
                                   no = e_t)

        # Update iXX_t and b_t
        d <- tcrossprod(x = iXX_t, y = x_t)
        iXX_t <- iXX_t - (tcrossprod(x = d, y = d) / (1.0 + drop(x_t %*% d)))
        b_t <- b_t + (iXX_t %*% crossprod(x = x_t, y = e_t))

    }

    return (rresid)
}

# Computes residuals used in estimating the sandwich covariance matrix
make_residuals_matrix <- function(leverage, ehat, nvar,
                                  res_opt = c("EH", "EB", "ET", "ED", "EM", "ES"))
{
    # Calculate different residuals for HAC estimation
    res_opt <- toupper(match.arg(res_opt))

    switch (EXPR = res_opt,
        "EH" = { emat <- repmat(ehat, 1L, nvar) },               # OLS residuals
        "EB" = { ebar <- sqrt(1.0 / (1.0 - leverage)) * ehat;    # Standardised residuals
                 emat <- repmat(ebar, 1L, nvar) },
        "ET" = { etilde <- ehat / (1.0 - leverage);              # Prediction error residuals
                 emat <- repmat(etilde, 1L, nvar)  },
        "ED" = { nht <- length(leverage);                        # Discounted error residuals
                 pht <- sum(leverage);
                 hbar <- (nht * leverage / pht);
                 delta <- pmin(4.0, hbar);
                 edot <- ehat / (1.0 - leverage)^(delta / 2.0);
                 emat <- repmat(edot, 1L, nvar) },
        "EM" = { nht <- length(leverage);                        # 'Modified discounted error' residuals
                 pht <- sum(leverage);
                 hbar <- (nht * leverage / pht);
                 gam1 <- 1.0;                                    # author recommended value
                 gam2 <- 1.5;                                    # author recommended value
                 delta <- pmin(gam1, hbar) + pmin(gam2, hbar);
                 edotm <- ehat / (1.0 - leverage)^(delta / 2.0);
                 emat <- repmat(edotm, 1L, nvar) },
        "ES" = { nht <- length(leverage);                        # HC5
                 pht <- sum(leverage);
                 hbar <- (nht * leverage / pht);
                 kc <- 0.7;                                      # author recommended value
                 delta <- pmin(hbar, pmax(4.0, (nht * kc * max(leverage) / pht)));
                 estar <- ehat / (1.0 - leverage)^(delta / 2.0);
                 emat <- repmat(estar, 1L, nvar) }
    )

    return (emat)

}

# Internal helper function used by lm_hac for computing the scores with forecast errors
fe_scores_matrix <- function(y, x, intercept, norm_opt = TRUE, trim = 0.1)
{
    # Compute the recursive residuals
    rres <- recursive_resid(y = y, x = x, intercept = intercept, norm_opt = norm_opt)

    nx <- dim(x)[1L]
    nr <- dim(rres)[1L]
    dn <- nx - nr

    # Check if a value was passed for 'trim'
    if (missing(trim) || is.null(trim)) {

        rrmat <- repmat(rres, 1L, dim(x)[2L])
        scores <- x[(dn + 1L):nx, , drop = FALSE] * rrmat

    } else {

        # Check 0.0 < trim <= 1.0
        if ((trim < 0.0) || (trim >= 1.0)) {
            stop("fe_scores_matrix(): not a suitable \'trim\' value\n")
        }

        # Trim the first couple of values
        tp <- floor(nr * trim)
        rrmat <- repmat(rres[(tp + 1L):nr], 1L, dim(x)[2L])
        scores <- x[(tp + dn + 1L):nx, , drop = FALSE] * rrmat

    }

    return (scores)
}

# Compute the automatic (data-dependent) bandwidth parameter using Andrews (1991)
compute_auto_bw <- function(xe, intercept, kern_opt = c("TR", "BT", "PZ", "TH", "QS"))
{
    # Get some useful quantities
    nobs <- dim(xe)[1L]
    nobsm1 <- nobs - 1.0
    nvar <- dim(xe)[2L]
    wa <- rep(1.0, nvar)

    if (intercept) {
        wa[1L] <- 0.0
    }

    # Pre-allocate storage for parameters
    rho <- matrix(data = NA_real_, nrow = nvar, ncol = 1L)
    s2 <- matrix(data = NA_real_, nrow = nvar, ncol = 1L)

    # Estimate rho_j using linear regression
    for (j in seq_len(nvar)) {
        v <- xe[, j, drop = FALSE]
        vt <- v[2L:nobs]
        vt_1 <- v[1L:nobsm1]
        rho_j <- sum(vt_1 * vt) / sum(vt_1 * vt_1); # NB: cov(x,y) / var(x) for speed
        et <- vt - (rho_j * vt_1)
        rho[j] <- rho_j
        s2[j] <- sum(et * et) / nobsm1
    }

    n0 <- 4.0 * (rho * rho * s2 * s2)
    dn <- (s2 * s2) / (1.0 - rho)^4.0

    # Compute alphas
    n1 <- ((1.0 - rho)^6.0) * ((1.0 - rho)^2.0)
    n2 <- (1.0 - rho)^8.0
    dns <- sum(wa * dn)
    a1 <- sum(wa * (n0 / n1)) / dns
    a2 <- sum(wa * (n0 / n2)) / dns

    # Now compute the bandwidth
    kern_opt <- toupper(match.arg(kern_opt))

    switch (EXPR = kern_opt,
        "TR" = { bw <- 0.6611 * (a2 * nobs)^(1.0 / 5.0) },  # Truncated Kernel
        "BT" = { bw <- 1.1447 * (a1 * nobs)^(1.0 / 3.0) },  # Bartlett Kernel
        "PZ" = { bw <- 2.6614 * (a2 * nobs)^(1.0 / 5.0) },  # Parzen Kernel
        "TH" = { bw <- 1.7462 * (a2 * nobs)^(1.0 / 5.0) },  # Tukey-Hanning Kernel
        "QS" = { bw <- 1.3221 * (a2 * nobs)^(1.0 / 5.0) }   # Quadratic Spectral Kernel
    )

    return (bw)

}

# Compute fixed interval bandwidth function of sample size T such that as i,T -> inf, i/T -> 0.
compute_fixed_bw <- function(nobs, vs = c("WD", "SW"))
{
    vs <- toupper(match.arg(vs))
    switch(EXPR = vs,
        "WD" = { interval <- floor(4.0 * ((nobs / 100.0)^(2.0 / 9.0))) },
        "SW" = { interval <- floor(0.75 * nobs^(1.0 / 3.0)) }
    )

    return (interval)

}

# Compute the kernel weights
compute_kernel_weights <- function(nobs, bw, kern_opt = c("TR", "BT", "PZ", "TH", "QS"))
{
    # Compute a sequence for estimating the kernel weights
    x <- seq(from = 0.0, to = (nobs - 1.0), by = 1.0) / bw
    wt <- matrix(data = NA_real_, nrow = nobs, ncol = 1L)

    # Compute the kernel weights using laq_seq
    kern_opt <- toupper(match.arg(kern_opt))

    switch (EXPR = kern_opt,
        "TR" = { wt[abs(x) <= 1.0] <- 1.0;                  # Truncated Kernel
                 wt <- wt[!is.na(wt)] },
        "BT" = { idx <- abs(x) <= 1.0;                      # Bartlett Kernel
                 wt[idx] <- 1.0 - abs(x[idx]);
                 wt <- wt[!is.na(wt)] },
        "PZ" = { PZ1 <- (abs(x) >= 0.0) & (abs(x) <= 0.5);  # Parzen Kernel
                 PZ2 <- (abs(x) > 0.5) & (abs(x) <= 1.0);
                 wt[PZ1] = 1.0 - 6.0 * x[PZ1]^2.0 + 6.0 * abs(x[PZ1])^3.0;
                 wt[PZ2] = 2.0 * (1.0 - abs(x[PZ2]))^3.0;
                 wt <- wt[!is.na(wt)] },
        "TH" = { idx <- abs(x) <= 1.0;                      # Tukey-Hanning Kernel
                 wt[idx] <- 0.5 * (1.0 - cos(pi * x[idx]));
                 wt <- wt[!is.na(wt)] },
        "QS" = { m <- (6.0 * pi * x) / 5.0;                 # Quadratic Spectral Kernel
                 wt <- 3.0 / (m^2.0) * (sin(m) / m - cos(m));
                 wt[x == 0] <- 1.0 }
    )

    return (wt)

}

####################################################################################################
# Main functions
####################################################################################################

# Function for performing regression with HAC covariance matrix
lm_hac <- function(y, x, intercept = TRUE, kern_opt = c("TR", "BT", "PZ", "TH", "QS"),
                   res_opt = c("EH", "EB", "ET", "ED", "EM", "ES", "FE"),
                   dbw_opt = TRUE, df_correct = TRUE, ...)
{
    # Do some preliminary things
    if (!is.matrix(y)) { y <- as.matrix(y) }
    if (!is.matrix(x)) { x <- as.matrix(x) }

    # Check data dimensions are conformable
    if (dim(y)[1L] != dim(x)[1L]) {
        stop("lm_hac(): Non conformable dimension.\n", call. = FALSE)
    }

    # Include an intercept?
    if (intercept) {
        x <- cbind(1.0, x)
    }

    # Get the selected kernel and residual
    kern_opt <- toupper(match.arg(kern_opt))
    res_opt <- toupper(match.arg(res_opt))

    # Get some useful values
    nobs <- dim(x)[1L]
    nvar <- dim(x)[2L]

    # Compute the QR decomposition which will be used for estimation
    qrstr <- qr(x = x)
    RRi <- chol2inv(x = qr.R(qr = qrstr, complete = FALSE))
    ht <- compute_leverage(qr = qrstr)

    # OLS Coefficients
    coefficients <- qr.coef(qr = qrstr, y = y)

    # Fitted values
    fitted <- qr.fitted(qr = qrstr, y = y)

    # Least Squared Residuals
    residuals <- qr.resid(qr = qrstr, y = y)

    # Compute the scores matrix
    if (res_opt == "FE") {
        xe <- fe_scores_matrix(y = y, x = x, intercept = FALSE, ...) # NB: 'intercept' option must be FALSE as handled elsewhere
    } else {
        rmat <- make_residuals_matrix(leverage = ht, ehat = residuals,
                                      nvar = nvar, res_opt = res_opt)
        xe <- x * rmat
    }

    # Compute the kernel weights, NB with WD's fixed interval St = m + 1
    nxe <- dim(xe)[1L]
    bw <- ifelse(test = dbw_opt,
                 yes = compute_auto_bw(xe, intercept, kern_opt),
                 no = compute_fixed_bw(nxe, "WD") + 1L)
    wt <- compute_kernel_weights(nxe, bw, kern_opt)
    wtn <- length(wt) - 1L # Minus 1 to prevent out of bounds error below

    # Lag zero...
    omega <- crossprod(x = xe, y = NULL)

    # ...Remaining lags
    for (j in seq_len(wtn)) {
        gamm <- crossprod(x = xe[(j + 1L):nxe, , drop = FALSE],
                          y = xe[1L:(nxe - j), , drop = FALSE])
        gamm <- gamm + t(gamm)
        omega <- omega + wt[j + 1L] * gamm
    }

    # HAC Variance-Covariance matrix sandwich estimator
    vcov <- RRi %*% omega %*% RRi

    # Apply a small sample degrees of freedom correction
    if (df_correct) {
        vcov <- (nxe * vcov) / (nxe - nvar)
    }

    # HAC-corrected standard errors for the estimated coefficients
    stderr <- sqrt(diag(vcov))

    # t-statistic and p-values (asymptotic standard normal) for estimated coefficients
    tstat <- coefficients / stderr
    pvalue <- compute_p_value(tstat)

    # Sum of Squared Residuals (SSR)
    ssr <- sum(square(residuals))

    # Estimated Residual Variance
    mse <- drop(ssr / (nobs - nvar))

    # Information Criterions
    loglik <- drop(-(nobs / 2.0) * (log(2.0 * pi) + 1.0) - (nobs / 2.0) * log(ssr / nobs))
    aic <- drop(log(ssr / nobs) + (nobs + 2.0 * nvar)  / nobs)
    aicc <- drop(log(ssr / nobs) + (nobs + nvar) / (nobs - nvar - 2.0))
    bic <- drop(log(ssr / nobs) + (nvar * log(nobs)) / nobs)

    # Measures of fit
    if (intercept) {
        rsq <- drop(1.0 - ssr / crossprod(x = (y - mean(y)), y = NULL))
        rsq_adj <- drop(1.0 - (1.0 - rsq)*((nobs - 1.0) / (nobs - nvar)))
    } else {
        rsq <- drop(1.0 - ssr / crossprod(x = y, y = NULL))
        rsq_adj <- drop(1.0 - (1.0 - rsq)*((nobs - 1.0) / (nobs - nvar)))
    }

    # Collect results as a list object
    results <- list()
    results$coefficients <- coefficients
    results$stderr <- stderr
    results$tstat <- tstat
    results$pvalue <- pvalue
    results$vcov <- vcov
    results$fitted.values <- fitted
    results$residuals <- residuals
    results$leverage <- ht
    results$ssr <- ssr
    results$mse <- mse
    results$loglik <- loglik
    results$aic <- aic
    results$aicc <- aicc
    results$bic <- bic
    results$rsq <- rsq
    results$rsq_adj <- rsq_adj
    results$kern_opt <- kern_opt
    results$res_opt <- res_opt
    results$dbw_opt <- dbw_opt
    results$bw <- bw
    results$nobs <- nobs
    results$nvar <- nvar
    results$intercept <- intercept

    # Return results with class "lm_hac"
    results$call <- match.call()
    class(results) <- "lm_hac"
    return (results)
}

# Accessor methods for class "lm_hac"
# Extract coefficients
coef.lm_hac <- function(object, ...)
{
    return (object$coefficients)
}

# Extract fitted values
fitted.lm_hac <- function(object, ...)
{
    return (object$fitted.values)
}

# Extract residuals
residuals.lm_hac <- function(object, ...)
{
    return (object$residuals)
}

# Extract robust variance-covariance matrix
vcov.lm_hac <- function(object, ...)
{
    return (object$vcov)
}

# Extract AIC
extractAIC.lm_hac <- function(fit, ...)
{
    return (fit$aic)
}

# Extract the log-likelihood function
logLik.lm_hac <- function(object, ...)
{
    return (object$loglik)
}

# Extract the number of observations
nobs.lm_hac <- function(object, ...)
{
    return (object$nobs)
}

# Predict method of "lm_hac"
predict.lm_hac <- function(object, newdata)
{
    # Check if there is any new data
    if (missing(newdata) || is.null(newdata)) {

        # Fitted values
        pred <- object$fitted.values

    } else {

        # Preliminary checks
        if (!is.matrix(newdata)) { newdata <- as.matrix(newdata) }

        if (object$nvar != ifelse(test = object$intercept,
                                  yes = (dim(newdata)[2L] + 1L),
                                  no = dim(newdata)[2L])) {
            stop("predict(): Non conformable dimension.\n", call. = FALSE)
        }

        # Predicted values
        if (object$intercept) {
            pred <- (newdata %*% object$coefficients[2L:object$nvar]) + object$coefficients[1L]
        } else {
            pred <- newdata %*% object$coefficients
        }
    }

    return (pred)

}

# Print method of "lm_hac"
print.lm_hac <- function(x, digits = 4L, print.gap = 3L, right = TRUE, ci_alpha = 0.05, ...)
{
    # Compute some preliminary things
    nvar <- x$nvar
    results <- t(x$coefficients)

    # Specify the row and column labels
    rownames(results) <- ""
    colnames(results) <- paste0('B', seq_len(nvar))

    # Print the results
    cat("\nCall: ", paste(deparse(x$call), sep = '\n', collapse = '\n'), '\n', sep = "")
    cat("\nCoefficients:\n")
    print.default(results, digits = digits, print.gap = print.gap, right = right, ...)
    cat('\n')
    invisible(x)
}

# Summary method of "lm_hac"
summary.lm_hac <- function(object, ci_size = 0.05)
{
    # Do some preliminary things
    nvar <- object$nvar
    zs <- qnorm(p = ci_size / 2.0, lower.tail = FALSE)
    width <- (1.0 - ci_size) * 100

    # Assemble the OLS estimation results
    output <- cbind(object$coefficients,
                    object$stderr,
                    object$tstat,
                    object$pvalue,
                    object$coefficients - zs * object$stderr,
                    object$coefficients + zs * object$stderr)

    # Specify the row and column labels
    rownames(output) <- seq_len(nvar)
    colnames(output) <- c("Coefficient", "Std. Err.", "t-stat.", "p-value",
                          sprintf("-%2.0f%% C.I.", width), sprintf("+%2.0f%% C.I.", width))

    bw_type <- ifelse(test = object$dbw_opt, yes = "data dependent", no = "fixed interval")

    # Collect results as a list object
    results <- list()
    results$output <- output
    results$se <- sqrt(object$mse)
    results$rsq <- object$rsq
    results$rsq_adj <- object$rsq_adj
    results$kern_opt <- object$kern_opt
    results$res_opt <- object$res_opt
    results$bw_type <- bw_type
    results$bw <- object$bw

    # Return results with class "summary.lm_hac"
    class(results) <- paste("summary", class(object), sep = '.')
    return (results)
}

# Print method of "summary.lm_hac"
print.summary.lm_hac <- function(x, digits = max(3L, getOption("digits") - 3L),
                                  print.gap = 3L, right = TRUE, ...)
{
    # Print the results
    cat("\nRegression Results with HAC Corrected Standard Errors\n")
    print.default(x$output, digits = digits, print.gap = print.gap, right = right, ...)
    cat('\n')
    cat(sprintf("HAC options: %s kernel, %s residuals, and %s bandwidth = %g\n", x$kern_opt, x$res_opt, x$bw_type, x$bw))
    cat(sprintf("Regression standard error: %4.6g\n", x$se))
    cat(sprintf("R-squared coefficient: %4.6g\n", x$rsq))
    cat(sprintf("Adjust. R-squared coefficient: %4.6g", x$rsq_adj))
    cat('\n')
    invisible(x)
}

# Wald Test for linear restrictions
wald_test <- function(x, rmat, qvec)
{
    # Check if x is of class 'lm_hac'
    if (class(x) != "lm_hac") {
        stop("wald_test(): x not of class \'lm_hac\'.\n", call. = FALSE)
    }

    # Check that data dimensions are conformable
    if ((dim(rmat)[2L] != x$nvar) || (length(qvec) != dim(rmat)[1L])) {
        stop("wald_test(): Non-conformable dimension.\n", call. = FALSE)
    }

    # Get some useful values
    mvec <- (rmat %*% x$coefficients) - qvec
    rvri <- qr.solve(rmat %*% x$vcov %*% t(rmat))

    # Compute test statistic
    #statistic <- x$nobs * as.numeric(t(mvec) %*% rvri %*% mvec)
    statistic <- drop(t(mvec) %*% rvri %*% mvec) # don't need to multiply by T

    # Compute p-value
    pvalue <- pchisq(q = statistic, df = length(qvec), lower.tail = FALSE)

    # Return results as a list object with class 'wald'
    results <- list()
    results$statistic <- statistic
    results$pvalue <- pvalue
    results$call <- match.call()
    class(results) <- "wald"
    return (results)
}

# Print method for class 'wald'
print.wald <- function(x, digits = 4L, print.gap = 3L, right = TRUE, ...)
{
    cat("\nCall: ", paste(deparse(x$call), sep = '\n', collapse = '\n'), '\n', sep = "")
    cat("\nWald Test for Linear Restrictions:\n\n")
    cat(sprintf("Test statistic:\t\t %2.4f\n", x$statistic))
    cat(sprintf("P-value:\t\t %2.4f\n", x$pvalue))
    cat('\n')
    invisible(x)
}

# EOF
