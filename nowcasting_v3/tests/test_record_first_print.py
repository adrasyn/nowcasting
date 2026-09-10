"""The step that records the first print and the miss BEFORE the nowcast runs.

WHAT THIS PROTECTS. The published nowcast is the model less the mean of its own
last eight misses against the ABS first print. Both appends used to happen in
`tools/emit_backtest_json.py`, which the weekly workflow runs AFTER the nowcast,
so on the Monday after a print the correction was measured over a window that
stopped one quarter short. `tools/record_first_print.py` runs first; these tests
are that it does the two appends and that an ordinary week, with nothing new to
record, is still a success.
"""
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import record_first_print as rfp                            # noqa: E402

from nyfed.au.bias_correction import load_misses            # noqa: E402
from nyfed.au.first_release import (                        # noqa: E402
    load_first_release, quarter_end_month,
)

MISSES_HEADER = ("quarter,release_date,model_qoq_pct,first_print_qoq_pct,"
                 "miss_pp,source\n")


def _levels(base_q: str, growth: list[float], start: float = 600_000.0):
    """A GDP level series whose quarterly growth is `growth`, in percent.

    `base_q` is the quarter BEFORE the first growth rate, so the series ends at
    `base_q` plus `len(growth)` quarters -- the newest quarter the ABS has
    printed, which is what `append_first_print` reads.
    """
    idx = pd.date_range(quarter_end_month(base_q), periods=len(growth) + 1,
                        freq="3MS")
    lvl = [start]
    for g in growth:
        lvl.append(lvl[-1] * (1 + g / 100))
    return pd.Series(lvl, index=idx, name="gdp")


@pytest.fixture
def files(tmp_path):
    """A first-print file and a misses file that both stop at 2026 Q1.

    2026 Q2 printed on 2026-09-02 and is the quarter the tool must add to both.
    """
    first = tmp_path / "gdp_first_release.csv"
    first.write_text(
        "quarter,qoq_pct,release_date,source\n"
        "2025Q1,0.2000,2025-06-04,abs_5206.0\n"
        "2025Q2,0.3000,2025-09-03,abs_5206.0\n"
        "2025Q3,0.4000,2025-12-03,abs_5206.0\n"
        "2025Q4,0.5000,2026-03-04,abs_5206.0\n"
        "2026Q1,0.3000,2026-06-03,abs_5206.0\n")
    misses = tmp_path / "first_print_misses.csv"
    misses.write_text(
        MISSES_HEADER
        + "2025Q1,2025-06-04,0.3000,0.2000,0.1000,backtest\n"
        + "2025Q2,2025-09-03,0.4000,0.3000,0.1000,backtest\n"
        + "2025Q3,2025-12-03,0.5000,0.4000,0.1000,backtest\n"
        + "2025Q4,2026-03-04,0.6000,0.5000,0.1000,backtest\n"
        + "2026Q1,2026-06-03,0.4000,0.3000,0.1000,backtest\n")
    history = tmp_path / "nowcast_history_v3.json"
    history.write_text(json.dumps({"runs": [
        # The model's last word on 2026 Q2 before the ABS printed it.
        {"run_date": "2026-09-01", "target_quarter": "2026 Q2",
         "kind": "nowcast", "qoq_growth_pct": 0.55,
         "model_qoq_growth_pct": 0.60},
        # A row written after the print, which was never on the site.
        {"run_date": "2026-09-08", "target_quarter": "2026 Q3",
         "kind": "nowcast", "qoq_growth_pct": 0.40,
         "model_qoq_growth_pct": 0.45},
    ]}))
    return first, misses, history


def _argv(files, asof: str) -> list[str]:
    first, misses, history = files
    return ["--first-release", str(first), "--misses", str(misses),
            "--history", str(history), "--asof", asof]


def test_a_newly_printed_quarter_reaches_both_files(monkeypatch, files):
    """The Monday after a print, and the reason this tool exists.

    2026 Q2 printed on 2026-09-02. By the time the nowcast reads the misses
    file on 2026-09-07, that quarter has to be in it, or the correction is a
    mean over a window one quarter out of date.
    """
    first, misses, _ = files
    # ...ending at 2026 Q2, which grew 0.45% on 2026 Q1.
    monkeypatch.setattr(rfp, "published_gdp",
                        lambda _dir: _levels("2024Q4", [0.2, 0.3, 0.4, 0.5,
                                                        0.3, 0.45]))
    assert rfp.main(_argv(files, "2026-09-07")) == 0

    fp = load_first_release(first)
    assert quarter_end_month("2026Q2") in fp.index
    assert float(fp[quarter_end_month("2026Q2")]) == pytest.approx(0.45, abs=1e-4)

    m = load_misses(misses)
    assert list(m["quarter"])[-1] == "2026Q2"
    row = m[m["quarter"] == "2026Q2"].iloc[0]
    # The MODEL's figure, not the published one: the miss being averaged is the
    # model's own error, and correcting the corrected figure would double-count.
    assert float(row["model_qoq_pct"]) == pytest.approx(0.60, abs=1e-4)
    assert float(row["first_print_qoq_pct"]) == pytest.approx(0.45, abs=1e-4)
    assert float(row["miss_pp"]) == pytest.approx(0.15, abs=1e-4)
    assert row["source"] == "live"


def test_an_ordinary_week_appends_nothing_and_still_succeeds(monkeypatch, files):
    """Three weeks in four there is no new print.

    This step runs before the nowcast and stops the job when it fails, so
    "nothing to do" must be a success and must not touch either file.
    """
    first, misses, _ = files
    before = (first.read_text(), misses.read_text())
    # The ABS's newest quarter is still 2026 Q1, already recorded.
    monkeypatch.setattr(rfp, "published_gdp",
                        lambda _dir: _levels("2024Q4", [0.2, 0.3, 0.4, 0.5, 0.3]))
    assert rfp.main(_argv(files, "2026-07-06")) == 0
    assert (first.read_text(), misses.read_text()) == before


def test_an_unusable_misses_file_stops_the_job(monkeypatch, files):
    """The one failure worth failing the week's nowcast over.

    The file is hand-edited when a quarter is missed. A bad edit that this step
    merely warned about would reach `run_au_nowcast.py` as a correction nobody
    can reproduce from the file it came out of.
    """
    _, misses, _ = files
    misses.write_text(MISSES_HEADER + "2025Q1,2025-06-04,0.3,0.2,0.9,backtest\n")
    monkeypatch.setattr(rfp, "published_gdp",
                        lambda _dir: _levels("2024Q4", [0.2, 0.3, 0.4, 0.5, 0.3]))
    assert rfp.main(_argv(files, "2026-07-06")) == 1


def test_a_failed_fetch_records_nothing_and_lets_the_nowcast_run(monkeypatch, files):
    """A dead ABS is not a reason to refuse to publish.

    Nothing is appended, so the nowcast runs on the window it already had, and
    `emit_backtest_json.py` retries the same appends later in the job.
    """
    first, misses, _ = files
    before = (first.read_text(), misses.read_text())

    def _boom(_dir):
        raise RuntimeError("abs.gov.au timed out")

    monkeypatch.setattr(rfp, "published_gdp", _boom)
    assert rfp.main(_argv(files, "2026-09-07")) == 0
    assert (first.read_text(), misses.read_text()) == before
