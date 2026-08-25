"""Model specification loader for the nowcast model.

Ports ``functions/load_spec.m``.

``load_spec`` sorts every field of the spec by frequency, monthly before
quarterly, using the order ``{'d', 'w', 'm', 'q', 'sa', 'a'}``. Every
downstream index (``isquart``, ``i_now``, ``Y_location``, ``Y_scale``)
assumes that order, so the permutation must be applied to *all* fields,
not just the text columns.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

FREQUENCY_ORDER = ("d", "w", "m", "q", "sa", "a")

# Mirrors the sequence of strrep calls in load_spec.m, in source order.
_UNITS_TRANSFORMED_SUBSTITUTIONS = (
    ("lin", "Levels (No Transformation)"),
    ("chg", "Change (Difference)"),
    ("ch1", "Year over Year Change (Difference)"),
    ("pch", "Percent Change"),
    ("pc1", "Year over Year Percent Change"),
    ("pca", "Percent Change (Annual Rate)"),
    ("cch", "Continuously Compounded Rate of Change"),
    ("cca", "Continuously Compounded Annual Rate of Change"),
    ("log", "Natural Log"),
)


@dataclass
class ModelSpec:
    """Model specification for the dynamic factor model."""

    series_id: list[str]
    series_name: list[str]
    frequency: list[str]
    units: list[str]
    transformation: list[str]
    category: list[str]
    units_transformed: list[str]
    trend: np.ndarray       # (n,)
    blocks: np.ndarray      # (n, n_f)
    prior: np.ndarray       # (n,)
    block_names: list[str]
    category_names: list[str]


def _find_column(header: list[str], name: str) -> str:
    for h in header:
        if h.lower() == name.lower():
            return h
    raise ValueError(f"{name} column missing from model specification.")


def load_spec(specfile: str | Path) -> ModelSpec:
    """Load model specification for a dynamic factor model (DFM)."""
    raw = pd.read_csv(specfile)
    header = list(raw.columns)

    # Parse fields given by column names in the spec worksheet
    text_field_names = (
        "SeriesID",
        "SeriesName",
        "Frequency",
        "Units",
        "Transformation",
        "Category",
    )
    text_fields = {
        name: raw[_find_column(header, name)].astype(str).tolist()
        for name in text_field_names
    }

    # Include text for transformed units
    units_transformed = list(text_fields["Transformation"])
    for code, label in _UNITS_TRANSFORMED_SUBSTITUTIONS:
        units_transformed = [s.replace(code, label) for s in units_transformed]

    # Parse trend
    trend_col = _find_column(header, "Trend")
    trend = raw[trend_col].to_numpy(dtype=float).copy()
    is_pch = np.array([t == "pch" for t in text_fields["Transformation"]])
    trend[is_pch] = trend[is_pch] / 12.0  # Scale down trend for monthly series

    # Parse blocks
    block_cols = [h for h in header if h.lower().startswith("block")]
    blocks = raw[block_cols].to_numpy(dtype=float).copy()
    blocks[blocks == 1] = np.nan  # Set unrestricted loadings to NaN
    blocks[blocks > 1] = 1.0      # Set normalizing loadings to 1

    # Parse prior
    prior_col = _find_column(header, "Prior")
    prior = raw[prior_col].to_numpy(dtype=float)

    # Sort all fields of spec in order of decreasing frequency
    frequency = text_fields["Frequency"]
    permutation = _frequency_permutation(frequency)
    # THE GUARD HAS TO LIVE HERE. The data panel is built in raw CSV column
    # order and is never permuted with the spec, so this permutation must be
    # the identity or every series label attaches to the wrong panel row. No
    # downstream caller can check that -- ModelSpec carries neither the raw
    # order nor the permutation, and by the line below `frequency` is the
    # sorted list, which is non-decreasing by construction.
    check_panel_row_order(frequency)

    series_id = [text_fields["SeriesID"][i] for i in permutation]
    series_name = [text_fields["SeriesName"][i] for i in permutation]
    frequency = [frequency[i] for i in permutation]
    units = [text_fields["Units"][i] for i in permutation]
    transformation = [text_fields["Transformation"][i] for i in permutation]
    category = [text_fields["Category"][i] for i in permutation]
    units_transformed = [units_transformed[i] for i in permutation]
    trend = trend[permutation]
    blocks = blocks[permutation, :]
    prior = prior[permutation]

    # Define block names
    block_names = [re.sub(r"Block\d+_", "", h) for h in block_cols]

    # Create category names
    category_names = sorted(set(category))

    return ModelSpec(
        series_id=series_id,
        series_name=series_name,
        frequency=frequency,
        units=units,
        transformation=transformation,
        category=category,
        units_transformed=units_transformed,
        trend=trend,
        blocks=blocks,
        prior=prior,
        block_names=block_names,
        category_names=category_names,
    )


def _frequency_permutation(frequency: Sequence[str]) -> np.ndarray:
    """``load_spec.m``'s stable sort of row indices into ``FREQUENCY_ORDER``.

    Shared by :func:`load_spec` and :func:`check_panel_row_order` so the guard
    can never test a different permutation from the one actually applied.

    Note this silently omits any row whose frequency is not in
    ``FREQUENCY_ORDER``; that is the MATLAB's behaviour and it is exactly what
    :func:`check_panel_row_order` exists to catch.
    """
    permutation: list[int] = []
    for freq in FREQUENCY_ORDER:
        permutation.extend(i for i, f in enumerate(frequency) if f == freq)
    return np.array(permutation, dtype=int)


def check_panel_row_order(frequency: Sequence[str]) -> None:
    """Raise unless the spec CSV needs no reordering and loses no rows.

    Takes the **raw** ``Frequency`` column, in CSV order, and must be called
    before ``load_spec`` permutes anything. It cannot be written against a
    loaded :class:`ModelSpec`: ``load_spec`` overwrites ``frequency`` with the
    permuted list, which is sorted by construction, so a ``ModelSpec``-taking
    version of this function passes on every input it can ever be handed.

    Two distinct failures, because they are different problems for whoever
    hits them:

    * **A dropped row.** The permutation omits any row whose frequency is not
      in ``FREQUENCY_ORDER``, shortening ``series_id``, ``blocks``, ``trend``
      and ``prior`` below the panel's row count while the data panel keeps
      every column. Nothing asserts those lengths agree.
    * **An unsorted spec.** ``load_spec`` permutes the spec monthly-before-
      quarterly but the data panel is built in raw ``.mat`` column order and
      is never permuted -- see ``example_nowcast.m``, which the port is
      faithful to. The two agree only while the permutation is the identity,
      which for ``model_spec_FRED.csv`` it is: 28 monthly rows, then 3
      quarterly ones. Interleave them and every series label in the news table
      attaches to the wrong panel row, and ``i_now`` -- which feeds the point
      nowcast, the revision terms, the weights, the impacts and the density
      loop -- points at the wrong series.
    """
    frequency = list(frequency)
    n = len(frequency)
    permutation = _frequency_permutation(frequency)

    if len(permutation) != n:
        bad_rows = [i for i, f in enumerate(frequency) if f not in FREQUENCY_ORDER]
        bad_freqs = sorted({frequency[i] for i in bad_rows})
        raise ValueError(
            f"load_spec would DROP {len(bad_rows)} of {n} spec rows: "
            f"row(s) {bad_rows} carry frequency {bad_freqs}, which is not in "
            f"FREQUENCY_ORDER = {FREQUENCY_ORDER}. Dropped rows shorten "
            "series_id/series_name/blocks/trend/prior below the panel's row "
            "count while the data panel keeps every column, so every "
            "downstream index would be off by the number of dropped rows. "
            "Add the frequency to FREQUENCY_ORDER, or remove the row from the "
            "spec and from the panel together."
        )

    ranks = [FREQUENCY_ORDER.index(f) for f in frequency]
    descent = next((i for i in range(1, n) if ranks[i] < ranks[i - 1]), None)
    if descent is not None:
        raise ValueError(
            "spec rows are NOT in frequency order, so load_spec's permutation "
            f"is not the identity: raw row {descent} is "
            f"{frequency[descent]!r} after raw row {descent - 1} is "
            f"{frequency[descent - 1]!r}. The data panel is built in raw CSV "
            "order and is not permuted with the spec, so series labels would "
            "attach to the wrong panel rows. Sort the spec CSV by frequency "
            f"in the order {FREQUENCY_ORDER}."
        )
