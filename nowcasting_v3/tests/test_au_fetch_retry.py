"""Retry behaviour around `build.fetch_vintage`, no network involved.

`_with_retries` is what stood between the 10 September 2026 quarterly
re-estimate and a single transient ABS download failure -- see the comment
above it in `nyfed/au/build.py`. These tests patch `build._SLEEP` so a retry
sequence runs instantly instead of waiting the real 30 s / 90 s.
"""

import pytest

from nyfed.au import build
from nyfed.au.sources import AU_SERIES


def _recording_sleep(monkeypatch):
    calls: list[int] = []
    monkeypatch.setattr(build, "_SLEEP", calls.append)
    return calls


def test_with_retries_succeeds_after_two_failures(monkeypatch):
    calls = _recording_sleep(monkeypatch)
    attempts = {"n": 0}

    def flaky():
        attempts["n"] += 1
        if attempts["n"] <= 2:
            raise RuntimeError(f"boom {attempts['n']}")
        return "sentinel"

    result = build._with_retries("thing", flaky)

    assert result == "sentinel"
    assert attempts["n"] == 3
    assert calls == [30, 90]


def test_with_retries_reraises_after_exhausting_attempts(monkeypatch):
    calls = _recording_sleep(monkeypatch)

    def always_fails():
        raise RuntimeError("still broken")

    with pytest.raises(RuntimeError, match="still broken"):
        build._with_retries("thing", always_fails)

    assert calls == [30, 90]


def test_fetch_vintage_retries_a_failing_series_fetch(monkeypatch):
    _recording_sleep(monkeypatch)
    calls = {"n": 0}
    one_source = (AU_SERIES[0],)

    def fake_fetch_one(source):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient")
        return "series-data"

    monkeypatch.setattr(build, "_fetch_one", fake_fetch_one)
    monkeypatch.setattr(build, "fetch_deflator_sources", lambda: {})

    vintage = build.fetch_vintage(sources=one_source)

    assert vintage.series == {AU_SERIES[0].key: "series-data"}
    assert vintage.deflator_sources == {}
    assert calls["n"] == 2
