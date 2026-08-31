"""The Australian panel for the v3 nowcast engine.

The engine in ``nyfed/`` is panel-agnostic: it consumes a spec CSV and a
standardised ``(n, T)`` matrix. This subpackage produces the Australian
versions of both and changes nothing in the engine.
"""

from nyfed.au.sources import AU_SERIES, SPEC_PATH, SeriesSource

__all__ = ["AU_SERIES", "SPEC_PATH", "SeriesSource"]
