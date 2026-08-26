"""PCA seeding for the Australian loading matrix.

The NY Fed ships ``initval.mat``; Australia generates its own. The seed only
has to be sane -- the Gibbs sampler re-estimates from it. What it must not do
is put a non-zero loading where the spec says a series does not load on a
factor: those zeros are structural, and a seed that fills them starts the
sampler somewhere the model cannot represent.

FILL STRATEGY
--------------
Missing observations are filled with 0.0 (the panel is already standardised,
so 0.0 is each series' own sample mean) before the SVD. ``initval.mat`` is a
delivered binary with no vendored source for how it was built, so this is
not claimed to reproduce it -- only to be a sane starting point for a
dynamic factor model, the same balanced-panel-by-zero-fill approximation
textbook PCA-based DFM initialisation (e.g. Stock & Watson) uses. Any bias
the zero-fill introduces is corrected once the Gibbs sampler starts drawing.

A row that is entirely missing (all-NaN, e.g. a series dropped mid-history)
is excluded from the decomposition rather than handed to it as a zero-filled
row. Mathematically an all-zero row's SVD contribution collapses to
~1e-16 either way once every retained singular value is non-zero, which is
the ordinary case for a noisy panel -- so excluding it is not correcting a
material bias. What it buys is exactness: the row is set to precisely 0.0
by construction rather than left at whatever floating-point residue the
decomposition happens to produce, which matters because a series with no
data at all should read as an unambiguous zero seed, not a value that is
merely close to it. (Verified empirically: without the exclusion, the same
test panel's all-NaN row comes back ``!= 0.0`` at the ~1e-17 level -- finite
and harmless, but not the exact zero a never-observed series should get.)
It is left at exactly 0.0 in ``Lambda`` -- finite, structurally sane, and
immediately overwritten by the sampler with real data.

The exclusion also guards the genuinely degenerate case: if fewer than two
rows carry any observation at all, the decomposition is skipped outright
(``observed.sum() >= 2`` below) rather than run on a near-empty matrix,
whose singular vectors would be numerically arbitrary rather than sane.

A row that has *some* observations but fewer than ``n_f`` does not get
special-cased: it is zero-filled at the missing timestamps and included in
the joint SVD like any other row, and comes back with whatever loading the
decomposition assigns it -- typically small, because a mostly-zero row
correlates weakly with the panel's common factors, but not NaN and not
forced to zero. The Australian panel has genuinely ragged history (household
spending from 2012, monthly CPI from 2024), and a short row is normal here,
not a bug to be caught.

The degenerate case where FEWER series are observed than there are factors
(``n_observed < n_f``) is also handled without special-casing: ``numpy``
slicing past the end of an array returns what exists rather than raising, so
the SVD's rank -- capped at ``min(n_observed, T)`` -- silently caps how many
factor columns get a non-trivial seed; the rest stay at zero. That is a
degenerate seed, not a crash, and it is not a configuration this 15-series
panel is expected to hit.
"""

from __future__ import annotations

import numpy as np

from nyfed.au.panel import Panel
from nyfed.au.sources import SPEC_PATH
from nyfed.spec import load_spec


def seed_lambda(panel: Panel, spec_path=SPEC_PATH) -> np.ndarray:
    """Seed ``param.Lambda`` by principal components on the assembled panel."""
    spec = load_spec(spec_path)
    n, n_f = spec.blocks.shape

    filled = np.where(np.isnan(panel.Y), 0.0, panel.Y)
    # Rows that are entirely missing are excluded rather than zero-filled and
    # handed to the SVD: it makes no material difference to what a never-
    # observed row's own loading would numerically come out to (see the
    # module docstring), but it does guarantee that loading is EXACTLY 0.0
    # rather than floating-point residue, and it keeps a near-empty panel
    # from feeding the decomposition a matrix with too few real rows to mean
    # anything.
    observed = ~np.isnan(panel.Y).all(axis=1)

    Lambda = np.zeros((n, n_f), dtype=float)
    if observed.sum() >= 2:
        U, S, _ = np.linalg.svd(filled[observed], full_matrices=False)
        components = U[:, :n_f] * S[:n_f]
        Lambda[observed, : components.shape[1]] = components[:, :n_f]

    # Orient each column to its block's NORMALISING series before anything
    # else looks at the signs. `np.linalg.svd` returns either sign of a
    # principal component with equal right, but `model_spec_AU.csv` fixes one
    # loading per block at +1 (the `100` entries, which `load_spec` rescales to
    # 1.0), and that fixes the factor's sign: the factor is DEFINED to move with
    # that series. An unoriented seed contradicts that about half the time, and
    # the contradiction is not cosmetic -- this matrix is the prior MEAN for
    # every free loading in the column (`construct_prior`, precision 10, so a
    # prior standard deviation near 0.32), so a flipped column pulls the whole
    # block toward the wrong sign while the normaliser stays pinned at +1.
    # Measured on the real panel before this line existed: the Global column
    # was seeded negative for 12 of 15 series, its own normaliser included, and
    # GDP's Global loading was still -0.76 after 3,000 sweeps -- real GDP growth
    # loading the broadest factor against real consumption growth. A block with
    # no normaliser (Soft) has no sign to be consistent with and is left alone.
    normalising = np.nan_to_num(spec.blocks) == 1.0
    for i_f in range(n_f):
        rows = np.flatnonzero(normalising[:, i_f])
        if rows.size and Lambda[rows[0], i_f] < 0.0:
            Lambda[:, i_f] = -Lambda[:, i_f]

    # Respect the spec's structural zeros BEFORE normalising, not after: a
    # block's structural-zero count is a fact about the panel's design (how
    # many series were specified to load on it), not evidence about the
    # strength of that factor, and normalising first would make each column's
    # seed magnitude a mechanical function of that count instead of signal.
    Lambda[spec.blocks == 0] = 0.0

    # Normalise each factor's loadings to unit scale so every block gets a
    # unit-norm prior mean regardless of how many series load on it, and so
    # the seed does not depend on the panel's length.
    norms = np.linalg.norm(Lambda, axis=0, keepdims=True)
    Lambda = np.divide(Lambda, norms, out=np.zeros_like(Lambda), where=norms > 0)
    return Lambda
