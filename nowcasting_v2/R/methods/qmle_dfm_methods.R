####################################################################################################
# Estimate a Dynamic Factor Model via the Expectation-Maximisation (EM) Algorithm
####################################################################################################
# PURPOSE:
#   These codes estimate a dynamic factor model in state space form using the EM algorithm.
#
#   The general model is:
#       x_t = C * F_t + e_t,             e_t ~ N(0, R)
#       F_t = A * F_t-1 + G * U_t,       U_t ~ N(0, Q)
#   with:
#       C = [C_0,...,C_s]
#       F_t = [f_t,...,f_t-s]
#       f_t = a_1 * f_t-1 + ... + a_p * f_t-p + u_t
#
#   Identifcation:
#       The dynamic factor model defined above is not identified without further
#       restrictions since one can always premultiply the dynamic factor f_t with an
#       arbitrary full rank q x q matrix to define a new model.
#
#       To overcome this Bai and Wang (2015) propose two identifying restrictions.
#
#       Let C = [C_0, C_1], where C_0 is a q x q matrix, then:
#
#       [1] "DFM1" - var(U_t) = I_q and the q x q matrix C_0 is a lower
#           diagonal matrix with strictly positive diagonal elements
#           NB: I implement the suggested variation of DFM1 in which var(U_t) is
#           diagonal and C_0 has 1's along the main diagonal.
#
#       [2] "DFM2" - The q x q block C_0 is an identity matrix: C = [I_q, *]
#
#       Two additional options that can be used include:
#
#       [3] "FSTD" - var(U_t) = I_q (as originally specified in Doz, Giannone and Reichlin, 2012)
#
#       [4] "NA"   - No normalisation. Suitable if the factors will be used in forecasting
#
# NOTES:
#   The observation series, x_t, can have an arbitrary number of missing observations (must be coded as 'NA')
#
# REFERENCES:
#   Bai, J. and Ng, S. (2013), "Principal Components Estimation and Identification of
#       Static Factors", Journal of Econometrics, Vol. 176, No. 1, pp. 18--29.
#
#   Bai, J. and Wang, P. (2015), "Identification and Bayesian Estimation of Dynamic factor Models",
#       Journal of Business & Economic Statistics, Vol. 33, Issue 2, pp 221--240.
#
#   Banbura, M. and Modugno, M. (2014), "Maximum Likelihood Estimation of Factor Models on Datasets
#       with Arbitrary Pattern of Missing Data", Journal of Applied Econometrics, Vol. 29, No. 1,
#       pp. 133--160.
#
#   Coroneo, L., Giannone, D., and Modugno, M. (2016), "Unspanned Macroeconomic Factors in the
#       Yield Curve", Journal of Business & Economic Statistics, Vol. 34, No. 3, pp. 472--485.
#
#   Doz, C., Giannone, D., and Reichlin, L. (2011), "A Two-Step Estimator for Large Approximate
#       Dynamic Factor Models based on Kalman Kiltering", Journal of Econometric, Vol. 164, Issue 1,
#       pp. 188--205.
#
#   Doz, C., Giannone, D., and Reichlin, L. (2012), "A Quasi Maximum Likelihood approach for Large
#       Approximate Dynamic Factor Models", The Review of Economics and Statistics, Vol. 94, No. 4,
#       pp. 1014--1024.
#
#   Durbin, J., and Koopman, S. J. (2012), "Time Series Analysis by State Space Methods",
#       (Second Edition). Oxford University Press.
#
#   Ghahramani, Z., and Hinton, G. (1996), "Parameter Estimation for Linear Dynamical Systems",
#       Technical Report CRG-TR-96-2, Department of Computer Science, University of Toronto.
#
#   Stock, J. H. and Watson, M. W. (2016), "Factor Models and Structural Vector Autoregressions
#       in Macroeconomics", Manuscript prepared for the Handbook of Macreconomics.
#
# AUTHOR:
#   Luke Hartigan (2024)
#   luke.hartigan(at)gmail(dot)com
#
####################################################################################################
# Helper functions used by the state space functions below
####################################################################################################

# Compute the inverse of a matrix using the Cholesky factorisation
chol_inv <- function(x)
{
    return (chol2inv(x = chol(x = x)))
}

# R emulation of MATLAB eye(N)
eye <- function(n)
{
    return (diag(x = 1, nrow = n))
}

# Return a column vector of ones with number of elements n
iota <- function(n)
{
    return (matrix(data = 1.0, nrow = n, ncol = 1L))
}

# Compute the quadratic form x' * A * x
quad_form <- function(mat, vec)
{
    # Preliminary stuff
    if (!is.matrix(mat)) { mat <- as.matrix(mat) }
    if (!is.matrix(vec)) { vec <- as.matrix(vec) }

    # Check argument dimensions are conformable
    if (dim(mat)[1L] != length(vec)) {
        stop("quad_form(): Non conformable dimension.\n", call. = FALSE)
    }

    # Calculate x'Ax using R's inbuilt matrix operations
    return (as.numeric(crossprod(x = crossprod(x = mat, y = vec), y = vec)))
}

# Compute the log of the determinant of a matrix using the LU decomposition
log_det <- function(x)
{
    if (!is.matrix(x)) { x <- as.matrix(x) }
    ld <- unlist(determinant(x = x, logarithm = TRUE))
    return (as.numeric(ld[1L] * ld[2L]))
}

# Compute lag matrix with dimensions (T - p, N * p)
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

# R emulation of MATLAB reshape(A, M, N, ...)
mreshape <- function(data, ...)
{
    dim(data) <- c(...)
    return (data)
}

# R emulation of MATLAB ones()
ones <- function(...)
{
    return (array(data = 1, dim = c(...)))
}

# R emulation of MATLAB repmat(A, M, N)
repmat <- function(mat, m, n)
{
    return (kronecker(matrix(data = 1, nrow = m, ncol = n), mat))
}

# Create a column vector from an array 'x'
vec <- function(x)
{
    return (matrix(data = c(x), nrow = length(x)))
}

# Create a column vectir from a symmetric matrix by retaining only the
# lower triangular part of array 'x'
vech <- function(x, diag_opt = TRUE)
{
    if (!is.matrix(x)) { x <- as.matrix(x) }
    n <- dim(x)[1L]
    idx <- lower.tri(x = x, diag = diag_opt)
    return (matrix(data = x[idx], nrow = (n * (n + 1L)/2L)))
}

# R emulation of MATLAB zeros()
zeros <- function(...)
{
    return (array(data = 0, dim = c(...)))
}

####################################################################################################
# Main functions
####################################################################################################

# Modified version of the Bai and Ng (2002) information criterion based
# on the convergence rate for the QMLE-based DFM estimates (Doz et al, 2012)
mod_bnic <- function(x, kmax, scale_opt = TRUE)
{
    # Preliminary settings and calculate some useful values
    if (missing(x) || missing(kmax)) {
        stop("mod_bnic(): Too few input arguments.\n", call. = FALSE)
    }

    # Compute some useful quantities
    if (!is.matrix(x)) { x <- as.matrix(x) }
    tobs <- dim(x)[1L]
    nvar <- dim(x)[2L]
    nti <- (nvar * tobs)^-1.0
    c2nt <- min(sqrt(tobs), (nvar / log(nvar)))

    # Check that 'kmax' is not greater than the dimension of the data
    if (kmax > min(nvar, tobs)) {
        stop("mod_bnic(): kmax higher than dimension.\n", call. = FALSE)
    }

    # Results storage
    k_vec <- seq_len(kmax)
    PC <- rep(NA_real_, kmax)
    IC <- rep(NA_real_, kmax)

    # Modified penalty function for QMLE-DFM (see Coroneo et al, 2014)
    g <- k_vec * (log(c2nt) / c2nt)

    # Standardise data before testing for the number of static factors
    if (scale_opt) {
        x <- scale(x = x, center = TRUE, scale = TRUE)
    }

    # Estimate Sum of Squared Residuals for k_max factors
    if (tobs > nvar) {
        # PCA of matrix X'X/NT
        eigval <- eigen(x = crossprod(x = x, y = NULL) * nti, symmetric = TRUE, only.values = TRUE)$values

        # Vkmax (residual sum of squares)
        Vkmax <- sum(eigval) - sum(eigval[seq_len(kmax)])

        # Calculate PCp and ICp for 1,...,kmax
        for (i in k_vec) {
            # Vi (residual sum of squares)
            Vi <- sum(eigval) - sum(eigval[seq_len(i)])

            # PC and IC
            PC[i] <- Vi + Vkmax * g[i]
            IC[i] <- log(Vi) + g[i]
        }

    } else {
        # PCA of matrix XX'/NT
        eigval <- eigen(x = tcrossprod(x = x, y = NULL) * nti, symmetric = TRUE, only.values = TRUE)$values

        # Vkmax (residual sum of squares)
        Vkmax <- sum(eigval) - sum(eigval[seq_len(kmax)])

        # Calculate PCp and ICp for 1,...,kmax
        for (i in k_vec) {
            # Vi (residual sum of squares)
            Vi <- sum(eigval) - sum(eigval[seq_len(i)])

            # PC and IC
            PC[i] <- Vi + Vkmax * g[i]
            IC[i] <- log(Vi) + g[i]
        }
    }

    # Determine which is the minimum and get the index position
    PCp <- which.min(PC)
    ICp <- which.min(IC)

    # Return results as a list object with class "bnic"
    results <- list()
    results$PCp <- PCp
    results$ICp <- ICp
    results$call <- match.call()
    class(results) <- c("mod_bnic", "bnic")
    return (results)
}

# Print method for "mod_bnic/bnic"
print.bnic <- function(x, digits = max(3L, getOption("digits") - 3L), ...)
{
    cat("\nCall: ", paste(deparse(x$call), sep = "\n", collapse = "\n"), "\n", sep = "")
    cat("\nBai & Ng (2002) Criterion for Determining the Number of Static Factors:\n\n")
    cat(sprintf("Penalty %s:\n\n", x$penalty))
    cat(sprintf("PCp = %d ; ICp = %d\n", x$PCp, x$ICp))
    cat('\n')
}

# Remove NA implementation
.rm_na_impl <- function(x, fn)
{
    cn <- fn(x = x, na.rm = TRUE)
    x[is.na(x)] <- cn
    return (x)
}

# Function to handle NA values
remove_na_values <- function(x, na_opt = c("exclude", "mean", "median", "zero"))
{
    # Do we have any NA values?
    if (any(is.na(x))) {

        # Compute a few useful values
        if (!is.matrix(x)) { x <- as.matrix(x) }

        # Compute the type of NA adjustment
        na_opt <- match.arg(na_opt)

        switch(EXPR = na_opt,
            # Remove all rows containing NAs
            "exclude" = { x <- na.exclude(x) },
            # Replace NAs in each column with column mean
            "mean" = { x <- apply(X = x, MARGIN = 2L,
                                  FUN = .rm_na_impl, fn = mean) },
            # Replace NAs in each column with column median
            "median" = { x <- apply(X = x, MARGIN = 2L,
                                    FUN = .rm_na_impl, fn = median) },
            # Replace NAs with zero
            "zero" = { x[is.na(x)] <- 0.0 }
        )

    }

    return (x)

}

# Extract static factors from the panel 'x' via the method of Principal Components (using SVD)
pc_factor <- function(x, r, norm_opt = c("NA", "LN", "FN"),
                      scale_opt = TRUE, sign_opt = TRUE, vardec_opt = FALSE)
{
    # Preliminary settings and calculate some useful values
    if (missing(x) || missing(r)) {
        stop("pc_factor(): Too few input arguments\n", call. = FALSE)
    }

    # Compute some useful quantities
    if (!is.matrix(x)) { x <- as.matrix(x) }
    nobs <- dim(x)[1L]
    nvar <- dim(x)[2L]
    nti <- 1.0 / (nvar * nobs)

    # Check that 'r' not greater than dimension of data
    if (r > min(nobs, nvar)) {
        stop("pc_factor(): Number of static factors higher than dimension.\n", call. = FALSE)
    }

    # Set up the value for 'norm_opt' if the default value "NA" is selected
    norm_opt <- toupper(match.arg(norm_opt))
    if (norm_opt == "NA") {
        if (nobs > nvar) {
            norm_opt <- "LN"
        } else {
            norm_opt <- "FN"
        }
    }

    # Standardise data before extracting static factors
    if (scale_opt) {
        x <- scale(x = x, center = TRUE, scale = TRUE)
    }

    # Normalisation option 1: L'L/N = I_r normalisation (F'F is a diagonal matrix).
    # This option is recommended for cases were tobs > nvar
    if (norm_opt == "LN") {
        # PCA of matrix X'X/NT
        pc <- svd(x = crossprod(x = x, y = NULL) * nti)
        loadings <- pc$u[, seq_len(r), drop = FALSE] * sqrt(nvar)
        # Flip sign for more sensible output
        if (sign_opt) {
            mask <- colSums(loadings) < 0.0
            loadings[, mask] <- -loadings[, mask]
        }
        factors <- (x %*% loadings) / nvar
    }

    # Normalisation option 2: F'F/T = I_r normalisation (L'L is a diagonal matrix)
    # This option is recommended for cases were tobs < nvar
    if (norm_opt == "FN") {
        # PCA of matrix XX'/NT
        pc <- svd(x = tcrossprod(x = x, y = NULL) * nti)
        factors <- pc$u[, seq_len(r), drop = FALSE] * sqrt(nobs)
        # Flip sign for more sensible output
        if (sign_opt) {
            mask <- colSums(factors) < 0.0
            factors[, mask] <- -factors[, mask]
        }
        loadings <- crossprod(x = x, y = factors) / nobs
    }

    # Sum of squared errors
    ssr <- sum(pc$d) - sum(pc$d[seq_len(r)])

    # Collect results as a list object
    results <- list()
    results$factors <- factors
    results$loadings <- loadings
    results$ssr <- ssr

    # Optional return: variance explained by each factor
    if (vardec_opt) {

        explvar <- round((pc$d / sum(pc$d)) * 100.0, 2)
        cumR2 <- cumsum(explvar)
        vardec <- cbind(explvar, cumR2)
        colnames(vardec) <- c("Explvar", "CumR2")
        rownames(vardec) <- seq_len(length(pc$d))
        results$vardec <- vardec

    }

    # Return results with class "pcfac"
    results$call <- match.call()
    class(results) <- "pcfac"
    return (results)

}

# Kalman filtering algorithm
kalman_filter <- function(x, C, R, A, Q, G, x0, P0)
{
    # Compute some useful quantities
    if (!is.matrix(x)) { x <- as.matrix(x) }
    nobs <- dim(x)[1L]
    nvar <- dim(x)[2L]
    nstate <- dim(A)[1L]
    y <- t(x)

    # Pre-allocate memory for all arrays
    xp <- zeros(nstate, nobs)
    xf <- zeros(nstate, nobs)
    Pp <- zeros(nstate, nstate, nobs)
    Pf <- zeros(nstate, nstate, nobs)

    # Pre-allocate memory for the log-likelihood
    logl <- zeros(nobs)
    loglik <- 0.0
    const <- log(2.0 * base::pi)

    # Compute a few things outside of the loop
    invR <- diag(x = (1.0 / diag(x = R)), nrow = nvar)
    GQG <- G %*% Q %*% t(G)
    In <- eye(nstate)

    # t = 1
    # Check for any NAs
    mask <- !is.na(y[, 1L])
    W <- eye(nvar)
    Wt <- W[mask, , drop = FALSE]

    # Prediction equations
    xp[, 1L] <- A %*% x0
    Pp[, , 1L] <- A %*% P0 %*% t(A) + GQG
    y[!mask, 1L] <- 0.0                                     # set NA values to be zero
    vt <- Wt %*% (y[, 1L] - C %*% xp[, 1L])                 # prediction error

    # Compute invFt directly using the Woodbury matrix identity
    CRC <- t(C) %*% t(Wt) %*% Wt %*% invR %*% t(Wt) %*% Wt %*% C
    invFt <- Wt %*% (invR - invR %*% C %*% MASS::ginv(MASS::ginv(Pp[, , 1L]) + CRC) %*% t(C) %*% invR) %*% t(Wt)

    # Correction equations
    Kt <- Pp[, , 1L] %*% t(C) %*% t(Wt) %*% invFt           # Kalman Gain
    xf[, 1L] <- xp[, 1L] + Kt %*% vt
    Pf[, , 1L] <- (In - Kt %*% Wt %*% C) %*% Pp[, , 1L]

    # Compute the log-likelihood function
    logdetFt <- sum(log(diag(Wt %*% R %*% t(Wt)))) + log_det(x = Pp[, , 1L]) +
        log_det(x = MASS::ginv(Pp[, , 1L]) + CRC)
    mahaldist <- quad_form(mat = invFt, vec = vt)
    logl[1L] <- -0.5 * (sum(as.double(mask)) * const + logdetFt + mahaldist)

    # t = 2,...,T
    for (i in 2L:nobs) {

        # Check for any NAs
        mask <- !is.na(y[, i])
        W <- eye(nvar)
        Wt <- W[mask, , drop = FALSE]

        # Check if there are any observations for this time period
        if (all(!mask)) {

            # No observations for the current period; project the existing state forward
            xf[, i] <- xp[, i]
            Pf[, , i] <- Pp[, , i]

        } else {

            # There are observations for the current period
            # Prediction equations
            xp[, i] <- A %*% xf[, i - 1L]
            Pp[, , i] <- A %*% Pf[, , i - 1L] %*% t(A) + GQG
            y[!mask, i] <- 0.0                              # set NA values to be zero
            vt <- Wt %*% (y[, i] - C %*% xp[, i])           # prediction error

            # Compute invFt directly using the Woodbury matrix identity
            CRC <- t(C) %*% t(Wt) %*% Wt %*% invR %*% t(Wt) %*% Wt %*% C
            invFt <- Wt %*% (invR - invR %*% C %*% MASS::ginv(MASS::ginv(Pp[, , i]) + CRC) %*% t(C) %*% invR) %*% t(Wt)

            # Correction equations
            Kt <- Pp[, , i] %*% t(C) %*% t(Wt) %*% invFt    # Kalman Gain
            xf[, i] <- xp[, i] + Kt %*% vt
            Pf[, , i] <- (In - Kt %*% Wt %*% C) %*% Pp[, , i]

            # Compute the log-likelihood function
            logdetFt <- sum(log(diag(Wt %*% R %*% t(Wt)))) + log_det(x = Pp[, , i]) +
                log_det(x = MASS::ginv(Pp[, , i]) + CRC)
            mahaldist <- quad_form(mat = invFt, vec = vt)
            logl[i] <- -0.5 * (sum(as.double(mask)) * const + logdetFt + mahaldist)

        }
    }

    # Sum of the log-likelihood
    loglik <- sum(logl)

    # Collect results as a list object
    results <- list()
    results$xp <- xp
    results$Pp <- Pp
    results$xf <- xf
    results$Pf <- Pf
    results$Kt <- Kt
    results$Wt <- Wt
    results$loglik <- loglik

    # Return results with class "kf"
    class(results) <- "kf"
    return (results)
}

# Rauch-Tung-Striebel (RTS) Smoothing (fixed interval) algorithm adapted to
# compute the lag-one covariance smoother needed in the EM algorithm
rts_smoother <- function(xp, Pp, xf, Pf, Kt, C, A, Wt = NULL)
{
    # Compute some useful quantities
    nobs <- dim(xf)[2L]
    nstate <- dim(A)[1L]
    In <- eye(nstate)
    if (!is.null(Wt)) { C <- Wt %*% C }

    # Pre-allocate memory for all arrays
    Jt <- zeros(nstate, nstate, nobs)
    xs <- zeros(nstate, nobs)
    Ps <- zeros(nstate, nstate, nobs)
    Pcs <- zeros(nstate, nstate, nobs)

    # t = T (Initial values for smoothed state and covariance)
    xs[, nobs] <- xf[, nobs]
    Ps[, , nobs] <- Pf[, , nobs]
    Pcs[, , nobs] <- (In - Kt %*% C) %*% A %*% Pf[, , nobs - 1L]

    # t = T-1,...,1 (Compute the rest of the values)
    for (i in (nobs - 1L):1L) {
        Jt[, , i] <- Pf[, , i] %*% t(A) %*% MASS::ginv(Pp[, , i + 1L])
        xs[, i] <- xf[, i] + Jt[, , i] %*% (xs[, i + 1L] - xp[, i + 1L])
        Ps[, , i] <- Pf[, , i] + Jt[, , i] %*% (Ps[, , i + 1L] - Pp[, , i + 1L]) %*% t(Jt[, , i])
    }

    # Lag 1 Covariance smoother
    for (i in (nobs - 1L):2L) {
        Pcs[, , i] <- Pf[, , i] %*% t(Jt[, , i - 1L]) +
            Jt[, , i] %*% (Pcs[, , i + 1L] - A %*% Pf[, , i]) %*% t(Jt[, , i - 1L])
    }

    # Collect results as a list object
    results <- list()
    results$xs <- xs
    results$Ps <- Ps
    results$Pcs <- Pcs

    # Return results with class "rts"
    class(results) <- "rts"
    return (results)
}

# Run the filter-smoother recursions
run_fs_recursions <- function(x, C, R, A, Q, G, x0, P0)
{
    # Compute the expected values via the KF-KS recursions
    kf <- kalman_filter(x = x, C = C, R = R, A = A, Q = Q, G = G, x0 = x0, P0 = P0)
    sm <- rts_smoother(xp = kf$xp, Pp = kf$Pp, xf = kf$xf, Pf = kf$Pf,
                       Kt = kf$Kt, C = C, A = A, Wt = kf$Wt)

    # Collect results as a list object
    results <- list()
    results$xs <- sm$xs
    results$Ps <- sm$Ps
    results$Pcs <- sm$Pcs
    results$loglik <- kf$loglik

    # Return results
    return (results)
}

# Initialise model parameters for the Kalman filter-smoother recursions
param_init <- function(x, q, s, p, id_opt = c("DFM1", "DFM2", "FSTD", "NA"),
                       na_opt = c("exclude", "replace"),
                       scale_opt = TRUE, sign_opt = FALSE)
{
    # Preliminary setting
    if(!is.matrix(x)) { x <- as.matrix(x) }

    # Set up the value for 'id_opt'
    id_opt <- toupper(match.arg(id_opt))

    # Standardise the panel if requested
    if (scale_opt) {
        x <- scale(x = x, center = TRUE, scale = TRUE)
    }

    # Set up the value for 'na_opt'
    na_opt <- tolower(match.arg(na_opt))
    x <- remove_na_values(x = x, na_opt = na_opt)

    # Compute some useful quantities
    nobs <- dim(x)[1L]
    nvar <- dim(x)[2L]
    r <- q * (s + 1L)
    qp <- q * p
    k <- max(p, s + 1L)
    qk <- q * k

    # Extract the first q PC factors from the adjusted panel
    pc <- pc_factor(x = x, r = q, norm_opt = "NA",
                    scale_opt = scale_opt, sign_opt = sign_opt)

    # Re-normalise signs of the factors
    sign_norm <- sign(x = diag(x = as.matrix(pc$loadings[seq_len(q), seq_len(q)])))
    pc_factors <- pc$factors %*% diag(x = sign_norm, nrow = q)

    # Compute the VAR coefficients
    lag_factors <- lag_mat(x = pc_factors, nlags = k)
    factors <- tail(x = pc_factors, n = (nobs - k))         # Factors are now T-k x q

    # Transition matrix for the KFS recursions
    A <- zeros(qk, qk)

    # Estimate a reduced form VAR: F_t = A * F_t-1 + u_t
    qrfac <- qr(x = lag_factors)
    coef <- qr.coef(qr = qrfac, y = factors)                # Estimate coefficients using OLS
    A[seq_len(q), seq_len(qp)] <- t(coef[seq_len(qp), seq_len(q)])
    if (qk > q) {
        A[(q + 1L):qk, 1L:(qk - q)] <- eye(qk - q)          # VAR companion matrix
    }
    u <- qr.resid(qr = qrfac, y = factors)                  # VAR residuals

    # Estimate the dynamic factors and associated loadings
    dyn_factors <- cbind(factors, lag_factors)[, seq_len(r)]
    invFtF <- chol_inv(x = crossprod(x = dyn_factors, y = NULL))
    Ftx <- t(crossprod(x = dyn_factors, y = tail(x = x, n = (nobs - k))))
    dyn_loadings <- Ftx %*% invFtF

    # Common component of the panel
    chi <- dyn_factors %*% t(dyn_loadings)

    # Idiosyncratic component of the panel (i.e. residuals)
    xi <- tail(x = x, n = (nobs - k)) - chi

    # Measurement noise covariance matrix for the KFS recursions (assumed to be diagonal)
    R <- diag(x = apply(X = xi, MARGIN = 2L, FUN = var, na.rm = TRUE), nrow = nvar)

    # Measurement matrix for KFS recursions
    C <- zeros(nvar, qk)

    # Impose one of the identifying restrictions from Bai and Wang (2015)
    # by constraining the factor loadings using the expression: M %*% vec(C) = hvec
    switch(EXPR = id_opt,
        # The q x q block of C is lower triangular with 1's along the main diagonal
        # and Q is a diagonal matrix
        "DFM1" = { m <- q * (q + 1L) / 2L;
                   seq_idx <- seq_len(m);
                   seq_jdx <- which(x = upper.tri(x = pc$loadings, diag = TRUE))
                   M <- zeros(m, nvar * r);
                   hvec <- as.matrix(eye(q)[upper.tri(x = eye(q), diag = TRUE)]);
                   # Build up the selector matrix M
                   for (i in seq_idx) {
                       j <- seq_jdx[i]
                       M[i, j] <- 1.0
                   }
                   Cvec <- vec(Ftx %*% invFtF) +
                           (invFtF %x% R) %*% t(M) %*%
                           MASS::ginv(M %*% (invFtF %x% R) %*% t(M)) %*%
                           (hvec - M %*% vec(Ftx %*% invFtF))
                   Q <- diag(x = diag(x = cov(u)), nrow = q)
                 },
        # The q x q block of C is an identity matrix I_q and Q is unrestricted
        "DFM2" = { m <- q^2L;
                   seq_idx <- seq(from = 1L, to = m, by = q);
                   seq_jdx <- seq(from = 1L, to = (nvar * r), by = nvar);
                   M <- zeros(m, nvar * r);
                   hvec <- vec(eye(q));
                   # Build up the selector matrix M
                   for (k in seq_len(length(seq_idx))) {
                       i <- seq_idx[k]
                       j <- seq_jdx[k]
                       M[i:(i + q - 1L), j:(j + q - 1L)] <- eye(q)
                   }
                   Cvec <- vec(Ftx %*% invFtF) +
                           (invFtF %x% R) %*% t(M) %*%
                           MASS::ginv(M %*% (invFtF %x% R) %*% t(M)) %*%
                           (hvec - M %*% vec(Ftx %*% invFtF))
                   Q <- cov(u)
                 },
        # Q is an identity matrix I_q
        "FSTD" = { Cvec <- vec(Ftx %*% invFtF);
                   Q <- eye(q)
                 },
        # No identification restriction
        "NA" = { Cvec <- vec(Ftx %*% invFtF);
                 Q <- cov(u)
               }
    )

    # Constrained factor loadings based on id_opt
    C[, seq_len(r)] <- mreshape(Cvec, nvar, r)

    # State noise covariance matrix for the KFS recursions
    G <- zeros(qk, q)
    G[seq_len(q), seq_len(q)] <- eye(q)

    # Constrained state noise covariance matrix based on id_opt
    GQG <- G %*% Q %*% t(G)

    # Set up the initial state mean and covariance for the KFS recursions
    # Initial state mean assuming a stationary distribution
    x0 <- mreshape(data = c(colMeans(factors), colMeans(lag_factors)[seq_len(qk - q)]), qk, 1L)

    # Initial state covariance assuming a stationary distribution
    P0 <- mreshape(MASS::ginv(eye(qk^2) - (A %x% A)) %*% vec(GQG), qk, qk)

    # Collect results as a list object
    results <- list()
    results$C <- C
    results$R <- R
    results$A <- A
    results$Q <- Q
    results$G <- G
    results$x0 <- x0
    results$P0 <- P0

    # Return results
    return (results)
}

# Define a stopping criteria for estimating the likelihood function using state-space forms
em_converged <- function(loglik, prior_loglik, threshold = 1E-5, check_increased = TRUE)
{
    # Preliminary setting
    converged <- FALSE
    decreased <- FALSE

    if (check_increased) {
        if (loglik - prior_loglik < -1E-3) {
            cat(sprintf("-- Log-likelihood function decreased from %g to %g --\n",
                prior_loglik, loglik))
            decreased <- TRUE
        }
    }

    delta_loglik <- abs(loglik - prior_loglik)
    avg_loglik <- (abs(loglik) + abs(prior_loglik) + .Machine$double.eps) / 2.0
    ratio <- delta_loglik / avg_loglik

    if (ratio < threshold) {
        converged <- TRUE
    }

    # Collect results as a list object
    results <- list()
    results$converged <- converged
    results$decreased <- decreased

    # Return results
    return (results)
}

# Run the Expectation-Maximisation algorithm and compute updated parameter values
em_step <- function(y, C, R, A, Q, G, x0, P0, q, s, p,
                    id_opt = c("DFM1", "DFM2", "FSTD", "NA"))
{
    # Compute a few useful values, NB: y == t(x) and is N * T
    if (!is.matrix(y)) { y <- as.matrix(y) }
    nvar <- dim(y)[1L]
    nobs <- dim(y)[2L]
    nstate <- dim(A)[1L]
    r <- q * (s + 1L)
    qp <- q * p
    k <- max(p, s + 1L)
    qk <- q * k

    # Set up the value for 'id_opt'
    id_opt <- toupper(match.arg(id_opt))

    # Set all NA observations to zero
    mask <- !is.na(y) # non-missing
    y[!mask] <- 0.0

    # Run the Kalman filter and RTS smoother recursions to compute:
    # xs = E[x_t | y_T]
    # Ps = Cov[x_t | y_T]
    # Pcs = Cov[x_t, x_t-1 | y_T] t >= 2
    # loglik = sum{t=1}{T} log(f(y_t))

    # Compute the expected values via the KF-RTS-S recursions
    fs <- run_fs_recursions(x = t(y), C = C, R = R, A = A,
                            Q = Q, G = G, x0 = x0, P0 = P0)

    # E-step
    # Compute the expected sufficient statistics:
    # xxt = sum_{t=1}^{T} [x_t * x'_t]
    # xx1 = sum_{t=1}^{T} [x_t-1 * x'_t-1]
    # xx2 = sum_{t=1}^{T} [x_t * x'_t]
    # xxt_1 = sum_{t=1}^{T} [x_t * x'_t-1]
    # yxt = sum_{t=1}^{T} [y_t * x'_t]

    xxt <- zeros(nstate, nstate)
    xxt_1 <- zeros(nstate, nstate)
    yxt <- zeros(nvar, nstate)

    for (i in seq_len(nobs)) {
        xxt <- xxt + tcrossprod(x = fs$xs[, i], y = fs$xs[, i]) + fs$Ps[, , i]
        yxt <- yxt + tcrossprod(x = y[, i], y = fs$xs[, i])
    }

    xx1 <- xxt - tcrossprod(x = fs$xs[, nobs], y = fs$xs[, nobs]) - fs$Ps[, , nobs]
    xx2 <- xxt - tcrossprod(x = fs$xs[, 1L], y = fs$xs[, 1L]) - fs$Ps[, , 1L]

    for (i in 2L:nobs) {
        xxt_1 <- xxt_1 + tcrossprod(x = fs$xs[, i], y = fs$xs[, i - 1L]) + fs$Pcs[, , i]
    }

    # M-step
    # Compute the parameters of the model as a function of the sufficient statistics
    # The formulas for the parameters derive from the maximum likelihood method
    # In the EM algorithm we substitute in the ML estimator the sufficient statistics
    # (computed in the E-step) and then re-evaluate the procedure until the likelihood is maximised

    # A = (sum_{t=2}^{T} [x_t * x'_t-1]) * (sum_{t=1}^{T} [x_t-1 * x'_t-1])^-1
    An <- xxt_1[seq_len(q), seq_len(qp)] %*% MASS::ginv(xx1[seq_len(qp), seq_len(qp)])
    A[seq_len(q), seq_len(qp)] <- An

    # Q = ((sum_{t=2}^{T} [x_t * x'_t]) - A * (sum_{t=1}^{T} [x_t-1 * x'_t])) / T-1
    Qn <- (xx2[seq_len(q), seq_len(q)] -
          tcrossprod(x = An, y = xxt_1[seq_len(q), seq_len(qp)])) / (nobs - 1.0)

    # vec(C) = (sum_{t=1}^{T} [x_t * x'_t] %x% Wt )^-1 * vec(sum_{t=1}^{T} Wt * [y_t * x'_t])
    invC <- chol_inv(xxt[seq_len(r), seq_len(r)])
    D <- yxt[, seq_len(r)]

    # Impose one of the identifying restrictions from Bai and Wang (2015)
    # by constraining the factor loadings using the expression: M %*% vec(C) = hvec
    switch(EXPR = id_opt,
        # The q x q block of C is lower triangular with 1's along the main diagonal
        # and Q is a diagonal matrix
        "DFM1" = { m <- q * (q + 1L) / 2L;
                   seq_idx <- seq_len(m);
                   seq_jdx <- which(x = upper.tri(x = C[, seq_len(q)], diag = TRUE))
                   M <- zeros(m, nvar * r);
                   hvec <- as.matrix(eye(q)[upper.tri(x = eye(q), diag = TRUE)]);
                   # Build up the selector matrix M
                   for (i in seq_idx) {
                       j <- seq_jdx[i]
                       M[i, j] <- 1.0
                   }
                   Cvec <- vec(D %*% invC) +
                           (invC %x% R) %*% t(M) %*%
                           MASS::ginv(M %*% (invC %x% R) %*% t(M)) %*%
                           (hvec - M %*% vec(D %*% invC))
                   QQ <- diag(x = diag(x = (Qn + t(Qn)) / 2.0), nrow = q)
                 },
        # The q x q block of C is an identity matrix I_q and Q is unrestricted
        "DFM2" = { m <- q^2L;
                   seq_idx <- seq(from = 1L, to = m, by = q);
                   seq_jdx <- seq(from = 1L, to = (nvar * r), by = nvar);
                   M <- zeros(m, nvar * r);
                   hvec <- vec(eye(q));
                   # Build up the selector matrix M
                   for (k in seq_len(length(seq_idx))) {
                       i <- seq_idx[k]
                       j <- seq_jdx[k]
                       M[i:(i + q - 1L), j:(j + q - 1L)] <- eye(q)
                   }
                   Cvec <- vec(D %*% invC) +
                           (invC %x% R) %*% t(M) %*%
                           MASS::ginv(M %*% (invC %x% R) %*% t(M)) %*%
                           (hvec - M %*% vec(D %*% invC))
                   QQ <- (Qn + t(Qn)) / 2.0
                 },
        # Q is an identity matrix I_q
        "FSTD" = { Cvec <- vec(D %*% invC);
                   QQ <- eye(q)
                 },
        # No identification restriction
        "NA" = { Cvec <- vec(D %*% invC);
                 QQ <- (Qn + t(Qn)) / 2.0
               }
    )

    # Constrained factor loadings based on id_opt
    C[, seq_len(r)] <- mreshape(Cvec, nvar, r)

    # Constrained state noise covariance matrix based on id_opt
    Q[seq_len(q), seq_len(q)] <- QQ

    # R = diag(1/T * sum_{t=1}^{T}(Wt * [y_t * y'_t] * Wt' - Wt * [y_t * x'_t] * C' * Wt - Wt * C * [x_t * y'_t] * Wt + Wt * C * [x_t * x'_t] * C' * Wt + (In - Wt) * R * (In - Wt))
    Rn <- zeros(nvar, nvar)
    In <- eye(nvar)
    for (i in seq_len(nobs)) {
        Wt <- diag(x = as.double(mask[, i]), nrow = nvar)
        In_Wt <- In - Wt
        Rn <- Rn + (y[, i] - Wt %*% C %*% fs$xs[, i]) %*%
              t(y[, i] - Wt %*% C %*% fs$xs[, i]) + Wt %*% C %*%
              fs$Ps[, , i] %*% t(C) %*% Wt + In_Wt %*% R %*% In_Wt
    }

    Rvec <- diag(x = Rn / nobs)
    Rvec[Rvec < 1E-6] <- 1E-6
    diag(R) <- Rvec

    # Initial state mean (x0) and state covariance (P0)
    x0[seq_len(qk)] <- fs$xs[, 1L]
    P0[seq_len(qk), seq_len(qk)] <- (fs$Ps[, , 1L] + t(fs$Ps[, , 1L])) / 2.0   # Ensure P0 is symmetric

    # Collect results as a list object
    results <- list()
    results$C <- C
    results$R <- R
    results$A <- A
    results$Q <- Q
    results$G <- G
    results$x0 <- x0
    results$P0 <- P0
    results$loglik <- fs$loglik

    # Return results
    return (results)
}

# Estimate the dynamic factor model parameters via the EM algorithm
estimate_params <- function(x, q, s, p, id_opt = c("DFM1", "DFM2", "FSTD", "NA"),
                            na_opt = c("exclude", "replace"), scale_opt = TRUE,
                            sign_opt = FALSE, max_iter = 500L, threshold = 1E-5,
                            check_increased = TRUE, verbose = TRUE)
{
    # Preliminary set-up for the EM algorithm
    if (!is.matrix(x)) { x <- as.matrix(x) }
    prior_loglik <- -.Machine$double.xmax
    LL <- rep_len(x = NA_real_, length.out = max_iter)
    converged <- FALSE
    iter <- 1L

    # Set up the value for 'id_opt'
    id_opt <- toupper(match.arg(id_opt))

    # Standardise the panel if requested
    if (scale_opt) {
        x <- scale(x = x, center = TRUE, scale = TRUE)
    }

    # Set up the value for 'na_opt'
    na_opt <- tolower(match.arg(na_opt))

    # Compute the initial values to be used in the Kalman filter-smoother recursions
    init <- param_init(x = x, q = q, s = s, p = p, id_opt = id_opt,
                       na_opt = na_opt, scale_opt = scale_opt, sign_opt = sign_opt)

    # Initial values for C, R, A, Q, x0, P0 via param_init()
    C_t <- init$C
    R_t <- init$R
    A_t <- init$A
    Q_t <- init$Q
    G_t <- init$G
    x0_t <- init$x0
    P0_t <- init$P0

    # Repeat the EM algorithm until convergence or iter == max_iter
    while (TRUE) {

        # Use em_step to update parameter estimates
        # NB: At the first iteration we set the initial values using PCA
        em <- em_step(y = t(x), C = C_t, R = R_t, A = A_t, Q = Q_t, G = G_t,
                      x0 = x0_t, P0 = P0_t, q = q, s = s, p = p, id_opt = id_opt)

        # Update the log-likelihood and save it
        loglik <- em$loglik
        LL[iter] <- loglik

        if (verbose) {
            cat(sprintf("-- Iteration %d : log-Likelihood = %g --\n", iter, loglik))
        }

        # Check convergence for this iteration
        sc <- em_converged(loglik = loglik, prior_loglik = prior_loglik,
                           threshold = threshold, check_increased = check_increased)

        # Test for convergence
        if (sc$converged) {
            cat(sprintf("EM algorithm converged after %d iterations.\n", iter))
            break
        }

        if (iter == max_iter) {
            cat("EM algorithm failed to converge after reaching the maximum number of evaluations.\n")
            break
        }

        # Increment the counter
        iter <- iter + 1L;

        # Update parameter estimates with new values
        C_t <- em$C
        R_t <- em$R
        A_t <- em$A
        Q_t <- em$Q
        G_t <- em$G
        x0_t <- em$x0
        P0_t <- em$P0

        # Save log-likelihood for the next round
        prior_loglik <- loglik

    }

    # Collect results as a list object
    results <- list()
    results$C <- C_t
    results$R <- R_t
    results$A <- A_t
    results$Q <- Q_t
    results$G <- G_t
    results$x0 <- x0_t
    results$P0 <- P0_t
    results$LL <- na.omit(LL)
    results$niter <- iter

    # Return results
    return (results)
}

# Convenience function to estimate a Dynamic factor model using the EM algorithm in one step
qmle_dfm <- function(x, q, s, p, id_opt = c("DFM1", "DFM2", "FSTD", "NA"),
                     na_opt = c("exclude", "replace"), scale_opt = TRUE,
                     sign_opt = FALSE, max_iter = 500L, threshold = 1E-5,
                     check_increased = TRUE, verbose = TRUE)
{
    # Preliminary checks
    if (missing(x) || missing(q) || missing(s) || missing(p)) {
        stop("qmle_dfm(): Too few input arguments\n", call. = FALSE)
    }

    # The number of static factors cannot be greater than dimension of data
    if (q > min(dim(x))) {
        stop("qmle_dfm(): Number of dynamic factors higher than dimension.\n", call. = FALSE)
    }

    # Check p, it p == 0, then should not use the EM estimation method
    if (p == 0L) {
        stop("qmle_dfm(): p == 0; cannot estimate a dynamic factor model.\n", call. = FALSE)
    }

    # Check if x is a matrix and if not convert it to a matrix
    if (!is.matrix(x)) {
        x <- as.matrix(x)
    }

    # Set up the value for 'id_opt'
    id_opt <- toupper(match.arg(id_opt))

    # Standardise the panel if requested
    if (scale_opt) {
        x <- scale(x = x, center = TRUE, scale = TRUE)
    }

    # Set up the value for 'na_opt'
    na_opt <- tolower(match.arg(na_opt))

    # Compute a few useful values
    nvar <- dim(x)[2L]
    r <- q * (s + 1L)
    qp <- r * p
    k <- max(p, s + 1L)
    qk <- q * k

    # Check if colnames(x) is NULL and if so set to 'X_i' for i = 1,...,nvar
    if (is.null(colnames(x))) {
        xnames <- paste0('X', seq_len(nvar))
    } else {
        xnames <- colnames(x)
    }

    # Estimate the dynamic factor model parameters
    pm <- estimate_params(x = x, q = q, s = s, p = p, id_opt = id_opt, na_opt = na_opt,
                          scale_opt = scale_opt, sign_opt = sign_opt,
                          max_iter = max_iter, threshold = threshold,
                          check_increased = check_increased, verbose = verbose)

    # Get the optimal estimates of the factors and loadings using the QMLE parameters
    fs <- run_fs_recursions(x = x, C = pm$C, R = pm$R, A = pm$A,
                            Q = pm$Q, G = pm$G, x0 = pm$x0, P0 = pm$P0)

    # Kalman filter model parameters
    params <- list()
    params$C <- pm$C
    params$R <- pm$R
    params$A <- pm$A
    params$Q <- pm$Q
    params$G <- pm$G
    params$x0 <- pm$x0
    params$P0 <- pm$P0

    # Estimated factors
    factors <- t(fs$xs[seq_len(r), , drop = FALSE])
    ft <- paste0('F', rep(x = seq_len(q), times = 1L), 't')

    if (s > 0L) {
        fn <- paste(ft, rep(x = seq_len(s), each = q), sep = '_')
        colnames(factors) <- c(ft, fn)
    } else {
        colnames(factors) <- ft
    }

    # Estimated factor loadings
    loadings <- pm$C[, seq_len(r), drop = FALSE]
    colnames(loadings) <- paste0('L', rep(x = seq_len(q), times = 1L),
                                 rep(x = (seq_len(s + 1L) - 1L), each = q))
    rownames(loadings) <- xnames

    # Estimated standard errors for the factors
    nobs <- dim(factors)[1L]
    factor_se <- zeros(nobs, r)
    colnames(factor_se) <- paste(colnames(factors), "se", sep = '_')

    if (r == 1L) {

        for (j in seq_len(nobs)) {
            factor_se[j, ] <- sqrt(x = fs$Ps[r, r, j])
        }

    } else {

        for (j in seq_len(nobs)) {
            factor_se[j, ] <- sqrt(diag(x = fs$Ps[seq_len(r), seq_len(r), j]))
        }

    }

    # Akaike Information Criterion (AIC)
    loglik <- tail(x = pm$LL, n = 1L)

    switch(EXPR = id_opt,
        "DFM1" = { m <- q * (q + 1.0) / 2.0;
                   h <- q
                 },
        "DFM2" = { m <- q^2.0;
                   h <- m
                 },
        "FSTD" = { m <- 0.0;
                   h <- 0.0
                 },
        "NA" = { m <- 0.0;
                 h <- 0.0
               }
    )

    # Compute the number of free parameters in: R, A, C and Q
    nparams <- nvar + (qp * q) + ((nvar * r) - m) + h
    aic <- -2.0 * loglik + 2.0 * (nparams)

    # Collect results as a list object
    results <- list()
    results$parameters <- params
    results$factors <- factors
    results$factor_se <- factor_se
    results$loadings <- loadings
    results$loglik <- loglik
    results$aic <- aic
    results$niter <- pm$niter

    # Return results with class "qmle_dfm"
    results$call <- match.call()
    class(results) <- "qmle_dfm"
    return (results)
}

# Real-time estimate of the factor(s) based on final QMLE parameters
real_time_factor <- function(x, q, s, p, params, scale_opt = TRUE)
{
    # Check if x is a matrix and if not convert it to a matrix
    if (!is.matrix(x)) {
        x <- as.matrix(x)
    }

    # Standardise the panel if requested
    if (scale_opt) {
        x <- scale(x = x, center = TRUE, scale = TRUE)
    }

    # Compute a few useful values
    r <- q * (s + 1L)

    # Re-run the Kalman Filter with the final QMLE parameters
    kf <- kalman_filter(x = x, C = params$C, R = params$R,
                        A = params$A, Q = params$Q, G = params$G,
                        x0 = params$x0, P0 = params$P0)

    # Estimated real-time factors (i.e. x_t|t)
    factors <- t(kf$xf[seq_len(r), , drop = FALSE])
    ft <- paste0('F', rep(x = seq_len(q), times = 1L), 't')

    if (s > 0L) {
        fn <- paste(ft, rep(x = seq_len(s), each = q), sep = '_')
        colnames(factors) <- c(ft, fn)
    } else {
        colnames(factors) <- ft
    }

    # Estimated real-time standard errors for the factors (i.e. P_t|t)
    nobs <- dim(factors)[1L]
    factor_se <- zeros(nobs, r)
    colnames(factor_se) <- paste(colnames(factors), "se", sep = '_')

    if (r == 1L) {

        for (j in seq_len(nobs)) {
            factor_se[j, ] <- sqrt(x = kf$Pf[r, r, j])
        }

    } else {

        for (j in seq_len(nobs)) {
            factor_se[j, ] <- sqrt(diag(x = kf$Pf[seq_len(r), seq_len(r), j]))
        }

    }

    # Collection results as a list object
    results <- list()
    results$factors <- factors
    results$factor_se <- factor_se

    # Return result
    return (results)
}

# Estimate of the common component based on the final QMLE parameters
common_component <- function(x, q, s, p, params, scale_opt = TRUE)
{
    # Check if x is a matrix and if not convert it to a matrix
    if (!is.matrix(x)) {
        x <- as.matrix(x)
    }

    # Standardise the panel if requested
    if (scale_opt) {
        mx <- colMeans(x = x, na.rm = TRUE)
        sx <- apply(X = x, MARGIN =  2, FUN = sd, na.rm = TRUE)
        x <- scale(x = x, center = TRUE, scale = TRUE)
    }

    # Compute a few useful values
    nvar <- dim(x)[2L]
    r <- q * (s + 1L)

    # Check if colnames(x) is NULL and if so set to 'X_i' for i = 1,...,nvar
    if (is.null(colnames(x))) {
        xnames <- paste0('X', seq_len(nvar))
    } else {
        xnames <- colnames(x)
    }

    # Re-run the KFS recursions with the final QMLE parameters
    fs <- run_fs_recursions(x = x, C = params$C, R = params$R,
                            A = params$A, Q = params$Q, G = params$G,
                            x0 = params$x0, P0 = params$P0)

    # Estimated factors: T x r
    factors <- t(fs$xs[seq_len(r), , drop = FALSE])

    # Estimated factor loadings: N x r
    loadings <- params$C[, seq_len(r), drop = FALSE]

    # Estimated common component: Ft * L'
    xcommon <- factors %*% t(loadings)
    colnames(xcommon) <- xnames

    # Rescale common component if scaling was previously requested
    if (scale_opt) {
        xcommon <- sweep(x = xcommon, MARGIN = 2, STATS = sx, FUN = '*')
        xcommon <- sweep(x = xcommon, MARGIN = 2, STATS = mx, FUN = '+')
    }

    # return common component
    return (xcommon)
}

# Decomposition of series contributions to the factor estimate
factor_decomposition <- function(x, q, s, p, params, scale_opt = TRUE)
{
    # Compute some useful quantities
    if (!is.matrix(x)) { x <- as.matrix(x) }
    nobs <- dim(x)[1L]
    nvar <- dim(x)[2L]
    nstate <- dim(params$A)[1L]
    r <- q * (s + 1L)

    # Standardise the panel if requested
    if (scale_opt) {
        x <- scale(x = x, center = TRUE, scale = TRUE)
    }

    y <- t(x)

    # Create row names
    rnames <- paste0('f', rep(x = seq_len(q), times = 1L), 't')

    if (s > 0L) {
        rlags <- paste(rnames, rep(x = seq_len(s), each = q), sep = '_')
        rnames <- c(rnames, rlags)
    }

    # Create column names
    if (is.null(colnames(x))) {
        cnames <- paste0('x', seq_len(nvar))
    } else {
        cnames <- colnames(x)
    }

    # Create slice names
    if (is.null(rownames(x))) {
        snames <- seq_len(nobs)
    } else {
        snames <- rownames(x)
    }

    # Pre-allocate memory for all arrays
    xp <- zeros(nstate, nobs)
    xf <- zeros(nstate, nobs)
    Pp <- zeros(nstate, nstate, nobs)
    Pf <- zeros(nstate, nstate, nobs)
    Dt <- array(data = NA_real_, dim = c(nstate, nvar, nobs),
                dimnames = list(rnames, cnames, snames))

    # Compute a few things outside of the loop
    invR <- diag(x = (1.0 / diag(x = params$R)), nrow = nvar)
    GQG <- params$G %*% params$Q %*% t(params$G)
    In <- eye(nstate)
    iota_r <- iota(n = nstate)

    # t = 1
    # Check for any NAs
    mask <- !is.na(y[, 1L])
    W <- eye(nvar)
    Wt <- W[mask, , drop = FALSE]

    # Prediction error
    xp[, 1L] <- params$A %*% params$x0
    Pp[, , 1L] <- params$A %*% params$P0 %*% t(params$A) + GQG
    y[!mask, 1L] <- 0.0
    vt <- Wt %*% (y[, 1L] - params$C %*% xp[, 1L])

    # Compute invFt directly using the Woodbury matrix identity
    CRC <- t(params$C) %*% t(Wt) %*% Wt %*% invR %*% t(Wt) %*% Wt %*% params$C
    invFt <- Wt %*% (invR - invR %*% params$C %*% MASS::ginv(MASS::ginv(Pp[, , 1L]) + CRC) %*% t(params$C) %*% invR) %*% t(Wt)

    # Kalman Gain
    Kt <- Pp[, , 1L] %*% t(params$C) %*% t(Wt) %*% invFt
    xf[, 1L] <- xp[, 1L] + Kt %*% vt
    Pf[, , 1L] <- (In - Kt %*% Wt %*% params$C) %*% Pp[, , 1L]

    # State update decomposition
    Dt[, , 1L] <- ((Kt %*% Wt) * (crossprod(x = vt, y = Wt) %x% iota_r))

    # t = 2,...,T
    for (i in 2L:nobs) {

        # Check for any NAs
        mask <- !is.na(y[, i])
        W <- eye(nvar)
        Wt <- W[mask, , drop = FALSE]

         # Check if there are any observations for this time period
        if (all(!mask)) {

            # No observations for the current period; project the existing state forward
            xf[, i] <- xp[, i]
            Pf[, , i] <- Pp[, , i]

        } else {

            # There are observations for the current period
            # Prediction error
            xp[, i] <- params$A %*% xf[, i - 1L]
            Pp[, , i] <- params$A %*% Pf[, , i - 1L] %*% t(params$A) + GQG
            y[!mask, i] <- 0.0
            vt <- Wt %*% (y[, i] - params$C %*% xp[, i])

            # Compute invFt directly using the Woodbury matrix identity
            CRC <- t(params$C) %*% t(Wt) %*% Wt %*% invR %*% t(Wt) %*% Wt %*% params$C
            invFt <- Wt %*% (invR - invR %*% params$C %*% MASS::ginv(MASS::ginv(Pp[, , i]) + CRC) %*% t(params$C) %*% invR) %*% t(Wt)

            # Kalman Gain
            Kt <- Pp[, , i] %*% t(params$C) %*% t(Wt) %*% invFt
            xf[, i] <- xp[, i] + Kt %*% vt
            Pf[, , i] <- (In - Kt %*% Wt %*% params$C) %*% Pp[, , i]

            # State update decomposition
            Dt[, , i] <- ((Kt %*% Wt) * (crossprod(x = vt, y = Wt) %x% iota_r))

        }

    }

    # Change dimensions so nobs are rows and each slice is a factor
    prediction <- t(xp)
    update <- aperm(a = Dt, perm = c(3L, 2L, 1L))

    # Collection results as a list object
    result <- list()
    result$prediction <- prediction
    result$update <- update

    # Return result
    return (result)
}

# EOF
