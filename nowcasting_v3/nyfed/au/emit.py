"""Unit conversion for the published Australian figure.

Spec decision D4: the model keeps the NY Fed's annualised quarterly growth and
its Mariano-Murasawa aggregation weights unchanged, so every Octave fixture
stays valid and the padding bug at construct_SSM.m:131 never fires. The
conversion to the quarter-on-quarter figure Australia publishes happens here,
at the presentation layer.

Compounding, not division. At 4% annualised the difference between the two is
0.0147pp -- larger than the +-0.01pp tolerance Plan A's gate held itself to.

Both directions reject growth at or below -100% with a ValueError, raised by
this module itself rather than relying on pytest's filterwarnings=error to
promote the RuntimeWarning that np.power otherwise emits. For
annualised_to_qoq specifically, below -100% the fourth root of a negative
base has no real value. For both directions, -100% means the quantity goes
to zero within the period -- not an economically reachable quarterly or
annual outcome for GDP, so the bound is enforced symmetrically even on the
qoq_to_annualised side, where raising an integer power does not itself
produce a NaN. This is the last module before a number reaches a reader, so
a silent NaN here must not be possible outside a test harness.
"""

from __future__ import annotations

import numpy as np


def annualised_to_qoq(annualised):
    """Annualised quarterly growth (percent) to quarter-on-quarter (percent)."""
    arr = np.asarray(annualised, dtype=float)
    if np.any(arr <= -100.0):
        raise ValueError(
            f"annualised growth must be > -100 (percent); got {annualised!r}. "
            "Below -100% the fourth root has no real value, and -100% "
            "annualised means output going to zero over a year, which is "
            "not an economically reachable quarterly outcome."
        )
    return 100.0 * (np.power(1.0 + arr / 100.0, 0.25) - 1.0)


def qoq_to_annualised(qoq):
    """Quarter-on-quarter growth (percent) to annualised (percent)."""
    arr = np.asarray(qoq, dtype=float)
    if np.any(arr <= -100.0):
        raise ValueError(
            f"qoq growth must be > -100 (percent); got {qoq!r}. -100% qoq "
            "means output going to zero within a single quarter, which is "
            "not an economically reachable outcome; the bound is kept "
            "symmetric with annualised_to_qoq's even though raising an "
            "integer power (4) of a negative base is mathematically well "
            "defined and would not itself produce a NaN here."
        )
    return 100.0 * (np.power(1.0 + arr / 100.0, 4.0) - 1.0)


# --------------------------------------------------------------------------- #
# The published artefact
# --------------------------------------------------------------------------- #
#
# `data/latest_v3.json`, read by the site's `/v3` route. Two things about its
# shape are deliberate and worth stating before the fields.
#
# THE BANDS ARE PROBABILITY BANDS, IN THE NY FED'S OWN SENSE. Their paper names
# reporting them as one of the reasons the model was rebuilt Bayesian -- "our
# Bayesian estimation approach ... enables us to report probability intervals
# alongside each point estimate of real GDP growth" (Staff Nowcast 2.0, p2) --
# and their figures label the shaded area "Probability band". The site uses
# their words, because the distinction is the one v2's chart got wrong.
#
# v2 carries `ci_basis: "empirical
# pseudo-out-of-sample error dispersion"` -- its bands are reconstructed after
# the fact from how wrong it has been, which cannot know that THIS quarter is
# harder than average. v3 draws from `density_nowcast`, so the interval is the
# posterior's, computed from the same chain as the point estimate. The field is
# still named `ci_basis` and still says which it is, because a reader comparing
# the two pages must be able to tell them apart.
#
# A REFUSAL IS AN OUTCOME, NOT AN ERROR. `status` is "ok" or "refused", and a
# refusal carries `refusal_reason` and no numbers. v3's defining behaviour is
# that it declines rather than publishing a figure it does not trust -- a stale
# feed, or a chain that left GDP disconnected from the panel. Emitting nothing
# at all would let the site show the previous week's number as if it were
# current, which is the exact failure the guards exist to prevent.

SCHEMA = "v3-preview-1"


def _pct(x) -> float:
    return round(float(x), 4)


def nowcast_payload(
    *,
    panel,
    horizons,
    draws,
    prev_level: float | None,
    prev_quarter: str | None,
    vintages: list[dict] | None = None,
    next_gdp_release_date: str | None = None,
    generated_at: str,
    asof: str,
    gdp_global_loading: float,
    collapse_floor: float,
    n_gs: int,
    n_burn: int,
    seed: int,
) -> dict:
    """Assemble the emitted object from an already-run, already-guarded fit.

    ``horizons`` is a list of ``(quarter_label, annualised_pct)`` in the order
    ``target_periods`` returned them: the first is the nowcast, any after it are
    forecasts. ``draws`` is ``(n_draw, n_horizon)`` of annualised percent from
    ``density_nowcast``; the bands are percentiles of it.

    This function does no estimation and no fetching. It is pure so that the
    emitted shape can be tested without a sampler run.
    """
    import numpy as np

    draws = np.asarray(draws, dtype=float)
    out_h = []
    for k, (label, ann) in enumerate(horizons):
        qoq = float(annualised_to_qoq(ann))
        col = draws[:, k] if draws.ndim == 2 and draws.shape[1] > k else None
        band = {}
        if col is not None and np.isfinite(col).sum() >= 20:
            q = np.nanpercentile(annualised_to_qoq(col[np.isfinite(col)]),
                                 [2.5, 16, 84, 97.5])
            band = {"ci_68_low": _pct(q[1]), "ci_68_high": _pct(q[2]),
                    "ci_95_low": _pct(q[0]), "ci_95_high": _pct(q[3])}
        entry = {"quarter": label, "kind": "nowcast" if k == 0 else "forecast",
                 "qoq_growth_pct": _pct(qoq),
                 "annualised_growth_pct": _pct(ann), **band}
        if k == 0 and prev_level is not None:
            entry["gdp_chain_volume_millions"] = round(
                float(prev_level) * (1.0 + qoq / 100.0))
        out_h.append(entry)

    return {
        "schema": SCHEMA,
        "status": "ok",
        "generated_at": generated_at,
        "as_of": asof,
        "target_quarter": out_h[0]["quarter"] if out_h else None,
        "data_through": str(panel.dates[-1].date())[:7],
        "prev_level": (
            {"value": round(float(prev_level)), "quarter": prev_quarter}
            if prev_level is not None else None),
        "horizons": out_h,
        # The weekly path for the CURRENT quarter, for the site's evolution
        # chart. Empty until `tools/band_coverage.py` has produced it: a chart
        # is not worth a fabricated point.
        "vintages": vintages or [],
        "next_gdp_release_date": next_gdp_release_date,
        "ci_basis": (
            "probability band: the 68%/95% mass of the model's posterior, from "
            f"{int(np.isfinite(draws).all(axis=1).sum())} density_nowcast draws on the same "
            "chain as the point estimate. Not a confidence interval, and not "
            "recalibrated from past errors."),
        "panel": {
            "n_series": int(panel.Y.shape[0]),
            "n_months": int(panel.Y.shape[1]),
            "first_month": str(panel.dates[0].date())[:7],
            "series": list(panel.series_id),
            "deflator_skipped": panel.deflator_skipped,
        },
        "diagnostics": {
            "gdp_global_loading": _pct(gdp_global_loading),
            "collapse_floor": collapse_floor,
            "n_gs": n_gs, "n_burn": n_burn, "seed": seed,
        },
    }


def refusal_payload(*, reason: str, detail: str, generated_at: str,
                    asof: str) -> dict:
    """What is emitted when the model declines to publish.

    Carries no figure at all. A partial payload with a stale number in it would
    be indistinguishable, on the page, from a current one.
    """
    return {
        "schema": SCHEMA,
        "status": "refused",
        "generated_at": generated_at,
        "as_of": asof,
        "refusal_reason": reason,
        "refusal_detail": detail,
        "horizons": [],
    }
