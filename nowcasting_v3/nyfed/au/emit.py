"""Unit conversion for the published Australian figure.

Spec decision D4: the model keeps the NY Fed's annualised quarterly growth and
its Mariano-Murasawa aggregation weights unchanged, so every Octave fixture
stays valid and the padding bug at construct_SSM.m:131 never fires. The
conversion to the quarter-on-quarter figure Australia publishes happens here,
at the presentation layer.

Compounding, not division. At 4% annualised the difference between the two is
0.0147pp -- larger than the +-0.01pp tolerance Plan A's gate held itself to.

Both directions reject growth at or below -100% with a ValueError, raised by
this module itself rather than relying on pytest's filterwarnings=error to
promote the RuntimeWarning that np.power otherwise emits. For
annualised_to_qoq specifically, below -100% the fourth root of a negative
base has no real value. For both directions, -100% means the quantity goes
to zero within the period -- not an economically reachable quarterly or
annual outcome for GDP, so the bound is enforced symmetrically even on the
qoq_to_annualised side, where raising an integer power does not itself
produce a NaN. This is the last module before a number reaches a reader, so
a silent NaN here must not be possible outside a test harness.
"""

from __future__ import annotations

import numpy as np


def annualised_to_qoq(annualised):
    """Annualised quarterly growth (percent) to quarter-on-quarter (percent)."""
    arr = np.asarray(annualised, dtype=float)
    if np.any(arr <= -100.0):
        raise ValueError(
            f"annualised growth must be > -100 (percent); got {annualised!r}. "
            "Below -100% the fourth root has no real value, and -100% "
            "annualised means output going to zero over a year, which is "
            "not an economically reachable quarterly outcome."
        )
    return 100.0 * (np.power(1.0 + arr / 100.0, 0.25) - 1.0)


def qoq_to_annualised(qoq):
    """Quarter-on-quarter growth (percent) to annualised (percent)."""
    arr = np.asarray(qoq, dtype=float)
    if np.any(arr <= -100.0):
        raise ValueError(
            f"qoq growth must be > -100 (percent); got {qoq!r}. -100% qoq "
            "means output going to zero within a single quarter, which is "
            "not an economically reachable outcome; the bound is kept "
            "symmetric with annualised_to_qoq's even though raising an "
            "integer power (4) of a negative base is mathematically well "
            "defined and would not itself produce a NaN here."
        )
    return 100.0 * (np.power(1.0 + arr / 100.0, 4.0) - 1.0)
