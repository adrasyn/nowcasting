% Probe: can Octave run the numerical core? No datetime anywhere below.
addpath('../nyfed_matlab/functions/general')
addpath('../nyfed_matlab/functions/model')
pkg load statistics
rand('state', 321); randn('state', 321);

% Minimal well-posed SSM: 2 series, 3 states, 20 periods
N = 2; M = 3; K = 3; T = 20;
SSM = struct();
SSM.D = zeros(N,1);
SSM.H = [1 0 0; 0 1 0];
SSM.Sigma_eps = 1e-4*eye(N);
SSM.C = zeros(M,1);
SSM.F = 0.5*eye(M);
SSM.G = eye(M);
SSM.Sigma_eta = eye(K);
SSM.mu_1 = zeros(M,1);
SSM.Sigma_1 = eye(M);
Y = randn(N, T);
Y(1, 5) = NaN;   % exercise the missing-data branch

[ll, pred, filt] = Kalman_filter(Y, SSM);
printf('loglik = %.12f\n', ll);
save('-v7', 'probe_out.mat', 'Y', 'SSM', 'll', 'pred', 'filt');
