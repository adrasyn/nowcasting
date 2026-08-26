"""Unit conversion for the published Australian figure.

Spec decision D4: the model keeps the NY Fed's annualised quarterly growth and
its Mariano-Murasawa aggregation weights unchanged, so every Octave fixture
stays valid and the padding bug at construct_SSM.m:131 never fires. The
conversion to the quarter-on-quarter figure Australia publishes happens here,
at the presentation layer.

Compounding, not division. At 4% annualised the difference between the two is
0.0147pp -- larger than the +-0.01pp tolerance Plan A's gate held itself to.
"""

from __future__ import annotations

import numpy as np


def annualised_to_qoq(annualised):
    """Annualised quarterly growth (percent) to quarter-on-quarter (percent)."""
    return 100.0 * (np.power(1.0 + np.asarray(annualised, dtype=float) / 100.0, 0.25) - 1.0)


def qoq_to_annualised(qoq):
    """Quarter-on-quarter growth (percent) to annualised (percent)."""
    return 100.0 * (np.power(1.0 + np.asarray(qoq, dtype=float) / 100.0, 4.0) - 1.0)
