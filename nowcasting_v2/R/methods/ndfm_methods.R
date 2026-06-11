####################################################################################################
#
# Methods to estimate Number of Generalised Dynamic Factors
#
####################################################################################################
# foo <- ct(x)
#
# PURPOSE:
#   Calculates the conjugate transpose of matrix 'x'
#
# INPUTS:
#   x = T x n matrix
#
# OUTPUTS:
#   y = n x T matrix
#
# DEPENDENCIES:
#   None
#
# REFERENCES:
#   None
#
# AUTHOR:
#   Luke Hartigan (2014)
####################################################################################################

ct <- function(x)
{
    return (t(Conj(x)))
}

####################################################################################################
# foo <- standardise(x)
#
# PURPOSE:
#   Function to standardise a matrix of data 'x' to have zero mean and unit variance
#
# INPUTS:
#   x = data series (vector or scalar)
#
# OUTPUTS:
#   sx = x with mean removed and unit variance.
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

standardise <- function(x)
{
    # Convert to a matrix object
    if (!is.matrix(x)) { x <- as.matrix(x) }

    # Calculate column means of matrix 'x'
    mx <- colMeans(x = x, na.rm = TRUE)

    # Subtract the column medians
    cx <- sweep(x = x, MARGIN = 2L, STATS = mx, FUN = '-')

    # Calculate column standard deviations of matrix 'x'
    sdx <- apply(X = cx, MARGIN = 2L, FUN = sd, na.rm = TRUE)
    sx <- sweep(x = cx, MARGIN = 2L, STATS = sdx, FUN = '/')

    # Return standardised data
    return (sx)

}

####################################################################################################
# foo <- triang(n)
#
# PURPOSE:
#   Calculates the n-point triangular window used in computing long-run covariance matrices
#
# INPUTS:
#   n = vector of points
#
# OUTPUTS:
#   w = weights with same length as n
#
# DEPENDENCIES:
#   None
#
# REFERENCES:
#   Conversion of Mathwork's 'triang.m' file
#
# AUTHOR:
#   Luke Hartigan (2014)
####################################################################################################

triang <- function(n)
{
    if (n %% 2 != 0){
        # It's an odd length sequence
        w <- 2 * (1:((n + 1) / 2)) / (n + 1)
        w <- c(w, w[((n - 1 ) / 2):1])
    } else {
        # It's an even length sequence
        w <- (2 * (1:((n + 1) / 2)) - 1) / n
        w <- c(w, w[(n / 2):1])
    }

    return(w)
}

####################################################################################################
# foo <- spectral(x, q, m, h)
#
# PURPOSE:
#   Computes the spectral decomposition for matrix 'x'.
#   Helper function for functions 'dyn_eig()', 'gdfm_onesided()', 'gdfm_twosided()', & 'num_dyn_factors()'
#
# INPUTs:
#   x = T x n data matrix (data should be covariance stationary and mean standardized).
#   q = dimension of the common space, (i.e. number of dynamic factors).
#   m = covariogram truncation, (default value: floor(sqrt(T))).
#   h = number of points in which the spectral density is computed, (default value: m).
#
# OUTPUT (list object):
#   P_chi = n x q x 2xh+1 matrix of dynamic eigenvectors associated with the
#           q largest dynamic eigenvalues for different frequency levels.
#   D_chi = q x 2xh+1 matrix of dynamic eigenvalues for different frequency levels.
#   Sigma_chi = (n x n x 2xh+1) spectral density matrix of common components with
#               the 2xh+1 density matrices for different frequency levels.
#
# DEPENDENCIES:
#   'triang()'
#     Returns the n-point triangular window used to calculate the smoothed covariogram.
#   'ct()'
#     Returns the Conjugate transpose of matrix 'x'.
#
# REFERENCES:
#   Conversion of the MATLAB file 'spectral.m'
#   Generalised Dynamic Factor Model - MATLAB toolbox v1.3
#     By Matteo Barigozzi, Mario Forni, Roman Liska, Charles Mathias
#     http://www.barigozzi.eu/mb/Codes.html
#
#   David Hiebeler's MATLAB / R Reference, 14 July 2011
#     http://www.math.umaine.edu/~hiebeler
#
# AUTHOR:
#   Luke Hartigan (2012)
####################################################################################################

spectral <- function(x, q, m = NULL, h = NULL)
{
    # Preliminary settings
    if (missing(x) || missing(q)) {
        stop("spectral(): Too few input arguments.\n", call. = FALSE)
    }

    # Compute some useful quantities
    if(!is.matrix(x)) { x <- as.matrix(x) }
    nobs <- dim(x)[1L]
    nvar <- dim(x)[2L]

    if (is.null(m)) {
        m <- floor(sqrt(nobs))
    }

    if (is.null(h)) {
        h <- m
    }

    # Compute M covariances
    M <- (2L * m) + 1L
    B <- triang(M)
    Gamma_k <- array(data = NA_real_, dim = c(nvar, nvar, M))

    for (k in seq_len(m + 1L)) {
        Gamma_k[, , m + k] <- B[m + k] * crossprod(x = x[k:nobs, ],
                              y = x[seq_len(nobs + 1L - k), ]) / (nobs - k)
        Gamma_k[, , (m - k + 2L)] <- t(Gamma_k[, , m + k])
    }

    # Compute the spectral density matrix in H points
    H <- (2L * h) + 1L
    frange <- (2.0 * pi * h) / H
    fstep <- (2.0 * pi) / H
    Factor <- exp((-1.0i) * (-m:m) %*% ct(seq(from = -frange, to = frange, by = fstep)))
    Sigma_x <- array(data = NA_real_, dim = c(nvar, nvar, H))

    for (j in seq_len(nvar)) {
        Sigma_x[j, , ] <- drop(Gamma_k[j, , ]) %*% Factor
    }

    # Create output elements
    P_chi <- array(data = NA_real_, dim = c(nvar , q, H))
    D_chi <- matrix(data = NA_real_, nrow = q , ncol = H)
    Sigma_chi <- array(data = NA_real_, dim = c(nvar, nvar ,H))

    # Compute eigenvalues and eigenvectors
    # Case with q < n-1
    if (q < (nvar - 1L)) {
        dpca <- eigen(x = Sigma_x[, , (h + 1L)], symmetric = TRUE)
        D <- dpca$values[seq_len(q)]
        P <- dpca$vectors[, seq_len(q)]
        D_chi[, h + 1L] <- D
        P_chi[, , h + 1L] <- P
        Sigma_chi[, , h + 1L] <- P %*% diag(x = D, nrow = q) %*% ct(P)

        for (j in seq_len(h)) {
            dpca <- eigen(x = Sigma_x[, , j], symmetric = TRUE)
            D <- dpca$values[seq_len(q)]
            P <- dpca$vectors[, seq_len(q)]

            D_chi[, j] <- D
            D_chi[, (H + 1L) - j] <- D

            P_chi[, , j] <- P
            P_chi[, , (H + 1L) - j] <- Conj(P)

            Sigma_chi[, , j] <- P %*% diag(x = D, nrow = q) %*% ct(P)
            Sigma_chi[, , (H + 1L) - j] <- Conj(P %*% diag(x = D, nrow = q) %*% ct(P))
        }
    }

    # Case with q >= n-1
    if (q >= (nvar - 1L)) {
        dpca <- eigen(x = Sigma_x[, , h + 1L], symmetric = TRUE)
        D <- dpca$values
        P <- dpca$vectors
        D_chi[, h + 1L] <- Re(D)
        P_chi[, , h + 1L] <- P
        Sigma_chi[, , h + 1L] <- P %*% diag(x = D, nrow = length(D)) %*% ct(P)

        for (j in seq_len(h)) {
            dpca <- eigen(x = Sigma_x[, , j], symmetric = TRUE)
            D <- dpca$values
            P <- dpca$vectors

            D_chi[, j] <- Re(D)
            D_chi[, (H + 1L) - j] <- Re(D)

            P_chi[, , j] <- P
            P_chi[, , (H + 1L) - j] <- Conj(P)

            Sigma_chi[, , j] <- P %*% diag(x = D, nrow = length(D)) %*% ct(P)
            Sigma_chi[, , (H + 1L) - j] <- Conj(P %*% diag(x = D, nrow = length(D)) %*% ct(P))
        }
    }

    # Collect results as a list object
    results <- list()
    results$P_chi <- P_chi
    results$D_chi <- D_chi
    results$Sigma_chi <- Sigma_chi

    # Return results with class "spectral"
    results$call <- match.call()
    class(results) <- "spectral"
    return (results)

}

####################################################################################################
# foo <- dyn_eig(x, q, m, h)
#
# PURPOSE:
#   Compute the dynamic eigenvalues of a matrix 'x'
#
# INPUTS:
#   x = T x N data matrix (data should be covariance stationary and mean standardized).
#   q = number of dynamic eigenvalues, (default value: N).
#   m = covariogram truncation, (default value: floor(sqrt(T))).
#   h = number of points in which the spectral density is computed, (default value: m).
#
# OUTPUTS (list object):
#   deigs = N x h matrix of the dynamic eigenvalues from the spectral density matrix of 'x'.
#   explvar = Variance explained by each dynamic eigenvalue.
#   cumR2 = Cumulative explained variation.
#
# DEPENDENCIES:
#   'spectral()'
#     Computes the spectral decomposition for matrix 'x'
#
# REFERENCES:
#   None.
#
# AUTHOR:
#   Luke Hartigan (2017)
####################################################################################################

dyn_eig <- function(x, q = NULL, m = NULL, h = NULL)
{
    # Preliminary settings
    if (missing(x)) {
        stop("dyn_eig(): Too few input arguments.\n", call. = FALSE)
    }

    # Compute some useful quantities
    if (!is.matrix(x)) { x <- as.matrix(x) }

    # Check if q is NULL
    if (is.null(q)) {
        q <- dim(x)[2L]
    }

    # Check if m is NULL
    if (is.null(m)) {
        m <- floor(sqrt(dim(x)[1L]))
    }

    # Check if h is NULL
    if (is.null(h)) {
        h <- m
    }

    sp <- spectral(x = x, q = q, h = h, m = m)
    es <- cbind(sp$D_chi[, h + 1L], sp$D_chi[, (h + 2L):((2L * h) + 1L)] * 2L)
    en <- (es %*% rep(1.0, (h + 1L))) / ((2.0 * h) + 1.0)

    # Dynamic eigenvalues by frequency (i.e. 0 -- pi)
    deigs <- t(es)
    colnames(deigs) <- paste0('D', seq_len(dim(deigs)[2L]))
    rownames(deigs) <- round(seq(from = 0.0, to = pi, by = pi / h), 4L)

    # Explained variation
    explvar <- round((en/ sum(en)) * 100.0, 2L)
    cumR2 <- cumsum(explvar)
    vardec <- cbind(explvar, cumR2)
    colnames(vardec) <- c("Explvar", "CumR2")
    rownames(vardec) <- seq_len(q)

    # Collect results as a list object
    results <- list()
    results$deigs <- deigs
    results$vardec <- vardec

    # Return object with class "deigs"
    results$call <- match.call()
    class(results) <- "deigs"
    return (results)

}

####################################################################################################
# foo <- num_dyn_factors(x, q_max, nbck, stp, c_max, penalty, cf, m, h,
#                        scale_opt, plot_opt, seed, ...)
#
# PURPOSE:
#   log criterion to determine the number of dynamic factors according to
#   Hallin and Liska (2007) "Determining the Number of Factors in the General
#   Dynamic Factor Model", Journal of the American Statistical Association,
#   102, 603-617.
#
# INPUT:
#   x = T x n data matrix (data should be covariance stationary)
#   q_max = upper bound on the number of factors
#   nbck, stp = T x n_j subpanels are used where n_j = n - nbck: stp: n.
#     (default value: nbck = floor(n/4), stp = 1)
#   c_max = c = [0:c_max], (default value: 3)
#   penalty options:
#      p1 = ((m/T)^0.5 + m^(-2) + n^(-1))*log(min([(T/m)^0.5;  m^2; n]))
#      p2 = (min([(T/m)^0.5;  m^2; n]))^(-1/2)
#      p3 = (min([(T/m)^0.5;  m^2; n]))^(-1)*log(min([(T/m)^0.5;  m^2; n]))
#     (default value: 'p1')
#   cf = 1/cf is granularity of c, (default value: 1000)
#   m = covariogram truncation, (default value: floor(sqrt(T)))
#   h = number of points in which the spectral density is computed, (default value: m)
#   scale_opt = user supplied choice to standardise the data matrix x.
#               (standardise == TRUE; don't standardise == FALSE) (Default value: TRUE)
#   plot_opt = option to plot the test results and return the data invisibly, (default == TRUE)
#   seed = number to use as the seed when using sample.int(). This allows for replication.
#   ... = options to be passed to the plot function for "ndfac"
#
# OUTPUT (list object with class "ndfac"):
#   nfact = number of dynamic factors as function of c computed for n_j = n
#   v_nfact = variance in the number of dynamic factors as function of c and computed
#             as the n_j varies
#   cr = values of c (needed for the plot - if selected)
#
# DEPENDENCIES:
#   'spectral()'
#     Computes the spectral decomposition for matrix 'x'
#
# REFERENCES:
#   Conversion of the MATLAB file 'numfactor.m'
#   Generalised Dynamic Factor Model - MATLAB toolbox v1.3
#     By Matteo Barigozzi, Mario Forni, Roman Liska, Charles Mathias
#     http://www.barigozzi.eu/mb/Codes.html
#
#  Hallin and Liska (2007) "Determining the Number of Factors in the General
#    Dynamic Factor Model", Journal of the American Statistical Association,
#    102, 603-617.
#
#   David Hiebeler's MATLAB / R Reference, 14 July 2011
#     http://www.math.umaine.edu/~hiebeler
#
# AUTHOR:
#   Luke Hartigan (2020)
####################################################################################################

num_dyn_factors <- function(x, q_max, nbck = NULL, stp = 1, c_max = 3,
                            penalty = c("p1", "p2", "p3"), cf = 1000,
                            m = NULL, h = NULL, scale_opt = TRUE,
                            plot_opt = FALSE, seed = 12041948L, ...)
{
    # Preliminary settings
    if (missing(x) || missing(q_max)) {
        stop("Too few input arguments.\n", call. = FALSE)
    }

    if (!is.matrix(x)) { x <- as.matrix(x) }
    nobs <- dim(x)[1L]
    nvar <- dim(x)[2L]

    # Check that 'q_max' is not greater than the dimension of the data
    if (q_max > nvar) {
        stop("num_dyn_factors(): q_max higher than dimension.\n", call. = FALSE)
    }

    if (is.null(nbck)) {
        nbck <- floor(nvar / 4L)
    }

    if (is.null(m)) {
        m <- floor(sqrt(nobs))
    }

    if (is.null(h)) {
        h <- m
    }

    # Standardise panel
    if (scale_opt) {
        x <- standardise(x)
    }

    # Set a few preliminary values
    set.seed(seed = seed) # for replicability
    i_vec <- seq(from = (nvar - nbck), to = nvar, by = stp)
    j_vec <- seq_len(floor(c_max * cf))
    o_log <- matrix(data = NA_real_, nrow = length(i_vec), ncol = length(j_vec))
    s <- 0L

    # Compute the number of generalised dynamic factors
    for (k in i_vec) {

        # Print current output to the console
        cat(sprintf("Sub-sample size: %d\n", k))
        s <- s + 1L
        subx <- x[, sample.int(n = nvar, size = k, replace = FALSE), drop = FALSE]

        # Standardise sub panel
        if (scale_opt) {
            subx <- standardise(subx)
        }

        # Spectral analysis
        sp <- spectral(x = subx, q = k, m = m, h = h)
        es <- cbind(sp$D_chi[ , h + 1L], sp$D_chi[ , (h + 2L):((2L * h) + 1L)] * 2L)
        en <- (es %*% rep(1.0, (h + 1L))) / ((2.0 * h) + 1.0)
        ic1 <- apply(X = apply(X = apply(X = en, MARGIN = 2L, FUN = rev),
                     MARGIN = 2L, FUN = cumsum), MARGIN = 2L, FUN = rev)
        ic1 <- ic1[seq_len(q_max + 1L), ]

        # Penalty Formula
        fn <- c((nobs / m)^0.5, m^2, 1i)

        # Get the penalty value
        penalty <- match.arg(penalty)
        switch(EXPR = penalty,
            "p1" = { p <- ((m / nobs)^0.5 + m^(-2) + 1i^(-1)) *
                     log(fn[which.min(abs(fn))]) %*% t(rep(1.0, (q_max + 1L))) },
            "p2" = { p <- (fn[which.min(abs(fn))])^(-0.5) %*% t(rep(1.0, (q_max + 1L))) },
            "p3" = { p <- (fn[which.min(abs(fn))])^(-1) *
                     log(fn[which.min(abs(fn))]) %*% t(rep(1.0, (q_max + 1L))) }
        )

        for (ci in j_vec) {
            cc <- ci / cf
            ic_log <- log(ic1 / 1i) + (t(0:q_max) * p * cc)
            rr <- which((ic_log == rep(1L, (q_max + 1L)) *
                       (ic_log[which.min(abs(ic_log))])) == 1) # how MATLAB calculates min with complex arguments
            o_log[s, ci] <- (rr - 1)
        }
    }

    # Results
    cr <- (j_vec) / cf
    nfactor <- o_log[nrow(o_log), ]
    v_nfactor <- apply(X = o_log, MARGIN = 2L, FUN = sd) # standard deviation of each column

    # Return values as a list object with class "ndfac"
    results <- list()
    results$penalty <- penalty
    results$nfactor <- nfactor
    results$v_nfactor <- v_nfactor
    results$cr <- cr
    results$penalty <- penalty
    results$call <- match.call()
    class(results) <- "ndfac"

    if (plot_opt) {
        plot(results, ...)
        return(invisible(results))
    } else {
        return(results)
    }

}

####################################################################################################
# Print Methods
####################################################################################################

# Print method for "ndfac"
print.ndfac <- function(x, digits = max(3L, getOption("digits") - 3L), ...)
{
    cat("\nCall: ", paste(deparse(x$call), sep = '\n', collapse = '\n'), '\n', sep = "")
    cat("\nHallin & Liska (2007) Criterion for the Number of Dynamic Factors:\n\n")

    cat("\nPenalty: ", x$penalty, "\n")

    cat("\ncr: \n")
    print.default(x$cr, digits = digits)

    cat("\nNumber of dynamic factor: \n")
    print.default(x$nfactor, digits = digits)

    cat("\nVariance of estimated number of dynamic factor: \n")
    print.default(x$v_nfactor, digits = digits)
    cat('\n')
}

####################################################################################################
# Plot Methods
####################################################################################################

# Plot method for class "ndfac"
plot.ndfac <- function(x, ...)
{
    # Save all 'par' settings which could be changed
    oldpar <- par(no.readonly = TRUE)

    # Reset plotting device to original settings on exit
    on.exit(par(oldpar))

    # Set up new plotting device
    newpar <- par(mar = c(4, 5, 4, 5) + 0.1, oma = c(0, 0, 0, 0),
                  lwd = 1, lty = 1, las = 1, xaxs = 'r', yaxs = 'r',
                  mgp = c(3, 1, 0), bty = 'o', tcl = 0.3,
                  cex.main = 1.5, font.main = 2,
                  cex.lab = 1.5, font.lab = 1,
                  cex.axis = 1.5, font.axis = 1)

    # Plotting options
    cell <- 5
    tcl_opt <- 0.5
    y1_col <- "royalblue2"
    y2_col <- "maroon2"

    # y1-axis
    min_y1 <- floor(min(x$nfactor))
    max_y1 <- ceiling(max(x$nfactor))
    y1_seq <- seq(from = min_y1, to =  max_y1, length.out = cell - 1L)

    # y2-axis
    min_y2 <- floor(min(x$v_nfactor))
    max_y2 <- ceiling(max(x$v_nfactor))
    y2_seq <- seq(from = min_y2, to =  max_y2, length.out = cell - 1L)

    # x-axis
    min_x <- floor(min(x$cr))
    max_x <- ceiling(max(x$cr))
    x_seq <- seq(from = min_x, to = max_x, length.out = cell)

    # Establish the y1 plotting region
    plot(x$cr, x$nfactor, type = 'n', col = NA, tcl = tcl_opt,
         ylim = c(min_y1, max_y1),
         xlim = c(min_x, max_x),
         yaxp = c(min_y1, max_y1, cell),
         yaxt = 'n', xaxt = 'n',
         xlab = "", ylab = "", main = "", ...)

    # Mark zero
    abline(h = 0.0, col = "black", lty = 1, lwd = 1)

    # Mark the estimated number of dynamic factors
    lines(x = x$cr, y = x$nfactor, type = 'S', col = y1_col, lwd = 1)

    # Mark the y1-axis ticks and labels on the LHS
    axis(side = 2, at = y1_seq, labels = as.character(floor(y1_seq)),
         las = 2, tcl = tcl_opt)
    mtext(text = "Number of dynamic factors",
          side = 2, line = 3, outer = FALSE, las = 0, cex = 1.25)

    # Establish new plotting device
    par(new = TRUE)

    # Establish the y2 plotting region
    plot(x$cr, x$v_nfactor, type = 'n', col = NA, tcl = tcl_opt,
         ylim = c(min_y2, max_y2),
         xlim = c(min_x, max_x),
         yaxp = c(min_y2, max_y2, cell),
         yaxt = 'n', xaxt = 's',
         xlab = "", ylab = "", main = "", ...)

    # Mark the std dev of the estimated number of dynamic factors
    lines(x = x$cr, y = x$v_nfactor, type = 'l', col = y2_col, lwd = 1)

    # Mark the y2-axis ticks and label on the RHS
    axis(side = 4, at = y2_seq, labels = as.character(round(y2_seq, 1)),
         las = 2, tcl = tcl_opt)
    mtext(text = "Standard deviation",
          side = 4, line = 3, outer = FALSE, las = 0, cex = 1.25)

    # Mark the x-axis ticks and labels on the bottom
    #axis(side = 1, at = x_seq, labels = as.character(x_seq), tcl = tcl_opt) # not needed
    mtext(text = expression(c[r]),
          side = 1, line = 2.5, outer = FALSE, cex = 1.25)

    # Plot the border
    box(which = "plot", col = "black", lwd = 1, lty = 1)

    # Main title
    mtext(text = "Estimated Number of Dynamic Factors",
          side = 3, line = 1.5, outer = FALSE, las = 1, cex = 1.5, font = 2)

    # Main sub title
    mtext(text = sprintf("Log criterion using penalty \'%s\'", x$penalty),
          side = 3, line = 0.25, outer = FALSE, las = 1, cex = 1.25, font = 1)

    # Mark the legend
    legend("top", col = c(y1_col, y2_col),
           lty = c(1, 1), lwd = c(1, 1), cex = 1.25,
           legend = c(expression(q[c]), expression(S[c])),
           bty = 'n', horiz = TRUE, xpd = NA)

    # Execute par(oldpar)
    invisible ()

}

####################################################################################################
