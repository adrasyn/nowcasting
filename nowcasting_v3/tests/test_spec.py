from pathlib import Path

import numpy as np
import pytest

from nyfed.spec import check_panel_row_order, load_spec

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


def test_panel_row_order_guard_accepts_the_reference_spec():
    """The US spec is already frequency-sorted, so load_spec's permutation is
    the identity and the raw-order panel lines up with the permuted labels."""
    check_panel_row_order(load_spec(SPEC_PATH))


def test_panel_row_order_guard_rejects_an_interleaved_spec():
    """The Plan B landmine, made executable.

    `load_spec` permutes the spec but `run_us_reference.load_vintage` builds Y
    in raw .mat column order, so `news_table` labelling panel row i with
    `spec.series_id[i]` is correct only while the permutation is the identity.
    Interleave one quarterly series and every label after it slides.
    """
    spec = load_spec(SPEC_PATH)
    spec.frequency = list(spec.frequency)
    spec.frequency[0] = "q"                    # a quarterly row before monthlies
    with pytest.raises(ValueError, match="not in frequency order"):
        check_panel_row_order(spec)
