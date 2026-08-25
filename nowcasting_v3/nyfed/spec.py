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
    permutation: list[int] = []
    for freq in FREQUENCY_ORDER:
        permutation.extend(i for i, f in enumerate(frequency) if f == freq)
    permutation = np.array(permutation, dtype=int)

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


def check_panel_row_order(spec: ModelSpec) -> None:
    """Raise unless the spec CSV was already in ``FREQUENCY_ORDER``.

    ``load_spec`` permutes every field monthly-before-quarterly, so
    ``spec.series_id[i]`` names the *permuted* row i. The data panel ``Y`` is
    built in the raw ``.mat`` column order and is never permuted -- see
    ``example_nowcast.m``, which the port is faithful to. The two orders agree
    only because ``model_spec_FRED.csv`` happens to list all 28 monthly series
    before its 3 quarterly ones, which makes the permutation the identity.

    Reorder that CSV, or point a new panel at a spec whose frequencies are
    interleaved, and every series label in the news table silently attaches to
    the wrong row. Nothing else in the port checks it, so this does.
    """
    ranks = [FREQUENCY_ORDER.index(f) if f in FREQUENCY_ORDER else len(FREQUENCY_ORDER)
             for f in spec.frequency]
    bad = [i for i in range(1, len(ranks)) if ranks[i] < ranks[i - 1]]
    if bad:
        i = bad[0]
        raise ValueError(
            "spec rows are not in frequency order, so load_spec's permutation is "
            f"not the identity: row {i} is {spec.frequency[i]!r} "
            f"({spec.series_id[i]}) after row {i - 1} is "
            f"{spec.frequency[i - 1]!r} ({spec.series_id[i - 1]}). "
            "The data panel is built in raw CSV order and is not permuted with "
            "the spec, so series labels would attach to the wrong panel rows. "
            f"Sort the spec CSV by frequency in the order {FREQUENCY_ORDER}."
        )
