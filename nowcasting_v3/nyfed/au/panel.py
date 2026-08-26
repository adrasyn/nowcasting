"""Assemble the Australian panel into the matrix the engine consumes.

The engine wants a standardised ``(n, T)`` array in spec row order, with
quarterly series observed in the last month of each quarter and NaN elsewhere.
Missing data stays NaN: the Kalman filter handles it natively, and filling it
would be inventing observations.

TWO THINGS THIS MODULE IS RESPONSIBLE FOR NOT LOSING SILENTLY
-------------------------------------------------------------
**Quarterly alignment.** ``_align`` keeps only months ``{3, 6, 9, 12}``, which
agrees with ``fetch_abs.parse_abs_frame`` dating a quarterly observation to the
LAST month of its quarter. The two halves have to be changed together. Task 2
briefly had start-of-quarter dating, and under it every quarterly observation --
including GDP, the nowcast target -- was dropped by this mask, leaving an
all-NaN target row that the model still ran on. ``standardise`` now refuses an
all-NaN row for that reason, and ``test_a_real_quarterly_payload_survives_the_
alignment_mask`` takes a recorded GDP payload through the real parser rather
than a hand-built test index.

**Imports is negative.** ABS reports imports as a debit, so the row is wholly
negative while exports is wholly positive. That is fine for a ratio ``pch`` and
fatal for a log-difference one: ``np.log`` of a negative number is NaN and
raises nothing, so the panel would quietly carry fourteen live series instead of
fifteen. ``_check_imports_survived`` turns that into a refusal.

WHAT THIS MODULE DOES NOT DO
----------------------------
It does not deflate, and it does not apply the spec's ``Transformation``
column. ``household_spending`` must be passed in ALREADY REAL -- see
``nyfed/au/deflator.py``; the registry's series is at current prices, and it
normalises the Global factor, so a nominal one sets that factor's scale from
inflation.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from nyfed.au.sources import AU_SERIES, SPEC_PATH, SeriesSource
from nyfed.spec import load_spec


@dataclass
class Panel:
    """One assembled vintage."""

    Y: np.ndarray            # (n, T), standardised
    y_location: np.ndarray   # (n, 1)
    y_scale: np.ndarray      # (n, 1)
    dates: pd.DatetimeIndex  # length T
    series_id: list[str]
    i_now: int               # row index of the nowcast target


def standardise(raw: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Centre and scale each row, ignoring NaN.

    A constant row has zero standard deviation; scale it by 1.0 rather than
    dividing by zero, which would turn a degenerate series into NaN and hide it.

    An all-NaN row is refused outright. ``np.nanmean`` would return NaN with a
    RuntimeWarning rather than an error, and a row of NaN is not a degenerate
    series -- it is a series that never arrived.
    """
    raw = np.atleast_2d(np.asarray(raw, dtype=float))
    empty = np.flatnonzero(~np.isfinite(raw).any(axis=1))
    if empty.size:
        raise ValueError(
            f"row(s) {[int(i) for i in empty]} carry no finite observation at "
            "all. A panel "
            "row of NaN is not missing data the filter can handle around, it is "
            "a series that never arrived -- check the alignment mask and the "
            "series' date range."
        )
    location = np.nanmean(raw, axis=1, keepdims=True)
    scale = np.nanstd(raw, axis=1, ddof=1, keepdims=True)
    scale = np.where((scale == 0) | ~np.isfinite(scale), 1.0, scale)
    return (raw - location) / scale, location, scale


def _align(s: pd.Series, dates: pd.DatetimeIndex, source: SeriesSource) -> np.ndarray:
    """Reindex one series onto the panel's monthly grid.

    The ``{3, 6, 9, 12}`` mask is what makes a quarterly row mixed-frequency in
    the shape ``construct_ssm`` expects (``nyfed/model.py``, the ``isquart``
    branch). It agrees with ``fetch_abs.parse_abs_frame``'s end-of-quarter
    dating by design; change one and you must check the other.
    """
    aligned = s.reindex(dates)
    if source.frequency == "q":
        keep = np.isin(dates.month, (3, 6, 9, 12))
        aligned = aligned.where(pd.Series(keep, index=dates))
    return aligned.to_numpy(dtype=float)


def _check_imports_survived(
    rows: dict[str, np.ndarray], dates: pd.DatetimeIndex
) -> None:
    """Refuse a panel whose negative ``imports`` row lost observations.

    The span compared is exports' own observed range, because the two ABS trade
    series are published together and cover the same months; anything less on
    the imports side means a transform, a sign convention or a units change ate
    observations rather than the data being genuinely absent.
    """
    if "imports" not in rows or "exports" not in rows:
        return
    exports, imports = rows["exports"], rows["imports"]
    observed = np.flatnonzero(np.isfinite(exports))
    if observed.size == 0:
        return
    span = slice(observed[0], observed[-1] + 1)
    n_exports = int(np.isfinite(exports[span]).sum())
    n_imports = int(np.isfinite(imports[span]).sum())
    if n_imports < n_exports:
        raise ValueError(
            f"imports carries {n_imports} observations against exports' "
            f"{n_exports} over {dates[observed[0]].date()}.."
            f"{dates[observed[-1]].date()}. ABS reports imports as a DEBIT, so "
            "the series is wholly negative -- np.log of it is NaN and raises "
            "nothing. Check that `pch` is a ratio, not a log difference."
        )


def assemble(
    series: dict[str, pd.Series],
    *,
    start: str,
    end: str,
    spec_path=SPEC_PATH,
    sources: tuple[SeriesSource, ...] = AU_SERIES,
) -> Panel:
    """Build one standardised vintage from fetched series."""
    spec = load_spec(spec_path)

    # The rows are STACKED from `sources` and LABELLED from `spec`. Nothing else
    # ties the two together, so if they ever diverge every series label -- and
    # `i_now`, which feeds the point nowcast, the weights and the impacts --
    # attaches to the wrong panel row, quietly and with the model still running.
    # A test pins it, but a test only covers the default arguments; this covers
    # the call. `load_spec` already refuses a spec whose rows are not in
    # frequency order, so the two guards together mean the panel cannot be
    # mislabelled by a spec edit or by a registry edit.
    if list(spec.series_id) != [s.series_id for s in sources]:
        raise ValueError(
            f"the spec has {len(spec.series_id)} rows and the registry "
            f"{len(sources)}, and they are not the same series in the same "
            f"order:\n  spec     {list(spec.series_id)}\n  registry "
            f"{[s.series_id for s in sources]}\nThe panel is stacked from the "
            "registry and labelled from the spec, so a mismatch attaches every "
            "label -- and i_now -- to the wrong row."
        )

    dates = pd.date_range(start, end, freq="MS")

    aligned: dict[str, np.ndarray] = {}
    for source in sources:
        if source.key not in series:
            raise KeyError(f"{source.key} is registered but was not fetched")
        aligned[source.key] = _align(series[source.key], dates, source)

    _check_imports_survived(aligned, dates)
    raw = np.vstack([aligned[source.key] for source in sources])

    Y, location, scale = standardise(raw)
    return Panel(
        Y=Y,
        y_location=location,
        y_scale=scale,
        dates=dates,
        series_id=list(spec.series_id),
        i_now=spec.series_id.index("gdp"),
    )
