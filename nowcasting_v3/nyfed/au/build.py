"""Fetch, guard and assemble the Australian panel, and run the model on it.

The one entry point Plans C, D and E call. Fetching happens here; every other
module in ``nyfed/au`` is pure and testable offline.

THE HOUSEHOLD SPENDING ROW IS DEFLATED HERE, AND ONLY HERE
----------------------------------------------------------
The registry fetches ``5682.0:A130200584T``, the Monthly Household Spending
Indicator **at current prices**. The panel row it feeds is "Household Spending
(real)" and mirrors the NY Fed's ``PCEC96``. Three separate reasons the nominal
series must not reach ``assemble``:

* its transformation is ``pch``, so a nominal series carries inflation straight
  into the factor;
* it **normalises the Global factor** (``Block0_Global = 100`` in
  ``model_spec_AU.csv``), so its scale sets the broadest factor's scale;
* v2 measured the size of the error: 2024 mean 3-month nominal growth 0.82%
  against real 0.19%, with real GDP around 0.4%.

So ``build_panel`` replaces the fetched series with
``deflator.real_household_spending(...)`` **before** the freshness check and
before ``assemble``. ``nyfed/au/panel.py`` deliberately does not deflate --
``assemble`` takes whatever it is handed -- so this line is the only thing
standing between the registry's nominal series and the Global factor.

AS OF MEANS AS OF -- BY RELEASE DATE, NOT BY REFERENCE DATE
------------------------------------------------------------
Every series and every deflator tier is cut at ``asof`` before anything else
happens, and the cut is on the observation's **release** date --
``observation date + source.publication_lag_days`` -- not on the observation's
own date.

The distinction is the whole point. An Australian series' panel date runs weeks
ahead of its release -- a monthly is dated to the first of its reference month
and published about two months later, a quarterly to the LAST month of its
quarter and published about three -- so cutting on the observation date admits
data that had not been published at ``asof``: at
``asof="2026-07-01"`` under the observation-date rule, six of the fourteen
series carried a 2026-07-01 observation, and this repo pins the release date of
one of them -- ``tests/test_au_fetch_rba.py`` records the 2026-07 commodity
index as released 4 August 2026, five weeks after the vintage claimed to stop.
Against ``gdp``'s 94-day lag the gap reaches nine weeks.

``build_panel`` is the primitive Plan C's backtest will call, and a backtest
whose vintage at date T contains indicators published after T is the classic
forward-looking evaluation error. It does not fail loudly; it flatters every
result.

Two consequences, both wanted:

* the panel holds the observations a real vintage held -- a build at 2026-06-01
  contains exactly the observations a person sitting at a desk on 2026-06-01
  could have seen, whether it is fetching live or replaying a recording;
* ``check_freshness`` measures age from the last observation **at that
  vintage**, so the guard judges the same data the model gets.

WHICH OBSERVATIONS EXISTED IS NOT WHAT THEY SAID
------------------------------------------------
The release-date cut reproduces the SET of observations available at ``asof``.
It does not reproduce their VALUES as published then: ABS revises seasonally
adjusted series, so a recording made on 2026-08-26 and replayed at 2026-06-01
carries two months of revisions that desk could not have seen. Harmless for the
gate, which only asks that the pipeline runs on a vintage-shaped panel. Not
harmless as a specification: a backtest built on this primitive is
**revision-aware in its dating and revision-blind in its values**, and Plan C
inherits both halves. A true real-time evaluation needs recorded vintages, one
per ``asof``, not one recording replayed at many.

Freshness is checked on the series that actually enter the panel, which means
``household_spending`` is checked *after* deflation: if the deflator ran out
before the nominal series did, the real row's trailing months are NaN and that
is a genuine staleness of the row the model sees.

There is no flag to skip the freshness check, and there must not be. A build
today refuses, and on exactly one series: ``aig_pmi`` is past its 117-day budget
because ``nowcasting_v2/data_raw/aig_pmi.csv`` stopped updating in May 2026 --
its last observation is 2026-05-01, so the refusal starts on 2026-08-27. Ai
Group is still publishing -- see ``sources.py``; it is v2's scraper that
stopped -- so the fix is a working fetcher, and in the meantime the refusal is
the guard doing its job. The way to nowcast anyway is not to widen the budget or
add a bypass.

That budget is 117 rather than 86 because Ai Group skips one December or
January in most years, so
a 31-day release interval refused a healthy series every February; ``sources.py``
carries the measurement and the per-series override. The cost is disclosed
there: the dead feed is caught 31 days later than it would have been.

TWO GUARDS, NOT ONE
-------------------
``check_freshness`` refuses a panel whose inputs have gone stale. The second
guard is further down and refuses a *model*: :func:`state_space` raises
:class:`CollapsedFactorError` when the fitted chain has left the nowcast target
disconnected from the factor its monthly series feed. NO seed of thirty lands
there on the shipping panel since `DEFAULT_START` moved to 1980; 18 of 30 did
before it, the result runs and produces a plausible number, and that number is
not a nowcast. Neither guard has a bypass flag.

VINTAGES: WHY THE GATE DOES NOT FETCH
-------------------------------------
``build_panel(asof=...)`` with no ``vintage`` fetches live, which is what a
production run does. A *recorded vintage* is the same data written to CSV, and
``build_panel(asof=..., vintage=path)`` replays it. The end-to-end gate replays
a recording for three reasons: a live build takes about two and a half minutes
and touches four hosts; ``readabs`` emits warnings that the suite's
``filterwarnings = ["error"]`` would turn into unrelated failures; and ABS
revises, so a networked gate would quietly measure a different panel every
week. The recording is real fetched data, checked against the trimmed payloads
that were verified against the ABS and RBA releases (see
``tests/test_au_end_to_end.py``), and ``load_vintage`` refuses a recording whose
locators no longer match the registry.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from nyfed.au.deflator import (
    DEFLATOR_SOURCES,
    fetch_deflator_sources,
    long_monthly_cpi,
    real_household_spending,
)
from nyfed.au.fetch_abs import fetch_abs_series
from nyfed.au.fetch_rba import fetch_rba_series
from nyfed.au.fetch_v2 import read_v2_series
from nyfed.au.freshness import check_freshness
from nyfed.au.initval import seed_lambda
from nyfed.au.panel import Panel, assemble
from nyfed.au.restrict import build_restrict
from nyfed.au.sources import AU_SERIES, SPEC_PATH, SeriesSource
from nyfed.gibbs import GibbsResult, gibbs_sampler
from nyfed.model import (
    InitVal, Latent, Prior, Restrict, construct_prior, construct_ssm,
)
from nyfed.nowcast import point_nowcast
from nyfed.parameters import Params, map_parameter, vec_parameter
from nyfed.settings import GibbsSettings
from nyfed.spec import ModelSpec, load_spec
from nyfed.ssm import StateSpace

__all__ = [
    "COLLAPSED_GLOBAL_LOADING",
    "CollapsedFactorError",
    "DEFAULT_START",
    "Vintage",
    "build_panel",
    "estimate_short",
    "fetch_vintage",
    "free_parameter_mask",
    "load_vintage",
    "quick_nowcast",
    "save_vintage",
    "state_space",
    "target_periods",
]

# Where the panel window opens. THIS IS A MODELLING CHOICE, NOT A DATA LIMIT,
# and it is the single largest lever measured on this panel.
#
# It was 1990 until 2026-08-30, uncommented, apparently mirroring the NY Fed's
# 468-month US panel. That is a defensible convention and it was the wrong one
# for Australia, because the COVID quarters' grip on the target is a function of
# how much history sits beside them. Thirty seeds at five vintages per start
# (`tools/panel_start_sweep.py`, rows in
# `docs/measurements/2026-08-29-panel-start-sweep.csv`):
#
#   start  cols  COVID share of GDP  chains identified  MAE   s/fit
#   1990    435        64.5%                33%         0.323   27
#   1985    495        57.9%                87%         0.246   31
#   1980    555        48.2%               100%         0.272   35
#   1970    675        32.4%               100%         0.250   43
#   1960    795        23.1%                97%         0.214   50
#
# 1980 takes the whole identification benefit for eight seconds a fit. Going
# further back buys no more of it, and buys it with hollow decades: 1960-1969
# carries ZERO monthly indicators -- only `gdp` and its near-twin `gdi`.
#
# THE OBVIOUS OBJECTION WAS TESTED AND REJECTED. A longer window might make "GDP
# loads the Global factor" true by CONSTRUCTION rather than earned -- if the
# factor has nothing but GDP to be identified from, the collapse guard would stop
# firing for the wrong reason. The discriminator is whether the MONTHLY series
# still load Global; a factor collapsing into GDP's own trend would raise GDP's
# loading while theirs fell. Ratio of GDP's loading to the mean monthly loading,
# by start: 5.59, 6.18, 5.76, 5.77, 5.68 (1990 -> 1960). No trend, and the
# monthly loadings themselves stay flat at 0.24..0.27. The factor keeps its
# character and is simply better identified.
#
# RESPONSIVENESS: this comment claimed on 2026-08-30 that the panel start fixes
# identification and "does not fix" responsiveness, citing a 0.61..0.69 band.
# THAT INFERENCE WAS WRONG, and wrong in a way worth recording. The sweep above
# runs five vintages at 2026-01..2026-05, which between them cover only TWO
# target quarters -- a narrow band was guaranteed by the design, not measured
# from it. Over the full backtest (`tools/plan_c_backtest.py`, 40 vintages, 14
# target quarters) the 1980 panel spans 0.27..0.80 with sd 0.119.
#
# It is still UNDER-DISPERSED -- the outcomes have sd 0.265 -- and that is the
# real residual: v3 wins on accuracy by being smooth, not by tracking. v2 is
# closer to the right variability (sd 0.233) and less accurate (MAE 0.340
# against 0.242). Under-dispersion is a smaller and different fault than the
# flat line this comment originally described.
DEFAULT_START = "1980-01-01"

# The floor the nowcast target's Global loading has to clear before a state
# space built from a sampler run may be used. See `CollapsedFactorError`.
#
# Measured over THIRTY seeds at n_gs=200, n_burn=100 on the 2026-06-01 vintage,
# and on THREE panels -- ninety chains in total.
#
# THERE ARE THREE GROUPS, NOT TWO, AND THE EARLIEST TEN-SEED MEASUREMENT MISSED
# THE MIDDLE ONE. On every panel measured, chains sit between the basins:
#
#   15-series, 28-obs cpi:   0.045..0.522 | 0.783 0.901 0.924 | 1.124..1.866
#   15-series, 103-obs cpi:  0.041..0.683 | 0.785 0.823 0.843 | 1.089..1.637
#   14-series (shipping):    0.065..0.745 | 0.796 0.856       | 1.096..1.712
#
# The old floor of 0.75 ADMITTED that middle band on all three: chains cleared
# the guard while sitting nowhere near the identified basin, and a warm-started
# run begun from one would inherit it silently. 1.0 sits inside the widest gap
# on ALL THREE (0.924->1.124, 0.843->1.089 and 0.856->1.096), so it is justified
# on three independent panels rather than on one ten-seed sample.
#
# The third panel is the one that ships: `cpi_trimmed` was dropped from the
# registry on 2026-08-28 (see `nyfed/au/sources.py`), and the floor was
# RE-MEASURED rather than carried over, because dropping a series changes which
# seed lands where -- two of the three seeds pinned in the end-to-end gate had
# swapped basins.
#
# It also has a reading, though the measurement is the justification: the
# normalising series' loading is fixed at exactly 1.0, so the rule is that the
# target must be at least as connected to the common factor as the series that
# defines that factor's scale.
#
# Cost, disclosed: the `cpi` splice roughly doubled the COLD-START collapse
# rate (9/30 -> 17/30 against this floor's predecessor), and dropping
# `cpi_trimmed` left it there (18/30). That is a property of the starting
# lottery, not of the fitted model, and Plan C is warm-started for exactly this
# reason -- it lands on the first vintage and the anchor fits, where the guard
# already retries.
COLLAPSED_GLOBAL_LOADING = 1.0


class CollapsedFactorError(Exception):
    """The fitted model does not connect the target series to the panel.

    GDP loads only the Global factor and the COVID factor, and the COVID factor
    is active for the 22 months holding 48.2% of GDP's standardised variation
    on the shipping panel (8 of 183 observations, including the five largest) and
    64.5% before `DEFAULT_START` moved to 1980. When a chain lets the
    COVID factor take the in-window variation and GDP's own idiosyncratic
    stochastic volatility take the rest, GDP's Global loading collapses toward
    zero -- and the Global factor is what every monthly series feeds. The result
    still runs, still produces a plausible number, and is not a nowcast: at the
    worst seed measured, a one-sigma shock to the ENTIRE monthly panel across
    the target quarter moved it by 0.015pp.

    NO SEED OF THIRTY LANDS THERE TODAY, and this is still raised rather than
    warned about. 18 of 30 collapsed at the 1990 start, and what changed is the
    window the panel opens at, not the mechanism: the COVID factor is still
    there, still confined to 22 months, still able to explain the target if a
    chain lets it. A spec change, a thinner vintage, or a shorter window brings
    it back. The whole point of this project's guards is to turn a plausible
    wrong number into a loud failure, and a guard that costs one comparison per
    fit does not need to justify itself by firing.

    ``tests/test_au_end_to_end.py`` keeps exercising it on a 1990-start panel
    for exactly that reason.

    Re-running with a different seed got a usable chain 12 times in 30 at the
    1990 start.
    That is a workaround, not a fix. The fix is a starting point that does what
    the NY Fed's fitted ``initval.mat`` does -- put the chain in the identified
    basin -- or a specification that does not make a 22-month factor compete
    with the Global factor for the target series. Plan C.
    """

# Factor-VAR and measurement-error lag orders. ``example_estimate.m:44-45``.
P_F, P_E = 4, 1


# --------------------------------------------------------------------------- #
# Fetching
# --------------------------------------------------------------------------- #


def _fetch_one(source: SeriesSource) -> pd.Series:
    """Dispatch one registry entry to its fetcher.

    Every fetcher takes the registry's ``locator`` and nothing else. The RBA
    column is encoded IN the locator (``"I2:GRCPAIAD"``), exactly as the ABS
    catalogue and series id are (``"6202.0:A84423043C"``) -- do not reintroduce
    a separate column argument or a module-level column constant. Task 3's
    review found that a hand-typed column let ``GRCPAISAD``, a one-character
    variant that is a genuinely different series, pass every test in the suite.
    """
    if source.fetcher == "abs":
        return fetch_abs_series(source.locator)
    if source.fetcher == "rba":
        return fetch_rba_series(source.locator)
    if source.fetcher == "v2":
        return read_v2_series(source.locator)
    raise ValueError(f"{source.key} has unknown fetcher {source.fetcher!r}")


@dataclass(frozen=True)
class Vintage:
    """Everything one build needs from outside, before any truncation.

    ``series`` is keyed by registry key and holds household spending **at
    current prices**, exactly as fetched: a Vintage is a recording of the
    sources, not of the panel. ``deflator_sources`` is keyed by
    ``DeflatorSource.key`` and is what turns that row real.
    """

    series: dict[str, pd.Series]
    deflator_sources: dict[str, pd.Series]
    recorded_at: str | None = None

    def as_of(self, asof) -> "Vintage":
        """This vintage as it stood on ``asof``, cut by RELEASE date.

        Public because the cut is a claim worth checking from outside, not an
        implementation detail: ``build_panel`` applies it, and
        ``tests/test_au_end_to_end.py`` reproduces it to verify that what
        reaches the model is what a person at a desk that day could have seen.
        """
        asof = pd.Timestamp(asof)
        return Vintage(
            series=_as_of(
                self.series, asof,
                {s.key: s.publication_lag_days for s in AU_SERIES},
            ),
            deflator_sources=_as_of(
                self.deflator_sources, asof,
                {d.key: d.publication_lag_days for d in DEFLATOR_SOURCES},
            ),
            recorded_at=self.recorded_at,
        )


def fetch_vintage(sources: tuple[SeriesSource, ...] = AU_SERIES) -> Vintage:
    """Retrieve every registered series and every deflator tier. Networked."""
    return Vintage(
        series={s.key: _fetch_one(s) for s in sources},
        deflator_sources=fetch_deflator_sources(),
        recorded_at=datetime.now(UTC).isoformat(timespec="seconds"),
    )


# --------------------------------------------------------------------------- #
# Recording a vintage
# --------------------------------------------------------------------------- #

_SERIES_CSV = "series.csv"
_DEFLATOR_CSV = "deflator_sources.csv"
_MANIFEST = "manifest.json"


def _tidy(series: dict[str, pd.Series]) -> pd.DataFrame:
    frames = [
        pd.DataFrame({"key": key, "date": s.index, "value": s.to_numpy(dtype=float)})
        for key, s in series.items()
    ]
    return pd.concat(frames, ignore_index=True)


def _untidy(frame: pd.DataFrame) -> dict[str, pd.Series]:
    out: dict[str, pd.Series] = {}
    for key, part in frame.groupby("key", sort=False):
        out[str(key)] = pd.Series(
            part["value"].to_numpy(dtype=float),
            index=pd.DatetimeIndex(part["date"]),
            name=str(key),
        ).sort_index()
    return out


def save_vintage(vintage: Vintage, directory: str | Path) -> Path:
    """Write a fetched vintage to ``directory`` as three small files.

    The manifest carries the registry locator each series was fetched from, so
    a later locator change in ``sources.py`` makes the recording refuse to load
    rather than silently keep the superseded series alive. That is the same
    failure ``fetch_abs.parse_abs_frame`` guards for a single payload -- a
    fixture recorded under a series id the registry has since moved off.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    _tidy(vintage.series).to_csv(directory / _SERIES_CSV, index=False)
    _tidy(vintage.deflator_sources).to_csv(directory / _DEFLATOR_CSV, index=False)
    (directory / _MANIFEST).write_text(
        json.dumps(
            {
                "recorded_at": vintage.recorded_at,
                "locators": {s.key: s.locator for s in AU_SERIES},
                "deflator_locators": {d.key: d.locator for d in DEFLATOR_SOURCES},
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    return directory


def load_vintage(directory: str | Path) -> Vintage:
    """Read a recorded vintage, refusing one the registry has moved off."""
    directory = Path(directory)
    manifest_path = directory / _MANIFEST
    if not manifest_path.is_file():
        raise FileNotFoundError(
            f"{manifest_path} is absent; record one with "
            "tools/record_au_vintage.py (needs network)."
        )
    manifest = json.loads(manifest_path.read_text())

    recorded = manifest.get("locators", {})
    current = {s.key: s.locator for s in AU_SERIES}
    if recorded != current:
        drifted = sorted(
            set(recorded) ^ set(current)
            | {k for k in set(recorded) & set(current) if recorded[k] != current[k]}
        )
        raise ValueError(
            f"the recorded vintage in {directory} was fetched from different "
            f"locators than the registry now names: {drifted}. Re-record it "
            "(tools/record_au_vintage.py) rather than trusting the recording: "
            "a superseded series parses and standardises perfectly well."
        )
    recorded_defl = manifest.get("deflator_locators", {})
    current_defl = {d.key: d.locator for d in DEFLATOR_SOURCES}
    if recorded_defl != current_defl:
        raise ValueError(
            f"the recorded vintage in {directory} was fetched from different "
            "deflator locators than nyfed.au.deflator now names. Re-record it."
        )

    return Vintage(
        series=_untidy(pd.read_csv(directory / _SERIES_CSV, parse_dates=["date"])),
        deflator_sources=_untidy(
            pd.read_csv(directory / _DEFLATOR_CSV, parse_dates=["date"])
        ),
        recorded_at=manifest.get("recorded_at"),
    )


# --------------------------------------------------------------------------- #
# The build
# --------------------------------------------------------------------------- #


def _as_of(
    series: dict[str, pd.Series],
    asof: pd.Timestamp,
    lags: dict[str, int],
) -> dict[str, pd.Series]:
    """Drop every observation not yet RELEASED at ``asof``.

    ``lags[key]`` is the series' ``publication_lag_days``, so the release date
    of an observation is its own date plus that. Cutting on the observation date
    instead is a nine-week look-ahead on the slowest series; see AS OF MEANS
    AS OF.
    """
    missing = sorted(set(series) - set(lags))
    if missing:
        raise KeyError(
            f"no publication lag for {missing}; a vintage cut-off cannot be "
            "computed without one, and cutting on the observation date instead "
            "would silently admit unreleased data"
        )
    return {
        key: s[s.index + pd.Timedelta(days=lags[key]) <= asof]
        for key, s in series.items()
    }


def build_panel(
    *,
    asof: str,
    start: str = DEFAULT_START,
    vintage: str | Path | Vintage | None = None,
) -> Panel:
    """Fetch every registered series, refuse if any is stale, and assemble.

    ``vintage`` is ``None`` for a live fetch, or a recorded vintage (a
    directory, or an already-loaded :class:`Vintage`) to replay.
    """
    asof_ts = pd.Timestamp(asof)
    if vintage is None:
        v = fetch_vintage()
    elif isinstance(vintage, Vintage):
        v = vintage
    else:
        v = load_vintage(vintage)

    vintage_asof = v.as_of(asof_ts)
    series, deflator_sources = vintage_asof.series, vintage_asof.deflator_sources

    # THE DEFLATED SERIES IS WHAT ENTERS THE PANEL, NOT THE NOMINAL ONE.
    # `assemble` will take the nominal series without complaint and the model
    # will run on it; see this module's docstring for the three reasons that is
    # wrong, and `nyfed/au/deflator.py` for how the deflator is built.
    #
    # THE UNCUT TIERS GO WITH THE CUT ONES. A vintage earlier than a deflator
    # tier's first release leaves that tier legitimately empty -- the live
    # 6401.0 monthly series does not exist before 2024 -- and `build_deflator`
    # needs the recording to tell that apart from a fetcher that returned
    # nothing. Without it the earliest buildable vintage was 2024-11-01, which
    # is most of the range Plan C's backtest wants.
    # THE `cpi` ROW IS SPLICED HERE, AND ONLY HERE. The registry fetches the
    # LIVE 6401.0 monthly series, whose every All-groups index number restarts
    # at 2024-04 because the ABS ceased the 6484.0 Monthly CPI Indicator. Used
    # raw, that gives the Nominal block's NORMALISER 28 observations and leaves
    # it absent for the first two years of a 2022+ backtest window. The ceased
    # tier is already in hand -- the deflator fetches it -- so no extra request
    # is made. `long_monthly_cpi` uses the two MONTHLY tiers only and never the
    # quarterly one: this row's transformation is `pch`, and an interpolated
    # quarterly level would become fabricated monthly changes.
    series["cpi"] = long_monthly_cpi(deflator_sources)

    series["household_spending"], deflator = real_household_spending(
        series["household_spending"],
        deflator_sources,
        recorded=v.deflator_sources,
    )

    check_freshness(series, asof_ts)
    panel = assemble(series, start=start, end=asof)
    # Carry the skips out. A skipped tier is not fatal -- a lower tier covers
    # the months -- but it means those months are priced by an interpolated
    # quarterly index rather than a real monthly one, and nothing else in the
    # production path says so.
    panel.deflator_skipped = deflator.skipped
    return panel


# --------------------------------------------------------------------------- #
# The model path
# --------------------------------------------------------------------------- #


def _initial_point(
    panel: Panel, spec: ModelSpec, restrict: Restrict
) -> tuple[Prior, InitVal]:
    """A neutral starting point for the sampler, and the prior mean it implies.

    ``InitVal`` needs a full parameter draw and a full latent draw
    (``nyfed/model.py:112-121``). The NY Fed ships one in ``initval.mat``,
    fitted; Australia has none, so this builds the blandest point the model can
    represent. The sampler moves off it on the first sweep -- it only has to be
    representable, and it must satisfy the restrictions.

    THREE THINGS READ OUT OF ``initval.mat`` RATHER THAN GUESSED. The plan's
    sketch had all three the other way, and each is silent:

    1. **Restricted loadings must carry their restriction value, not the PCA
       seed.** ``gibbs_update`` draws only the entries where ``restrict.Lambda``
       is NaN and keeps ``param.Lambda`` verbatim everywhere else
       (``nyfed/gibbs.py:553-571``). So a normalising loading -- the ``100``
       entries in ``model_spec_AU.csv``, which ``load_spec`` turns into ``1.0``
       -- stays at whatever the initial value put there, for the whole chain.
       Seeding it from PCA would fix the Global factor's normaliser at an
       arbitrary number and quietly rescale the factor. ``initval.mat``'s
       Lambda is exactly ``1.0`` at all four of the US spec's normalisers and
       exactly ``0.0`` at its structural zeros; this reproduces that.
    2. **``pi_f`` and ``pi_e`` are the probability of NO outlier.**
       ``gibbs._s_support`` puts mass ``pi`` on scale 1 and spreads ``1 - pi``
       over scales 2..5, and ``construct_prior`` centres them at
       ``1 - 1/(2*12) = 0.958``. ``initval.mat`` carries 0.95..0.98. A starting
       value of 0.05 would declare 95% of every series' months outliers, which
       runs, and quietly discards the data.
    3. **The ``gamma`` parameters are standard deviations and start at the
       prior scale, not zero.** ``update_vol`` propagates
       ``ln sigma_t^2 = ln sigma_{t-1}^2 + gamma * ups_t``, so ``gamma = 0``
       is a degenerate random walk. ``initval.mat`` has ``gamma_g = 0.0107``
       against ``sqrt(s2_g) = 0.01``.
    """
    n, n_f = spec.blocks.shape
    T = panel.Y.shape[1]

    # Free loadings take the PCA seed; restricted ones take the restriction.
    Lambda0 = np.where(
        np.isnan(restrict.Lambda), np.nan_to_num(seed_lambda(panel)), restrict.Lambda
    )

    # `example_estimate.m:88`: the prior mean for Lambda IS the initial value.
    prior = construct_prior((n, n_f, P_F, P_E), Lambda0)
    prior.P_Phi = prior.P_Phi / 5      # example_estimate.m:89

    # Mild persistence rather than zero, so the factor VAR is not degenerate on
    # sweep one; then the restrictions (the COVID factor's row and column) are
    # imposed on top, as they are for Lambda.
    Phi0 = np.zeros((n_f, n_f, P_F))
    Phi0[:, :, 0] = 0.5 * np.eye(n_f)
    Phi0 = np.where(np.isnan(restrict.Phi), Phi0, restrict.Phi)

    pi_f0 = prior.a_f / (prior.a_f + prior.b_f)
    pi_e0 = prior.a_e / (prior.a_e + prior.b_e)
    param0 = Params(
        mu=np.zeros(n),
        gamma_g=float(np.sqrt(prior.s2_g)),
        Lambda=Lambda0,
        Phi=Phi0,
        gamma_f=np.full(n_f, np.sqrt(prior.s2_f)),
        pi_f=np.full(n_f, pi_f0),
        phi=np.zeros((n, P_E)),
        gamma_e=np.full(n, np.sqrt(prior.s2_e)),
        pi_e=np.full(n, pi_e0),
    )
    latent0 = Latent(sigma=np.ones((n_f + n, T)), s=np.ones((n_f + n, T)))
    return prior, InitVal(param=param0, latent=latent0)


def estimate_short(
    panel: Panel,
    *,
    n_gs: int = 200,
    n_burn: int = 100,
    n_thin: int = 1,
    seed: int = 4,
    spec_path=SPEC_PATH,
) -> GibbsResult:
    """A short sampler run on one assembled panel.

    Proves the sampler completes on this panel and does not collapse; it is not
    an accuracy check, because there is nothing to check against. Nobody
    publishes an Australian nowcast from this model.

    Latents are always stored: :func:`state_space` needs them, and at these
    lengths they cost a few hundred kilobytes.
    """
    spec = load_spec(spec_path)
    restrict = build_restrict(panel, spec, p_f=P_F)
    prior, initval = _initial_point(panel, spec, restrict)
    settings = GibbsSettings(n_gs=n_gs, n_burn=n_burn, n_thin=n_thin)
    return gibbs_sampler(
        panel.Y,
        prior,
        restrict,
        initval,
        settings,
        np.random.default_rng(seed),
        need_latents=True,
    )


def state_space(
    panel: Panel, result: GibbsResult, *, spec_path=SPEC_PATH
) -> StateSpace:
    """One state space from a sampler run: median parameters, mean latents.

    The same summary ``tests/test_end_to_end.py`` uses against the published US
    figures -- ``median(param_Gibbs)`` with the latents averaged over stored
    draws.
    """
    if result.sigmas is None or result.ss is None:
        raise ValueError("the sampler run stored no latents; need_latents was off")
    spec = load_spec(spec_path)
    n, n_f = spec.blocks.shape
    param = map_parameter(np.median(result.params, axis=1), (n, n_f, P_F, P_E))

    # THE COLLAPSE GUARD. This is the one funnel from a sampler run to a state
    # space, so it is the one place that can refuse before a collapsed chain
    # becomes a number. `map_parameter` and `construct_ssm` are still available
    # to anyone deliberately inspecting a collapsed run -- as
    # `test_the_gdp_loading_is_bimodal_across_seeds` does.
    if "Global" not in spec.block_names:
        raise ValueError(
            f"the spec has no Global block (blocks: {spec.block_names}), so the "
            "collapse guard cannot be applied. It checks the nowcast target's "
            "loading on the factor every monthly series feeds; a spec without "
            "one needs a different guard, not no guard."
        )
    i_global = spec.block_names.index("Global")
    loading = float(param.Lambda[panel.i_now, i_global])
    if loading <= COLLAPSED_GLOBAL_LOADING:
        raise CollapsedFactorError(
            f"{panel.series_id[panel.i_now]}'s loading on the Global factor is "
            f"{loading:.3f}, at or below the {COLLAPSED_GLOBAL_LOADING} floor: "
            "this chain settled in the basin where the target series is not "
            "connected to the panel, and any nowcast from it would be driven by "
            "the target's own dynamics rather than by the monthly data. "
            "Measured over ninety chains (thirty seeds on each of three "
            "panels), 18 of 30 landed below this floor at the 1990 start and "
            "9 of 30 on the shortest-cpi control, and lengthening the chain to "
            "2,000 sweeps does not resolve it. See CollapsedFactorError for why "
            "a different seed is a workaround and not a fix."
        )

    latent = Latent(sigma=result.sigmas.mean(axis=2), s=result.ss.mean(axis=2))
    return construct_ssm(param, latent, build_restrict(panel, spec, p_f=P_F))


def free_parameter_mask(restrict: Restrict, dims: tuple[int, int, int, int]) -> np.ndarray:
    """Which entries of the stored parameter vector the sampler may draw.

    ``GibbsResult.params`` stores the WHOLE parameter vector, restricted entries
    included, and those never move -- a structural zero in ``model_spec_AU.csv``
    and a normalising ``1.0`` are held fixed for the entire chain by design
    (``nyfed/gibbs.py:553-571``). So "every parameter moved" is a false
    expectation of a correct run: of the Australian panel's 246 stored
    parameters, 74 are restricted -- 42 loadings (the spec's structural zeros
    and its four normalising ones) and 32 factor-VAR coefficients (the COVID
    factor's row and column, across four lags). Asking whether every FREE
    parameter moved is the question
    that has a right answer, and this builds the mask the engine's own layout
    implies rather than re-deriving the offsets by hand.
    """
    n, n_f, p_f, p_e = dims
    marker = Params(
        mu=np.full(n, np.nan),
        gamma_g=np.nan,
        Lambda=np.asarray(restrict.Lambda, dtype=float),
        Phi=np.asarray(restrict.Phi, dtype=float),
        gamma_f=np.full(n_f, np.nan),
        pi_f=np.full(n_f, np.nan),
        phi=np.full((n, p_e), np.nan),
        gamma_e=np.full(n, np.nan),
        pi_e=np.full(n, np.nan),
    )
    return np.isnan(vec_parameter(marker))


def target_periods(panel: Panel) -> np.ndarray:
    """Panel columns to nowcast: the quarters after the last observed GDP.

    ``example_nowcast.m`` steps three months at a time from the quarter after
    the target series' last observation, and each step lands on the LAST month
    of a quarter, which is where ``panel._align`` puts a quarterly observation.

    Worked through at the vintage the gate uses, 2026-06-01: GDP is observed
    through 2025-12, so the steps are 2026-03 and 2026-06 -- Q1 2026, which is
    the nowcast, and Q2 2026, which is a forecast. :func:`quick_nowcast` takes
    the first. How many horizons there are is a property of the vintage, not a
    constant: it depends on how far the panel runs past the target series' last
    observation, and under the release-date cut that distance is itself a
    function of the publication lags.
    """
    observed = np.flatnonzero(np.isfinite(panel.Y[panel.i_now]))
    if observed.size == 0:
        raise ValueError("the nowcast target row carries no observation")
    t_now = np.arange(int(observed[-1]) + 3, panel.Y.shape[1], 3)
    if t_now.size == 0:
        raise ValueError(
            f"the panel ends {panel.dates[-1].date()}, which is inside the last "
            f"observed quarter of {panel.series_id[panel.i_now]}; there is no "
            "quarter left to nowcast."
        )
    return t_now


def quick_nowcast(
    panel: Panel,
    *,
    ssm: StateSpace | None = None,
    t_now: np.ndarray | None = None,
    n_gs: int = 200,
    n_burn: int = 100,
    seed: int = 4,
) -> float:
    """The nowcast for the first target quarter, in GDP's own units.

    GDP's spec transformation is ``pca``, so the returned number is an
    **annualised** quarterly growth rate in percent; ``nyfed.au.emit`` converts
    it to the quarter-on-quarter figure Australia publishes.

    Its only job is to give the leakage check a number to compare. It is not a
    published figure and there is nothing to check it against.

    IT CAN REFUSE. When it estimates for itself it goes through
    :func:`state_space`, which raises :class:`CollapsedFactorError` if the chain
    settled in the basin where the target series is not connected to the panel.
    An injected ``ssm`` has been through the same guard, because
    :func:`state_space` is the only thing in this module that builds one from a
    sampler run. The default seed is one that lands in the identified basin, but
    a default is not a guard -- most seeds collapse, so the guard is what
    makes this function safe to call with your own.

    ``ssm`` and ``t_now`` are injectable so that two panels can be compared
    through the SAME state space. That is what makes the leakage check a
    measurement of the DATA channel: re-estimating on each panel would mix the
    effect of removing observations with the sampler's own noise, and the
    difference would then be uninterpretable in either direction.
    """
    if ssm is None:
        ssm = state_space(
            panel, estimate_short(panel, n_gs=n_gs, n_burn=n_burn, seed=seed)
        )
    if t_now is None:
        t_now = target_periods(panel)

    point = point_nowcast(panel.Y, panel.Y, ssm, ssm, panel.i_now, t_now)
    location = float(panel.y_location[panel.i_now, 0])
    scale = float(panel.y_scale[panel.i_now, 0])
    return location + scale * float(point.nowcast[3, 0])
