"""Annualised to quarter-on-quarter conversion (spec decision D4).

The model works in annualised quarterly growth, as the NY Fed's does.
Australian headline GDP is QoQ. The conversion is compounding, not division:
dividing by four is wrong by about 4% of the figure at typical growth rates,
which is four times the gate tolerance Plan A held itself to.
"""

import numpy as np
import pandas as pd
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


def test_annualised_below_minus_100_raises():
    """Below -100% annualised the fourth root has no real value, and -100%
    annualised means output going to zero over a year -- not an economically
    reachable quarterly outcome. This must raise on its own, not merely under
    pytest's filterwarnings=error: a silent NaN reaching the published figure
    is exactly the failure class this project hunts."""
    with pytest.raises(ValueError, match=r"annualised.*-100"):
        annualised_to_qoq(-150.0)


def test_qoq_below_minus_100_raises():
    """Symmetric bound on the other direction: a quarter-on-quarter rate at or
    below -100% means the quantity goes to zero (or below) within a single
    quarter, which is not an economically reachable outcome either."""
    with pytest.raises(ValueError, match=r"qoq.*-100"):
        qoq_to_annualised(-150.0)


# --------------------------------------------------------------------------- #
# The emitted artefact
# --------------------------------------------------------------------------- #

import numpy as np

from nyfed.au.emit import SCHEMA, nowcast_payload, refusal_payload
from nyfed.au.panel import Panel


def _panel(n_months: int = 60) -> Panel:
    dates = pd.date_range("2021-01-01", periods=n_months, freq="MS")
    Y = np.zeros((3, n_months))
    return Panel(Y=Y, y_location=np.zeros((3, 1)), y_scale=np.ones((3, 1)),
                 dates=dates, series_id=["a", "b", "gdp"], i_now=2)


def test_a_refusal_carries_no_number_at_all():
    """The whole point of refusing.

    A payload with a figure in it -- even a stale one, even flagged -- renders
    on the page as a nowcast. The site distinguishes the two on `status`, so a
    refusal must have nothing for a template to accidentally show.
    """
    p = refusal_payload(reason="stale input", detail="AiG PMI is 120 days old",
                        generated_at="2026-08-31T00:00:00+00:00",
                        asof="2026-08-31")
    assert p["status"] == "refused"
    assert p["horizons"] == []
    assert "AiG PMI" in p["refusal_detail"]
    for banned in ("qoq_growth_pct", "target_quarter", "prev_level", "panel"):
        assert banned not in p, f"a refusal must not carry {banned}"


def test_the_bands_come_from_the_draws_not_from_a_rule_of_thumb():
    """68% and 95% are percentiles of `density_nowcast`'s output.

    v2's bands are reconstructed from its own past errors, which cannot know
    that this quarter is harder than average. If these ever stop tracking the
    draws they hand a reader v2's guarantee under v3's label.
    """
    rng = np.random.default_rng(0)
    draws = rng.normal(4.0, 1.0, size=(4000, 1))     # annualised percent
    p = nowcast_payload(
        panel=_panel(), horizons=[("2026 Q2", 4.0)], draws=draws,
        prev_level=700_000.0, prev_quarter="2026 Q1",
        generated_at="x", asof="2026-08-31", gdp_global_loading=1.3,
        collapse_floor=1.0, n_gs=200, n_burn=100, seed=4)
    h = p["horizons"][0]
    want = np.percentile(annualised_to_qoq(draws[:, 0]), [2.5, 16, 84, 97.5])
    assert h["ci_95_low"] == pytest.approx(want[0], abs=5e-4)
    assert h["ci_68_low"] == pytest.approx(want[1], abs=5e-4)
    assert h["ci_68_high"] == pytest.approx(want[2], abs=5e-4)
    assert h["ci_95_high"] == pytest.approx(want[3], abs=5e-4)
    assert h["ci_68_low"] > h["ci_95_low"] and h["ci_68_high"] < h["ci_95_high"]


def test_the_published_figure_is_qoq_not_annualised():
    """Spec decision D4 reaching the artefact.

    The model works in annualised growth and Australia publishes QoQ. Emitting
    the annualised number under a QoQ label would overstate growth by a factor
    of about four -- the single most consequential unit error available here.
    """
    p = nowcast_payload(
        panel=_panel(), horizons=[("2026 Q2", 4.0)], draws=np.zeros((0, 1)),
        prev_level=700_000.0, prev_quarter="2026 Q1", generated_at="x",
        asof="2026-08-31", gdp_global_loading=1.3, collapse_floor=1.0,
        n_gs=200, n_burn=100, seed=4)
    h = p["horizons"][0]
    assert h["annualised_growth_pct"] == pytest.approx(4.0)
    assert h["qoq_growth_pct"] == pytest.approx(0.98534, abs=1e-4)
    # ...and the level is built from the QoQ figure, not the annualised one.
    assert h["gdp_chain_volume_millions"] == round(700_000 * 1.0098534)


def test_too_few_draws_emits_no_bands_rather_than_fake_ones():
    """A band from a handful of draws is noise wearing an interval's clothes."""
    p = nowcast_payload(
        panel=_panel(), horizons=[("2026 Q2", 4.0)], draws=np.zeros((5, 1)),
        prev_level=None, prev_quarter=None, generated_at="x", asof="2026-08-31",
        gdp_global_loading=1.3, collapse_floor=1.0, n_gs=200, n_burn=100, seed=4)
    assert "ci_68_low" not in p["horizons"][0]
    assert p["horizons"][0]["qoq_growth_pct"] == pytest.approx(0.98534, abs=1e-4)


def test_later_horizons_are_labelled_forecasts_not_nowcasts():
    """`target_periods` returns the nowcast first, then forecasts.

    The distinction is the reader's, not the model's: a quarter that has ENDED
    and is awaiting publication is a different claim from one still running.
    """
    draws = np.random.default_rng(1).normal(3.0, 1.0, size=(500, 2))
    p = nowcast_payload(
        panel=_panel(), horizons=[("2026 Q2", 3.0), ("2026 Q3", 2.5)],
        draws=draws, prev_level=700_000.0, prev_quarter="2026 Q1",
        generated_at="x", asof="2026-08-31", gdp_global_loading=1.3,
        collapse_floor=1.0, n_gs=200, n_burn=100, seed=4)
    kinds = [h["kind"] for h in p["horizons"]]
    assert kinds == ["nowcast", "forecast"]
    assert p["target_quarter"] == "2026 Q2"
    # Only the nowcast gets a level: a forecast's level would compound off a
    # quarter that has not been published either.
    assert "gdp_chain_volume_millions" in p["horizons"][0]
    assert "gdp_chain_volume_millions" not in p["horizons"][1]


def test_the_schema_is_stamped_so_the_site_can_refuse_an_old_shape():
    for p in (refusal_payload(reason="r", detail="d", generated_at="x", asof="y"),
              nowcast_payload(panel=_panel(), horizons=[("2026 Q2", 4.0)],
                              draws=np.zeros((0, 1)), prev_level=None,
                              prev_quarter=None, generated_at="x",
                              asof="y", gdp_global_loading=1.3,
                              collapse_floor=1.0, n_gs=1, n_burn=1, seed=1)):
        assert p["schema"] == SCHEMA
