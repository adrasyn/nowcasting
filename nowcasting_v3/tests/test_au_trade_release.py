"""Trade availability uses the ABS release date, including in recorded replays."""
import json
from pathlib import Path

import pandas as pd
import pytest

from nyfed.au import build

FIXTURE = Path(__file__).parent / "fixtures" / "au" / "trade_release_aug2026.html"


def trade_vintage():
    series = {key: pd.Series(values,
                            index=pd.to_datetime(["2026-07-01", "2026-08-01"]))
              for key, values in {"exports": [45726., 47433.],
                                  "imports": [-44375., -46938.]}.items()}
    return build.Vintage(series, {}, release_dates={
        key: {"2026-08-01": "2026-10-01"} for key in series
    })


def test_trade_enters_on_its_actual_release_date_and_not_before():
    vintage = trade_vintage()
    for key in ("exports", "imports"):
        assert vintage.as_of("2026-09-30").series[key].index[-1] == pd.Timestamp("2026-07-01")
        assert vintage.as_of("2026-10-01").series[key].index[-1] == pd.Timestamp("2026-08-01")
        assert vintage.as_of("2026-10-05").series[key].index[-1] == pd.Timestamp("2026-08-01")
    assert vintage.as_of("2026-10-05").release_dates == vintage.release_dates


def test_older_recordings_without_release_dates_keep_the_conservative_cut():
    vintage = trade_vintage()
    legacy = build.Vintage(vintage.series, {})
    assert legacy.as_of("2026-10-05").series["exports"].index[-1] == pd.Timestamp("2026-07-01")


def test_a_delayed_actual_release_is_not_admitted_by_the_earlier_estimate():
    vintage = trade_vintage()
    dates = {key: {"2026-08-01": "2026-10-08"} for key in vintage.series}
    delayed = build.Vintage(vintage.series, {}, release_dates=dates)
    assert delayed.as_of("2026-10-06").series["exports"].index[-1] == pd.Timestamp("2026-07-01")
    assert delayed.as_of("2026-10-08").series["exports"].index[-1] == pd.Timestamp("2026-08-01")


def test_recorded_release_dates_survive_save_load_and_first_print_build(tmp_path, monkeypatch):
    vintage = build.load_vintage(Path(__file__).parent / "fixtures" / "au" / "vintage")
    dates = {"exports": {"2026-06-01": "2026-08-06"}}
    recorded = build.Vintage(vintage.series, vintage.deflator_sources,
                             recorded_at=vintage.recorded_at, release_dates=dates)
    build.save_vintage(recorded, tmp_path)
    loaded = build.load_vintage(tmp_path)
    assert loaded.release_dates == dates
    assert json.loads((tmp_path / "manifest.json").read_text())["release_dates"] == dates
    # The first-print GDP substitution must not drop the trade release dates.
    original = build.Vintage.as_of
    def check_dates(self, asof):
        assert self.release_dates == dates
        return original(self, asof)
    monkeypatch.setattr(build.Vintage, "as_of", check_dates)
    panel = build.build_panel(asof="2026-08-06", vintage=loaded)
    row = panel.series_id.index("exports")
    assert pd.notna(panel.Y[row, panel.dates.get_loc("2026-06-01")])


def test_official_abs_metadata_pairs_reference_month_with_publication_date():
    from nyfed.au.fetch_abs import parse_trade_release
    assert parse_trade_release(FIXTURE.read_text()) == ("2026-08-01", "2026-10-01")


@pytest.mark.parametrize("html", ["<html></html>",
    '<meta name="dcterms.isPartOf" content="6202.0">',
    '<meta name="dcterms.isPartOf" content="5368.0"><meta name="dcterms.temporal" content="August 2026"><meta name="dcterms.issued" content="Thu, 01/07/2026 - 11:30">'])
def test_bad_or_wrong_catalogue_metadata_fails_loudly(html):
    from nyfed.au.fetch_abs import parse_trade_release
    with pytest.raises(ValueError):
        parse_trade_release(html)


def test_live_fetch_attaches_one_publication_date_to_both_trade_series(monkeypatch):
    from nyfed.au.sources import AU_SERIES
    sources = tuple(s for s in AU_SERIES if s.key in ("exports", "imports"))
    series = trade_vintage().series
    monkeypatch.setattr(build, "_fetch_one", lambda source: series[source.key])
    monkeypatch.setattr(build, "fetch_deflator_sources", lambda: {})
    monkeypatch.setattr(build, "fetch_trade_release", lambda: ("2026-08-01", "2026-10-01"))
    assert build.fetch_vintage(sources).release_dates == trade_vintage().release_dates


def test_live_fetch_refuses_mismatched_release_page_and_spreadsheet(monkeypatch):
    from nyfed.au.sources import AU_SERIES
    sources = tuple(s for s in AU_SERIES if s.key == "exports")
    monkeypatch.setattr(build, "_fetch_one", lambda source: trade_vintage().series["exports"])
    monkeypatch.setattr(build, "fetch_deflator_sources", lambda: {})
    monkeypatch.setattr(build, "fetch_trade_release", lambda: ("2026-09-01", "2026-11-05"))
    with pytest.raises(ValueError, match="release.*spreadsheet"):
        build.fetch_vintage(sources)


def test_indicator_display_uses_the_same_actual_trade_date(tmp_path, monkeypatch):
    from tools import emit_indicators
    monkeypatch.setattr(emit_indicators, "fetch_vintage", trade_vintage)
    monkeypatch.setattr(emit_indicators, "OUT", tmp_path / "indicators.json")
    monkeypatch.setattr(emit_indicators.sys, "argv", ["emit_indicators.py"])
    assert emit_indicators.main() == 0
    rows = json.loads((tmp_path / "indicators.json").read_text())["indicators"]
    assert len(rows) == 2
    assert all(r["last_release_date"] == "2026-10-01" for r in rows)
