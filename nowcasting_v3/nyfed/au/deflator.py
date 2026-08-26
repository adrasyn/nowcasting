"""A spliced monthly CPI, and the deflation of household spending by it.

WHY THIS MODULE EXISTS
----------------------
The registry fetches ``5682.0:A130200584T``, the Monthly Household Spending
Indicator at CURRENT PRICES -- nominal, seasonally adjusted. The spec row calls
it "Household Spending (real)" and mirrors the NY Fed's ``PCEC96``, which is
*real* personal consumption expenditures. Its transformation is ``pch``, so a
nominal series carries inflation straight into the factor, and this series
normalises the Global factor (``Block0_Global = 100`` in ``model_spec_AU.csv``),
so its scale sets that factor's scale.

v2 found this empirically and wrote it into its panel notes: nominal MHSI
over-read real GDP through the 2024 inflation -- 2024 mean 3-month nominal
0.82% against real 0.19%, with real GDP around 0.4%.

ABS publishes no monthly, real, seasonally adjusted household spending series.
The variants are monthly/nominal/SA (what the registry fetches),
monthly/real/Original (not seasonally adjusted) and quarterly/real/SA. So a
monthly panel row mirroring ``PCEC96`` has to be DERIVED, by deflating the
nominal seasonally adjusted series.

WHY THE DEFLATOR IS A HYBRID
----------------------------
Australia's monthly CPI history is split across a dead publication and a live
one, and neither alone covers household spending's span (2012-07 onward):

===========================  ==========================  ===================
tier                         series                      coverage
===========================  ==========================  ===================
6401.0 live monthly          A130607789R                 2024-04 -> current
6484.0 ceased monthly        A128481587A                 2017-09 -> 2025-09
6401.0 quarterly             A2325846C                   1948Q3  -> current
===========================  ==========================  ===================

A monthly-only deflator would cut roughly six years off the series that
normalises the Global factor. A quarterly-only one -- v2's method -- invents
within-quarter price movement that never happened. The hybrid uses real monthly
prices over the span where nearly all of the model's signal lives, and
approximates only the early tail.

WHY THE SPLICE IS BY RATIO
--------------------------
The three sources are index numbers on DIFFERENT BASES, and the gaps are large.
The live monthly series is 100.0 at 2024-04; the ceased one is 100.0 at its own
start, 2017-09, and reads about 123.6 at 2024-04; the quarterly one was rebased
to 2025-26 = 100 and reads about 95.4 at 2024Q1. Joining them end to end
therefore puts a step change of 19% at one seam and 4.6% at the other into the
deflator -- and ``pch`` turns a step change into one large false month in the
series that sets the Global factor's scale.

So at each join the older series is rescaled by the ratio of the two series over
their overlap before it is used, which makes the level continuous. The ratio is
the GEOMETRIC mean of the pointwise ratio, not the arithmetic mean: these are
index numbers, the natural centre of a set of ratios is multiplicative, and the
geometric mean is the only choice that gives the same answer whichever direction
you splice in.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from nyfed.au.fetch_abs import fetch_abs_series


@dataclass(frozen=True)
class DeflatorSource:
    """One tier of the spliced deflator."""

    key: str
    locator: str      # "<catalogue>:<series id>", as in sources.py
    frequency: str    # "m" | "q"
    note: str


# In PRECEDENCE order, most preferred first. `build_deflator` walks this
# sequence and each entry supplies only the months no earlier entry covers.
DEFLATOR_SOURCES: tuple[DeflatorSource, ...] = (
    DeflatorSource(
        "cpi_monthly_live",
        "6401.0:A130607789R",
        "m",
        "All groups CPI, seasonally adjusted, monthly, ABS 6401.0 table 640106. "
        "The same series the registry fetches as `cpi`, and deliberately so: "
        "the panel's price row and the consumption deflator should not be two "
        "different measures of the same month. Short -- 2024-04 onward -- "
        "because 6401.0's monthly analytical series begin there.",
    ),
    DeflatorSource(
        "cpi_monthly_ceased",
        "6484.0:A128481587A",
        "m",
        "All groups CPI, seasonally adjusted, monthly, ABS 6484.0 table 648401 "
        "-- the Monthly CPI Indicator, CEASED after September 2025. Its frozen "
        "release page still serves the spreadsheet, which is why it can be "
        "used at all; `fetch_abs.CEASED_CATALOGUE_URLS` carries the override "
        "that reaches it. This tier is what makes the deflator monthly back to "
        "2017-09 rather than 2024-04.",
    ),
    DeflatorSource(
        "cpi_quarterly",
        "6401.0:A2325846C",
        "q",
        "All groups CPI, Australia, quarterly, ABS 6401.0 -- 312 observations "
        "back to 1948Q3. Interpolated to monthly, so it INVENTS within-quarter "
        "movement; it is the fallback tier and covers only the months no "
        "monthly series reaches. For household spending that is 2012-07 to "
        "2017-08, about a third of the series.",
    ),
)


@dataclass(frozen=True)
class Seam:
    """The measured join between two tiers, kept so a splice can be audited.

    ``max_abs_deviation`` is the largest relative gap between the two series
    after rescaling, as a fraction. It is not zero and is not meant to be: two
    price measures of the same month differ, and the ratio only removes the
    average difference. It is the number that says whether the two sources are
    telling the same story, so it is measured rather than assumed.
    """

    preferred: str
    older: str
    n_overlap: int
    overlap_start: pd.Timestamp
    overlap_end: pd.Timestamp
    ratio: float
    max_abs_deviation: float
    max_abs_deviation_at: pd.Timestamp
    mean_abs_deviation: float


@dataclass(frozen=True)
class Deflator:
    """A spliced monthly price index, with the evidence for how it was built."""

    index: pd.Series
    seams: tuple[Seam, ...]
    contributed: dict[str, pd.DatetimeIndex]   # tier key -> months it supplied

    def coverage(self) -> dict[str, tuple[pd.Timestamp, pd.Timestamp, int]]:
        """First month, last month and count each tier actually contributed."""
        return {
            key: (months[0], months[-1], len(months))
            for key, months in self.contributed.items()
            if len(months)
        }


def quarterly_to_monthly(quarterly: pd.Series) -> pd.Series:
    """Interpolate a quarterly index onto a monthly first-of-month grid.

    ``parse_abs_frame`` dates a quarterly observation to the LAST month of its
    quarter (``to_timestamp(how="end")``), which is both the convention the
    panel uses and what ``panel._align``'s ``{3, 6, 9, 12}`` mask requires. So
    the interpolation runs between March, June, September and December, and the
    two intervening months of each quarter are linear in time.

    That is an approximation and is the reason this tier is last in precedence:
    it manufactures within-quarter movement that was never measured. It is
    still far better than nothing for 2012-2017, where the alternative is no
    deflator at all.
    """
    if not quarterly.index.is_monotonic_increasing:
        quarterly = quarterly.sort_index()
    months = set(pd.DatetimeIndex(quarterly.index).month)
    if not months <= {3, 6, 9, 12}:
        raise ValueError(
            "a quarterly series must be dated to the last month of its quarter "
            f"before interpolation; got months {sorted(months)}. See "
            "fetch_abs._first_of_month_index -- start-of-quarter dating would "
            "shift every interpolated value by two months."
        )
    grid = pd.date_range(quarterly.index[0], quarterly.index[-1], freq="MS")
    return quarterly.reindex(grid).interpolate(method="time")


MIN_SPLICE_OVERLAP = 6


def splice(
    preferred: pd.Series,
    older: pd.Series,
    *,
    name: str = "",
    older_name: str = "",
    min_overlap: int = MIN_SPLICE_OVERLAP,
) -> tuple[pd.Series, Seam]:
    """Rebase ``older`` onto ``preferred``'s level and fill the months it lacks.

    The rescaling factor is the geometric mean of ``preferred / older`` over the
    overlap. ``preferred`` is returned untouched wherever it exists, so the most
    recent, most authoritative numbers are never modified by the splice.

    THE RATIO IS FIT OVER THE WHOLE OVERLAP, NOT LOCALLY AT THE JOIN. That is a
    deliberate trade-off and it is worth stating, because the alternative is
    equally defensible. A global fit centres the residual over the entire
    overlap -- measured on the real seams, the signed residual over seam 2's 106
    months has mean +0.0004% and median -0.0013%, so the level is right on
    average across nine years. A local fit, taking the ratio from a short window
    at the handover, would instead make the join exactly continuous and let the
    error accumulate at the far end of the older series.

    Neither is free, because the two sources DRIFT: seam 2's yearly mean residual
    moves monotonically from about +0.16% in 2017-19 to about -0.26% in 2024, a
    slow divergence between a partial-basket monthly indicator and a full-basket
    quarterly index. Under the global fit that drift shows up as roughly 0.15% of
    level offset at the handover month; under a local fit it would show up as
    roughly 0.4% at the start of the interpolated tier instead. The global fit is
    chosen because ``pch`` is a first difference: a level offset spread evenly
    over 106 months is invisible to it, whereas concentrating the error at one
    end puts more of it into fewer months. Measured, the join months are
    unremarkable either way -- 0.247% and 0.217% month-on-month against a median
    absolute monthly move of 0.286%.

    ``min_overlap`` guards the other end of the same argument. An overlap of one
    or two months produces a ratio with essentially no evidence behind it, and
    -- worse -- a single-point overlap makes ``Seam.max_abs_deviation`` exactly
    0.0, so the audit record would look flawless precisely when it is emptiest.
    Six months is the floor: enough that the deviation statistics mean something,
    and far below the 18 and 106 months the real seams have.
    """
    preferred = preferred.dropna().sort_index()
    older = older.dropna().sort_index()
    overlap = preferred.index.intersection(older.index)
    if len(overlap) == 0:
        raise ValueError(
            f"{name or 'preferred'} and {older_name or 'older'} do not overlap "
            f"({preferred.index[0].date()}..{preferred.index[-1].date()} vs "
            f"{older.index[0].date()}..{older.index[-1].date()}), so there is "
            "no ratio to rebase by. Concatenating them instead would put a step "
            "change in the deflator at the join."
        )
    if len(overlap) < min_overlap:
        raise ValueError(
            f"{name or 'preferred'} and {older_name or 'older'} overlap over "
            f"only {len(overlap)} month(s) "
            f"({overlap[0].date()}..{overlap[-1].date()}), below the "
            f"{min_overlap}-month minimum. A ratio fit over that little has no "
            "evidence behind it, and at a single point the seam's deviation "
            "statistics are identically zero -- the audit record would look "
            "perfect while measuring nothing."
        )
    if (preferred.loc[overlap] <= 0).any() or (older.loc[overlap] <= 0).any():
        raise ValueError(
            "a price index must be positive over the splice overlap; got a "
            "non-positive value, which makes the ratio meaningless"
        )

    ratios = preferred.loc[overlap] / older.loc[overlap]
    factor = float(np.exp(np.log(ratios).mean()))
    rescaled = older * factor

    deviation = (ratios / factor - 1.0).abs()
    seam = Seam(
        preferred=name or "preferred",
        older=older_name or "older",
        n_overlap=len(overlap),
        overlap_start=overlap[0],
        overlap_end=overlap[-1],
        ratio=factor,
        max_abs_deviation=float(deviation.max()),
        max_abs_deviation_at=deviation.idxmax(),
        mean_abs_deviation=float(deviation.mean()),
    )
    return preferred.combine_first(rescaled).sort_index(), seam


def build_deflator(sources: dict[str, pd.Series]) -> Deflator:
    """Splice ``DEFLATOR_SOURCES`` into one monthly index, best tier first.

    ``sources`` is keyed by ``DeflatorSource.key``. Quarterly tiers are
    interpolated to monthly first; every tier after the first is rebased onto
    what has already been built, then supplies only the months still missing.
    """
    missing = [s.key for s in DEFLATOR_SOURCES if s.key not in sources]
    if missing:
        raise KeyError(f"deflator source(s) not supplied: {missing}")

    built: pd.Series | None = None
    built_from: list[str] = []
    seams: list[Seam] = []
    contributed: dict[str, pd.DatetimeIndex] = {}

    for source in DEFLATOR_SOURCES:
        tier = sources[source.key].dropna().sort_index()
        if tier.empty:
            raise ValueError(f"deflator source {source.key} is empty")
        if source.frequency == "q":
            tier = quarterly_to_monthly(tier)

        if built is None:
            built, contributed[source.key] = tier, tier.index
        else:
            already = built.index
            built, seam = splice(
                built,
                tier,
                name="+".join(built_from),
                older_name=source.key,
            )
            seams.append(seam)
            contributed[source.key] = built.index.difference(already)
        built_from.append(source.key)

    assert built is not None  # DEFLATOR_SOURCES is never empty
    return Deflator(
        index=built.rename("cpi_spliced"),
        seams=tuple(seams),
        contributed=contributed,
    )


def fetch_deflator_sources() -> dict[str, pd.Series]:
    """Retrieve every tier of the deflator. The only networked call here."""
    return {s.key: fetch_abs_series(s.locator) for s in DEFLATOR_SOURCES}


def deflate(
    nominal: pd.Series, deflator: pd.Series, *, base: pd.Timestamp | None = None
) -> pd.Series:
    """Convert a nominal series to real terms with ``deflator``.

    The deflator is renormalised to 100 at ``base`` -- by default the first
    month ``nominal`` is observed -- so the real series equals the nominal one
    in the base month and diverges from it thereafter by exactly the cumulative
    price change. The choice of base does not affect ``pch``, which is scale
    invariant; it is made explicit so the output is interpretable rather than
    on the arbitrary base of whichever CPI vintage led the splice.

    A GAP AT THE LEADING EDGE OR IN THE MIDDLE IS FATAL; A GAP AT THE TRAILING
    EDGE IS NOT. The two are different failures and only one is a failure.

    If the deflator starts after the nominal series does, deflating anyway would
    silently truncate the panel's longest consumption record -- the row that
    normalises the Global factor -- and the model would run on the shortened
    version without complaint. Same for a hole in the middle: a monthly price
    index does not have holes, so one means something is wrong upstream. Both
    raise.

    A deflator that stops short at the RECENT end is ordinary ragged edge, which
    is the condition a nowcast exists to work in. Those months come back NaN and
    the Kalman filter handles them natively. Halting the build for it would be
    actively harmful here: monthly CPI currently leads household spending by
    exactly one month, so the margin is a SINGLE RELEASE, and one late ABS
    publication would take down the whole panel rather than costing the last
    month of one row.
    """
    nominal = nominal.dropna().sort_index()
    if nominal.empty:
        raise ValueError("nominal series is empty")
    deflator = deflator.dropna().sort_index()
    if deflator.empty:
        raise ValueError("deflator is empty")

    first, last = deflator.index[0], deflator.index[-1]
    leading = nominal.index[nominal.index < first]
    if len(leading):
        raise ValueError(
            f"the deflator does not cover the first {len(leading)} month(s) of "
            f"the nominal series ({leading[0].date()}..{leading[-1].date()}); it "
            f"begins at {first.date()}. Deflating anyway would silently truncate "
            "the series at the LEADING edge, which is history, not ragged edge."
        )
    interior = nominal.index[
        (nominal.index >= first) & (nominal.index <= last)
    ].difference(deflator.index)
    if len(interior):
        raise ValueError(
            f"the deflator has {len(interior)} gap(s) inside its own span, first "
            f"{interior[0].date()} and last {interior[-1].date()}. A monthly "
            "price index does not have holes; something is wrong upstream."
        )

    base = nominal.index[0] if base is None else pd.Timestamp(base)
    if base not in deflator.index:
        raise ValueError(f"base month {base.date()} is not in the deflator")
    base_value = deflator.loc[base]
    if base_value <= 0:
        raise ValueError(f"deflator is non-positive at the base month {base.date()}")

    rebased = deflator.reindex(nominal.index) / base_value
    return (nominal / rebased).rename(nominal.name)


def real_household_spending(
    nominal: pd.Series, sources: dict[str, pd.Series]
) -> pd.Series:
    """The panel's ``household_spending`` row: nominal MHSI, deflated.

    This is the function the build step must call. ``build.build_panel`` fetches
    ``5682.0:A130200584T`` straight from the registry, which is NOMINAL -- pass
    it through here before it reaches ``assemble``, or the Global factor's
    normaliser carries inflation.
    """
    return deflate(nominal, build_deflator(sources).index)
