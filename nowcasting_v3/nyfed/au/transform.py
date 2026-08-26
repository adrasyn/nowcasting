"""Apply the spec's ``Transformation`` column to the raw panel.

WHY THIS MODULE EXISTS
----------------------
The NY Fed drop ships **pre-transformed** ``Data_*.mat`` files and
``example_nowcast.m`` only standardises them, so the vendored MATLAB carries no
transform code to port. Verified against ``nyfed_matlab/data/Data_2023_09_29.mat``:
``PAYEMS`` (spec ``chg``) runs -20514..4565 rather than the ~150,000 level,
``CPIAUCSL`` (spec ``pch``) runs -1.77..1.38 rather than the ~300 index, and
``GDPC1`` (spec ``pca``) ends at 2.06 -- that quarter's annualised growth.

We fetch levels, so we have to build the step they did not ship. Without it the
Australian panel reaches the engine as standardised LEVELS where the spec
declares growth rates. The model runs, and every number it produces is wrong,
with nothing downstream to contradict it.

THE STEP IS NOT ALWAYS ONE MONTH
--------------------------------
The panel grid is monthly. A monthly series' predecessor is the previous grid
column, so ``k = 1``. A quarterly series is observed only in months 3, 6, 9 and
12 (``panel._align``), so its predecessor is **three** grid columns back, not
one: ``k = 3``. With ``k = 1`` every quarterly cell would be compared against an
empty month and the whole row would go NaN.

The annualisation exponent comes from the same fact. ``pca`` raises the
period-on-period ratio to the number of periods in a year: 12 for a monthly
series, **4** for a quarterly one. Annualising a quarterly ratio by 12 does not
look wrong -- 1% a quarter becomes 12.7% instead of 4.1%, which is a number a
reader would accept.

``pch`` IS A RATIO, NEVER A LOG DIFFERENCE
------------------------------------------
ABS reports ``imports`` as a debit, so that row is wholly negative
(2026-06 = -45768.0 against exports at +47696.0). ``np.log`` of a negative
number is NaN and raises nothing, so a log-difference ``pch`` would empty the
row in silence and the model would run on fourteen series.
``panel._check_imports_survived`` is the trip wire for exactly that, and it runs
on the output of this module.

ORDER
-----
This runs BEFORE ``standardise``. ``example_nowcast.m`` computes ``Y_location``
and ``Y_scale`` from transformed data; standardising first would centre and
scale the levels and then difference them, which is a different number.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from nyfed.spec import ModelSpec

# Grid columns back to the previous OBSERVATION, and periods per year, keyed by
# the spec's Frequency code. Both entries of a pair come from the same fact --
# how often the series is observed on a monthly panel grid -- so they are
# written as one table rather than two, and an unknown frequency raises here
# rather than defaulting to monthly.
_FREQUENCY: dict[str, tuple[int, int]] = {
    "m": (1, 12),
    "q": (3, 4),
}

TRANSFORMATIONS = frozenset({"lin", "chg", "pch", "pca"})


def _ratio(x: np.ndarray, lag: np.ndarray) -> np.ndarray:
    """``x / lag`` with NaN wherever the ratio is not defined.

    Guarded rather than left to numpy because the suite runs under
    ``filterwarnings = ["error"]``: ``0 / 0`` and ``x / 0`` are RuntimeWarnings,
    which would surface as a test error far from the series that caused them.
    A zero denominator is a percent change against nothing, so NaN is the
    honest answer.
    """
    out = np.full(x.shape, np.nan)
    ok = np.isfinite(x) & np.isfinite(lag) & (lag != 0.0)
    out[ok] = x[ok] / lag[ok]
    return out


def _shift(row: np.ndarray, k: int) -> np.ndarray:
    """``row`` moved forward ``k`` columns, NaN-padded at the front."""
    lag = np.full(row.shape, np.nan)
    lag[k:] = row[:-k]
    return lag


def _check_monthly_grid(dates: pd.DatetimeIndex, n_columns: int) -> None:
    """Refuse a grid the quarterly step of 3 would be wrong on.

    ``k = 3`` means "one quarter" only because the columns are consecutive
    months. On any other grid the quarterly rows would be differenced against
    the wrong period and still produce plausible numbers.
    """
    dates = pd.DatetimeIndex(dates)
    if len(dates) != n_columns:
        raise ValueError(
            f"dates has {len(dates)} entries but the panel has {n_columns} "
            "columns; the transform's lag is measured in columns, so the two "
            "must describe the same grid."
        )
    if len(dates) > 1:
        expected = pd.date_range(dates[0], periods=len(dates), freq="MS")
        if not dates.equals(expected):
            raise ValueError(
                "the panel grid is not consecutive month starts. The quarterly "
                "step of 3 columns means 'one quarter' only on a monthly grid; "
                "on any other grid quarterly series would be differenced "
                "against the wrong period."
            )


def transform_panel(
    raw: np.ndarray, spec: ModelSpec, dates: pd.DatetimeIndex
) -> np.ndarray:
    """Apply each row's spec transformation, returning an array of the same shape.

    Row ``i`` of ``raw`` must be the series ``spec.series_id[i]`` -- the pairing
    ``panel.assemble`` guards before it calls here.

    Raises on an unrecognised transformation or frequency code. Falling through
    to levels is the failure this module exists to remove, so it must never be
    the default.
    """
    raw = np.atleast_2d(np.asarray(raw, dtype=float))
    n = raw.shape[0]
    if n != len(spec.series_id):
        raise ValueError(
            f"the panel has {n} rows and the spec {len(spec.series_id)}; the "
            "transformation of row i is read from spec row i, so a mismatch "
            "would transform series by the wrong rule."
        )
    _check_monthly_grid(dates, raw.shape[1])

    out = np.empty_like(raw)
    for i, (code, freq) in enumerate(zip(spec.transformation, spec.frequency)):
        if code not in TRANSFORMATIONS:
            raise ValueError(
                f"row {i} ({spec.series_id[i]!r}) declares transformation "
                f"{code!r}, which is not implemented. Known codes are "
                f"{sorted(TRANSFORMATIONS)}. Refusing rather than returning the "
                "series untransformed: an untransformed level standardises "
                "cleanly and the model runs on it without complaint."
            )
        if freq not in _FREQUENCY:
            raise ValueError(
                f"row {i} ({spec.series_id[i]!r}) declares frequency {freq!r}, "
                f"for which no lag is known. Known frequencies are "
                f"{sorted(_FREQUENCY)}. The lag to the previous observation and "
                "the annualisation exponent both depend on it."
            )

        row = raw[i]
        if code == "lin":
            out[i] = row
            continue

        k, periods_per_year = _FREQUENCY[freq]
        lag = _shift(row, k)
        if code == "chg":
            out[i] = row - lag
        elif code == "pch":
            out[i] = 100.0 * (_ratio(row, lag) - 1.0)
        else:  # "pca"
            out[i] = 100.0 * (_ratio(row, lag) ** periods_per_year - 1.0)
    return out
