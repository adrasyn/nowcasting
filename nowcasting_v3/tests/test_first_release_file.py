"""The committed first-release GDP file: shape, coverage and provenance.

Two sources are merged. The RBA's RDP 2024-04 file carries first-release growth
1959Q4-2022Q2 (Lee, Olekalns, Shields and Wang's real-time database, carried
forward by the RBA). The ABS vintage spreadsheets carry 2019Q2 onward, parsed
in docs/measurements/2026-09-09-gdp-first-release-vs-latest-2019q2-2026q2.csv.
Where both exist the ABS figure is kept, and the two must agree: they are the
same number read from two places.
"""
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
CSV = REPO / "data" / "gdp_first_release.csv"
RBA = REPO.parent / "nowcasting_v2/rba_paper/content/Data/rt_dgdp_qtr.csv"


def _load() -> pd.DataFrame:
    return pd.read_csv(CSV, dtype={"quarter": str, "source": str})


def test_the_file_exists_with_the_agreed_columns():
    f = _load()
    assert list(f.columns) == ["quarter", "qoq_pct", "release_date", "source"]


def test_quarters_are_consecutive_from_1959q4_and_reach_2026q2():
    f = _load()
    idx = pd.PeriodIndex(f["quarter"], freq="Q")
    assert str(idx[0]) == "1959Q4"
    assert str(idx[-1]) >= "2026Q2"
    diffs = [(b - a).n for a, b in zip(idx[:-1], idx[1:])]
    assert set(diffs) == {1}, f"non-consecutive quarters at {[str(q) for q, d in zip(idx[1:], diffs) if d != 1]}"


def test_the_abs_and_rba_sources_agree_where_they_overlap():
    f = _load().set_index("quarter")
    rba = pd.read_csv(RBA)
    rba.index = pd.to_datetime(rba["Date"], dayfirst=True).dt.to_period("Q").astype(str)
    overlap = [q for q in f.index if f.loc[q, "source"].startswith("abs_") and q in rba.index]
    assert len(overlap) >= 13, overlap
    for q in overlap:
        assert abs(float(f.loc[q, "qoq_pct"]) - float(rba.loc[q, "RT-DGDP-QTR"])) < 0.02, q


def test_known_first_prints():
    """2023Q1 printed at +0.2 (0.2332 from the levels); 2026Q1 at +0.3 (0.2743)."""
    f = _load().set_index("quarter")
    assert abs(float(f.loc["2023Q1", "qoq_pct"]) - 0.2332) < 1e-3
    assert abs(float(f.loc["2026Q1", "qoq_pct"]) - 0.2743) < 1e-3
    assert f.loc["2023Q1", "source"] == "abs_5206.0_mar-2023"
    assert f.loc["2010Q1", "source"] == "rba_rdp_2024_04"
