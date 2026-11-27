import copy
from datetime import datetime
import unittest

from final_window import release_slot
from nyfed.au.finality import checked_final_stamp, lock_active, missing_monthly_inputs


class FinalWindow(unittest.TestCase):
    def setUp(self):
        self.calendar = {"target_quarter": "2026 Q3",
                         "latest_actual": {"quarter": "2026 Q2"},
                         "next_gdp_release_date": "2026-12-02"}
        self.when = datetime.fromisoformat("2026-12-01T06:30:00+00:00")
        self.slot = release_slot(self.calendar, self.when)
        self.model = {"as_of": "2026-12-01", "target_quarter": "2026 Q3",
                      "final_input_check": self.slot}
        h = dict(quarter="2026 Q3", kind="nowcast", months_with_data=3,
                 qoq_growth_pct=0.42, ci_68_low=0.3, ci_68_high=0.54,
                 ci_95_low=0.08, ci_95_high=0.76)
        row = dict(h, target_quarter="2026 Q3", run_date="2026-12-01",
                   v2_run_date="2026-12-01", horizon="current")
        self.payload = dict(status="ok", as_of="2026-12-01",
                            generated_at=self.when.isoformat(), target_quarter="2026 Q3",
                            horizons=[h], vintages=[row],
                            components={"v2": {"run_date": "2026-12-01"},
                                        "v3": {"as_of": "2026-12-01"}})

    def test_sydney_cut_and_rescheduled_release(self):
        self.assertEqual(self.slot["release_at"], "2026-12-02T11:30:00+11:00")
        for time in ("2026-12-01T00:30:00+00:00", "2026-12-02T00:05:00+00:00",
                     "2026-11-30T06:30:00+00:00"):
            self.assertIsNone(release_slot(self.calendar, datetime.fromisoformat(time)))
        shifted = {**self.calendar, "next_gdp_release_date": "2026-12-03"}
        self.assertIsNone(release_slot(shifted, self.when))
        winter = dict(target_quarter="2026 Q1", latest_actual={"quarter": "2025 Q4"},
                      next_gdp_release_date="2026-06-03")
        slot = release_slot(winter, datetime.fromisoformat("2026-06-02T06:00:00+00:00"))
        self.assertEqual(slot["release_at"], "2026-06-03T11:30:00+10:00")
        first = dict(target_quarter="2027 Q2", latest_actual={"quarter": "2027 Q1"},
                     next_gdp_release_date="2027-09-01")
        self.assertIsNotNone(release_slot(first, datetime.fromisoformat("2027-08-31T06:00:00+00:00")))

    def test_requires_each_month_and_recognises_one_turn_of_year_gap(self):
        observed = {"cpi": {"2026-10", "2026-12"},
                    "aig_pmi": {"2026-10", "2026-11", "2027-01"}}
        keys = ["cpi", "aig_pmi"]
        self.assertEqual(missing_monthly_inputs(observed, quarter="2026 Q4", monthly_keys=keys),
                         ["cpi (2026-11)"])
        observed["aig_pmi"].remove("2027-01")
        self.assertIn("aig_pmi (2026-12)",
                      missing_monthly_inputs(observed, quarter="2026 Q4", monthly_keys=keys))

    def test_lock_binds_publication_and_expires_at_release_or_actual(self):
        stamp = checked_final_stamp(self.payload, self.model, self.model, self.slot,
                                    self.when.isoformat())
        self.payload["final_estimate"] = stamp
        self.assertTrue(lock_active(self.payload, [], self.when))
        self.assertFalse(lock_active(self.payload, [{"quarter": "2026 Q3"}], self.when))
        self.assertFalse(lock_active(self.payload, [], datetime.fromisoformat(stamp["release_at"])))
        self.assertFalse(lock_active({**self.payload, "generated_at": "2026-12-01T07:00:00Z"}, [], self.when))

    def test_rejects_uncertified_stale_refused_or_disagreeing_row(self):
        with self.assertRaises(ValueError):
            checked_final_stamp(self.payload, {}, self.model, self.slot, self.when.isoformat())
        for change in (
            lambda p: p.update(status="refused"),
            lambda p: p["components"]["v2"].update(stale_days=1),
            lambda p: p["vintages"][0].update(ci_68_low=0.01),
            lambda p: p["horizons"][0].update(months_with_data=2),
        ):
            changed = copy.deepcopy(self.payload)
            change(changed)
            with self.assertRaises(ValueError):
                checked_final_stamp(changed, self.model, self.model, self.slot, self.when.isoformat())

    def test_can_publish_as_soon_as_model_inputs_are_complete_then_revise(self):
        from nyfed.au.finality import coverage_stamp, quarter_months
        day = "2026-11-16"
        now = datetime.fromisoformat(day + "T00:30:00+00:00")
        h = self.payload["horizons"][0]
        h.update(release_date="2026-12-02", complete_months=quarter_months("2026 Q3"))
        self.payload.update(as_of=day, generated_at=now.isoformat())
        self.payload["components"]["v2"]["run_date"] = day
        self.payload["components"]["v3"]["as_of"] = day
        stamp = coverage_stamp(self.payload, [], now)
        self.assertEqual(stamp["run_date"], day)
        self.assertEqual(stamp["release_at"], self.slot["release_at"])
        # A later publication may revise the estimate and remain complete.
        next_day = "2026-11-23"
        later = datetime.fromisoformat(next_day + "T00:35:00+00:00")
        self.payload.update(as_of=next_day, generated_at=later.isoformat())
        self.payload["components"]["v2"]["run_date"] = next_day
        self.payload["components"]["v3"]["as_of"] = next_day
        h["qoq_growth_pct"] = 0.401
        self.assertEqual(coverage_stamp(self.payload, [], later)["run_date"], next_day)
        self.assertIsNone(coverage_stamp(self.payload, [{"quarter": "2026 Q3"}], later))
        h["complete_months"].pop()
        self.assertIsNone(coverage_stamp(self.payload, [], later))
        h["complete_months"].append("2026-09")
        self.payload["components"]["v2"]["run_date"] = day
        self.assertIsNone(coverage_stamp(self.payload, [], later))
