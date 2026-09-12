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
    P_E,
    P_F,
    Panel,
    build_panel,
    collapse_floor,
    fetch_vintage,
    load_vintage,
    months_with_data,
    pad_to_next_quarter,
    target_periods,
)
from nyfed.au.bias_correction import load_misses, rolling_miss
from nyfed.au.clock import today_str
from nyfed.au.emit import (annualised_to_qoq, gdp_release_date,
                           migrate_history_runs_v3, nowcast_payload,
                           refusal_payload)
from nyfed.au.first_release import load_first_release
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
    # `now` is an absolute instant and stays UTC (it carries its offset).
    # The AS-OF DATE is Sydney's: the job fires Sunday evening UTC, which is
    # Monday morning in Sydney, and every vintage is keyed on the Monday.
    now = datetime.now(UTC).isoformat(timespec="seconds")
    asof = today_str()
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
    gdp = vintage.series["gdp"].dropna()
    print(f"panel {panel.Y.shape[0]}x{panel.Y.shape[1]}, "
          f"{panel.dates[0].date()}..{panel.dates[-1].date()}"
          f"{f' (+{n_pad} forecast month(s))' if n_pad else ''}", flush=True)
    if str(panel.dates[0].date()) != meta["panel_first"]:
        print(f"PANEL START MOVED: estimate begins {meta['panel_first']}, this "
              f"panel begins {panel.dates[0].date()}. The saved latents are "
              "indexed by month and would be misaligned. Re-estimate.",
              file=sys.stderr)
        return 1

    # THE SAVED FIT MUST HAVE LEARNED THE SERIES THIS PANEL CARRIES.
    # `build_panel` and `estimate_au.py` moved to the first-print target on
    # 2026-09-10; the estimate file's shape did not change, so a fit made on
    # the revised target loads without complaint and produces a number that
    # means something else entirely -- a nowcast of the revised figure on a
    # page that says it nowcasts the first print. Nothing downstream can see
    # the difference, so it is refused here.
    #
    # EXIT 1, NOT A `refused` PAYLOAD. A stale feed is a fact about this week
    # and the site renders it; this is a deployment error -- the quarterly job
    # has not been re-run since the target changed -- and it is fixed by
    # running `tools/estimate_au.py`, not by waiting a week.
    #
    # Estimates saved before 2026-09-10 carry no `target` key at all, and every
    # one of them was fitted on the revised target, so that is what a missing
    # key means.
    est_target = meta.get("target", "latest")
    if est_target != panel.target:
        print(f"TARGET MISMATCH: the saved estimate was fitted on the "
              f"{est_target!r} GDP target and this panel carries "
              f"{panel.target!r}. The parameters describe a different quantity, "
              "and nothing further down would show it. Re-run "
              "tools/estimate_au.py to fit the quarterly estimate on "
              f"{panel.target!r}.", file=sys.stderr)
        return 1

    # ---- the bias correction (may refuse) --------------------------------
    # THE MODEL STILL RUNS HIGH. It is trained on first prints now, so no mean
    # revision is subtracted any more -- that would double-count. What is left
    # is the model's own bias against the quantity it predicts: +0.20pp with
    # t = 3.9 over the first-print backtest. The published figure takes off the
    # mean of the last eight printed quarters' misses, rolling, from
    # `data/first_print_misses.csv`. That file was brought up to date earlier in
    # the same weekly job by `tools/record_first_print.py`, so a quarter the ABS
    # printed last Wednesday is already in the window this reads.
    #
    # A MISSING ESTIMATE IS A REFUSAL, not a degrade. Publishing the raw model
    # would put an uncorrected figure on a page whose `basis` says the bias has
    # been taken off — the wrong number under the right name, which is worse
    # than no number, because nothing on the page would show it had changed
    # meaning. Refusing is the behaviour v3 exists for.
    #
    # ANY failure, not just the anticipated ones. The misses file is appended by
    # the weekly job and hand-edited when a quarter is missed, so a bad edit
    # surfaces as a KeyError or a ParserError just as easily as the ValueError
    # `rolling_miss` raises on a thin sample — and letting it kill the runner
    # here would write no payload at all, not even a refusal.
    try:
        correction = rolling_miss(load_misses(), asof=asof)
        print(f"bias correction {correction.pp:+.4f}pp over {correction.n} printed "
              f"quarters {correction.first_quarter}..{correction.last_quarter}",
              flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"no bias correction: {exc}", file=sys.stderr)
        write(refusal_payload(reason="no bias estimate",
                              detail=str(exc)[:400], generated_at=now, asof=asof))
        return 0

    # ---- the state space, from the saved fit -----------------------------
    spec = load_spec(SPEC_PATH)
    n, n_f = spec.blocks.shape
    param = map_parameter(est["param_vec"], (n, n_f, P_F, P_E))
    loading = float(param.Lambda[panel.i_now, 0])
    # The floor follows the panel's target, and the check above has already
    # established that the estimate was fitted on the same one.
    floor = collapse_floor(panel.target)
    if loading <= floor:
        write(refusal_payload(
            reason="collapsed model",
            detail=(f"the saved estimate has {panel.series_id[panel.i_now]}'s "
                    f"loading on the Global factor at {loading:.3f}, at or below "
                    f"the {floor} floor for the {panel.target} target"),
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
        # THE PUBLISHED FIGURE, point and bands alike, so the record can be
        # scored directly against the ABS's first print and the evolution chart
        # plots the same quantity the page headlines. `target` travels with the
        # row because the migration keys on printed quarters, not on schema
        # stamps, and a row has to be able to say for itself which model wrote
        # it.
        model_k = float(annualised_to_qoq(ann[k]))
        written.append({
            "run_date": asof, "target_quarter": lab,
            "kind": "nowcast" if k == 0 else "forecast",
            "qoq_growth_pct": round(model_k - correction.pp, 4),
            "model_qoq_growth_pct": round(model_k, 4),
            "bias_correction_pp": round(correction.pp, 4),
            "target": "first_print",
            "ci_95_low": round(qk[0] - correction.pp, 4),
            "ci_68_low": round(qk[1] - correction.pp, 4),
            "ci_68_high": round(qk[2] - correction.pp, 4),
            "ci_95_high": round(qk[3] - correction.pp, 4),
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
                    "qoq_growth_pct": round(pt_k - correction.pp, 4),
                    "model_qoq_growth_pct": round(pt_k, 4),
                    "bias_correction_pp": round(correction.pp, 4),
                    "target": "first_print",
                    "ci_95_low": round(qb[0] - correction.pp, 4),
                    "ci_68_low": round(qb[1] - correction.pp, 4),
                    "ci_68_high": round(qb[2] - correction.pp, 4),
                    "ci_95_high": round(qb[3] - correction.pp, 4),
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

    vintages = _record(written, labels, asof)

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

    payload = nowcast_payload(
        panel=panel, horizons=horizons, draws=draws,
        prev_level=float(gdp.iloc[-1]), prev_quarter=_quarter(gdp.index[-1]),
        vintages=vintages, next_gdp_release_date=release,
        generated_at=now, asof=asof, gdp_global_loading=loading,
        collapse_floor=floor,
        n_gs=meta["n_gs"], n_burn=meta["n_burn"], seed=SEED,
        months_with_data=months, correction=correction)
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


def _record(entries: list[dict], labels: list[str], asof: str) -> list[dict]:
    """Merge new runs into the standing record and hand back the live targets'.

    The record is the single source for both the evolution chart and, once the
    ABS prints a quarter, this model's LIVE score for it as distinct from the
    backtested rows. Keyed on run date, so re-running a Monday corrects that
    Keyed on (run date, target quarter), NOT run date alone. A run now writes a
    row per horizon -- the nowcast and the next quarter's forecast share a run
    date -- so de-duplicating on the date by itself would let each row evict the
    other and leave whichever happened to be written last.
    """
    hist = {"schema": "v3-history-3", "runs": []}
    if HISTORY.is_file():
        try:
            hist = json.loads(HISTORY.read_text())
        except json.JSONDecodeError:
            print(f"{HISTORY.name} unreadable; starting a new record", flush=True)
    # THE WHOLE RECORD MOVES WITH THE MODEL. Rows written before 2026-09-10 came
    # from a model fitted on the REVISED vintage and corrected by a forty-year
    # mean ABS revision. A printed quarter's rows are kept exactly as they are:
    # they record what the site published on the mornings before each release,
    # and the track record scores them. A quarter the ABS has not printed yet is
    # still live on the evolution chart, so its old rows are dropped rather than
    # left to share a line with the new model's -- the step between two
    # different quantities reads as news rather than as a change of definition.
    # `--backfill` rebuilds those weeks from the new model.
    #
    # PRINTED MEANS THE ABS HAS RELEASED IT. `load_first_release` holds a row
    # per printed quarter, and `gdp_release_date` says when each went out, so a
    # quarter counts only once its release date has passed on this run's date.
    # Stamping the new schema makes the migration one-way: a `v3-history-3` file
    # is left alone, or every Monday would drop the quarter in flight.
    was = hist.get("schema")
    if was != "v3-history-3":
        labels_out = [_quarter(ts) for ts in load_first_release().dropna().index]
        printed = {lab for lab in labels_out
                   if (gdp_release_date(lab) or "9999-99-99") <= asof}
        before = len(hist["runs"])
        hist["runs"] = migrate_history_runs_v3(hist["runs"], printed)
        hist["schema"] = "v3-history-3"
        print(f"migrated {HISTORY.name} from {was!r}: kept "
              f"{len(hist['runs'])} row(s) for quarters the ABS has printed, "
              f"dropped {before - len(hist['runs'])} belonging to the superseded "
              "model (--backfill rebuilds them)", flush=True)
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
