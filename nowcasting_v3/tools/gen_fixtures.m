% GEN_FIXTURES  Generate test-oracle fixtures from the vendored MATLAB code.
%
% Runs reference functions in nyfed_matlab/ (read-only) on small, fixed-seed
% inputs and saves the inputs and outputs as -v7 .mat files. Those are then
% converted to .npz for the Python tests:
%
%   cd nowcasting_v3/tools
%   octave gen_fixtures.m
%   ../.venv/bin/python matload.py fixtures_mat/kalman_basic.mat ../tests/fixtures/kalman_basic.npz
%
% Fixtures are gitignored; regenerate them rather than committing them.
% Later tasks append further fixture blocks to this file.

addpath('../nyfed_matlab/functions/general')
addpath('../nyfed_matlab/functions/model')
pkg load statistics

mkdir('fixtures_mat');


%% kalman_basic: Kalman_filter on a small SSM with one missing observation
rand('state', 321); randn('state', 321);

N = 2; M = 3; K = 3; T = 20;
SSM = struct();
SSM.D         = zeros(N,1);
SSM.H         = [1 0 0; 0 1 0];
SSM.Sigma_eps = 1e-4*eye(N);
SSM.C         = zeros(M,1);
SSM.F         = 0.5*eye(M);
SSM.G         = eye(M);
SSM.Sigma_eta = eye(K);
SSM.mu_1      = zeros(M,1);
SSM.Sigma_1   = eye(M);
Y = randn(N, T);
Y(1, 5) = NaN;   % exercise the missing-data branch

[ll, pred, filt] = Kalman_filter(Y, SSM);
printf('kalman_basic: loglik = %.12f\n', ll);
save('-v7', 'fixtures_mat/kalman_basic.mat', 'Y', 'SSM', 'll', 'pred', 'filt');
