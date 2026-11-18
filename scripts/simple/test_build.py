"""Exercise live data, future refreshes, refusals and source/output isolation."""
import copy
import hashlib
import datetime as dt
from decimal import Decimal
from html.parser import HTMLParser
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from PIL import Image
from build import build_site, fixed

ROOT = Path(__file__).resolve().parents[2]

class Tables(HTMLParser):
    def __init__(self):
        super().__init__(); self.tables = {}; self.table = None; self.row = None; self.cell = None; self.pre = None; self.histories = []
    def handle_starttag(self, tag, attrs):
        if tag == 'table':
            self.table = []; self.tables[dict(attrs)['id']] = self.table
        elif tag == 'tr': self.row = []
        elif tag in ('th', 'td'): self.cell = ''
        elif tag == 'pre': self.pre = ''
    def handle_endtag(self, tag):
        if tag in ('th', 'td'): self.row.append(self.cell); self.cell = None
        elif tag == 'tr': self.table.append(self.row); self.row = None
        elif tag == 'table': self.table = None
        elif tag == 'pre': self.histories.append(self.pre); self.pre = None
    def handle_data(self, value):
        if self.cell is not None: self.cell += value
        if self.pre is not None: self.pre += value

class BuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.data = self.root/'data'; self.data.mkdir()
        for p in (ROOT/'data').glob('*.json'): shutil.copyfile(p, self.data/p.name)
        self.out = self.root/'out'/'simple'
    def read(self, name): return json.loads((self.data/name).read_text())
    def write(self, name, value): (self.data/name).write_text(json.dumps(value))
    def generate(self):
        result = build_site(self.data, self.out, 'test-commit')
        self.html = (self.out/'index.html').read_text(); self.parsed = Tables(); self.parsed.feed(self.html)
        return result
    def test_main_page_rounding_on_half_ties(self):
        self.assertEqual(fixed(.125),'0.13')
        self.assertEqual(fixed(-.125),'-0.13')
        self.assertEqual(fixed(1.005),'1.00')

    def test_current_data_all_values_and_isolation(self):
        sentinel = self.out.parent/'index.html'; sentinel.parent.mkdir(); sentinel.write_text('MAIN UNCHANGED')
        before = {p.name:p.read_bytes() for p in self.data.iterdir()}
        result = self.generate(); latest = self.read('latest_combo.json'); gdp = self.read('gdp.json')['series']
        self.assertEqual(sentinel.read_text(), 'MAIN UNCHANGED')
        self.assertEqual(before, {p.name:p.read_bytes() for p in self.data.iterdir()})
        self.assertEqual(result['as_of'], latest['as_of'])
        self.assertEqual(set(p.name for p in self.out.iterdir()), {'index.html','nowcast.gif','record.gif'})
        for name in ['nowcast.gif','record.gif']:
            digest=hashlib.sha256((self.out/name).read_bytes()).hexdigest()[:12]
            self.assertIn(f'/simple/{name}?v={digest}',self.html)
        for token in ['<script','<style','<svg','_next/','research preview','does not update automatically']:
            self.assertNotIn(token, self.html)
        self.assertGreater(self.html.index('<h2>Methodology'), self.html.index('<h2>Indicator history'))
        self.assertIn('GDP observations above are revised', self.html)
        self.assertIn('name="build-commit" content="test-commit"', self.html)
        indicators = self.read('indicators_combo.json')['indicators']
        self.assertEqual(len(indicators), len(self.parsed.histories))
        for i,text in zip(indicators,self.parsed.histories):
            actual = [row.split() for row in text.splitlines()[1:]]
            self.assertEqual(len(actual), len(i['series']))
            for (period,value),src in zip(actual,i['series']):
                self.assertEqual(period,src['date']); self.assertEqual(Decimal(value),Decimal(str(src['value'])))
        a,b = latest['horizons']; levels = {r['quarter']:r['value'] for r in gdp}
        expected=[]
        for h,level in [(a,a['gdp_chain_volume_millions']),(b,a['gdp_chain_volume_millions']*(1+b['qoq_growth_pct']/100))]:
            year,q=h['quarter'].split(); expected.append(f"{(level/levels[f'{int(year)-1} {q}']-1)*100:.2f}%")
        self.assertEqual(self.parsed.tables['estimates'][2],['Growth y/y']+expected)
        self.assertEqual(len(self.parsed.tables['track-record'])-1,len(self.read('performance_combo.json')['errors']))
        self.assertEqual(len(self.parsed.tables['gdp-history'])-1,len(gdp))
        self.assertEqual(sum(len(t)-1 for name,t in self.parsed.tables.items() if name.startswith('weekly-')),len(self.read('nowcast_history_combo.json')['runs']))
        self.assertGreater(result['observations'],1900)
        self.assertGreater(result['yoy'][0],0)
        self.assert_blank_future(result)
    def assert_blank_future(self,result):
        g=result['charts']['nowcast.gif']; axis=g['date_axis']; L,T,R,B=g['plot_bounds']; hi,lo=axis['domain'][1],axis['domain'][0]
        source=g['source_points']
        for points,key in zip(g['series_pixels'],['qoq_growth_pct','ci_68_low','ci_68_high']):
            for (x,y),row in zip(points,source):
                days=(dt.date.fromisoformat(row['run_date'])-dt.date.fromisoformat(axis['release_date'])).days
                self.assertEqual(x,round(L+(days-lo)*(R-L)/(hi-lo)))
                self.assertEqual(y,round(B-(row[key]-g['ymin'])*(B-T)/(g['ymax']-g['ymin'])))
        last=max(x for points in g['series_pixels'] for x,y in points); rx=g['release_line_x']
        with Image.open(self.out/'nowcast.gif') as image:
            im=image.convert('RGB')
        self.assertEqual(im.size,(288,144))
        self.assertTrue(all(im.getpixel((x,y))==(255,255,255) for x in range(last+1,rx) for y in range(T,B)))
        self.assertEqual(axis['last_observed_date'],source[-1]['run_date'])
    def test_new_quarter_observation_and_model_basis_refresh(self):
        self.generate(); old=(self.out/'nowcast.gif').read_bytes()
        c=self.read('latest_combo.json'); c['as_of']='2027-02-01'; c['next_gdp_release_date']='1900-01-01'
        a,b=c['horizons']; a.update(quarter='2026 Q4',release_date='2027-03-03',qoq_growth_pct=.55,gdp_chain_volume_millions=705000)
        b.update(quarter='2027 Q1',release_date='2027-06-02',qoq_growth_pct=.3,months_with_data=1,components={'v2':None,'v3':.3})
        c['bias_correction']['pp']=.12
        v=copy.deepcopy(c['vintages'][-1]); v.update(target_quarter='2026 Q4',run_date='2027-02-01',qoq_growth_pct=.55)
        c['vintages']=[v]; self.write('latest_combo.json',c)
        i=self.read('indicators_combo.json'); i['indicators'][0]['series'].append({'date':'2027-01','value':15001.25}); self.write('indicators_combo.json',i)
        result=self.generate()
        self.assertIn('1 Feb 2027',self.html); self.assertIn('Q1 2027',self.html)
        self.assertIn('Q1 2027 currently uses v3 alone',self.html)
        self.assertIn('0.12pp currently',self.html)
        self.assertIn('2027-01  15001.25',self.html)
        self.assertIn('3 Mar 2027',self.html); self.assertNotIn('1900',self.html)
        self.assertNotEqual(old,(self.out/'nowcast.gif').read_bytes())
        self.assertEqual(result['charts']['nowcast.gif']['date_axis']['release_date'],'2027-03-03')
        self.assert_blank_future(result)
    def test_no_data_forecast_is_withheld_like_main_page(self):
        c=self.read('latest_combo.json'); c['horizons'][1]['months_with_data']=0
        self.write('latest_combo.json',c); self.generate()
        self.assertEqual(self.parsed.tables['estimates'][1][-1],'No data')
        self.assertEqual(self.parsed.tables['estimates'][2][-1],'-')
        self.assertNotIn('y/y uses',self.html)

    def test_refusal_removes_old_nowcast_and_image(self):
        self.generate(); c=self.read('latest_combo.json'); c.update(status='refused',refusal_detail='Test refusal: data stale')
        self.write('latest_combo.json',c); self.generate()
        self.assertNotIn('id="estimates"',self.html); self.assertNotIn('src="/simple/nowcast.gif',self.html)
        self.assertFalse((self.out/'nowcast.gif').exists()); self.assertIn('Test refusal: data stale',self.html)
    def test_v3_fallback_and_optional_forecast(self):
        (self.data/'latest_combo.json').unlink(); (self.data/'indicators_combo.json').unlink(); (self.data/'performance_combo.json').unlink()
        c=self.read('latest_v3.json'); c['horizons']=[h for h in c['horizons'] if h['kind']=='nowcast']; self.write('latest_v3.json',c)
        result=self.generate(); self.assertFalse(result['combo'])
        self.assertIn('currently uses v3 alone because no combination payload',self.html)
        self.assertIn('probability band',self.html); self.assertNotIn("y/y uses",self.html)
        self.assertEqual(result['series'],len(self.read('indicators_v3.json')['indicators']))
        self.assertEqual(len(self.parsed.tables['estimates'][0]),2)

if __name__=='__main__': unittest.main()
