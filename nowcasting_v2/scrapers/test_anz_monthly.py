"""Source/vintage regression tests; never use a network or write production data."""
import copy
import datetime as dt
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from anz_monthly import HEADER, ROOT, parse_monthly, plan, read_csv, refresh, update_indicator


class MonthlyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        raw = self.root/"nowcasting_v2/data_raw"; raw.mkdir(parents=True)
        self.csv = raw/"anz_sent.csv"; self.meta = raw/"anz_sent.meta.json"
        current = read_csv(ROOT/"nowcasting_v2/data_raw/anz_sent.csv")
        self.original = "date,value\n"+"".join(f"{r['date']},{r['value']}\n" for r in current if r["date"] <= "2026-07-01")
        self.csv.write_text(self.original)
        self.state = json.loads((ROOT/"nowcasting_v2/data_raw/anz_sent.meta.json").read_text())
        initial_source = self.state['vintages'][0]['source_path']
        self.state["observations"] = {k:v for k,v in self.state["observations"].items() if k <= "2026-07-01"}
        self.state["vintages"] = []; self.state.pop("latest_source", None)
        self.meta.write_text(json.dumps(self.state))
        self.text = (ROOT/initial_source).read_text()
        self.checked = dt.datetime.now(dt.timezone.utc).isoformat()

    def run_refresh(self, text=None, write=True, **kwargs):
        return refresh(self.root, self.text if text is None else text, self.checked, "test-official-excerpt", write, **kwargs)

    def test_full_history_audit_and_append_only_backfill(self):
        result = self.run_refresh()
        self.assertEqual(result["audit"]["compared"], 578)
        self.assertEqual(result["audit"]["differences"], self.state["frozen_conflicts"])
        self.assertEqual([(r['date'],r['value'],r['provisional']) for r in result['changes']], [
            ('2026-08-01',74.4,False),('2026-09-01',74.6,False),
            ('2026-10-01',67.7,True),('2026-11-01',65.3,True)])
        self.assertTrue(self.csv.read_text().startswith(self.original))
        state=json.loads(self.meta.read_text()); snapshot=self.root/state['latest_source']['source_path']
        self.assertEqual(snapshot.read_text(),self.text)
        self.assertIsNone(state['latest_source']['release_date'])

    def test_dry_run_and_no_change_are_no_writes(self):
        before={p.relative_to(self.root):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.run_refresh(write=False)
        self.assertEqual(before,{p.relative_to(self.root):p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        self.run_refresh(); before={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        self.assertEqual(self.run_refresh()['changes'],[])
        self.assertEqual(before,{p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_provisional_updates_and_finalization_keep_prior_vintages(self):
        self.run_refresh()
        self.run_refresh(self.text.replace('67.7**','67.8'))
        state=json.loads(self.meta.read_text())
        self.assertEqual(state['vintages'][-1]['changes'][0]['old'],67.7)
        self.assertEqual(state['vintages'][0]['changes'][2]['value'],67.7)
        self.assertFalse(state['observations']['2026-10-01']['provisional'])
        before=self.csv.read_bytes()
        with self.assertRaisesRegex(ValueError,'Final observation revised'):
            self.run_refresh(self.text.replace('67.7**','68.0'))
        self.assertEqual(self.csv.read_bytes(),before)

    def test_unreviewed_legacy_conflict_is_not_overwritten(self):
        with self.assertRaisesRegex(ValueError,'Unreviewed legacy conflict'):
            self.run_refresh(self.text.replace('75.4','75.5'))
        self.assertEqual(self.csv.read_text(),self.original)

    def test_weekly_reordered_missing_duplicate_invalid_and_future_tables_fail(self):
        bad = [self.text.replace('Australian CC Monthly Ratings','Australian CC Weekly Results'),
               self.text.replace('JAN  | FEB','FEB  | JAN'),
               self.text.replace('74.4  | 74.6','  | 74.6'),
               self.text.replace('74.4','999'),self.text.replace('74.4','unknown'),
               self.text.replace('65.3**  |  |','65.3**  | 70.0 |')]
        year_row=next(l for l in self.text.splitlines() if l.startswith('2026 '))
        bad.append(self.text+'\n'+year_row)
        for text in bad:
            with self.subTest(text=text[:80]), self.assertRaises(ValueError):
                source=parse_monthly(text,dt.date(2026,11,18))
                plan(read_csv(self.csv),source,self.state,self.checked)
        self.assertEqual(self.csv.read_text(),self.original)

    def test_html_and_text_tables_preserve_flags_and_header_mapping(self):
        lines=[l for l in self.text.splitlines() if '|' in l]
        html='Australian CC Monthly Ratings<table>'+''.join('<tr>'+''.join('<td>'+c+'</td>' for c in l.split('|'))+'</tr>' for l in lines)+'</table>'
        self.assertEqual(parse_monthly(html,dt.date(2026,11,18)),parse_monthly(self.text,dt.date(2026,11,18)))

    def test_source_failure_does_not_fall_back_to_fixture(self):
        from anz_monthly import main
        with patch('sys.argv',['anz_monthly.py','--write']), patch('urllib.request.urlopen',side_effect=OSError('403')):
            with self.assertRaises(OSError): main()
        self.assertEqual(self.csv.read_text(),self.original)

    def test_bad_retrieval_time_and_metadata_disagreement_fail_before_writes(self):
        for stamp in ['2026-01-01T00:00:00+00:00','2099-01-01T00:00:00+00:00','2026-11-18T00:00:00']:
            with self.assertRaises(ValueError): refresh(self.root,self.text,stamp,'test',True)
        self.run_refresh()
        self.csv.write_text(self.csv.read_text().replace('2026-11-01,65.3','2026-11-01,66.6'))
        with self.assertRaisesRegex(ValueError,'metadata disagree'): self.run_refresh()

    def test_display_sync_only_changes_anz_and_never_a_model_payload(self):
        data=self.root/'data';data.mkdir()
        original={'indicators':[{'id':'anz_sent','series':[{'date':'2022-05','value':90.3}],
                                'last_release_date':'2026-11-10','next_release_estimate':'2026-11-17'},
                                {'id':'wmi_sent','series':[{'date':'2026-11','value':78.2}]}]}
        for name in ['indicators_v2.json','indicators_combo.json']:(data/name).write_text(json.dumps(original))
        model=data/'latest_v2.json';model.write_text('MODEL UNCHANGED')
        self.run_refresh(sync_display=True)
        for name in ['indicators_v2.json','indicators_combo.json']:
            doc=json.loads((data/name).read_text());anz=doc['indicators'][0]
            self.assertEqual(doc['indicators'][1],original['indicators'][1])
            self.assertEqual(anz['series'][-1],{'date':'2026-11','value':65.3,'provisional':True})
            self.assertNotIn('last_release_date',anz);self.assertNotIn('next_release_estimate',anz)
            self.assertFalse(anz['updated_this_run']);self.assertEqual(anz['source_checked_at'],self.checked)
        self.assertEqual(model.read_text(),'MODEL UNCHANGED')

    def test_normal_weekly_generator_keeps_source_dates_and_provisional_flags(self):
        self.run_refresh()
        data=self.root/'data';data.mkdir()
        path=data/'indicators_v2.json'
        path.write_text(json.dumps({'indicators':[{'id':'anz_sent','name':'ANZ',
            'series':[{'date':'2026-06','value':70.8},{'date':'2026-07','value':75.0}],
            'last_release_date':'2026-11-10','next_release_estimate':'2026-11-17'}]}))
        spec=importlib.util.spec_from_file_location('anz_generator_under_test',ROOT/'nowcasting_v2/gen_indicators_v2.py')
        gen=importlib.util.module_from_spec(spec);spec.loader.exec_module(gen)
        gen.ROOT=str(self.root);gen.IND=str(path);gen.RAW=str(self.csv.parent);gen.V1_IND=str(data/'missing.json')
        gen.main()
        anz=json.loads(path.read_text())['indicators'][0]
        self.assertEqual(anz['series'][-1],{'date':'2026-11','value':65.3,'provisional':True})
        self.assertEqual(anz['source_checked_at'],self.checked)
        self.assertNotIn('last_release_date',anz);self.assertNotIn('next_release_estimate',anz)


if __name__ == '__main__': unittest.main()
