"""First-release (first-print) real GDP growth, and the revision it implies.

WHY THIS EXISTS. The model is trained on, and the backtest was scored against,
the ABS's LATEST vintage of GDP. The site is judged against the FIRST print, on
the day. The ABS revises quarterly growth UP by about 0.1pp on average
(+0.107pp over 1980-2022 and again over 2019-2026, positive in every decade;
docs/2026-09-09-unrevised-data-feasibility.md). Scored against first prints,
v3's bias is +0.20pp, not the +0.12pp the track record showed. This module is
the source of first prints and of the adjustment that removes the average
revision from the published figure.

THE FILE. `data/gdp_first_release.csv`, built once by
`tools/build_first_release_gdp.py` and appended by the weekly job through
`append_first_print`. Quarter-on-quarter growth in percent, one row per
quarter, `YYYYQn` labels.

THE ADJUSTMENT. `mean_revision` is the mean of (latest growth - first-print
growth) over the last `window` quarters whose first print is at least
`min_age` quarters old. Young quarters are excluded because their revision
has barely begun and would pull the mean toward zero. Latest growth is taken
from whatever level series the caller has fetched, so the estimate moves with
the current vintage. It is a mean, not a median: the bias is what is being
removed, and the bias is the mean.

WHAT "FIRST PRINT" MEANS WHEN APPENDING. The weekly job runs on the Monday
after the Wednesday the ABS prints, so the newest quarter in a live fetch IS
its first print until the next quarterly release revises it. The append is
refused once the print is more than `MAX_FIRST_PRINT_AGE_DAYS` old, because a
job that missed a quarter would otherwise record a revised figure as a first
print. A missed quarter is filled by hand from that release's Key Aggregates
spreadsheet (see the feasibility note, section 3).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from nyfed.au.emit import gdp_release_date

FIRST_RELEASE_CSV = Path(__file__).resolve().parents[2] / "data" / "gdp_first_release.csv"
REVISION_WINDOW_QUARTERS = 40
REVISION_MIN_AGE_QUARTERS = 4
MAX_FIRST_PRINT_AGE_DAYS = 80
_MIN_SAMPLE = 8


def quarter_end_month(label: str) -> pd.Timestamp:
    """``"2026Q2"`` or ``"2026 Q2"`` -> 2026-06-01, the panel's date for it."""
    year, q = label.replace(" ", "").upper().split("Q")
    return pd.Timestamp(int(year), 3 * int(q), 1)


def quarter_label(ts) -> str:
    ts = pd.Timestamp(ts)
    return f"{ts.year}Q{(ts.month - 1) // 3 + 1}"


def load_first_release(path: str | Path = FIRST_RELEASE_CSV) -> pd.Series:
    frame = pd.read_csv(path, dtype={"quarter": str})
    idx = pd.DatetimeIndex([quarter_end_month(q) for q in frame["quarter"]])
    if idx.has_duplicates:
        dup = sorted({quarter_label(t) for t in idx[idx.duplicated()]})
        raise ValueError(f"{path}: duplicate quarters {dup}")
    s = pd.Series(frame["qoq_pct"].to_numpy(dtype=float), index=idx,
                  name="first_release_qoq")
    if not s.index.is_monotonic_increasing:
        raise ValueError(f"{path}: quarters are not in order")
    # A GAP MUST DEGRADE VISIBLY, NOT KILL THE JOB. A missed quarter is filled
    # by hand and until it is, the revision mean is computed over fewer
    # quarters than the window says. That is a degraded figure, not a wrong
    # one, so this warns rather than raises: the weekly log is where anyone
    # would notice, and refusing to load would cost the publish.
    if len(s) > 1:
        expected = pd.date_range(s.index[0], s.index[-1], freq="3MS")
        gaps = expected.difference(s.index)
        if len(gaps):
            print(f"::warning::{path}: missing quarters "
                  f"{[quarter_label(g) for g in gaps]}", flush=True)
    return s


def published_gdp(fallback_vintage_dir: str | Path) -> pd.Series:
    """Every quarter of real GDP the ABS has actually printed.

    THIS USED TO READ A TEST FIXTURE. `tests/fixtures/au/vintage` is a recording
    made for replay tests, and its GDP stops at 2026 Q1. The callers append
    quarters the model called live once the ABS prints them — and decide "has it
    printed?" by looking the quarter up in this series. Against a frozen
    recording the answer was permanently no, so the append never fired: 2026 Q2,
    the first quarter this model nowcast in public, sat in
    `nowcast_history_v3.json` and never reached the table. The commit that added
    that block is called "a quarter the model called live would never reach the
    track record". It was right about the problem and fed the fix a fixture.

    Fetches GDP alone, not the whole panel — one ABS call. Falls back to the
    recording at `fallback_vintage_dir` if the fetch fails, because a track
    record that is one quarter stale beats a weekly job that dies, and says
    which it used either way.

    LIVES HERE, NOT IN A TOOL. `tools/record_first_print.py` records the first
    print and the miss before the nowcast runs, and `tools/emit_backtest_json.py`
    keeps the same appends as a safety net; both need the same live series, and
    two copies of this could drift into scoring against two different vintages.
    The build imports are local because `nyfed.au.build` imports this module.
    """
    from nyfed.au.build import fetch_vintage, load_vintage
    from nyfed.au.sources import AU_SERIES

    src = tuple(s for s in AU_SERIES if s.key == "gdp")
    try:
        g = fetch_vintage(src).series["gdp"].dropna()
        print(f"  actuals: live ABS, through {g.index[-1].date()}", flush=True)
        return g
    except Exception as exc:                                    # noqa: BLE001
        g = load_vintage(Path(fallback_vintage_dir)).series["gdp"].dropna()
        print(f"::warning::live GDP fetch failed ({type(exc).__name__}: {exc}); "
              f"scoring against the recorded vintage, which ends "
              f"{g.index[-1].date()} — quarters after it cannot be scored",
              flush=True)
        return g


def latest_qoq(levels: pd.Series) -> pd.Series:
    g = levels.dropna().sort_index()
    return (g / g.shift(1) - 1) * 100


@dataclass(frozen=True)
class RevisionEstimate:
    pp: float
    n: int
    first_quarter: str
    last_quarter: str
    window_quarters: int
    min_age_quarters: int

    def as_dict(self) -> dict:
        return {
            "pp": self.pp, "n": self.n,
            "first_quarter": self.first_quarter, "last_quarter": self.last_quarter,
            "window_quarters": self.window_quarters,
            "min_age_quarters": self.min_age_quarters,
            "basis": ("mean of (latest-vintage growth - first-print growth) over "
                      f"the last {self.n} quarters whose first print is at least "
                      f"{self.min_age_quarters} quarters old"),
        }


def mean_revision(
    first: pd.Series,
    latest_levels: pd.Series,
    *,
    asof,
    window: int = REVISION_WINDOW_QUARTERS,
    min_age: int = REVISION_MIN_AGE_QUARTERS,
) -> RevisionEstimate:
    if window < 1:
        raise ValueError(f"window must be at least 1, got {window}")
    if min_age < 0:
        raise ValueError(f"min_age must not be negative, got {min_age}")
    asof = pd.Timestamp(asof)
    cur = latest_qoq(latest_levels).dropna()
    both = first.index.intersection(cur.index)
    # A quarter dated M is released about M + 3 months; it has settled once
    # `min_age` further quarters have been released on top of it.
    cutoff = asof - pd.DateOffset(months=3 * (min_age + 1))
    eligible = both[both <= cutoff][-window:]
    if len(eligible) < _MIN_SAMPLE:
        raise ValueError(
            f"fewer than {_MIN_SAMPLE} settled quarters with both a first print "
            f"and a latest value before {cutoff.date()} ({len(eligible)} found)")
    rev = cur[eligible] - first[eligible]
    return RevisionEstimate(
        pp=round(float(rev.mean()), 4), n=int(len(eligible)),
        first_quarter=quarter_label(eligible[0]),
        last_quarter=quarter_label(eligible[-1]),
        window_quarters=window, min_age_quarters=min_age)


def append_first_print(path: str | Path, latest_levels: pd.Series, *, asof) -> str | None:
    """Record the newest quarter's growth as its first print, if it is new and fresh.

    Returns the quarter label appended, or None. Prints why when it declines,
    because the weekly log is the only place anyone will look.
    """
    path = Path(path)
    first = load_first_release(path)
    g = latest_levels.dropna().sort_index()
    if len(g) < 2:
        return None
    q = g.index[-1]
    if q in first.index:
        return None
    label = quarter_label(q)
    if g.index[-2] != q - pd.DateOffset(months=3):
        print(f"  first print: {label} has no preceding quarter in the fetched "
              "levels; not recorded", flush=True)
        return None
    missing = pd.date_range(first.index[-1] + pd.DateOffset(months=3), q, freq="3MS")[:-1]
    if len(missing):
        print(f"  first print: {[quarter_label(m) for m in missing]} were never "
              "recorded and cannot be recovered live; fill them from that "
              "release's Key Aggregates spreadsheet", flush=True)
    release = gdp_release_date(f"{q.year} Q{(q.month - 1) // 3 + 1}")
    age = (pd.Timestamp(asof) - pd.Timestamp(release)).days
    if age > MAX_FIRST_PRINT_AGE_DAYS:
        print(f"  first print: {label} was released {release}, {age} days before "
              f"{pd.Timestamp(asof).date()}; it may already be revised, not "
              "recorded", flush=True)
        return None
    qoq = 100 * (float(g.iloc[-1]) / float(g.iloc[-2]) - 1)
    line = f"{label},{qoq:.4f},{release},abs_5206.0_live_{pd.Timestamp(asof).date()}\n"
    text = path.read_text()
    path.write_text(text + ("" if text.endswith("\n") else "\n") + line)
    print(f"  first print: recorded {label} at {qoq:+.4f}% (released {release})", flush=True)
    return label


def first_release_index(first: pd.Series, anchor: pd.Series) -> pd.Series:
    """A level series with first-print growth, on ``anchor``'s dates and scale.

    THE MODEL TAKES LEVELS. `gdp` enters the panel as chain-volume millions and
    is transformed to annualised growth there, so a first-print TARGET has to
    be handed over as a level series too. There is no such thing as a
    first-print level series (every release rebases), so this cumulates the
    first-print growth rates into an index and pins it to the latest vintage's
    level at the last quarter the two share. Growth is preserved exactly; the
    level is a scale factor the transformation removes.

    The index starts at the quarter BEFORE the first first-print (its base
    level, growth zero by construction) when ``anchor`` has it. Earlier
    quarters of ``anchor`` are dropped, because a level with no first-print
    growth behind it would be latest-vintage growth in disguise. Quarters after
    the last first-print are carried from ``anchor`` as they are.
    """
    a = anchor.dropna().sort_index()
    f = first.dropna().sort_index()
    if len(f) > 1:
        steps = {(b - a_).n for a_, b in zip(f.index.to_period("Q")[:-1],
                                            f.index.to_period("Q")[1:])}
        if steps != {1}:
            raise ValueError("first-release series has a gap; fill it before building an index")
    start = max(a.index[0], f.index[0] - pd.DateOffset(months=3))
    a = a[a.index >= start]
    common = a.index.intersection(f.index)
    if len(common) == 0:
        raise ValueError("no quarter is in both the first-release series and the anchor")
    last = common[-1]
    # Cumulate forward from 1.0, then rescale so the index equals the anchor at `last`.
    growth = f.reindex(a.index[a.index <= last])
    growth.iloc[0] = 0.0                           # the first level is the base
    idx = (1 + growth / 100).cumprod()
    idx = idx * (float(a[last]) / float(idx[last]))
    tail = a[a.index > last]
    out = pd.concat([idx, tail]).sort_index()
    out.name = "gdp"
    return out
