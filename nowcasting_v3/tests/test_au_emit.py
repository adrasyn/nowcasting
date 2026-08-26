"""Annualised to quarter-on-quarter conversion (spec decision D4).

The model works in annualised quarterly growth, as the NY Fed's does.
Australian headline GDP is QoQ. The conversion is compounding, not division:
dividing by four is wrong by about 4% of the figure at typical growth rates,
which is four times the gate tolerance Plan A held itself to.
"""

import numpy as np
import pytest

from nyfed.au.emit import annualised_to_qoq, qoq_to_annualised


def test_zero_maps_to_zero():
    assert annualised_to_qoq(0.0) == 0.0
    assert qoq_to_annualised(0.0) == 0.0


def test_a_known_pair():
    """4% annualised compounds from 0.9853% per quarter."""
    assert annualised_to_qoq(4.0) == pytest.approx(0.98534, abs=1e-5)
    assert qoq_to_annualised(0.98534) == pytest.approx(4.0, abs=1e-4)


def test_the_round_trip_is_exact():
    values = np.array([-8.0, -2.5, 0.0, 0.3, 2.0, 4.0, 12.0])
    assert qoq_to_annualised(annualised_to_qoq(values)) == pytest.approx(values, rel=1e-12)


def test_it_is_not_division_by_four():
    """The lazy conversion is out by enough to matter at the gate tolerance."""
    a = 4.0
    assert abs(annualised_to_qoq(a) - a / 4) > 0.01


def test_negative_growth_converts_without_producing_nan():
    assert np.isfinite(annualised_to_qoq(-6.0))
    assert annualised_to_qoq(-6.0) < 0


def test_it_handles_arrays_elementwise():
    got = annualised_to_qoq(np.array([0.0, 4.0]))
    assert isinstance(got, np.ndarray)
    assert got == pytest.approx([0.0, 0.98534], abs=1e-5)
