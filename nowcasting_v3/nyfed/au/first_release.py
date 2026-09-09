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
    return s


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
