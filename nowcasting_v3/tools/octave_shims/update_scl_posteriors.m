function posteriors = update_scl_posteriors(x, vals, probs)
% UPDATE_SCL_POSTERIORS  Deterministic part of update_scl.m.
%
%   Byte-for-byte the body of nyfed_matlab/functions/model/update_scl.m up to
%   and including the "Set posterior to prior if data is missing" line, but it
%   RETURNS the posterior weight matrix instead of drawing from it.
%
%   The two lines dropped from the end of the original are
%       weights = mnrnd(1, posteriors);
%       s       = weights*vals;
%   A draw is not reproducible in Python and is worthless as a test oracle, so
%   the fixture captures POSTERIORS (Txn_s) instead.
%
%   Nothing else is changed. nyfed_matlab/ is never modified.

% Transform inputs to column vector
x     = x(:);
vals  = vals(:);
probs = probs(:);
T     = size(x, 1);
n_s   = length(probs);

% Define arrays for likelihood computations
x_rep     = repmat(x, 1, n_s);
vals_rep  = repmat(vals', T, 1);
probs_rep = repmat(probs', T, 1);

% Apply Bayes rule
likelihood       = (exp(-(1/2)*(x_rep./vals_rep).^2))./vals_rep;
pxlikelihood     = likelihood .* probs_rep;
xmlikelihood     = sum(pxlikelihood, 2);
xmlikelihood_rep = repmat(xmlikelihood, 1, n_s);
posteriors       = pxlikelihood./xmlikelihood_rep;

% Set posterior to prior if data is missing
posteriors(isnan(posteriors)) = probs_rep(isnan(posteriors));

end
