"""First-release GDP: loading, the mean revision, and appending a new print."""
import numpy as np
import pandas as pd
import pytest

from nyfed.au.first_release import (
    MAX_FIRST_PRINT_AGE_DAYS, RevisionEstimate, append_first_print,
    latest_qoq, load_first_release, mean_revision, quarter_end_month,
    quarter_label,
)


def _levels(first_q: str, growth: list[float], start=100.0) -> pd.Series:
    """A level series whose growth is `growth`, dated like the panel."""
    idx = pd.date_range(quarter_end_month(first_q), periods=len(growth) + 1, freq="3MS")
    lv = [start]
    for g in growth:
        lv.append(lv[-1] * (1 + g / 100))
    return pd.Series(lv, index=idx, name="gdp")


def _first(first_q: str, growth: list[float]) -> pd.Series:
    idx = pd.date_range(quarter_end_month(first_q), periods=len(growth), freq="3MS")
    return pd.Series(growth, index=idx, name="first_release_qoq")


def test_quarter_end_month_accepts_both_label_forms():
    assert quarter_end_month("2026Q2") == pd.Timestamp("2026-06-01")
    assert quarter_end_month("2026 Q2") == pd.Timestamp("2026-06-01")
    assert quarter_end_month("1959Q4") == pd.Timestamp("1959-12-01")
    assert quarter_label(pd.Timestamp("2026-06-01")) == "2026Q2"


def test_load_first_release_reads_the_committed_file():
    s = load_first_release()
    assert s.index[0] == pd.Timestamp("1959-12-01")
    assert s.index.is_monotonic_increasing and not s.index.has_duplicates
    assert abs(s[pd.Timestamp("2023-03-01")] - 0.2332) < 1e-3


def test_load_first_release_refuses_duplicates(tmp_path):
    p = tmp_path / "f.csv"
    p.write_text("quarter,qoq_pct,release_date,source\n2020Q1,0.1,,x\n2020Q1,0.2,,x\n")
    with pytest.raises(ValueError, match="duplicate"):
        load_first_release(p)


def test_load_first_release_warns_about_a_gap_but_still_loads(tmp_path, capsys):
    p = tmp_path / "f.csv"
    p.write_text("quarter,qoq_pct,release_date,source\n"
                 "2020Q1,0.1,,x\n2020Q3,0.3,,x\n2020Q4,0.4,,x\n")
    s = load_first_release(p)
    assert len(s) == 3
    out = capsys.readouterr().out
    assert "::warning::" in out and "2020Q2" in out


def test_latest_qoq_is_percent_growth():
    lv = _levels("2020Q1", [1.0, -0.5])
    g = latest_qoq(lv)
    assert np.isnan(g.iloc[0])
    assert g.iloc[1] == pytest.approx(1.0)
    assert g.iloc[2] == pytest.approx(-0.5)


def test_mean_revision_is_latest_minus_first_over_settled_quarters():
    # 12 quarters of first prints all 0.4; latest growth all 0.5 -> revision +0.1
    first = _first("2020Q2", [0.4] * 12)                 # 2020Q2..2023Q1
    lv = _levels("2020Q1", [0.5] * 12)                    # growth dated 2020Q2..2023Q1
    est = mean_revision(first, lv, asof="2024-09-09", window=40, min_age=4)
    assert isinstance(est, RevisionEstimate)
    assert est.pp == pytest.approx(0.1, abs=1e-6)
    # settled = quarter end month + 3 (release) + 12 (four quarters) <= asof
    # 2024-09-09 - 15 months = 2023-06-09 -> everything through 2023Q1 qualifies
    assert est.n == 12
    assert est.first_quarter == "2020Q2" and est.last_quarter == "2023Q1"


def test_mean_revision_excludes_quarters_too_young_to_have_settled():
    first = _first("2020Q2", [0.0] * 12)
    lv = _levels("2020Q1", [0.0] * 11 + [5.0])           # the last quarter looks revised
    est = mean_revision(first, lv, asof="2023-09-09", window=40, min_age=4)
    # asof - 15 months = 2022-06-09 -> 2022Q2 is the last settled quarter; 2023Q1 excluded
    assert est.last_quarter == "2022Q2"
    assert est.pp == pytest.approx(0.0)


def test_mean_revision_takes_only_the_window():
    first = _first("2000Q1", [0.0] * 60)
    growth = [1.0] * 20 + [0.0] * 40                       # old quarters heavily revised
    lv = _levels("1999Q4", growth)
    est = mean_revision(first, lv, asof="2020-01-01", window=40, min_age=4)
    assert est.n == 40
    assert est.pp == pytest.approx(0.0)


def test_mean_revision_refuses_a_thin_sample():
    first = _first("2020Q2", [0.0] * 4)
    lv = _levels("2020Q1", [0.0] * 4)
    with pytest.raises(ValueError, match="fewer than 8"):
        mean_revision(first, lv, asof="2030-01-01")


def test_mean_revision_refuses_a_non_positive_window():
    first = _first("2020Q2", [0.0] * 12)
    lv = _levels("2020Q1", [0.0] * 12)
    with pytest.raises(ValueError, match="window"):
        mean_revision(first, lv, asof="2024-09-09", window=0)


def test_mean_revision_refuses_a_negative_min_age():
    first = _first("2020Q2", [0.0] * 12)
    lv = _levels("2020Q1", [0.0] * 12)
    with pytest.raises(ValueError, match="min_age"):
        mean_revision(first, lv, asof="2024-09-09", min_age=-1)


def test_revision_estimate_as_dict_has_the_expected_keys_and_values():
    est = RevisionEstimate(pp=0.0903, n=40, first_quarter="2015Q2",
                            last_quarter="2025Q1", window_quarters=40,
                            min_age_quarters=4)
    d = est.as_dict()
    assert set(d) == {"pp", "n", "first_quarter", "last_quarter",
                       "window_quarters", "min_age_quarters", "basis"}
    assert d["pp"] == 0.0903
    assert d["n"] == 40
    assert d["first_quarter"] == "2015Q2"
    assert d["last_quarter"] == "2025Q1"
    assert d["window_quarters"] == 40
    assert d["min_age_quarters"] == 4
    assert isinstance(d["basis"], str) and d["basis"]
    assert "40" in d["basis"] and "4" in d["basis"]


def test_append_first_print_adds_the_newest_quarter_once(tmp_path):
    p = tmp_path / "f.csv"
    p.write_text("quarter,qoq_pct,release_date,source\n2026Q1,0.2743,2026-06-03,abs\n")
    lv = _levels("2026Q1", [0.4195])                      # 2026Q1 level, 2026Q2 level
    # ABS printed 2026Q2 on 2026-09-02; the weekly job runs 2026-09-07
    assert append_first_print(p, lv, asof="2026-09-07") == "2026Q2"
    s = load_first_release(p)
    assert s[pd.Timestamp("2026-06-01")] == pytest.approx(0.4195, abs=1e-4)
    assert p.read_text().splitlines()[-1].startswith("2026Q2,0.4195,2026-09-02,abs_5206.0_live_2026-09-07")
    assert append_first_print(p, lv, asof="2026-09-14") is None      # already there


def test_append_first_print_refuses_a_stale_print(tmp_path, capsys):
    """A quarter first seen 80+ days after its release may already be revised."""
    p = tmp_path / "f.csv"
    p.write_text("quarter,qoq_pct,release_date,source\n2026Q1,0.2743,2026-06-03,abs\n")
    lv = _levels("2026Q1", [0.4195])
    late = str((pd.Timestamp("2026-09-02") + pd.Timedelta(days=MAX_FIRST_PRINT_AGE_DAYS + 1)).date())
    assert append_first_print(p, lv, asof=late) is None
    assert "2026Q2" in capsys.readouterr().out
    assert len(p.read_text().splitlines()) == 2
