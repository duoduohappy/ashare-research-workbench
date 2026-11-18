import tempfile,unittest
from pathlib import Path
from server import demo
from workbench import watchlist,ledger,rotation,finance,screen,event_calendar,audit,experiments,paper

class WorkbenchTests(unittest.TestCase):
    def setUp(self):self.bars=demo()['bars'];self.end=self.bars[-1]['date']
    def test_saved_watchlist_is_persistent(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'test.sqlite'
            watchlist(p,'研究池',['600519','000001'])
            self.assertEqual(watchlist(p)[0]['codes'],['600519','000001'])
            watchlist(p,'研究池',['300750'])
            self.assertEqual(len(watchlist(p)),1)
            self.assertEqual(watchlist(p)[0]['codes'],['300750'])
    def test_fifo_fees_cash_and_t1(self):
        a={'id':1,'code':'000001','day':'2025-01-02','side':'buy','quantity':100,'price':10,'fee':5}
        b={'id':2,'code':'000001','day':'2025-01-03','side':'sell','quantity':100,'price':11,'fee':5}
        r=ledger([a,b],'2025-01-03')
        self.assertAlmostEqual(r['cash'],300090);self.assertAlmostEqual(r['realized'][0]['profit'],90)
        self.assertEqual(r['positions'],{})
        with self.assertRaises(ValueError):ledger([a,dict(b,day='2025-01-02')],'2025-01-03')
        self.assertEqual(ledger([a,b],'2025-01-02')['positions'],{'000001':100})
    def test_paper_save_and_rollback(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'test.sqlite';bar=self.bars[100];day=bar['date']
            trade={'code':'000001','day':day,'side':'buy','quantity':100,'price':bar['raw_close'],'fee':5,'note':'test'}
            hist=lambda _: {'bars':self.bars}
            r=paper(p,day,hist,trade);self.assertEqual(len(r['trades']),1)
            with self.assertRaises(ValueError):paper(p,day,hist,dict(trade,side='sell'))
            with self.assertRaises(ValueError):paper(p,day,hist,dict(trade,price=100000))
            self.assertEqual(len(paper(p,day,hist)['trades']),1)
    def test_screen_cutoff(self):
        end=self.bars[300]['date']
        a=screen({'600519':self.bars},end)
        b=screen({'600519':self.bars[:301]},end)
        self.assertEqual(a,b)
        self.assertLessEqual(a['stages'][-1],a['stages'][0])
    def test_rotation_cutoff(self):
        a=rotation({'a':self.bars,'b':self.bars},{'a':'A','b':'B'},self.bars[300]['date'])
        self.assertTrue(all(p['x']==0 and p['y']==0 for s in a['paths'] for p in s['points']))
        self.assertTrue(all(p['date']<=self.bars[300]['date'] for s in a['lines'] for p in s['points']))
    def test_finance_disclosure_cutoff(self):
        rows=[{'NOTICE_DATE':'2022-03-01','REPORTDATE':'2021-12-31','BPS':10,'BASIC_EPS':1},
              {'NOTICE_DATE':'2099-01-01','REPORTDATE':'2025-12-31','BPS':10000,'BASIC_EPS':100}]
        r=finance(self.bars,rows,'2023-01-01')
        self.assertTrue(all(v['date']<='2023-01-01' for v in r['valuations']))
        self.assertTrue(all(v['pb']>1 for v in r['valuations']))
    def test_event_known_at_time(self):
        manual=[{'date':'2025-03-01','published_at':'2025-01-01','kind':'解禁','title':'已披露'},
                {'date':'2025-03-01','published_at':'2025-02-01','kind':'解禁','title':'尚未知'}]
        r=event_calendar([],manual,'2025-01-15')
        self.assertEqual(len(r['events']),1)
        self.assertEqual(r['events'][0]['title'],'已披露')
    def test_audit_union_not_fake_calendar(self):
        a=self.bars[:50];b=self.bars[:20]+self.bars[22:50]
        r=audit({'a':{'bars':a},'b':{'bars':b}},self.end)
        self.assertEqual(sum(r['rows'][1]['presence']),48)
        self.assertEqual(r['rows'][0]['invalid'],0)
    def test_lab_training_selection_has_no_holdout_leak(self):
        bars=self.bars[:500];cut=273+int((500-273)*.7)
        a=experiments(bars,bars[-1]['date'],20,.05,[20,60],[20],300000,True)
        altered=[dict(b) for b in bars]
        for b in altered[cut:]:
            b['close']*=1.5;b['raw_close']*=1.5;b['raw_open']*=1.5
        b=experiments(altered,bars[-1]['date'],20,.05,[20,60],[20],300000,True)
        self.assertEqual(a['cells'],b['cells']);self.assertEqual(a['best'],b['best'])

if __name__=='__main__':unittest.main()
