"""Weekly: nowcast from the saved estimate and write `data/latest_v3.json`.

THIS NO LONGER RE-ESTIMATES. `tools/estimate_au.py` does that quarterly and
saves the fitted state; this loads it and runs the filter over whatever data has
arrived since. That is the NY Fed's own cadence ("parameters are re-estimated
every quarter ... the Staff Nowcast is updated each Friday", Staff Nowcast 2.0
p2) and it is what makes a weekly GitHub job feasible at all: re-estimating took
~95 minutes locally and would have been hours on a hosted runner, every week, to
redo work the model does not need redone weekly.

A REFUSAL IS A SUCCESSFUL RUN. `check_freshness` refuses a stale feed and the
collapse floor refuses a model that has left GDP disconnected from the panel.
Both write `status: "refused"` and exit 0, because the site renders a refusal
rather than showing last week's number as if it were current. Exit 1 is for a
genuine fault: a host that will not answer, a missing estimate, a bug here.

    cd nowcasting_v3
    caffeinate -i .venv/bin/python -u tools/run_au_nowcast.py            # live
    caffeinate -i .venv/bin/python -u tools/run_au_nowcast.py --vintage  # replay
    ... --quick     # fewer density draws, for checking the wiring
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from nyfed.au.build import (
    COLLAPSED_GLOBAL_LOADING,
    P_E,
    P_F,
    Panel,
    build_panel,
    fetch_vintage,
    load_vintage,
    target_periods,
)
from nyfed.au.emit import (annualised_to_qoq, gdp_release_date,
                           nowcast_payload, refusal_payload)
from nyfed.au.freshness import StaleSeriesError
from nyfed.au.restrict import build_restrict
from nyfed.au.sources import AU_SERIES, SPEC_PATH
from nyfed.model import Latent, construct_ssm
from nyfed.nowcast import density_nowcast, point_nowcast
from nyfed.parameters import map_parameter
from nyfed.spec import load_spec

REPO = Path(__file__).resolve().parents[1]
SITE_DATA = REPO.parent / "data"
ESTIMATE = REPO / "state" / "au_estimate.npz"
HISTORY = REPO.parent / "data" / "nowcast_history_v3.json"

N_DENSITY = 1_250
SEED = 4

# How stale a saved estimate may be before this refuses to use it. The model is
# meant to be re-estimated quarterly; a little over two quarters means the
# quarterly job has failed twice without anyone noticing, and the parameters are
# describing an economy two GDP releases ago.
MAX_ESTIMATE_AGE_DAYS = 200


def _quarter(ts) -> str:
    return f"{ts.year} Q{(ts.month - 1) // 3 + 1}"


def _fit_latents(sigma: np.ndarray, s: np.ndarray, n_cols: int):
    """Stretch or trim the saved latents onto this week's panel.

    They are (n_f + n, T) over the ESTIMATION panel's months, and the weekly
    panel is longer. Repeating the last column is a starting value the filter
    refines, not an imputation, and it is the same treatment the evolution
    chart uses when replaying earlier weeks.
    """
    pad = n_cols - sigma.shape[1]
    if pad > 0:
        sigma = np.concatenate([sigma, np.repeat(sigma[:, -1:], pad, axis=1)], axis=1)
        s = np.concatenate([s, np.repeat(s[:, -1:], pad, axis=1)], axis=1)
    elif pad < 0:
        sigma, s = sigma[:, :n_cols], s[:, :n_cols]
    return sigma, s


def pad_to_next_quarter(panel) -> int:
    """Extend the panel with empty months so the quarter AFTER the current
    target has a column, and return how many were added.

    `target_periods` steps three months at a time from the quarter after GDP's
    last observation and stops at the panel's last column, so how many horizons
    come back is a property of where the panel ENDS. `build_panel` ends it at
    the as-of date, which through most of a quarter falls short of the next
    quarter's aligned column -- on 2026-08-31 the panel ended 2026-08 and the
    only horizon was 2026 Q2, a quarter that had already closed nine weeks
    earlier. Two months in every three the page led with a quarter nobody could
    learn anything more about.

    The added columns are all-NaN. The filter treats a missing observation as
    missing, which is exactly what a quarter that has not happened yet is, so
    this buys a forecast rather than fabricating an input. It also leaves the
    NOWCAST untouched: padding moved 2026 Q2 by less than a basis point.

    PADDING HAPPENS HERE, NOT IN `build_panel`. The estimation path and the
    Plan C backtest both call `build_panel`, and neither wants a panel that
    runs past its data.
    """
    obs = np.flatnonzero(np.isfinite(panel.Y[panel.i_now]))
    if obs.size == 0:
        return 0
    need = int(obs[-1]) + 7          # arange(obs+3, T, 3) has to reach obs+6
    pad = need - panel.Y.shape[1]
    if pad <= 0:
        return 0
    panel.Y = np.hstack([panel.Y, np.full((panel.Y.shape[0], pad), np.nan)])
    panel.dates = panel.dates.append(
        pd.date_range(panel.dates[-1] + pd.DateOffset(months=1),
                      periods=pad, freq="MS"))
    return pad


def months_with_data(panel, t: int) -> int:
    """How many of the three months ending at column ``t`` carry any series."""
    lo = max(0, t - 2)
    return int(np.isfinite(panel.Y[:, lo:t + 1]).any(axis=0).sum())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vintage", action="store_true")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--backfill", action="store_true",
                    help="also recompute this quarter's earlier weeks, "
                         "for a chart that has no history yet")
    ap.add_argument("--estimate", default=str(ESTIMATE))
    ap.add_argument("--out", default=str(SITE_DATA / "latest_v3.json"))
    args = ap.parse_args()

    started = time.perf_counter()
    now = datetime.now(UTC).isoformat(timespec="seconds")
    asof = str(pd.Timestamp.now(tz="UTC").date())
    out = Path(args.out)

    def write(payload: dict) -> None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2) + "\n")
        print(f"wrote {out}  status={payload['status']}", flush=True)

    # ---- the saved estimate ----------------------------------------------
    est_path = Path(args.estimate)
    if not est_path.is_file():
        print(f"NO ESTIMATE at {est_path} — run tools/estimate_au.py first",
              file=sys.stderr)
        return 1
    est = np.load(est_path)
    meta = json.loads(str(est["meta"]))
    age = (pd.Timestamp(asof) - pd.Timestamp(meta["asof"])).days
    print(f"estimate from {meta['asof']} ({age}d old, {meta['n_gs']} draws)",
          flush=True)
    if age > MAX_ESTIMATE_AGE_DAYS:
        print(f"ESTIMATE IS {age} DAYS OLD (limit {MAX_ESTIMATE_AGE_DAYS}) — "
              "the quarterly job has not run; refusing rather than publishing "
              "from stale parameters", file=sys.stderr)
        return 1

    # ---- fetch -----------------------------------------------------------
    if args.vintage:
        print("replaying tests/fixtures/au/vintage", flush=True)
        vintage = load_vintage(REPO / "tests/fixtures/au/vintage")
        asof = str(pd.Timestamp(vintage.recorded_at).date())
    else:
        print("fetching live (ABS x2, RBA, v2 CSVs)...", flush=True)
        try:
            vintage = fetch_vintage()
        except Exception as exc:                                # noqa: BLE001
            print(f"FETCH FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1

    # ---- build (may refuse) ---------------------------------------------
    try:
        panel = build_panel(asof=asof, vintage=vintage)
    except StaleSeriesError as exc:
        names = {s.key: s.name for s in AU_SERIES}

        def _age(key: str, days: int, budget: int) -> str:
            label = names.get(key, key)
            if days >= 10 ** 6:
                return f"{label} has no observations at all"
            return f"{label} is {days} days old, against a {budget}-day budget"

        write(refusal_payload(reason="stale input",
                              detail="; ".join(_age(k, a, b) for k, a, b in exc.stale),
                              generated_at=now, asof=asof))
        return 0
    except ValueError as exc:
        write(refusal_payload(reason="panel could not be assembled",
                              detail=str(exc)[:400], generated_at=now, asof=asof))
        return 0

    n_pad = pad_to_next_quarter(panel)
    print(f"panel {panel.Y.shape[0]}x{panel.Y.shape[1]}, "
          f"{panel.dates[0].date()}..{panel.dates[-1].date()}"
          f"{f' (+{n_pad} forecast month(s))' if n_pad else ''}", flush=True)
    if str(panel.dates[0].date()) != meta["panel_first"]:
        print(f"PANEL START MOVED: estimate begins {meta['panel_first']}, this "
              f"panel begins {panel.dates[0].date()}. The saved latents are "
              "indexed by month and would be misaligned. Re-estimate.",
              file=sys.stderr)
        return 1

    # ---- the state space, from the saved fit -----------------------------
    spec = load_spec(SPEC_PATH)
    n, n_f = spec.blocks.shape
    param = map_parameter(est["param_vec"], (n, n_f, P_F, P_E))
    loading = float(param.Lambda[panel.i_now, 0])
    if loading <= COLLAPSED_GLOBAL_LOADING:
        write(refusal_payload(
            reason="collapsed model",
            detail=(f"the saved estimate has {panel.series_id[panel.i_now]}'s "
                    f"loading on the Global factor at {loading:.3f}, at or below "
                    f"the {COLLAPSED_GLOBAL_LOADING} floor"),
            generated_at=now, asof=asof))
        return 0

    sigma, s = _fit_latents(est["sigma"], est["s"], panel.Y.shape[1])
    restrict = build_restrict(panel, spec, p_f=P_F)
    ssm = construct_ssm(param, Latent(sigma=sigma, s=s), restrict)

    # ---- nowcast ---------------------------------------------------------
    t_now = target_periods(panel)
    months = [months_with_data(panel, int(t)) for t in t_now]
    loc = float(panel.y_location[panel.i_now, 0])
    scl = float(panel.y_scale[panel.i_now, 0])
    n_draw = N_DENSITY if not args.quick else 200
    rng = np.random.default_rng(SEED)

    point = point_nowcast(panel.Y, panel.Y, ssm, ssm, panel.i_now, t_now)
    ann = [loc + scl * float(point.nowcast[3, k]) for k in range(len(t_now))]
    horizons = [(_quarter(panel.dates[t]), a) for t, a in zip(t_now, ann)]
    draws = np.vstack([
        loc + scl * density_nowcast(panel.Y, ssm, panel.i_now, t_now, rng)
        for _ in range(n_draw)])

    # ---- this week's figure, appended to the standing record --------------
    # NOT A RECOMPUTE OF THE WHOLE QUARTER. An earlier draft rebuilt every week
    # on each run, which was wrong twice over. It used TODAY's state space for
    # weeks actually produced with the PREVIOUS quarter's parameters, so it did
    # not reproduce history — it fabricated a tidier version, and every point
    # would shift whenever the quarterly re-estimate landed. And by baking
    # today's revisions into every point equally it flattened the very movement
    # the chart exists to show.
    #
    # Each week's figure is what this model said with the data it had. Written
    # once, not revisited. `--backfill` recomputes a quarter's earlier weeks for
    # a chart with no history yet, and marks what it writes, because those
    # points were never published on the dates they carry.
    tgt = panel.dates[t_now[0]]
    label = _quarter(tgt)
    labels = [_quarter(panel.dates[int(t)]) for t in t_now]
    # The last month CARRYING DATA. `dates[-1]` is now a padded forecast month.
    seen = np.flatnonzero(np.isfinite(panel.Y).any(axis=0))
    dthru = str(panel.dates[int(seen[-1])].date())[:7] if seen.size else asof[:7]
    written = []
    for k, lab in enumerate(labels):
        # A FORECAST QUARTER WITH NO DATA IN IT IS NOT A VINTAGE.
        # `target_periods` will happily reach a quarter that has not started,
        # and the model answers: it conditions on nothing and returns the trend
        # anchor. Recorded weekly, that draws a flat line on the evolution chart
        # that looks like a settled view and is actually the absence of one --
        # 2026 Q3 sat at +0.60 to +0.67 for the ten weeks before any July
        # indicator existed, then stepped to +0.76 the week one did.
        #
        # The record is meant to show an estimate MOVING AS DATA ARRIVES, so it
        # starts when data does. The nowcast is exempt: it is the page's primary
        # number, and a nowcast quarter with no data at all is a fault to
        # surface, not a row to drop.
        if k > 0 and months[k] == 0:
            print(f"  {lab}: no month of data yet, not recorded", flush=True)
            continue
        qk = np.nanpercentile(annualised_to_qoq(draws[:, k]),
                              [2.5, 16, 84, 97.5])
        written.append({
            "run_date": asof, "target_quarter": lab,
            "kind": "nowcast" if k == 0 else "forecast",
            "qoq_growth_pct": round(float(annualised_to_qoq(ann[k])), 4),
            "ci_95_low": round(qk[0], 4), "ci_68_low": round(qk[1], 4),
            "ci_68_high": round(qk[2], 4), "ci_95_high": round(qk[3], 4),
            "data_through": dthru, "months_with_data": months[k],
            "estimate_asof": meta["asof"],
        })

    if args.backfill:
        print(f"backfilling earlier weeks of {label}...", flush=True)
        # FROM THE QUARTER'S FIRST MONTH, not the target column's. `tgt` is the
        # aligned column, which is the quarter's LAST month, so starting there
        # began the record two thirds of the way through the quarter's life:
        # 2026 Q2's chart started at 93 days to release when its first indicator
        # had landed at about 118. The zero-data guard below trims whatever
        # front of the window has no observation in the quarter yet, so widening
        # it costs nothing but the weeks that turn out to be real.
        q_start = pd.Timestamp(tgt.year, 3 * ((tgt.month - 1) // 3) + 1, 1)
        for d0 in pd.date_range(q_start, pd.Timestamp(asof), freq="W-MON"):
            if str(d0.date()) >= asof:
                continue
            try:
                pv = build_panel(asof=str(d0.date()), vintage=vintage)
            except Exception:                                   # noqa: BLE001
                continue
            Yv = np.full_like(panel.Y, np.nan)
            k = min(pv.Y.shape[1], panel.Y.shape[1])
            Yv[:, :k] = pv.Y[:, :k]
            vp = Panel(Y=Yv, y_location=panel.y_location, y_scale=panel.y_scale,
                       dates=panel.dates, series_id=panel.series_id,
                       i_now=panel.i_now)
            pv_pt = point_nowcast(vp.Y, vp.Y, ssm, ssm, vp.i_now, t_now)
            pv_draws = np.vstack([
                loc + scl * density_nowcast(vp.Y, ssm, vp.i_now, t_now, rng)
                for _ in range(n_draw)])
            pv_seen = pd.DatetimeIndex(pv.dates)[np.isfinite(pv.Y).any(axis=0)]
            shown = []
            for k, lab in enumerate(labels):
                # EVERY horizon, including the nowcast. The live path exempts
                # the nowcast because a current quarter with no data at all is a
                # fault worth seeing on the page; a REPLAY of a week before the
                # quarter had any data is just the anchor, and drawing a flat
                # line of those is the thing this guard exists to stop.
                if months_with_data(vp, int(t_now[k])) == 0:
                    continue
                pt_k = float(annualised_to_qoq(
                    loc + scl * float(pv_pt.nowcast[3, k])))
                qb = np.nanpercentile(annualised_to_qoq(pv_draws[:, k]),
                                      [2.5, 16, 84, 97.5])
                written.append({
                    "run_date": str(d0.date()), "target_quarter": lab,
                    "kind": "nowcast" if k == 0 else "forecast",
                    "qoq_growth_pct": round(pt_k, 4),
                    "ci_95_low": round(qb[0], 4), "ci_68_low": round(qb[1], 4),
                    "ci_68_high": round(qb[2], 4), "ci_95_high": round(qb[3], 4),
                    "data_through": str(pv_seen[-1].date())[:7],
                    "months_with_data": months_with_data(vp, int(t_now[k])),
                    "estimate_asof": meta["asof"], "backfilled": True,
                })
                shown.append(f"{lab} {pt_k:+.3f}")
            # A week where every horizon was skipped wrote nothing, and saying
            # "(backfilled)" against an empty list reads as though it did.
            print(f"  {d0.date()}  "
                  + ("  ".join(shown) + "  (backfilled)" if shown
                     else "no quarter has data yet, nothing recorded"),
                  flush=True)

    vintages = _record(written, labels)

    # THE FETCHED DATE IS ONLY USED IF IT NAMES THIS TARGET'S QUARTER.
    # `data/latest.json` belongs to the R pipeline, which runs 90 minutes before
    # this one and can fail on its own. When it does, its `next_gdp_release_date`
    # stays on the quarter the ABS has just printed while this model has already
    # rolled forward, and the page ends up counting down to the wrong release —
    # every vintage lands outside the chart's domain and it renders empty.
    #
    # The scraped date is still preferred where it agrees, because the ABS moves
    # a release occasionally and `gdp_release_date` only knows the rule. Agreeing
    # on the MONTH is the test: a reschedule shifts a release by days within its
    # month, never into another quarter.
    release = None
    site_latest = SITE_DATA / "latest.json"
    if site_latest.is_file():
        fetched = json.loads(site_latest.read_text()).get("next_gdp_release_date")
        expected = gdp_release_date(labels[0]) if labels else None
        if fetched and expected and fetched[:7] == expected[:7]:
            release = fetched
        else:
            release = expected
            if fetched:
                print(f"  release date {fetched} is not in {labels[0]}'s release "
                      f"month; using the scheduling rule ({expected})", flush=True)

    gdp = vintage.series["gdp"].dropna()
    payload = nowcast_payload(
        panel=panel, horizons=horizons, draws=draws,
        prev_level=float(gdp.iloc[-1]), prev_quarter=_quarter(gdp.index[-1]),
        vintages=vintages, next_gdp_release_date=release,
        generated_at=now, asof=asof, gdp_global_loading=loading,
        collapse_floor=COLLAPSED_GLOBAL_LOADING,
        n_gs=meta["n_gs"], n_burn=meta["n_burn"], seed=SEED,
        months_with_data=months)
    payload["estimate"] = {"estimated_at": meta["estimated_at"],
                           "asof": meta["asof"], "age_days": age}
    write(payload)

    for h in payload["horizons"]:
        band = (f"  68% [{h['ci_68_low']}, {h['ci_68_high']}]"
                if "ci_68_low" in h else "")
        print(f"  {h['kind']:8s} {h['quarter']}  {h['qoq_growth_pct']:+.2f}%{band}",
              flush=True)
    print(f"total {(time.perf_counter() - started) / 60:.1f} min", flush=True)
    return 0


def _record(entries: list[dict], labels: list[str]) -> list[dict]:
    """Merge new runs into the standing record and hand back the live targets'.

    The record is the single source for both the evolution chart and, once the
    ABS prints a quarter, this model's LIVE score for it as distinct from the
    backtested rows. Keyed on run date, so re-running a Monday corrects that
    Keyed on (run date, target quarter), NOT run date alone. A run now writes a
    row per horizon -- the nowcast and the next quarter's forecast share a run
    date -- so de-duplicating on the date by itself would let each row evict the
    other and leave whichever happened to be written last.
    """
    hist = {"schema": "v3-history-1", "runs": []}
    if HISTORY.is_file():
        try:
            hist = json.loads(HISTORY.read_text())
        except json.JSONDecodeError:
            print(f"{HISTORY.name} unreadable; starting a new record", flush=True)
    # Keyed on what was actually WRITTEN, not on `labels`. A run that declines
    # to record a data-less forecast must leave any existing row for that
    # quarter alone rather than treating its silence as a deletion.
    #
    # AND A BACKFILLED ROW NEVER REPLACES A LIVE ONE. `--backfill` walks every
    # Monday of the quarter, which includes Mondays the weekly job already ran
    # for real. Those rows are what this model actually published on the day,
    # with the data it actually had; a replay reproduces them from TODAY's
    # revisions and parameters and is a different object that happens to sit
    # very close. On 2026-09-01 a backfill silently rewrote the 2026-08-31 live
    # row -- 0.6354 became 0.6362 and the provenance flag flipped -- which is
    # precisely the "fabricated a tidier version" failure the docstring above
    # warns about.
    live = {(r["run_date"], r.get("target_quarter"))
            for r in hist["runs"] if not r.get("backfilled")}
    entries = [e for e in entries
               if not (e.get("backfilled")
                       and (e["run_date"], e["target_quarter"]) in live)]
    keys = {(e["run_date"], e["target_quarter"]) for e in entries}
    runs = [r for r in hist["runs"]
            if (r["run_date"], r.get("target_quarter")) not in keys] + entries
    hist["runs"] = sorted(runs, key=lambda r: (r["run_date"],
                                               r.get("target_quarter", "")))
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    HISTORY.write_text(json.dumps(hist, indent=2) + "\n")
    mine = [r for r in hist["runs"] if r["target_quarter"] in set(labels)]
    counts = "; ".join(
        f"{sum(1 for r in mine if r['target_quarter'] == lab)} for {lab}"
        for lab in labels)
    print(f"recorded {len(entries)} row(s); {HISTORY.name} holds "
          f"{len(hist['runs'])} ({counts})", flush=True)
    return mine


if __name__ == "__main__":
    raise SystemExit(main())
