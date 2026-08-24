% GEN_FIXTURES  Generate test-oracle fixtures from the vendored MATLAB code.
%
% Runs the reference functions in nyfed_matlab/ (read-only) and saves every
% INPUT and every OUTPUT of each call into a -v7 .mat file. matload.py then
% converts those to tests/fixtures/*.npz, which the Python tests load, feed to
% the port, and compare against.
%
%   cd nowcasting_v3/tools
%   octave gen_fixtures.m
%   ../.venv/bin/python matload.py
%   ../.venv/bin/python extract_published.py
%
% extract_published.py is separate because the NY Fed's PUBLISHED figures live in
% MATLAB table/datetime objects that Octave cannot decode at all; see its header.
%
% Two shimmed functions live in octave_shims/ (see the headers there). They
% exist because update_scl and update_vol end in a random draw; the fixtures
% capture the posterior the draw is taken from, never the draw.
%
% SIZE DISCIPLINE. The US fixtures are windowed to the last WINDOW periods of
% the T = 468 month sample and the oracle is run ON THE WINDOWED SYSTEM, so the
% stored outputs are exactly reproducible from the stored inputs. The window
% start is saved in every US fixture as window_start (1-based, MATLAB) and
% window_start_py (0-based, Python). kalman_small is full length.

close all; clear; clc;

addpath('../nyfed_matlab/functions/general')
addpath('../nyfed_matlab/functions/model')
addpath('octave_shims')

if ~exist('fixtures_mat', 'dir'), mkdir('fixtures_mat'); end

WINDOW = 60;


%% ------------------------------------------------------------------
%% kalman_small - Kalman_filter + fast_smoother on a 2x3 system, full length.
%% Two cases: the Task 0 probe (anchor loglik = -60.919914554813) and the same
%% system with one entirely missing column, which exercises the empty-nonmiss
%% branch that the US fixtures also hit at the forecast edge.
%% ------------------------------------------------------------------
clear -x WINDOW

N = 2; M = 3; K = 3; T = 20;
SSM           = struct();
SSM.D         = zeros(N, 1);
SSM.H         = [1 0 0; 0 1 0];
SSM.Sigma_eps = 1e-4*eye(N);
SSM.C         = zeros(M, 1);
SSM.F         = 0.5*eye(M);
SSM.G         = eye(M);
SSM.Sigma_eta = eye(K);
SSM.mu_1      = zeros(M, 1);
SSM.Sigma_1   = eye(M);

rand('state', 321); randn('state', 321);
Y = randn(N, T);
Y(1, 5) = NaN;                       % one missing element

[loglik, prediction, filter] = Kalman_filter(Y, SSM);
[disturbances, states, MSEs] = fast_smoother(Y, SSM);
printf('kalman_small: loglik = %.12f (Task 0 anchor -60.919914554813)\n', loglik);

Y_allmiss           = Y;
Y_allmiss(:, 12)    = NaN;           % one entirely missing period
[loglik_allmiss, prediction_allmiss, filter_allmiss] = Kalman_filter(Y_allmiss, SSM);
[disturbances_allmiss, states_allmiss, MSEs_allmiss] = fast_smoother(Y_allmiss, SSM);
printf('kalman_small: loglik_allmiss = %.12f\n', loglik_allmiss);

save('-v7', 'fixtures_mat/kalman_small.mat', ...
    'Y', 'SSM', 'loglik', 'prediction', 'filter', ...
    'disturbances', 'states', 'MSEs', ...
    'Y_allmiss', 'loglik_allmiss', 'prediction_allmiss', 'filter_allmiss', ...
    'disturbances_allmiss', 'states_allmiss', 'MSEs_allmiss');


%% ------------------------------------------------------------------
%% Shared US setup. Everything below uses these.
%% ------------------------------------------------------------------
clear -x WINDOW

est    = load('../nyfed_matlab/Estimates_2023_09_20.mat');
dimvec = est.dimvec;
n = dimvec(1); n_f = dimvec(2); p_f = dimvec(3); p_e = dimvec(4);

% Series ids, read straight from the spec csv (readtable is not needed).
fid = fopen('../nyfed_matlab/model_spec_FRED.csv');
fgetl(fid);
ids = {}; k = 0;
while true
    ln = fgetl(fid);
    if ~ischar(ln), break; end
    k = k + 1;
    parts  = strsplit(ln, ',');
    ids{k} = parts{1};
end
fclose(fid);
i_now = find(strcmpi(ids, 'GDPC1'));

% The estimation sample was extended to the forecast horizon (2023-12) when the
% estimates were produced, so f_active carries the full T. example_nowcast.m
% pads the nowcast data with NaN columns to the same length; do that here
% without touching datetime, which Octave cannot read from these .mat files.
T_full          = size(est.restrict.f_active, 2);
w0              = T_full - WINDOW + 1;
window_start    = w0;                 % 1-based (MATLAB)
window_start_py = w0 - 1;             % 0-based (Python)
window_len      = WINDOW;
printf('US window: t = %d..%d of %d\n', w0, T_full, T_full);

% Standardise and pad a vintage to T_full, then window it. example_nowcast.m
% works out the pad length from timekey, which is a MATLAB datetime that Octave
% cannot read; T_full - rows gives the same answer without touching it.
function Y = load_vintage(name, est, n, T_full, w0)
    D = load(['../nyfed_matlab/data/Data_' name '.mat']);
    Y = [(D.data' - est.Y_location)./est.Y_scale, NaN(n, T_full - size(D.data, 1))];
    Y = Y(:, w0:T_full);
end

Y_old = load_vintage('2023_09_22', est, n, T_full, w0);
Y_new = load_vintage('2023_09_29', est, n, T_full, w0);

% restrict, windowed on its only time-indexed field
restrict          = est.restrict;
restrict.f_active = est.restrict.f_active(:, w0:T_full);
printf('COVID factor active in %d of %d window periods\n', ...
    nnz(restrict.f_active(end, :)), WINDOW);

% Canonical parameter and latent draw of example_nowcast.m, windowed.
param_vec    = median(est.param_Gibbs, 2);
param        = map_parameter(param_vec, dimvec);
latent       = struct();
latent.sigma = mean(est.latents.sigmas(:, w0:T_full, :), 3);
latent.s     = mean(est.latents.ss(:, w0:T_full, :), 3);

% Time indices (within the window) at which the n_state^2 and n^2 per-period
% MSE/covariance arrays are stored. Storing all 60 slices of a 73x73 array
% would put a single fixture over the whole directory budget on its own, and
% buys almost nothing: prediction.gain = Sigma*H'*S_inv is stored at ALL 60
% periods, so a wrong Sigma at any t shows up there and in loglik anyway.
% The chosen indices bracket both COVID f_active transitions (14/15 off->on,
% 36/37 on->off) and the ragged edge at the end of the window.
sub_t    = [1, 10, 14, 15, 30, 36, 37, 45, 55, WINDOW];
sub_t_py = sub_t - 1;


%% ------------------------------------------------------------------
%% construct_ssm_us - the highest-value fixture. param/latent/restrict in,
%% all eight state-space matrices out.
%% ------------------------------------------------------------------
SSM = construct_SSM(param, latent, restrict);
printf('construct_ssm_us: n_state = %d, H = %s, Sigma_eta = %s\n', ...
    size(SSM.F, 1), mat2str(size(SSM.H)), mat2str(size(SSM.Sigma_eta)));

save('-v7', 'fixtures_mat/construct_ssm_us.mat', ...
    'dimvec', 'param_vec', 'param', 'latent', 'restrict', 'SSM', ...
    'window_start', 'window_start_py', 'window_len', 'T_full', 'i_now');


%% ------------------------------------------------------------------
%% kalman_us - Kalman_filter on the real windowed system.
%% ------------------------------------------------------------------
Y = Y_new;
[loglik, prediction, filter] = Kalman_filter(Y, SSM);
printf('kalman_us: loglik = %.12f\n', loglik);

% filter.mu is stored at every period; filter.Sigma only at sub_t (see above).
filter_sub       = struct();
filter_sub.mu    = filter.mu;
filter_sub.Sigma = filter.Sigma(:, :, sub_t);

save('-v7', 'fixtures_mat/kalman_us.mat', ...
    'Y', 'SSM', 'loglik', 'prediction', 'filter_sub', 'sub_t', 'sub_t_py', ...
    'window_start', 'window_start_py', 'window_len', 'T_full');


%% ------------------------------------------------------------------
%% fast_smoother_us - same inputs, all three outputs.
%% disturbances and states are stored at full window length. The three MSE
%% arrays are stored only at the sub_t periods defined above.
%% ------------------------------------------------------------------
[disturbances, states, MSEs] = fast_smoother(Y, SSM);

MSEs_sub          = struct();
MSEs_sub.m_errors = MSEs.m_errors(:, :, sub_t);
MSEs_sub.states   = MSEs.states(:, :, sub_t);
% MSEs.shocks has only T-1 slices, so drop the last index for it.
sub_t_shocks    = sub_t(sub_t < WINDOW);
sub_t_shocks_py = sub_t_shocks - 1;
MSEs_sub.shocks = MSEs.shocks(:, :, sub_t_shocks);
printf('fast_smoother_us: states %s, shocks %s\n', ...
    mat2str(size(states)), mat2str(size(disturbances.shocks)));

save('-v7', 'fixtures_mat/fast_smoother_us.mat', ...
    'Y', 'SSM', 'disturbances', 'states', 'MSEs_sub', ...
    'sub_t', 'sub_t_py', 'sub_t_shocks', 'sub_t_shocks_py', ...
    'window_start', 'window_start_py', 'window_len', 'T_full');


%% ------------------------------------------------------------------
%% nowcast_us - point_nowcast on the windowed system.
%%
%% example_nowcast.m derives SSM_old and SSM_new by running S_update 1250 times
%% per vintage, which is stochastic and slow, and which - because both vintages
%% load the SAME estimate file - would otherwise give SSM_old == SSM_new and
%% leave row 2 (the parameter-revision row) untested. Here the two SSMs come
%% from two DISJOINT halves of the Gibbs output instead: deterministic, and
%% genuinely different in D, H, F and Sigma_eta. point_nowcast is deterministic
%% given the two SSMs, so the fixture is still an exact oracle.
%% ------------------------------------------------------------------
n_draw = size(est.param_Gibbs, 2);
n_lat  = size(est.latents.sigmas, 3);
h_draw = floor(n_draw/2);
h_lat  = floor(n_lat/2);

param_vec_old = median(est.param_Gibbs(:, 1:h_draw), 2);
param_vec_new = median(est.param_Gibbs(:, (h_draw+1):n_draw), 2);
param_old     = map_parameter(param_vec_old, dimvec);
param_new     = map_parameter(param_vec_new, dimvec);

latent_old       = struct();
latent_old.sigma = mean(est.latents.sigmas(:, w0:T_full, 1:h_lat), 3);
latent_old.s     = mean(est.latents.ss(:, w0:T_full, 1:h_lat), 3);
latent_new       = struct();
latent_new.sigma = mean(est.latents.sigmas(:, w0:T_full, (h_lat+1):n_lat), 3);
latent_new.s     = mean(est.latents.ss(:, w0:T_full, (h_lat+1):n_lat), 3);

SSM_old = construct_SSM(param_old, latent_old, restrict);
SSM_new = construct_SSM(param_new, latent_new, restrict);

t_now    = (find(~isnan(Y_new(i_now, :)), 1, 'last')+3):3:WINDOW;
t_now_py = t_now - 1;
releases = (~isnan(Y_new) & isnan(Y_old));
printf('nowcast_us: t_now (in window) = %s, %d releases\n', ...
    mat2str(t_now), nnz(releases));

[nowcast, forecasts, news, weights] = point_nowcast(Y_old, Y_new, SSM_old, SSM_new, i_now, t_now);
printf('nowcast_us: nowcast rows 1-4 at first horizon = %s\n', mat2str(nowcast(:, 1)', 8));

Y_location = est.Y_location;
Y_scale    = est.Y_scale;

save('-v7', 'fixtures_mat/nowcast_us.mat', ...
    'Y_old', 'Y_new', 'SSM_old', 'SSM_new', 'i_now', 't_now', 't_now_py', ...
    'param_vec_old', 'param_vec_new', 'latent_old', 'latent_new', 'restrict', ...
    'dimvec', 'Y_location', 'Y_scale', ...
    'nowcast', 'forecasts', 'news', 'weights', ...
    'window_start', 'window_start_py', 'window_len', 'T_full');


%% ------------------------------------------------------------------
%% nowcast_us_1006 - the same oracle for the 2023_09_29 -> 2023_10_06 pair.
%% That is the week Task 9 gates against, and it carries more releases than the
%% 09_22 -> 09_29 pair, so every release's impact gets its own comparison.
%% The two SSMs are the same disjoint-Gibbs-half pair used above.
%% ------------------------------------------------------------------
Y_old = load_vintage('2023_09_29', est, n, T_full, w0);
Y_new = load_vintage('2023_10_06', est, n, T_full, w0);

t_now    = (find(~isnan(Y_new(i_now, :)), 1, 'last')+3):3:WINDOW;
t_now_py = t_now - 1;
releases = (~isnan(Y_new) & isnan(Y_old));
printf('nowcast_us_1006: t_now (in window) = %s, %d releases\n', ...
    mat2str(t_now), nnz(releases));

[nowcast, forecasts, news, weights] = point_nowcast(Y_old, Y_new, SSM_old, SSM_new, i_now, t_now);
printf('nowcast_us_1006: nowcast rows 1-4 at first horizon = %s\n', mat2str(nowcast(:, 1)', 8));

save('-v7', 'fixtures_mat/nowcast_us_1006.mat', ...
    'Y_old', 'Y_new', 'SSM_old', 'SSM_new', 'i_now', 't_now', 't_now_py', ...
    'param_vec_old', 'param_vec_new', 'latent_old', 'latent_new', 'restrict', ...
    'dimvec', 'Y_location', 'Y_scale', ...
    'nowcast', 'forecasts', 'news', 'weights', ...
    'window_start', 'window_start_py', 'window_len', 'T_full');


%% ------------------------------------------------------------------
%% construct_prior_us - dims and m_Lambda in, the whole prior struct out.
%% ------------------------------------------------------------------
initval  = load('../nyfed_matlab/initval.mat').initval;
m_Lambda = initval.param.Lambda;
prior    = construct_prior(dimvec, m_Lambda);
printf('construct_prior_us: P_Lambda %s, P_Phi %s, P_phi %s\n', ...
    mat2str(size(prior.P_Lambda)), mat2str(size(prior.P_Phi)), mat2str(size(prior.P_phi)));

save('-v7', 'fixtures_mat/construct_prior_us.mat', 'dimvec', 'm_Lambda', 'prior');


%% ------------------------------------------------------------------
%% update_scl - posterior weights only, never the draw.
%% Inputs use the real support from S_update.m (n_s = 100, vals = [1; 2..5])
%% and the real median pi_f/pi_e, on a deterministic x built without any RNG so
%% a human can regenerate it by hand. Two cases: no missing, and missing.
%% ------------------------------------------------------------------
T_scl    = WINDOW;
tt       = (1:T_scl)';
n_s_vals = 100;
vals     = [1; linspace(2, 5, n_s_vals-1)'];

pi_f  = param.pi_f(1);
probs = [pi_f, (1-pi_f)/(n_s_vals-1)*ones(1, n_s_vals-1)];

x            = 2*sin(tt) + cos(tt/3);
x(20)        = 7.5;      % clear outlier -> posterior mass away from vals = 1
x(40)        = 0;        % exact zero
x_miss       = x;
x_miss([5 6 7]) = NaN;
x_miss(55:T_scl) = NaN;  % ragged tail

posteriors      = update_scl_posteriors(x,      vals, probs);
posteriors_miss = update_scl_posteriors(x_miss, vals, probs);
printf('update_scl: posteriors %s, row 20 argmax at vals = %g\n', ...
    mat2str(size(posteriors)), vals(find(posteriors(20, :) == max(posteriors(20, :)), 1)));

save('-v7', 'fixtures_mat/update_scl.mat', ...
    'x', 'x_miss', 'vals', 'probs', 'posteriors', 'posteriors_miss');


%% ------------------------------------------------------------------
%% update_vol_cond - the mixture posteriors plus the whole local-level filter
%% and smoother, run with the two random draws injected (see the shim header).
%% Two cases exercise the two separate filter branches in update_vol.m.
%% ------------------------------------------------------------------
sigma_in   = 0.5 + 0.4*sin(tt/5);              % strictly positive
gamma      = param.gamma_f(1);
mean_prior = 0;
var_prior  = 1e6;
utmp       = sin((1:(T_scl+1))'/2);            % deterministic stand-in for randn

% Deterministic stand-in for mnrnd: the one-hot argmax of each posterior row.
onehot = @(P) double(bsxfun(@eq, P, max(P, [], 2)) & ...
    cumsum(double(bsxfun(@eq, P, max(P, [], 2))), 2) == 1);

posteriors0 = update_vol_cond(x, sigma_in, gamma, zeros(T_scl, 10), utmp, mean_prior, var_prior);
weights     = onehot(posteriors0);
[posteriors, mean_t, vars_t, y_t, x1_KF, p1_KF, x2_KF, p2_KF, ln_sigmasq, sigma_out] = ...
    update_vol_cond(x, sigma_in, gamma, weights, utmp, mean_prior, var_prior);

posteriors0_miss = update_vol_cond(x_miss, sigma_in, gamma, zeros(T_scl, 10), utmp, mean_prior, var_prior);
weights_miss     = onehot(posteriors0_miss);
[posteriors_miss, mean_t_miss, vars_t_miss, y_t_miss, x1_KF_miss, p1_KF_miss, ...
 x2_KF_miss, p2_KF_miss, ln_sigmasq_miss, sigma_out_miss] = ...
    update_vol_cond(x_miss, sigma_in, gamma, weights_miss, utmp, mean_prior, var_prior);

printf('update_vol_cond: posteriors %s, sigma_out in [%g, %g]\n', ...
    mat2str(size(posteriors)), min(sigma_out), max(sigma_out));
printf('update_vol_cond: missing branch, %d NaN in y_t\n', sum(isnan(y_t_miss)));

save('-v7', 'fixtures_mat/update_vol_cond.mat', ...
    'x', 'x_miss', 'sigma_in', 'gamma', 'utmp', 'mean_prior', 'var_prior', ...
    'weights', 'posteriors', 'mean_t', 'vars_t', 'y_t', ...
    'x1_KF', 'p1_KF', 'x2_KF', 'p2_KF', 'ln_sigmasq', 'sigma_out', ...
    'weights_miss', 'posteriors_miss', 'mean_t_miss', 'vars_t_miss', 'y_t_miss', ...
    'x1_KF_miss', 'p1_KF_miss', 'x2_KF_miss', 'p2_KF_miss', 'ln_sigmasq_miss', 'sigma_out_miss');

printf('\nAll fixtures written to fixtures_mat/. Now run: ../.venv/bin/python matload.py\n');
