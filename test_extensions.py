import unittest
from unittest.mock import patch
from server import demo
from extensions import factors,machine_learning,execute,minute_data,text_analysis,article
from threadpoolctl import threadpool_limits

class ExtensionTests(unittest.TestCase):
    def setUp(self):self.bars=demo()['bars'][:500];self.series={'600519':self.bars,'000001':self.bars};self.end=self.bars[-1]['date']

    def test_factor_missing_and_future(self):
        r=factors(self.series,{'600519':{'NOTICE_DATE':'2099-01-01','BPS':100}},self.end,[1]*6)
        self.assertEqual(len(r['used']),2)
        self.assertTrue(all(x['score']==50 for x in r['rows']))
        self.assertEqual(len(r['missing']),4)

    def test_ml_label_purge_and_no_future(self):
        with threadpool_limits(limits=1):
            a=machine_learning(self.series,self.bars[399]['date'],'ridge')
            b=machine_learning({k:v[:400] for k,v in self.series.items()},self.bars[399]['date'],'ridge')
        self.assertEqual(a,b)
        for row in a['validation']:self.assertLess(row['train_label_end'],row['date'])
        self.assertTrue(a['validation_samples']>0)

    def test_execution_capacity_and_conservation(self):
        rows=minute_data('600519',self.end,True)
        for method in ('twap','vwap','pov','iceberg'):
            r=execute(rows,method,10000,'buy',.1,.001)
            self.assertEqual(r['filled']+r['remaining'],10000)
            volumes={x['time']:x['volume'] for x in rows}
            for order in r['orders']:
                self.assertLessEqual(order['quantity'],volumes[order['time']]*.1)
                self.assertEqual(order['quantity']%100,0)
        with self.assertRaises(ValueError):execute(rows[-240:],'vwap',10000,'buy',.1,.001)

    def test_zero_volume_no_false_fill(self):
        rows=[dict(r,volume=0) for r in minute_data('600519',self.end,True)]
        r=execute(rows,'twap',10000,'buy',.1,0)
        self.assertEqual(r['filled'],0);self.assertEqual(r['fees'],0)

    def test_provider_future_minutes_rejected(self):
        upstream={'data':{'klines':['2099-01-01 10:00,10,10,10,10,100,1000,0']}}
        with patch('extensions.get_json',side_effect=[upstream,{'data':{}}]):
            with self.assertRaises(ValueError):minute_data('600519',self.end)

    def test_text_summary_and_negation(self):
        r=text_analysis('公司未出现亏损，营业收入增长 20%，但收到监管处罚。公司提醒经营风险。')
        self.assertIn('20%',r['numbers'])
        self.assertTrue(any(h['word']=='亏损' and h['polarity']==1 for h in r['hits']))
        self.assertIn(r['summary'].split('。')[0],'公司未出现亏损，营业收入增长 20%，但收到监管处罚。公司提醒经营风险。')

    def test_future_article_rejected(self):
        with patch('extensions.get_json',return_value={'data':{'notice_date':'2099-01-01','notice_content':'future'}}):
            with self.assertRaises(ValueError):article('AN202610301831245501',self.end)

if __name__=='__main__':unittest.main()
