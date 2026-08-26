"""Model restrictions for the Australian panel.

Ports ``example_estimate.m:70-85``. This is where spec decision D3 lives:
``Restrict.f_active`` is the boolean mask that confines the COVID factor to the
pandemic window, and without it that factor is active over the whole sample
and distorts every other factor.

The window is March 2020 to December 2021. **That is identical to the NY
Fed's own window** -- spec D3 chose it from Australia's lockdowns and the
closed border, and it happens to coincide, so no re-dating is required. Do
not go looking for a difference from the US code here; there isn't one.

Three details that are easy to get backwards:

1. ``iota`` divides the spec's trend by the PANEL's ``y_scale`` -- the scale
   computed AFTER standardisation, not any scale read off the raw trend.
   Building it from the raw trend puts the trend on the wrong scale and the
   model fits around it.
2. The COVID factor is isolated in the factor VAR: its row and column of
   ``Phi`` are zeroed, and only its own diagonal is left free (``NaN``, the
   engine's marker for "estimate this"), so it neither drives nor is driven
   by the other factors.
3. ``f_active`` is set ``False`` OUTSIDE the window, not inside it. Inverting
   this switches the pandemic factor on for the whole sample except the
   pandemic -- a plausible-looking bug that is exactly backwards.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from nyfed.au.panel import Panel
from nyfed.model import Restrict
from nyfed.spec import ModelSpec

COVID_START = pd.Timestamp("2020-03-01")
COVID_END = pd.Timestamp("2021-12-01")


def build_restrict(panel: Panel, spec: ModelSpec, *, p_f: int = 4) -> Restrict:
    """Build the restriction struct for one assembled panel.

    Mirrors ``example_estimate.m:70-85``: ``Lambda`` is the spec's block
    pattern verbatim, ``Phi`` starts fully free (``NaN``) and then has the
    COVID factor's row/column zeroed if a COVID block is present, ``iota`` is
    the spec's trend on the panel's own scale, and ``f_active`` confines the
    COVID factor to ``[COVID_START, COVID_END]`` inclusive.
    """
    n, n_f = spec.blocks.shape
    T = panel.Y.shape[1]

    Lambda = spec.blocks.copy()
    Phi = np.full((n_f, n_f, p_f), np.nan)
    # iota divides by the PANEL's scale (example_estimate.m:72: `Y_scale`),
    # not any scale derived from the raw trend -- see docstring point 1.
    iota = spec.trend / panel.y_scale.ravel()
    isquart = np.array([f == "q" for f in spec.frequency], dtype=bool)
    f_active = np.ones((n_f, T), dtype=bool)

    if "COVID" in spec.block_names:
        i_cov = spec.block_names.index("COVID")
        # Isolate the pandemic factor in the factor VAR: it neither drives
        # nor is driven by the others (example_estimate.m:80-82, docstring
        # point 2).
        Phi[i_cov, :, :] = 0.0
        Phi[:, i_cov, :] = 0.0
        Phi[i_cov, i_cov, :] = np.nan
        # False OUTSIDE the window, not inside it -- docstring point 3.
        outside = (panel.dates < COVID_START) | (panel.dates > COVID_END)
        f_active[i_cov, outside] = False

    return Restrict(
        Lambda=Lambda, Phi=Phi, iota=iota, f_active=f_active, isquart=isquart
    )
