"""Score the equal-weight v2+v3 combination at both horizons, and calibrate its bands.

WHAT THIS IS FOR. The homepage publishes the average of two models and a band
around it. The average has no posterior of its own -- averaging two point
estimates does not average their distributions -- so the band has to be the
spread of the combination's OWN misses, measured at the horizon the figure was
made at. This tool measures them and writes
`pipeline/seed/ci_params_combo.json`, which is the file
`tools/emit_combination.py` reads every week (it falls back to a pooled
current-quarter band, labelled provisional, when the file is absent).

THE TWO HORIZONS. CURRENT is the earliest quarter the ABS has not printed; NEXT
is the one after it. A next-quarter figure is built on at most one month of
data, so its band must be wider, and the whole point of the second horizon here
is to find out by how much.

WHAT IS PAIRED WITH WHAT. Both backtests run at the same Monday as-ofs, so a
row exists where both models nowcast the SAME QUARTER at the SAME MONDAY. They
can disagree about which quarter that is: v2's backtest replays a flat 60-day
GDP lag and v3's replays the ABS's real release dates, so in the days around a
print v2 has already moved on to the next quarter while v3 has not. Those rows
pair with nothing and are dropped rather than being forced together.

THE ONE-MONTH RULE AT THE NEXT HORIZON. A row is scored only where BOTH models
had at least one month of data in the next quarter, because that is the live
rule: v3 declines to record a forecast with no month behind it, and v2's
U-MIDAS has nothing to forecast from. Without the rule the band would be
calibrated on figures the site never publishes.

WHAT v3's FIGURE IS. The median across seeds 4/13/19 of the retrained
(first-print target) backtest, less the live rolling-miss correction
(`bias_correction.rolling_miss` over the BACKTEST rows of
`data/first_print_misses.csv`, window 8, minimum 4, zero before four prints
exist). Collapsed chains are dropped before the median, as the live job drops
them. The same correction is applied at both horizons, which is what
`run_au_nowcast` does: the correction is the model's recent mean miss, not a
per-horizon parameter. Both the raw and the corrected column are reported, so
the reader can see how much of the combination's accuracy is the correction.

WHAT v2's FIGURE IS. Its published nowcast, uncorrected: v2 ships raw and
correcting it as well was measured (`2026-09-12-v2-v3-weekly-combination.md`)
to remove the residual bias without improving MAE.

THE REGRESSION CHECK. The current horizon must reproduce the single-horizon
measurement already in the doc (MAE 0.129, bias +0.059, n 181, error
correlation +0.05). The tool prints the comparison and says PASS or DIFFERS; a
difference is not automatically an error -- the v3 run behind the doc did not
pad the panel and this one does -- but it is something to explain rather than
to discover later.

USAGE
    .venv/bin/python tools/combination_backtest.py            # write both files
    .venv/bin/python tools/combination_backtest.py --dry-run  # print only
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "nowcasting_v3"))

from nyfed.au.bias_correction import load_misses, rolling_miss  # noqa: E402
from nyfed.au.emit import gdp_release_date  # noqa: E402
from nyfed.au.first_release import load_first_release, quarter_label  # noqa: E402

MEASUREMENTS = ROOT / "docs" / "measurements"
V2_CSV = MEASUREMENTS / "2026-09-12-v2-backtest-initial-estimate-target-two-horizons.csv"
V3_CSVS = [MEASUREMENTS / f"2026-09-12-v3-weekly-two-horizons-seed{s}.csv"
           for s in (4, 13, 19)]
OUT_CSV = MEASUREMENTS / "2026-09-12-v2-v3-weekly-combination-two-horizons.csv"
OUT_PARAMS = ROOT / "pipeline" / "seed" / "ci_params_combo.json"

SEEDS = (4, 13, 19)
BASIS = ("empirical absolute-error quantiles of the equal-weight v2+v3 average "
         "against the ABS's initial estimate, weekly vintages, targets 2022Q4 "
         "onward, centred on the point.")

# What the single-horizon measurement doc reports for the current quarter.
REGRESSION = {"mae": 0.129, "bias": 0.059, "n": 181, "corr": 0.05}

V2_COLUMNS = ["as_of", "target", "v2", "months_with_data_v2"]
V3_COLUMNS = ["as_of", "target", "v3_raw", "v3", "months_with_data_v3"]


# --------------------------------------------------------------------------- #
# The pure functions
# --------------------------------------------------------------------------- #


def pair(v2: pd.DataFrame, v3: pd.DataFrame, *, min_months: int = 0) -> pd.DataFrame:
    """One row per Monday and quarter that BOTH models have a figure for.

    `v2` carries `as_of, target, v2, months_with_data_v2`; `v3` carries
    `as_of, target, v3_raw, v3, months_with_data_v3`, v3 already corrected.
    The merge is an inner join on (as_of, target): a Monday only one model ran,
    or one where the two models name different quarters, drops out.

    `min_months` is the live publication rule at the next-quarter horizon: a
    row survives only if both models had at least that many months of data in
    the target quarter. A blank month count (v3 does not record one for the
    current quarter) is treated as unknown and never filtered out, because the
    rule it would be filtering on is about the next quarter.
    """
    for frame, cols, name in ((v2, V2_COLUMNS, "v2"), (v3, V3_COLUMNS, "v3")):
        missing = [c for c in cols if c not in frame.columns]
        if missing:
            raise ValueError(f"{name} frame is missing column(s) {missing}")
    out = v2[V2_COLUMNS].merge(v3[V3_COLUMNS], on=["as_of", "target"], how="inner")
    if min_months:
        for c in ("months_with_data_v2", "months_with_data_v3"):
            months = pd.to_numeric(out[c], errors="coerce")
            out = out[months.isna() | (months >= min_months)]
    out = out.copy()
    out["combo"] = (out["v2"].astype(float) + out["v3"].astype(float)) / 2
    return out.sort_values(["as_of", "target"]).reset_index(drop=True)


def score(errors) -> dict:
    """`{bias, mae, rmse, n}` over the signed errors that exist.

    Rows with no error (a quarter the ABS has not printed) are dropped rather
    than propagated: one nan would otherwise make every figure in the table nan
    and hide which rows were actually scored.

    Unrounded on purpose: rounding here and again at the printer turns a
    0.1845 into a 0.184 where the published doc says 0.185, and a regression
    check that trips on a double rounding teaches nobody anything.
    """
    err = pd.Series(list(errors), dtype=float).dropna()
    if err.empty:
        return {"bias": None, "mae": None, "rmse": None, "n": 0}
    return {"bias": float(err.mean()),
            "mae": float(err.abs().mean()),
            "rmse": float(np.sqrt((err ** 2).mean())),
            "n": int(err.size)}


def bands(errors) -> dict:
    """`{p68, p95, n, mae, bias}`: the band parameters the emitter publishes.

    The 68th and 95th percentiles of the ABSOLUTE error, applied symmetrically
    around the point. Symmetric because the published figure is the point and
    the reader is being told how far it has missed by, not which way: the
    direction is the bias, which is reported beside the band and never folded
    into it.

    This is `nyfed.au.combination.bands_from_errors`, called rather than
    reimplemented, so the calibrated file and the emitter's own fallback are
    the same arithmetic.
    """
    from nyfed.au.combination import bands_from_errors

    err = pd.Series(list(errors), dtype=float).dropna()
    if err.empty:
        raise ValueError("bands(): no errors to calibrate on")
    return bands_from_errors(err.tolist())


# --------------------------------------------------------------------------- #
# Reading the two backtests
# --------------------------------------------------------------------------- #


def _flat(label: str) -> str:
    """``"2026 Q2"`` -> ``"2026Q2"``, the form both sides are keyed on."""
    return str(label).replace(" ", "")


def load_v2(path: Path = V2_CSV) -> dict[str, pd.DataFrame]:
    """v2's two horizons from its backtest CSV, keyed "current" and "next"."""
    raw = pd.read_csv(path)
    raw["as_of"] = raw["as_of"].astype(str).str[:10]
    cur = raw.dropna(subset=["qoq_growth_forecast"]).copy()
    cur["target"] = [_flat(q) for q in cur["target_quarter"]]
    cur = cur.rename(columns={"qoq_growth_forecast": "v2",
                              "n_months_in_quarter": "months_with_data_v2"})
    nxt = raw.dropna(subset=["qoq_growth_forecast_next"]).copy()
    nxt["target"] = [_flat(q) for q in nxt["next_target_quarter"]]
    nxt = nxt.rename(columns={"qoq_growth_forecast_next": "v2",
                              "n_months_in_next_quarter": "months_with_data_v2"})
    return {"current": cur[V2_COLUMNS].reset_index(drop=True),
            "next": nxt[V2_COLUMNS].reset_index(drop=True)}


def _correction(asof: str, seeded: pd.DataFrame) -> float:
    """The live rolling miss at a run date; zero before four quarters printed.

    `rolling_miss` refuses under four prints rather than returning a small
    number from two, and the live job publishes the raw model until then. The
    backtest has to do the same or its early rows would be corrected by a
    figure that was never on the site.
    """
    try:
        return float(rolling_miss(seeded, asof=asof).pp)
    except ValueError:
        return 0.0


def load_v3(paths=V3_CSVS) -> dict[str, pd.DataFrame]:
    """v3's two horizons: the seed median, less the live rolling-miss correction.

    Collapsed chains are dropped before the median (the funnel refuses them
    live, so a collapsed seed was never part of a published figure); where one
    of the three collapsed, the median is over the remaining two.
    """
    raw = pd.concat([pd.read_csv(p) for p in paths], ignore_index=True)
    raw["asof"] = raw["asof"].astype(str).str[:10]
    raw = raw[raw["collapsed"] != 1]

    seeded = load_misses()
    seeded = seeded[seeded["source"] == "backtest"]

    def horizon(value_col: str, target_col: str, months_col: str) -> pd.DataFrame:
        frame = raw.dropna(subset=[value_col]).copy()
        frame = frame[frame[target_col].astype(str).str.len() > 0]
        grouped = frame.groupby(["asof", target_col], as_index=False).agg(
            v3_raw=(value_col, "median"),
            seeds=("seed", "nunique"),
            months_with_data_v3=(months_col, "max"))
        grouped = grouped.rename(columns={"asof": "as_of", target_col: "target"})
        grouped["target"] = [_flat(t) for t in grouped["target"]]
        grouped["correction"] = [_correction(a, seeded) for a in grouped["as_of"]]
        grouped["v3"] = grouped["v3_raw"] - grouped["correction"]
        return grouped

    cur = horizon("nowcast_qq", "target", "horizon_months")
    # v3's backtest records no month count for the CURRENT quarter -- only
    # `horizon_months`, which counts from the vintage to the quarter's end and
    # is not the same thing. Left blank rather than filled with a proxy.
    cur["months_with_data_v3"] = np.nan
    nxt = horizon("forecast_next_qq", "next_target", "next_months_with_data")
    keep = V3_COLUMNS + ["seeds", "correction"]
    return {"current": cur[keep], "next": nxt[keep]}


def attach_actuals(rows: pd.DataFrame, horizon: str) -> pd.DataFrame:
    """Add the ABS's initial estimate, the days to its release, and the horizon.

    A quarter with no initial estimate yet (the one in flight) is dropped: it
    cannot be scored, and carrying it into the tables as a blank row invites
    someone to count it.
    """
    first = load_first_release()
    by_label = {quarter_label(ts): float(v) for ts, v in first.items()}
    out = rows.copy()
    out["horizon"] = horizon
    out["first"] = [by_label.get(t) for t in out["target"]]
    out = out[out["first"].notna()].copy()
    out["days_to_release"] = [
        (pd.Timestamp(gdp_release_date(f"{t[:4]} Q{t[-1]}")) - pd.Timestamp(a)).days
        for t, a in zip(out["target"], out["as_of"])]
    return out


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #

ARMS = [("v2", "v2"), ("v3_raw", "v3 raw"), ("v3", "v3"), ("combo", "combination")]


def arm_scores(rows: pd.DataFrame) -> dict[str, dict]:
    return {arm: score(rows[arm] - rows["first"]) for arm, _ in ARMS}


def _fmt(s: dict) -> str:
    if s["n"] == 0:
        return "no rows"
    return (f"bias {s['bias']:+.3f}  MAE {s['mae']:.3f}  "
            f"RMSE {s['rmse']:.3f}  n {s['n']}")


def report(rows: pd.DataFrame, horizon: str) -> dict:
    print(f"\n== {horizon} horizon: {len(rows)} Mondays, "
          f"{rows['target'].nunique()} quarters "
          f"({rows['target'].min()} to {rows['target'].max()})")
    scores = arm_scores(rows)
    for arm, name in ARMS:
        print(f"   {name:12s} {_fmt(scores[arm])}")
    err_v2, err_v3 = rows["v2"] - rows["first"], rows["v3"] - rows["first"]
    corr = round(float(np.corrcoef(err_v2, err_v3)[0, 1]), 3)
    band = bands(rows["combo"] - rows["first"])
    print(f"   error correlation v2/v3: {corr:+.3f}")
    print(f"   combination band: 68% +/-{band['p68']:.3f}pp, "
          f"95% +/-{band['p95']:.3f}pp")
    by_months = {}
    for col, who in (("months_with_data_v2", "v2"), ("months_with_data_v3", "v3")):
        months = pd.to_numeric(rows[col], errors="coerce")
        if months.isna().all():
            continue
        for m, group in rows.groupby(months.fillna(-1)):
            if m < 0:
                continue
            b = bands(group["combo"] - group["first"])
            key = f"{who}:{int(m)}"
            by_months[key] = {"n": len(group),
                              **{arm: score(group[arm] - group["first"])["mae"]
                                 for arm, _ in ARMS},
                              "p68": b["p68"], "p95": b["p95"]}
            print(f"   {who} months={int(m)}  n {len(group):3d}  " +
                  "  ".join(f"{name} {by_months[key][arm]:.3f}"
                            for arm, name in ARMS) +
                  f"  | 68% +/-{b['p68']:.2f}  95% +/-{b['p95']:.2f}")
    return {"scores": scores, "corr": corr, "band": band, "by_months": by_months}


def regression_check(current: dict) -> bool:
    """Print the current horizon against the single-horizon measurement doc."""
    got = {"mae": current["scores"]["combo"]["mae"],
           "bias": current["scores"]["combo"]["bias"],
           "n": current["scores"]["combo"]["n"], "corr": current["corr"]}
    ok = (abs(got["mae"] - REGRESSION["mae"]) < 0.005
          and abs(got["bias"] - REGRESSION["bias"]) < 0.005
          and got["n"] == REGRESSION["n"]
          and abs(got["corr"] - REGRESSION["corr"]) < 0.01)
    print("\n== regression check against 2026-09-12-v2-v3-weekly-combination.md")
    for k in ("mae", "bias", "n", "corr"):
        here = got[k] if k == "n" else f"{got[k]:.4f}"
        print(f"   {k:5s} doc {REGRESSION[k]:>7}   here {here:>7}")
    print("   " + ("PASS: the current horizon reproduces the published figures"
                   if ok else
                   "DIFFERS: explain the difference before shipping the bands"))
    return ok


# --------------------------------------------------------------------------- #


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="print the tables; write neither the CSV nor the params")
    ap.add_argument("--out-csv", default=str(OUT_CSV))
    ap.add_argument("--out-params", default=str(OUT_PARAMS))
    args = ap.parse_args()

    v2, v3 = load_v2(), load_v3()
    current = attach_actuals(pair(v2["current"], v3["current"]), "current")
    # The next horizon is scored only where the figure would have been
    # published: both models with a month of data in the quarter.
    nxt = attach_actuals(pair(v2["next"], v3["next"], min_months=1), "next")

    summary = {"current": report(current, "current"), "next": report(nxt, "next")}
    ok = regression_check(summary["current"])

    cols = ["as_of", "horizon", "target", "first", "v2", "v3_raw", "v3", "combo",
            "months_with_data_v2", "months_with_data_v3", "days_to_release"]
    joined = pd.concat([current, nxt], ignore_index=True)[cols]
    for c in ("first", "v2", "v3_raw", "v3", "combo"):
        joined[c] = joined[c].astype(float).round(4)
    # Month counts are counts: `3.0` in a measurement CSV invites a reader to
    # wonder what a third of a month is. Nullable so v3's blank stays blank.
    for c in ("months_with_data_v2", "months_with_data_v3"):
        joined[c] = pd.to_numeric(joined[c], errors="coerce").astype("Int64")
    joined = joined.sort_values(["as_of", "horizon"]).reset_index(drop=True)

    params = {
        "schema": "combo-ci-1",
        "basis": BASIS,
        "current": summary["current"]["band"],
        "next": summary["next"]["band"],
        "source": {"v2": str(V2_CSV.relative_to(ROOT)),
                   "v3": [str(p.relative_to(ROOT)) for p in V3_CSVS],
                   "joined": str(Path(args.out_csv).resolve().relative_to(ROOT)),
                   "target": "nowcasting_v3/data/gdp_first_release.csv"},
        "computed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00"),
    }

    if args.dry_run:
        print("\n(dry run: nothing written)")
        print(json.dumps(params, indent=2))
        return 0 if ok else 1

    joined.to_csv(args.out_csv, index=False)
    Path(args.out_params).write_text(json.dumps(params, indent=2) + "\n")
    print(f"\nwrote {Path(args.out_csv).name} ({len(joined)} rows) and "
          f"{Path(args.out_params).name}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
