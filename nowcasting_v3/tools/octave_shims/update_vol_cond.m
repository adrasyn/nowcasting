function [posteriors, mean_t, vars_t, y_t, x1_KF, p1_KF, x2_KF, p2_KF, ln_sigmasq, sigma_out] = ...
    update_vol_cond(x, sigma, gamma, weights, utmp, mean_prior, var_prior)
% UPDATE_VOL_COND  update_vol.m with its two random draws INJECTED.
%
%   Identical to nyfed_matlab/functions/model/update_vol.m except that the two
%   stochastic statements are replaced by arguments, and the intermediates are
%   returned so a Python port can be checked stage by stage:
%
%     original                          shim
%     --------------------------------  ----------------------------------
%     weights = mnrnd(1, posteriors);   weights is an INPUT argument
%     utmp    = randn(T+1, 1);          utmp is an INPUT argument
%
%   Conditional on WEIGHTS and UTMP the whole routine is deterministic, so the
%   fixture captures the mixture POSTERIORS (the thing the draw is taken from,
%   which is what a test can compare) plus the full local-level filter and
%   smoother that follow.
%
%   Every other line, including the missing-data branch of the filter and the
%   bd = 15 upper bound, is unchanged. nyfed_matlab/ is never modified.

% Transform inputs to column vector
x     = x(:);
sigma = sigma(:);
T     = size(x, 1);

% Define constants for log chi-square approximation
probs  =      [0.00609 0.04775 0.13057 0.20674  0.22715  0.18842  0.12047  0.05591  0.01575   0.00115];
means  =      [1.92677 1.34744 0.73504 0.02266 -0.85173 -1.97278 -3.46788 -5.55246 -8.68384 -14.65000];
stdvs  = sqrt([0.11265 0.17788 0.26768 0.40611  0.62699  0.98583  1.57469  2.54498  4.16591   7.33342]);
n_comp = length(probs);
barr   = 1e-4;

% Construct log(eps_t^2)
ln_eps = log(x.^2 + barr) - log(sigma.^2);

% Define arrays for likelihood computations
ln_eps_rep = repmat(ln_eps, 1, n_comp);
means_rep  = repmat(means, T, 1);
stdvs_rep  = repmat(stdvs, T, 1);
probs_rep  = repmat(probs, T, 1);

% Apply Bayes rule
likelihood       = (exp(-(1/2)*((ln_eps_rep-means_rep)./stdvs_rep).^2))./stdvs_rep;
pxlikelihood     = likelihood .* probs_rep;
xmlikelihood     = sum(pxlikelihood, 2);
xmlikelihood_rep = repmat(xmlikelihood, 1, n_comp);
posteriors       = pxlikelihood./xmlikelihood_rep;

% Set posterior to prior if data is missing
posteriors(isnan(posteriors)) = probs_rep(isnan(posteriors));

% SHIM: weights = mnrnd(1, posteriors) -> supplied by caller

% Define constants for local-level model smoothing
if (nargin < 6), mean_prior = 0; end
if (nargin < 7), var_prior = 1e6; end
small = 1e-10;
gamsq = gamma^2;

% Construct log(x_t^2) and parameters from mixture draws
ln_x   = log(x.^2 + barr);
mean_t = weights*means';
vars_t = (weights*stdvs').^2;
y_t    = ln_x - mean_t;

% Initialize univariate filter
x1_KF = zeros(T+1, 1);
p1_KF = zeros(T+1, 1);
x2_KF = zeros(T+1, 1);
p2_KF = zeros(T+1, 1);
ln_sigmasq = zeros(T+1, 1);

% Compute covariance matrix
x1       = mean_prior;
p1       = var_prior;
x1_KF(1) = x1;
p1_KF(1) = p1;

if ~any(isnan(y_t))
    % Apply filter if no missing values
    for t = 1:T
        % Forecast state mean and variance
        x2 = x1;
        p2 = p1 + gamsq;
        h  = p2 + vars_t(t);
        k  = p2/h;

        % Update state mean and variance
        x1 = x2 + k*(y_t(t) - x2);
        p1 = p2 - k*p2;

        % Store state means and variances
        x1_KF(t+1) = x1;
        p1_KF(t+1) = p1;
        x2_KF(t+1) = x2;
        p2_KF(t+1) = p2;
    end
else
    % Apply filter if missing data
    for t = 1:T
        % Forecast state mean and variances
        x2 = x1;
        p2 = p1 + gamsq;

        % Update state mean and variance
        if isnan(y_t(t))
            x1 = x2;
            p1 = p2;
        else
            h  = p2 + vars_t(t);
            k  = p2/h;
            p1 = p2 - k*p2;
            x1 = x2 + k*(y_t(t) - x2);
        end

        % Store state means and variances
        x1_KF(t+1) = x1;
        p1_KF(t+1) = p1;
        x2_KF(t+1) = x2;
        p2_KF(t+1) = p2;
    end
end

% Apply smoothing
% SHIM: utmp = randn(T+1, 1) -> supplied by caller
x3mean = x1;
p3     = p1;
chol_p = sqrt(p3);
x3     = x3mean + chol_p*utmp(T+1);
ln_sigmasq(T+1) = x3;

for t = T:(-1):1
    x1 = x1_KF(t);
    p1 = p1_KF(t);
    x2 = x2_KF(t+1);
    p2 = p2_KF(t+1);
    if (p2 > small)
        p2i    = 1/p2;
        k      = p1*p2i;
        x3mean = x1 + k*(x3-x2);
        p3     = p1 - k*p1;
    else
        x3mean = x1;
        p3     = p1;
    end
    chol_p = sqrt(p3);
    x3     = x3mean + chol_p*utmp(t);
    ln_sigmasq(t) = x3;
end

% Compute updated volatilities
sigma_out = exp(ln_sigmasq(2:(T+1))/2);

% Define and impose upper bound
bd = 15;
sigma_out = min(sigma_out, bd);

end
