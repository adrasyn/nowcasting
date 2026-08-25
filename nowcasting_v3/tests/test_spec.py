from pathlib import Path

import numpy as np
import pytest

from nyfed.spec import _frequency_permutation, check_panel_row_order, load_spec

SPEC_PATH = Path(__file__).parents[1] / "nyfed_matlab" / "model_spec_FRED.csv"


def test_loads_the_us_reference_panel():
    spec = load_spec(SPEC_PATH)
    assert len(spec.series_id) == 31
    assert spec.blocks.shape == (31, 5)
    assert spec.block_names == ["Global", "Soft", "Nominal", "Labor", "COVID"]


def test_series_are_sorted_monthly_before_quarterly():
    """load_spec.m permutes by frequency. Every downstream index depends on it."""
    spec = load_spec(SPEC_PATH)
    freq = np.array(spec.frequency)
    quarterly = freq == "q"
    assert quarterly.sum() == 3
    assert not quarterly[:28].any()
    assert quarterly[28:].all()
    assert set(np.array(spec.series_id)[quarterly]) == {
        "PRS85006112", "A261RX1Q020SBEA", "GDPC1",
    }


def test_gdp_is_locatable_after_sorting():
    spec = load_spec(SPEC_PATH)
    i_now = spec.series_id.index("GDPC1")
    assert spec.frequency[i_now] == "q"
    assert spec.trend[i_now] == 1.0


def test_blocks_encode_all_three_loading_states():
    """load_spec.m recodes in this order: `==1 -> NaN` (free), then `>1 -> 1`
    (normalising). A 0 is left as 0 (excluded from the block).

    INDPRO's CSV row is Global=100, Soft=0, Nominal=0, Labor=0, COVID=1,
    so it exhibits all three states at once."""
    spec = load_spec(SPEC_PATH)
    i = spec.series_id.index("INDPRO")
    assert spec.blocks[i, 0] == 1.0          # 100 -> normalising loading
    assert spec.blocks[i, 1] == 0.0          # 0   -> excluded, stays 0
    assert np.isnan(spec.blocks[i, 4])       # 1   -> free loading


def test_block_recoding_order_does_not_double_convert():
    """`==1 -> NaN` runs before `>1 -> 1`. Reversing the two would turn every
    free loading into a normalising one and silently over-identify the model."""
    spec = load_spec(SPEC_PATH)
    free = np.isnan(spec.blocks)
    assert free.any()
    assert ((spec.blocks == 1.0) | (spec.blocks == 0.0) | free).all()


def test_monthly_percent_change_trend_is_scaled_down_by_twelve():
    spec = load_spec(SPEC_PATH)
    i = spec.series_id.index("GDPC1")        # quarterly pca, not rescaled
    assert spec.trend[i] == 1.0
    monthly_pch = [
        j for j, (f, t) in enumerate(zip(spec.frequency, spec.transformation))
        if f == "m" and t == "pch"
    ]
    assert all(spec.trend[j] == 0.0 for j in monthly_pch)


def _write_spec(tmp_path, rows, fieldnames):
    """Write a spec CSV to disk so load_spec parses it like any other."""
    import csv

    path = tmp_path / "spec.csv"
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _reference_rows():
    import csv

    with open(SPEC_PATH, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return rows, list(rows[0].keys())


def test_reference_spec_needs_no_reordering():
    """model_spec_FRED.csv is already sorted, so the permutation is arange and
    the guard passes silently. This is what keeps US behaviour unchanged."""
    rows, _ = _reference_rows()
    frequency = [row["Frequency"] for row in rows]
    check_panel_row_order(frequency)                  # must not raise
    assert np.array_equal(_frequency_permutation(frequency),
                          np.arange(len(frequency)))
    load_spec(SPEC_PATH)                              # nor here


def test_load_spec_rejects_an_interleaved_spec(tmp_path):
    """The Plan B landmine, made executable AGAINST load_spec.

    The panel is built in raw .mat column order and is never permuted with the
    spec, so `spec.series_id[i]` labelling raw row i is correct only while
    load_spec's permutation is the identity. Interleave the three quarterly
    rows into raw positions 2, 7 and 12 and the permutation reorders 29 of 31
    rows.

    This must go through `load_spec` on a real file. An earlier version of this
    test hand-set `spec.frequency[0] = "q"` on an already-loaded ModelSpec,
    which is a state load_spec cannot produce -- load_spec overwrites
    `frequency` with the permuted list, which is sorted by construction. That
    test passed while the guard it was checking was a no-op on every real spec.
    """
    rows, fieldnames = _reference_rows()
    monthly = [r for r in rows if r["Frequency"] == "m"]
    quarterly = [r for r in rows if r["Frequency"] == "q"]
    assert len(quarterly) == 3
    interleaved = list(monthly)
    for position, row in zip((2, 7, 12), quarterly):
        interleaved.insert(position, row)
    assert [r["Frequency"] for r in interleaved][:3] == ["m", "m", "q"]

    path = _write_spec(tmp_path, interleaved, fieldnames)
    with pytest.raises(ValueError, match="NOT in frequency order"):
        load_spec(path)


def test_load_spec_rejects_a_row_it_would_silently_drop(tmp_path):
    """The second hole: `for freq in FREQUENCY_ORDER` omits any row whose
    frequency is not one of the six, shortening series_id/blocks/trend/prior
    below the panel's row count while the panel keeps every column. Nothing
    downstream asserts those lengths agree, so the rows would simply slide."""
    rows, fieldnames = _reference_rows()
    mangled = [dict(row) for row in rows]
    mangled[5]["Frequency"] = "biweekly"              # not in FREQUENCY_ORDER

    path = _write_spec(tmp_path, mangled, fieldnames)
    with pytest.raises(ValueError, match="would DROP 1 of 31 spec rows"):
        load_spec(path)


def test_the_two_failures_report_differently(tmp_path):
    """A dropped row and an unsorted spec are different problems; a reader who
    hits one must not be told about the other. The dropped-row check runs
    first, because a short spec is the more structural defect."""
    rows, fieldnames = _reference_rows()
    mangled = [dict(row) for row in rows]
    mangled[0]["Frequency"] = "q"                     # unsorted ...
    mangled[5]["Frequency"] = "biweekly"              # ... and a dropped row

    path = _write_spec(tmp_path, mangled, fieldnames)
    with pytest.raises(ValueError, match="would DROP") as excinfo:
        load_spec(path)
    assert "NOT in frequency order" not in str(excinfo.value)
