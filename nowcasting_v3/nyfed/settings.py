"""Gibbs sampler settings for the New York Fed Nowcast 2.0.

Ports ``functions/load_settings.m``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GibbsSettings:
    """Settings for the Gibbs sampler.

    Mirrors ``load_settings.m``'s numeric fields (``settings.n_GS`` etc).
    The MATLAB struct also carries ``plot_MCMC`` / ``plot_each`` display
    flags, which are display-only and out of scope here.
    """

    n_gs: int = 10000
    n_burn: int = 8000
    n_init: int = 50
    n_thin: int = 2
    n_each: int = 8
    state_each: int = 1
