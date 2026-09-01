"""Turn the committed backtest measurements into `data/backtest_v3.json`.

No estimation: this is a transform of two CSVs that are already in the repo, so
the site's track-record section cannot drift from the measurement that produced
it. Re-run it when either CSV changes.

  v3  docs/measurements/2026-08-30-plan-c-backtest.csv   (tools/plan_c_backtest.py)
  v2  nowcasting_v2/cache/ci_recalib/qa_a10_acc.csv      (v2's SHIPPING backtest)

The v2 file is the shipping configuration, not the `_leaky` diagnostic beside
it -- see `tools/compare_v3_v2.py`.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from nyfed.au.build import load_vintage

def _quarter_start(label: str) -> pd.Timestamp:
    """"2026 Q2" -> 2026-06-01, the month a quarterly observation is dated to."""
    year, q = label.split(" Q")
    return pd.Timestamp(int(year), (int(q) - 1) * 3 + 3, 1)


REPO = Path(__file__).resolve().parents[1]
ROOT = REPO.parent
OUT = ROOT / "data" / "backtest_v3.json"


def main() -> int:
    v3 = pd.read_csv(ROOT / "docs/measurements/2026-08-30-plan-c-backtest.csv",
                     parse_dates=["asof", "target_date"])
    v3 = v3[v3["collapsed"] == 0].copy()
    v3["nowcast_qq"] = pd.to_numeric(v3["nowcast_qq"], errors="coerce")
    m = v3.groupby(["asof", "target", "target_date", "actual_qq"],
                   as_index=False)["nowcast_qq"].median()

    # ---- the same numbers in the site's existing Performance shape ---------
    # So `PerformanceSection` renders v3 without a v3-specific component. One
    # row per target quarter, scored at that quarter's LAST vintage -- the
    # figure that stood when the ABS published, which is what "how wrong was it"
    # means to a reader. Averaging a quarter's three vintages would flatter the
    # model by cancelling revisions within the quarter.
    gdp = load_vintage(ROOT / "nowcasting_v3/tests/fixtures/au/vintage").series["gdp"].dropna()

    # WHAT THE MODEL ACTUALLY SAID AT THE TIME, where it was running. Every row
    # in the backtest is a re-run over data that was already known, which is the
    # weaker claim: a backtest cannot be wrong in a way its author would notice,
    # because the author chose the window. A live call can. As quarters complete
    # with `nowcast_history_v3.json` behind them, their rows are replaced by what
    # was published before the ABS printed, and flagged so the table can say so.
    live: dict[str, dict] = {}
    hist_path = ROOT / "data" / "nowcast_history_v3.json"
    if hist_path.is_file():
        for r in json.loads(hist_path.read_text())["runs"]:
            # The LAST run before the print is the model's final word on that
            # quarter and the only one worth scoring. A backfilled row was never
            # published, so it cannot stand as a live call.
            if r.get("backfilled"):
                continue
            # NOR CAN A FORECAST ROW. A quarter is the NEXT-quarter forecast for
            # a few weeks before it becomes the nowcast, and those rows are a
            # different and much harder claim: one month of the quarter's data
            # rather than three. Scoring one as the live call would put a
            # forecast in a table that says nowcast. Keyed on the explicit
            # "forecast" value so rows written before `kind` existed, which are
            # all nowcasts, still count.
            if r.get("kind") == "forecast":
                continue
            q = r["target_quarter"]
            if q not in live or r["run_date"] > live[q]["run_date"]:
                live[q] = r

    # The RBA's own Statement on Monetary Policy forecast, where one lines up.
    # Only the June and December quarters have one: the SoMP publishes a
    # YEAR-ENDED forecast, so the comparison is on year-ended growth, and only
    # those quarters have a SoMP released roughly two months before our
    # full-quarter estimate. Scored exactly as v2 does it (04_emit_json.R:593):
    #     edge = |our error| - |RBA error|,  negative meaning we landed closer.
    somp = pd.read_csv(ROOT / "pipeline/rba_somp_forecasts_v2.csv")
    somp = somp.set_index("target_quarter")

    last = m.sort_values("asof").groupby("target", as_index=False).last()

    # QUARTERS THE MODEL CALLED LIVE, WHICH THE BACKTEST CANNOT CONTAIN. The
    # backtest CSV is a fixed measurement ending at 2026Q1. Every quarter after
    # it is one this model nowcast in public and the ABS has since printed, and
    # they have to be appended or the table silently stops growing — the first
    # real result the project produced would never reach its own track record,
    # which is the row a reader should care most about.
    known = set(last["target"])
    for q, r in sorted(live.items()):
        key = q.replace(" ", "")
        if key in known:
            continue
        tgt = _quarter_start(q)
        if tgt not in gdp.index:
            continue        # the ABS has not printed it yet; nothing to score
        prev = gdp[gdp.index < tgt]
        if prev.empty:
            continue
        actual_qq = 100 * (float(gdp[tgt]) / float(prev.iloc[-1]) - 1)
        last = pd.concat([last, pd.DataFrame([{
            "asof": r["run_date"], "target": key, "target_date": tgt,
            "actual_qq": round(actual_qq, 4),
            "nowcast_qq": r["qoq_growth_pct"],
        }])], ignore_index=True)
        print(f"  + {q}: live nowcast {r['qoq_growth_pct']:+.2f}% "
              f"against actual {actual_qq:+.2f}%")
    last = last.sort_values("target_date")

    errors = []
    for r in last.itertuples():
        label = r.target.replace("Q", " Q")
        published = live.get(label)
        lvl = float(gdp[gdp.index < r.target_date].iloc[-1])
        actual_lvl = lvl * (1 + r.actual_qq / 100)
        # A live figure supersedes the backtest for its quarter. Reporting a
        # backtested number for a quarter the model actually called would be
        # quietly flattering: the backtest sees the whole sample.
        nowcast_qq = (published["qoq_growth_pct"] if published
                      else float(r.nowcast_qq))
        nowcast_lvl = lvl * (1 + nowcast_qq / 100)

        # Year-ended: this quarter's level against the level four quarters back.
        back = gdp[gdp.index < r.target_date]
        yoy_nc = yoy_ac = yoy_rba = edge = release = None
        if len(back) >= 4:
            base = float(back.iloc[-4])
            yoy_nc = round(100 * (nowcast_lvl / base - 1), 2)
            yoy_ac = round(100 * (actual_lvl / base - 1), 2)
            if label in somp.index:
                yoy_rba = float(somp.loc[label, "yoy_forecast_pct"])
                release = str(somp.loc[label, "somp_release"])
                edge = round(abs(yoy_nc - yoy_ac) - abs(yoy_rba - yoy_ac), 2)

        errors.append({
            "target_quarter": label,
            "final_nowcast": round(nowcast_lvl),
            "actual": round(actual_lvl),
            "error_millions": round(nowcast_lvl - actual_lvl),
            "error_pct": round(100 * (nowcast_lvl - actual_lvl) / actual_lvl, 3),
            "qoq_nowcast_pct": round(nowcast_qq, 2),
            "qoq_actual_pct": round(float(r.actual_qq), 2),
            "qoq_error_pp": round(nowcast_qq - float(r.actual_qq), 2),
            "is_live": bool(published),
            "live_run_date": published["run_date"] if published else None,
            "yoy_nowcast": yoy_nc, "yoy_actual": yoy_ac, "yoy_rba": yoy_rba,
            "somp_release": release, "edge_pp": edge,
        })
    e = pd.DataFrame(errors)
    # The quarters where an RBA forecast exists, with each side's absolute miss
    # against the ABS year-ended actual.
    paired = pd.DataFrame([
        {"our_err": abs(x["yoy_nowcast"] - x["yoy_actual"]),
         "rba_err": abs(x["yoy_rba"] - x["yoy_actual"]),
         "edge": x["edge_pp"]}
        for x in errors if x["edge_pp"] is not None])
    perf = {
        "mae_millions": round(float(e.error_millions.abs().mean())),
        "mae_pct": round(float((e.qoq_nowcast_pct - e.qoq_actual_pct).abs().mean()), 2),
        "bias_millions": round(float(e.error_millions.mean())),
        "bias_pct": round(float((e.qoq_nowcast_pct - e.qoq_actual_pct).mean()), 2),
        # A MEAN SIGNED GAP IS NOT A LEGIBLE ACCURACY CLAIM. "-0.05pp average
        # edge" tells a reader almost nothing: it hides how big either
        # forecaster's misses were, and one large error in each direction
        # cancels to zero. The two error rates side by side, and a count of who
        # landed closer, say the same thing in a form that can be argued with.
        # `avg_edge_pp` is kept because v2's page reads it.
        "rba_comparison": {
            "n": int(len(paired)),
            "avg_edge_pp": (round(float(np.mean(paired["edge"])), 2)
                            if len(paired) else None),
            "ours_mae": (round(float(paired["our_err"].mean()), 2)
                         if len(paired) else None),
            "rba_mae": (round(float(paired["rba_err"].mean()), 2)
                        if len(paired) else None),
            "we_were_closer": (int((paired["our_err"] < paired["rba_err"]).sum())
                               if len(paired) else None),
        },
        "errors": errors,
    }
    perf_path = ROOT / "data" / "performance_v3.json"
    perf_path.write_text(json.dumps(perf, indent=2) + "\n")
    print(f"wrote {perf_path}  ({len(errors)} quarters, "
          f"MAE {perf['mae_pct']}pp, bias {perf['bias_pct']}pp)")
    # THE v2 HEAD-TO-HEAD IS OPTIONAL, AND IT HAS TO BE. v2's backtest lives in
    # `nowcasting_v2/cache/`, which is GITIGNORED — a cache regenerated by v2's
    # own R pipeline, absent on a CI runner. The first weekly run carrying this
    # step failed outright on it, publishing nothing, over a file the site does
    # not read: nothing renders `backtest_v3.json` any more. The track record
    # above is what the page shows, and it is written before we get here.
    v2_path = ROOT / "nowcasting_v2/cache/ci_recalib/qa_a10_acc.csv"
    if not v2_path.is_file():
        print(f"no v2 backtest at {v2_path.relative_to(ROOT)} — track record "
              "written, skipping the v2 comparison")
        return 0

    v2 = pd.read_csv(v2_path, parse_dates=["as_of", "target_quarter_date"]
                     ).dropna(subset=["qoq_actual"])

    rows = []
    for _, r in m.iterrows():
        c = v2[(v2["target_quarter_date"] == r["target_date"])
               & (v2["as_of"] <= r["asof"])].sort_values("as_of")
        rows.append({
            "asof": str(r["asof"].date()), "target": r["target"],
            "actual": round(float(r["actual_qq"]), 4),
            "v3": round(float(r["nowcast_qq"]), 4),
            "v2": round(float(c.iloc[-1]["qoq_growth_forecast"]), 4) if len(c) else None,
        })
    p = pd.DataFrame(rows).dropna(subset=["v2"])

    def score(col: str) -> dict:
        e = p[col] - p["actual"]
        r2 = float(np.corrcoef(p[col], p["actual"])[0, 1] ** 2)
        return {
            "mae": round(float(e.abs().mean()), 4),
            "rmse": round(float(np.sqrt((e ** 2).mean())), 4),
            "bias": round(float(e.mean()), 4),
            "r_squared": round(r2, 4),
            # An honest conditional mean varies at sqrt(R^2) of the outcome's
            # spread. More than that is confidence the model has not earned.
            "dispersion_ratio": round(float(p[col].std() / p["actual"].std()), 4),
            "calibrated_ratio": round(float(np.sqrt(r2)), 4),
        }

    gdp_q = p.groupby("target").agg(
        actual=("actual", "first"), v3=("v3", "mean"), v2=("v2", "mean"),
        n=("v3", "size")).reset_index()

    payload = {
        "schema": "v3-backtest-1",
        "window": {"first_target": p["target"].iloc[0],
                   "last_target": p["target"].iloc[-1],
                   "n_vintages": int(len(p)),
                   "n_quarters": int(p["target"].nunique())},
        "scores": {"v3": score("v3"), "v2": score("v2")},
        "by_quarter": [
            {"target": r.target, "actual": round(r.actual, 4),
             "v3": round(r.v3, 4), "v2": round(r.v2, 4), "n_vintages": int(r.n)}
            for r in gdp_q.itertuples()],
        "notes": {
            "pseudo_real_time": (
                "Both models see REVISED data and are scored against revised "
                "outcomes. That flatters both, comparably. A first-print "
                "backtest does not exist for either."),
            "window_start": (
                "Starts 2023. The COVID factor runs to December 2021, so a 2022 "
                "vintage sits on its edge and v3 runs a quarter behind through "
                "it -- 2.12pp mean error in 2022 against 0.45pp in 2024."),
            "v2_config": (
                "v2 at cache/ci_recalib/qa_a10_acc.csv, its shipping backtest. "
                "Its predictor selection is fixed to the full sample, a "
                "look-ahead that flatters v2 and has no counterpart in v3."),
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"wrote {OUT}")
    for k, v in payload["scores"].items():
        print(f"  {k}: MAE {v['mae']}  R2 {v['r_squared']:.1%}  "
              f"varies at {v['dispersion_ratio']} vs calibrated "
              f"{v['calibrated_ratio']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
