"""The model's rolling miss against the ABS first print.

WHY THIS EXISTS. The published nowcast is a model trained on first-print GDP,
less a rolling mean of that model's own recent misses. Section 4.1 of
`docs/2026-09-01-upside-bias-report.md` measured the same over-prediction in all
three models and recommended an explicit, published correction: subtract the
recent mean error, show it as a separate line, never fold it in silently. That
section declined to ship the correction for v3, on the ground that v3's residual
bias (+0.089pp) was smaller than its own standard error. The addendum of
9 September (Mechanism 4 in the same report, and
`docs/2026-09-09-unrevised-data-feasibility.md`) changed the arithmetic: scored
against FIRST PRINTS rather than the latest ABS vintage, v3's bias is +0.20pp
with t = 3.9, not +0.12 with t = 1.8. The ABS revises quarterly growth up by
about 0.107pp on average, so scoring against revised data had been hiding
roughly 40% of what a reader saw on print day. A bias that large, against the
number the site is actually judged by, is worth correcting.

WHAT "THE MODEL'S FINAL NOWCAST" MEANS. The last figure published for a quarter
before the ABS printed it — the number a reader was looking at on the morning of
the release. In the seed file that is the median over sampler seeds at the last
backtest `asof` for the target; live it is the last history run for the target
whose `run_date` falls before the release date, ignoring forecast rows (a
forecast is the quarter that has not started yet, a different and much harder
call) and backfilled rows (those were written after the fact and were never on
the site). The miss is that figure minus the ABS first print, so a positive miss
is an over-prediction and the correction is subtracted.

ROLLING, NOT EXPANDING. The report's implementation note, section 4.1: the bias
is itself drifting — v2's was +0.449 over its first nine quarters and +0.217
over its last eight, v3's +0.160 then +0.080 — so an expanding mean keeps
correcting for an error the model has already grown out of. Eight quarters is
the window the report tested. It is a mean and not a median because the bias
being removed is a mean.

THE FILE. `data/first_print_misses.csv`, one row per printed quarter, seeded
2022Q4-2026Q2 from the Plan C first-print backtest by
`tools/build_first_print_misses.py` (`source` = `backtest`) and appended by the
weekly job on the Monday after each ABS print through `append_miss`
(`source` = `live`). A quarter that was never nowcast live cannot be
reconstructed after the fact, so the append skips it loudly rather than
inventing one.

RETIREMENT. Also from section 4.1, and the point of writing this down: the
correction is a patch, not a permanent part of the model. If the rolling miss
stays inside +/-0.05pp for six consecutive quarters, drop it — the defect it
covers has gone, and a correction that small is noise being published as if it
were information.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from nyfed.au.emit import gdp_release_date
from nyfed.au.first_release import quarter_label

MISSES_CSV = Path(__file__).resolve().parents[2] / "data" / "first_print_misses.csv"
BIAS_WINDOW_QUARTERS = 8
BIAS_MIN_QUARTERS = 4

COLUMNS = ["quarter", "release_date", "model_qoq_pct", "first_print_qoq_pct",
           "miss_pp", "source"]


def _spaced(label: str) -> str:
    """``2026Q2`` -> ``2026 Q2``, the form the history and `gdp_release_date` use."""
    return f"{label[:4]} Q{label[-1]}"


def load_misses(path: str | Path = MISSES_CSV) -> pd.DataFrame:
    """The recorded misses, oldest print first.

    Duplicate quarters are refused rather than averaged: two rows for one
    quarter means an append ran twice or a hand edit went wrong, and either way
    the mean would be silently weighted toward that quarter.
    """
    frame = pd.read_csv(path, dtype={"quarter": str, "source": str})
    missing = [c for c in COLUMNS if c not in frame.columns]
    if missing:
        raise ValueError(f"{path}: missing columns {missing}")
    dup = sorted(frame["quarter"][frame["quarter"].duplicated()].unique())
    if dup:
        raise ValueError(f"{path}: duplicate quarters {dup}")
    frame["release_date"] = pd.to_datetime(frame["release_date"])
    for c in ("model_qoq_pct", "first_print_qoq_pct", "miss_pp"):
        frame[c] = frame[c].astype(float)
    # THE THREE NUMBER COLUMNS MUST AGREE. `miss_pp` is what the correction is
    # a mean of, and the other two are what a reader would check it against, so
    # a row where they disagree is a hand edit that changed one field and not
    # the others. Silently trusting `miss_pp` would publish a correction that no
    # pair of figures in the file supports. 1e-4 is the file's own precision.
    bad = (frame["miss_pp"]
           - (frame["model_qoq_pct"] - frame["first_print_qoq_pct"])).abs() > 1e-4
    if bad.any():
        q = sorted(frame["quarter"][bad])
        raise ValueError(
            f"{path}: miss_pp is not model_qoq_pct - first_print_qoq_pct for "
            f"{q}; fix the row rather than the miss")
    return frame[COLUMNS].sort_values("release_date").reset_index(drop=True)


@dataclass(frozen=True)
class BiasEstimate:
    pp: float
    n: int
    window_quarters: int
    min_quarters: int
    first_quarter: str
    last_quarter: str

    def as_dict(self) -> dict:
        return {
            "pp": self.pp, "n": self.n,
            "window_quarters": self.window_quarters,
            "min_quarters": self.min_quarters,
            "first_quarter": self.first_quarter,
            "last_quarter": self.last_quarter,
            "basis": ("mean of the model's final nowcast minus the ABS first "
                      f"print over the last {self.n} printed quarters"),
        }


def rolling_miss(
    misses: pd.DataFrame,
    asof,
    *,
    window: int = BIAS_WINDOW_QUARTERS,
    min_n: int = BIAS_MIN_QUARTERS,
) -> BiasEstimate:
    """The mean miss over the last `window` quarters printed on or before `asof`.

    `asof` is the run date, so a quarter counts only once the ABS has actually
    printed it. Refuses to return a figure from fewer than `min_n` quarters: a
    correction estimated from two or three misses is noise, and publishing it
    would be worse than publishing the raw model.
    """
    if window < 1:
        raise ValueError(f"window must be at least 1, got {window}")
    if min_n < 1:
        raise ValueError(f"min_n must be at least 1, got {min_n}")
    asof = pd.Timestamp(asof)
    printed = misses[misses["release_date"] <= asof].sort_values("release_date")
    sel = printed.tail(window)
    if len(sel) < min_n:
        raise ValueError(
            f"fewer than {min_n} quarters printed on or before {asof.date()} "
            f"({len(sel)} found); no bias correction can be estimated")
    return BiasEstimate(
        pp=round(float(sel["miss_pp"].mean()), 4),
        n=int(len(sel)),
        window_quarters=window,
        min_quarters=min_n,
        first_quarter=str(sel["quarter"].iloc[0]),
        last_quarter=str(sel["quarter"].iloc[-1]),
    )


def _final_nowcast(runs: list[dict], label: str, release: pd.Timestamp) -> dict | None:
    """The last row a reader would have seen for `label` before it printed."""
    target = _spaced(label)
    eligible = [
        r for r in runs
        if r.get("target_quarter") == target
        and not r.get("backfilled")
        and (r.get("kind") or "nowcast") == "nowcast"
        and r.get("model_qoq_growth_pct") is not None
        and pd.Timestamp(r["run_date"]) < release
    ]
    if not eligible:
        return None
    return max(eligible, key=lambda r: pd.Timestamp(r["run_date"]))


def append_miss(path: str | Path, runs: list[dict], first: pd.Series, *, asof) -> list[str]:
    """Record the miss for every quarter printed since the file's last one.

    `runs` is the history log (`data/nowcast_history_v3.json`, `runs`); `first`
    is a `load_first_release` series. Returns the quarter labels appended.

    Only quarters AFTER the last one in the file are considered. The file is
    seeded across the whole backtest era, so anything older is already there by
    construction, and a live job has no way to reconstruct a nowcast that
    predates its own history log.
    """
    path = Path(path)
    misses = load_misses(path)
    known = set(misses["quarter"])
    asof = pd.Timestamp(asof)

    floor = misses["release_date"].max() if len(misses) else pd.Timestamp.min

    appended: list[str] = []
    lines: list[str] = []
    for ts, first_print in first.dropna().sort_index().items():
        label = quarter_label(ts)
        if label in known:
            continue
        release_s = gdp_release_date(_spaced(label))
        if release_s is None:
            continue
        release = pd.Timestamp(release_s)
        if release <= floor or release > asof:
            continue
        run = _final_nowcast(runs, label, release)
        if run is None:
            print(f"  first-print miss: {label} printed {release_s} but no live "
                  "nowcast for it survives in the history; skipped (it cannot be "
                  "reconstructed after the fact)", flush=True)
            continue
        model = float(run["model_qoq_growth_pct"])
        miss = round(model - float(first_print), 4)
        lines.append(f"{label},{release_s},{model:.4f},{float(first_print):.4f},"
                     f"{miss:.4f},live\n")
        appended.append(label)
        print(f"  first-print miss: {label} model {model:+.4f}% vs first print "
              f"{float(first_print):+.4f}% -> miss {miss:+.4f}pp "
              f"(run {run['run_date']}, printed {release_s})", flush=True)

    if lines:
        text = path.read_text()
        path.write_text(text + ("" if text.endswith("\n") else "\n") + "".join(lines))
    return appended
