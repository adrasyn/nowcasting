"""The model's rolling miss against the ABS first print."""
import pandas as pd
import pytest

from nyfed.au.bias_correction import (
    BIAS_MIN_QUARTERS, BIAS_WINDOW_QUARTERS, BiasEstimate, append_miss,
    load_misses, rolling_miss,
)
from nyfed.au.emit import gdp_release_date
from nyfed.au.first_release import quarter_end_month

HEADER = "quarter,release_date,model_qoq_pct,first_print_qoq_pct,miss_pp,source\n"


def _quarters(first_q: str, n: int) -> list[str]:
    idx = pd.date_range(quarter_end_month(first_q), periods=n, freq="3MS")
    return [f"{t.year}Q{(t.month - 1) // 3 + 1}" for t in idx]


def _misses_csv(path, first_q: str, misses: list[float], source="backtest"):
    """A misses file whose `miss_pp` column is `misses`, from `first_q` on."""
    lines = [HEADER]
    for q, m in zip(_quarters(first_q, len(misses)), misses):
        model, first = 0.5, round(0.5 - m, 4)
        lines.append(f"{q},{gdp_release_date(q[:4] + ' ' + q[4:])},"
                     f"{model},{first},{m},{source}\n")
    path.write_text("".join(lines))
    return path


def _misses(tmp_path, first_q: str, misses: list[float]) -> pd.DataFrame:
    return load_misses(_misses_csv(tmp_path / "m.csv", first_q, misses))


def _first(first_q: str, growth: list[float]) -> pd.Series:
    idx = pd.date_range(quarter_end_month(first_q), periods=len(growth), freq="3MS")
    return pd.Series(growth, index=idx, name="first_release_qoq")


def test_rolling_miss_uses_the_last_eight_printed_quarters(tmp_path):
    # 12 quarters, 2023Q1..2025Q4, misses +0.1 .. +1.2; everything has printed.
    m = _misses(tmp_path, "2023Q1", [round(0.1 * i, 4) for i in range(1, 13)])
    est = rolling_miss(m, "2026-09-10")
    assert isinstance(est, BiasEstimate)
    # the last eight are 2024Q1..2025Q4, +0.5 .. +1.2, mean +0.85
    assert est.pp == pytest.approx(0.85, abs=1e-9)
    assert est.n == 8
    assert est.first_quarter == "2024Q1" and est.last_quarter == "2025Q4"
    assert est.window_quarters == BIAS_WINDOW_QUARTERS == 8
    assert est.min_quarters == BIAS_MIN_QUARTERS == 4
    d = est.as_dict()
    assert set(d) == {"pp", "n", "window_quarters", "min_quarters",
                      "first_quarter", "last_quarter", "basis"}
    assert d["pp"] == est.pp and d["n"] == 8
    assert isinstance(d["basis"], str) and "first print" in d["basis"] and "8" in d["basis"]


def test_rolling_miss_ignores_quarters_not_yet_printed(tmp_path):
    # 9 quarters, 2024Q1..2026Q1; the last one is a wild miss.
    m = _misses(tmp_path, "2024Q1", [0.2] * 8 + [9.0])
    assert gdp_release_date("2026 Q1") == "2026-06-03"
    est = rolling_miss(m, "2026-06-02")          # the day before 2026Q1 prints
    assert est.n == 8
    assert est.last_quarter == "2025Q4"
    assert est.pp == pytest.approx(0.2, abs=1e-9)
    # and on the print day itself it counts
    assert rolling_miss(m, "2026-06-03").last_quarter == "2026Q1"


def test_rolling_miss_needs_four_quarters(tmp_path):
    m = _misses(tmp_path, "2025Q1", [0.1, 0.2, 0.3])
    with pytest.raises(ValueError, match="fewer than"):
        rolling_miss(m, "2026-09-10")


def test_append_miss_takes_the_last_live_nowcast_before_the_print(tmp_path):
    p = _misses_csv(tmp_path / "m.csv", "2026Q1", [0.27])          # 2026Q1 only
    first = _first("2026Q1", [0.2743, 0.4195])                     # 2026Q2 printed 2026-09-02
    runs = [
        {"run_date": "2026-08-24", "target_quarter": "2026 Q2", "kind": "nowcast",
         "model_qoq_growth_pct": 0.9, "backfilled": True},          # backfilled: ignored
        {"run_date": "2026-08-25", "target_quarter": "2026 Q2", "kind": "forecast",
         "model_qoq_growth_pct": 0.8},                              # a forecast: ignored
        {"run_date": "2026-08-17", "target_quarter": "2026 Q2", "kind": "nowcast",
         "model_qoq_growth_pct": 0.7},                              # eligible, earlier
        {"run_date": "2026-08-31", "target_quarter": "2026 Q2",
         "model_qoq_growth_pct": 0.64},                             # eligible, later, kind absent
        {"run_date": "2026-09-07", "target_quarter": "2026 Q2", "kind": "nowcast",
         "model_qoq_growth_pct": 0.5},                              # after the print: ignored
    ]
    assert append_miss(p, runs, first, asof="2026-09-07") == ["2026Q2"]
    m = load_misses(p)
    assert list(m["quarter"]) == ["2026Q1", "2026Q2"]
    row = m[m["quarter"] == "2026Q2"].iloc[0]
    assert row["model_qoq_pct"] == pytest.approx(0.64)
    assert row["first_print_qoq_pct"] == pytest.approx(0.4195)
    assert row["miss_pp"] == pytest.approx(0.2205, abs=1e-6)
    assert row["source"] == "live"
    assert row["release_date"] == pd.Timestamp("2026-09-02")
    assert append_miss(p, runs, first, asof="2026-09-14") == []     # already recorded
    assert len(load_misses(p)) == 2


def test_append_miss_skips_a_quarter_with_no_live_row_and_says_so(tmp_path, capsys):
    p = _misses_csv(tmp_path / "m.csv", "2026Q1", [0.27])
    first = _first("2026Q1", [0.2743, 0.4195])
    runs = [{"run_date": "2026-08-31", "target_quarter": "2026 Q2", "kind": "forecast",
             "model_qoq_growth_pct": 0.8}]
    before = p.read_text()
    assert append_miss(p, runs, first, asof="2026-09-07") == []
    assert p.read_text() == before
    assert "2026Q2" in capsys.readouterr().out


def test_load_misses_refuses_duplicates(tmp_path):
    p = tmp_path / "m.csv"
    p.write_text(HEADER
                 + "2025Q1,2025-06-04,0.5,0.2,0.3,backtest\n"
                 + "2025Q1,2025-06-04,0.6,0.2,0.4,backtest\n")
    with pytest.raises(ValueError, match="duplicate"):
        load_misses(p)


def test_load_misses_refuses_a_row_whose_miss_is_not_its_own_arithmetic(tmp_path):
    """A hand edit that moved one figure and not the others.

    `miss_pp` is what the correction averages, and the two columns beside it are
    what anyone would check it against. A row where they disagree would publish
    a correction that no pair of numbers in the file supports, and nothing on
    the page would show it. The quarter has to be named or the file is a
    haystack.
    """
    p = tmp_path / "m.csv"
    p.write_text(HEADER
                 + "2025Q1,2025-06-04,0.5000,0.2000,0.3000,backtest\n"
                 + "2025Q2,2025-09-03,0.6000,0.2000,0.3000,backtest\n")
    with pytest.raises(ValueError, match="2025Q2"):
        load_misses(p)
    # ...and the arithmetic that does hold is not disturbed by rounding at the
    # file's own precision.
    p.write_text(HEADER + "2025Q1,2025-06-04,0.5000,0.2000,0.3000,backtest\n")
    assert float(load_misses(p)["miss_pp"].iloc[0]) == pytest.approx(0.3)


def test_the_committed_misses_file_covers_the_backtest_era():
    m = load_misses()
    assert len(m) == 15
    assert list(m["quarter"]) == _quarters("2022Q4", 15)
    assert m["quarter"].iloc[0] == "2022Q4" and m["quarter"].iloc[-1] == "2026Q2"
    assert set(m["source"]) == {"backtest"}
    assert m["miss_pp"].abs().max() < 1.0
    assert m["release_date"].is_monotonic_increasing
    q2 = m.iloc[-1]
    assert q2["model_qoq_pct"] == pytest.approx(0.45, abs=0.02)
    assert q2["first_print_qoq_pct"] == pytest.approx(0.4195, abs=1e-4)
    assert q2["miss_pp"] == pytest.approx(q2["model_qoq_pct"] - q2["first_print_qoq_pct"],
                                          abs=1e-6)
    assert q2["release_date"] == pd.Timestamp("2026-09-02")
