import copy
import json
import tempfile
import unittest
from pathlib import Path
from point_in_time import HistoryDataset, PITStore, demo_dataset, financial_asof, strict_backtest, dispatch
from ashare_rules import daily_rule, execution_quote, price_tick

class HistoricalResearchTests(unittest.TestCase):
    def setUp(self):self.payload=demo_dataset();self.ds=HistoryDataset(self.payload)

    def test_dynamic_members_keep_dead_and_exclude_unlisted(self):
        ds=self.ds
        self.assertIn('600001',ds.members(ds.calendar[50]))
        self.assertNotIn('688001',ds.members(ds.calendar[34]))
        self.assertIn('688001',ds.members(ds.calendar[35]))
        self.assertIn('600001',ds.members(ds.calendar[100]))
        self.assertNotIn('600001',ds.members(ds.calendar[101]))

    def test_revisions_and_publication_are_separate_gates(self):
        records=self.ds.financials;c='000001';days=self.ds.calendar
        self.assertEqual(financial_asof(records,c,days[90])['version'],'original')
        self.assertEqual(financial_asof(records,c,days[91])['version'],'correction')
        self.assertEqual(financial_asof(records,c,days[91]+'T08:59:59+08:00')['version'],'original')
        altered=copy.deepcopy(records)
        for r in altered:
            if r['version']=='correction':r['values']['roe']=9999
        self.assertEqual(financial_asof(records,c,days[89]),financial_asof(altered,c,days[89]))

    def test_date_only_notice_excluded_on_publication_date(self):
        records=[{'code':'000001','report_date':'2024-09-30','published_at':'2024-10-30','available_at':'2024-10-30','version':'v1','values':{'roe':1}}]
        self.assertIsNone(financial_asof(records,'000001','2024-10-30'))
        self.assertIsNotNone(financial_asof(records,'000001','2024-10-31'))

    def test_duplicate_bad_times_and_unannounced_suspension_rejected(self):
        for mutate in (lambda p:p['daily'].append(p['daily'][0]),
                       lambda p:p['daily'].pop(40),
                       lambda p:p['financials'][0].update(available_at='2020-01-01'),
                       lambda p:p['daily'][0].update(suspended='false')):
            p=copy.deepcopy(self.payload);mutate(p)
            with self.assertRaises(ValueError):HistoryDataset(p)

    def test_st_and_suspensions_not_silently_deleted(self):
        audit=self.ds.audit(self.ds.calendar[-1])
        self.assertEqual(audit['timeline'][72]['suspended'],1)
        self.assertEqual(audit['timeline'][72]['st'],1)
        r=strict_backtest(self.ds,self.ds.calendar[-1])
        self.assertTrue(any(s['excluded']['st'] for s in r['selections']))
        for s in r['selections']:
            self.assertLess(s['signal_date'],s['execution_date'])
            self.assertTrue(set(s['target'])<=set(s['pool']))

    def test_late_data_cannot_change_prior_selection_or_account(self):
        cutoff=self.ds.calendar[89]
        p=copy.deepcopy(self.payload)
        for r in p['financials']:
            if r['version']=='correction':r['values']['roe']=9000
        for r in p['daily']:
            if r['date']>cutoff and not r['suspended']:
                for k in ('raw_open','raw_high','raw_low','raw_close','close','reference_price'):r[k]*=1.2
        for factor in ('momentum','roe'):
            a=strict_backtest(self.ds,cutoff,factor=factor)
            b=strict_backtest(HistoryDataset(p),cutoff,factor=factor)
            for key in ('equity','orders','selections','metrics'):self.assertEqual(a[key],b[key])

    def test_delisted_position_is_settled_and_missing_exit_blocks(self):
        r=strict_backtest(self.ds,self.ds.calendar[-1])
        self.assertTrue(r['settlements'])
        self.assertEqual(r['settlements'][0]['kind'],'scenario')
        p=copy.deepcopy(self.payload);p['settlements']=[]
        with self.assertRaisesRegex(ValueError,'缺少退出'):strict_backtest(HistoryDataset(p),self.ds.calendar[-1])

    def test_integer_shares_capacity_cash_and_fees(self):
        r=strict_backtest(self.ds,self.ds.calendar[-1])
        for o in r['orders']:
            self.assertIsInstance(o['filled'],int)
            if o['filled']:
                self.assertLessEqual(o['filled'],o['auction_capacity'])
                self.assertGreater(o['fees'],0)
        self.assertAlmostEqual(r['fees'],sum(o.get('fees',0) for o in r['orders']))
        self.assertTrue(all(e['cash']>=0 for e in r['equity']))
        self.assertTrue(all(o['date']>o['signal_date'] for o in r['orders']))

    def test_missing_auction_volume_does_not_use_total_volume(self):
        p=copy.deepcopy(self.payload)
        for r in p['daily']:r.pop('auction_volume_shares',None)
        r=strict_backtest(HistoryDataset(p),self.ds.calendar[-1])
        self.assertTrue(r['orders']);self.assertFalse(any(o['filled'] for o in r['orders']))
        self.assertEqual(r['equity'][-1]['value'],r['capital'])

    def test_corporate_action_across_suspension_blocks(self):
        p=copy.deepcopy(self.payload)
        # Fastest momentum guarantees the affected symbol is selected before the gap.
        for r in p['daily']:
            if r['code']=='600001' and r['date']>=self.ds.calendar[45]:r['close']*=2
        with self.assertRaisesRegex(ValueError,'复权因子'):strict_backtest(HistoryDataset(p),self.ds.calendar[70])

    def test_store_export_replay_and_content_tamper(self):
        with tempfile.TemporaryDirectory() as root:
            d=dispatch({'action':'demo'},root);identifier=d['dataset_id']
            run=dispatch({'action':'run','dataset_id':identifier,'end':d['asof'],'config':{'factor':'roe'}},root)
            replay=dispatch({'action':'replay','dataset_id':identifier,'end':d['asof'],'config':{'factor':'roe'},'expected_hash':run['result_hash']},root)
            self.assertTrue(replay['matched'])
            self.assertEqual(dispatch({'action':'export','dataset_id':identifier},root)['dataset'],self.payload)
            p=Path(root)/'point_in_time'/(identifier+'.json');value=json.loads(p.read_text(encoding='utf-8'));value['provenance']['source']='changed';p.write_text(json.dumps(value),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'校验'):PITStore(root).load(identifier)

class DailyRuleTests(unittest.TestCase):
    def rule(self,code='600001',day='2025-01-02',**kw):
        return daily_rule(code,day,{'is_st':False,'suspended':False,**kw},10,10,'2010-01-01')
    def test_rule_changes_use_effective_day(self):
        self.assertEqual(self.rule('300001','2020-08-21')['ratio'],.1)
        self.assertEqual(self.rule('300001','2020-08-24')['ratio'],.2)
        self.assertEqual(self.rule(day='2026-07-03',is_st=True)['ratio'],.05)
        self.assertEqual(self.rule(day='2026-07-06',is_st=True)['ratio'],.1)
    def test_ipo_and_explicit_bands(self):
        r=daily_rule('688001','2025-01-02',{'is_st':False,'suspended':False},10,1,'2025-01-02')
        self.assertIsNone(r['upper'])
        self.assertEqual(self.rule(limit_up=12,limit_down=8)['upper'],12)
        with self.assertRaises(ValueError):self.rule(limit_up=12)
        with self.assertRaises(ValueError):self.rule(special_session='relist')
        self.assertIsNone(self.rule(special_session='relist',no_price_limit=True)['upper'])
    def test_quantities_t1_partial_and_odd_lot(self):
        b={'raw_open':10.,'raw_low':9.8,'raw_high':10.2,'volume_shares':100000,'auction_volume_shares':10000}
        f=lambda rule,side,q,available:execution_quote('600001','2025-01-02',b,rule,side,q,available,.001,.02)
        self.assertEqual(f(self.rule(),'buy',1500,0)['filled'],200)
        self.assertEqual(f(self.rule(),'sell',100,0)['filled'],0)
        self.assertEqual(f(self.rule(),'sell',73,73)['filled'],73)
        self.assertEqual(f(self.rule('688001'),'buy',199,0)['filled'],0)
    def test_locked_open_and_tick_rounding(self):
        b={'raw_open':11,'raw_high':11,'raw_low':11,'volume_shares':10000,'auction_volume_shares':10000}
        self.assertEqual(execution_quote('600001','2025-01-02',b,self.rule(),'buy',100,0,0,.1)['filled'],0)
        self.assertEqual(price_tick(10.005),10.01)

if __name__=='__main__':unittest.main()
