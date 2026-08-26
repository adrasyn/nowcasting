"""Executable tests for the four landmines Plan A recorded.

Each was a place where the port faithfully reproduces MATLAB behaviour that is
correct for the US panel and silently wrong for a different one. Comments do
not stop a landmine; these do.
"""

import csv

import numpy as np
import pytest

from nyfed.au.sources import AU_SERIES, SPEC_PATH
from nyfed.model import Latent, Restrict, construct_ssm
from nyfed.parameters import Params
from nyfed.spec import load_spec

BLOCK_COLS = [
    "Block0_Global",
    "Block1_Soft",
    "Block2_Nominal",
    "Block3_Labor",
    "Block4_COVID",
]

MM_WEIGHTS = np.array([1.0, 2.0, 3.0, 2.0, 1.0]) / 9.0


def test_covid_is_the_fifth_factor():
    """LANDMINE 2. Gibbs_update.m:156-158 pins factor five's stochastic
    volatility at one by hard-coded index. In the NY Fed panel factor five is
    COVID, so the literal port does the intended thing -- but only while COVID
    stays in slot five. Reorder the blocks and that factor silently loses its
    stochastic volatility, with nothing downstream contradicting it, because
    the end-to-end gate nowcasts from stored estimates and never runs the
    sampler."""
    spec = load_spec(SPEC_PATH)
    assert spec.block_names[4] == "COVID"
    assert len(spec.block_names) == 5


def test_the_spec_csv_is_frequency_sorted():
    """LANDMINE 1. load_spec permutes fields monthly-before-quarterly while the
    panel is built in raw CSV order. The guard inside load_spec raises if the
    permutation is not the identity; this asserts the Australian CSV satisfies
    it rather than relying on the guard firing during a live run."""
    with open(SPEC_PATH, newline="") as fh:
        freqs = [r["Frequency"] for r in csv.DictReader(fh)]
    assert freqs == sorted(freqs, key=["d", "w", "m", "q", "sa", "a"].index)


def test_the_quarterly_aggregation_weights_are_unchanged():
    """LANDMINE 3. construct_SSM.m:131 pads the quarterly H branch using
    len(vec_m) where len(vec_q) is meant. Harmless only while both are length
    five. Spec decision D4 keeps the model annualised precisely so this never
    fires; if a later change re-derives the filter for QoQ, this test is the
    trip wire.

    Builds a minimal two-series (one monthly, one quarterly), single-factor
    state space directly -- not from a fixture -- and inspects the actual
    constructed ``H`` matrix rather than a docstring, so a length change to
    ``vec_q`` (construct_ssm.py's port of ``vec_q``) fails this test even
    when the padding arithmetic still happens to produce the right shape.
    """
    n, n_f, p_f, p_e, T = 2, 1, 1, 1, 6
    iota_q = 3.0
    lambda_q = 2.0
    param = Params(
        mu=np.zeros(n),
        gamma_g=1.0,
        Lambda=np.array([[1.0], [lambda_q]]),
        Phi=np.full((n_f, n_f, p_f), 0.5),
        gamma_f=np.ones(n_f),
        pi_f=np.full(n_f, 0.1),
        phi=np.zeros((n, p_e)),
        gamma_e=np.ones(n),
        pi_e=np.full(n, 0.1),
    )
    latent = Latent(sigma=np.ones((n_f + n, T)), s=np.ones((n_f + n, T)))
    restrict = Restrict(
        Lambda=param.Lambda,
        Phi=param.Phi,
        iota=np.array([1.0, iota_q]),
        f_active=None,
        isquart=np.array([False, True]),
    )
    ssm = construct_ssm(param, latent, restrict)

    isq = restrict.isquart
    h0 = ssm.H[:, :, 0]
    # Trend block (state cols 0:5): kron(vec_q, iota_q).
    assert np.allclose(h0[isq, :5], iota_q * MM_WEIGHTS, rtol=0, atol=1e-12)
    # Factor block (state cols 5:10 for n_f=1): kron(vec_q, Lambda_q).
    assert np.allclose(h0[isq, 5:10], lambda_q * MM_WEIGHTS, rtol=0, atol=1e-12), (
        "quarterly row of H no longer carries the Mariano-Murasawa weights on "
        "the factor loading; re-read construct_SSM.m:131 before trusting any "
        "quarterly row of H"
    )


def test_update_vol_does_not_propagate_nan_at_the_volatility_cap():
    """LANDMINE 4. np.minimum propagates NaN where MATLAB's min omits it, at
    the bd = 15 cap in update_vol. Unreachable with US missingness. Australian
    missingness differs -- ragged starts and quarterly-only series -- and this
    is the one landmine that cannot be ruled out by inspection.

    Drive the updater with a NaN in the position the cap touches and assert the
    output is finite."""
    from nyfed.updates import update_vol

    rng = np.random.default_rng(11)
    T = 60
    x = rng.standard_normal(T)
    x[7] = np.nan                      # the ragged-start pattern US data lacks
    sigma = np.full(T, 0.5)
    out = update_vol(x, sigma, 0.9, 0.0, 1e6, rng)
    assert np.isfinite(np.asarray(out)).all(), (
        "a NaN observation produced a NaN volatility; the bd = 15 cap "
        "propagated it. See Plan A landmine 4."
    )


def test_every_factor_except_soft_has_exactly_one_normaliser():
    """Not a Plan A landmine, but the same class: two of the NY Fed's three
    normalising series (INDPRO for Global, PCEPI for Nominal) have no
    Australian counterpart, so Australia nominates its own. A factor with no
    normaliser has an unidentified scale and the sampler will wander."""
    with open(SPEC_PATH, newline="") as fh:
        rows = list(csv.DictReader(fh))
    counts = {c: sum(float(r[c]) > 1 for r in rows) for c in BLOCK_COLS}
    assert counts["Block0_Global"] == 1
    assert counts["Block2_Nominal"] == 1
    assert counts["Block3_Labor"] == 1
    assert counts["Block4_COVID"] == 1
    assert counts["Block1_Soft"] == 0
