import unittest
from model import analyze
from research import indicators,backtest,fee,metrics
from server import demo

class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.bars=demo()['bars'][:360]
        self.frames=analyze(self.bars)

    def test_indicators_no_future(self):
        self.assertEqual(indicators(self.bars)[:200],indicators(self.bars[:200]))
        self.assertIsNone(indicators(self.bars)[18]['ma20'])
        self.assertIsNotNone(indicators(self.bars)[59]['ma60'])

    def test_backtest_no_future(self):
        end=self.bars[319]['date']
        a=backtest(self.bars,self.frames,'600519',end=end)
        b=backtest(self.bars[:320],self.frames[:320],'600519',end=end)
        self.assertEqual(a,b)
        for r in a['results'].values():
            for t in r['trades']:self.assertLess(t['signal_date'],t['date'])
            self.assertEqual(len(set(t['date'] for t in r['trades'])),len(r['trades']))

    def test_stamp_change_and_minimum(self):
        self.assertAlmostEqual(fee(10000,'2023-08-25',True,0,0),10.1)
        self.assertAlmostEqual(fee(10000,'2023-08-28',True,0,0),5.1)
        self.assertGreaterEqual(fee(10,'2026-01-01',False,.0003,5),5)

    def test_flat_hold_accounting(self):
        bars=[dict(b,close=10,raw_open=10,raw_close=10,raw_high=10,raw_low=10,volume=100) for b in self.bars]
        r=backtest(bars,analyze(bars),'600519',commission=0,min_fee=0,slippage=0)['results']['hold']
        t=r['trades'][0]
        self.assertEqual(t['quantity']%100,0)
        self.assertAlmostEqual(r['equity'][-1]['value'],100000-r['fees'])
        self.assertTrue(r['open_position'])
        self.assertEqual(r['metrics']['max_drawdown'],r['metrics']['return'])

    def test_limit_up_and_suspension(self):
        bars=[dict(b,close=10,raw_open=10,raw_close=10,raw_high=10,raw_low=10,volume=100) for b in self.bars]
        bars[273]=dict(bars[273],raw_open=11,raw_high=11)
        bars[274]=dict(bars[274],volume=0)
        r=backtest(bars,analyze(bars),'600519')['results']['hold']
        self.assertIn('涨停',r['blocked'][0]['reason'])
        self.assertIn('零成交量',r['blocked'][1]['reason'])
        self.assertEqual(r['trades'][0]['date'],bars[275]['date'])

    def test_limit_down_blocks_exit(self):
        bars=[dict(b,close=10+i*.001,raw_open=10+i*.001,raw_close=10+i*.001,volume=100) for i,b in enumerate(self.bars)]
        frames=analyze(bars)
        for frame in frames:frame['signal']=1
        frames[273]['signal']=-1
        bars[274]['raw_open']=bars[273]['raw_close']*.89
        r=backtest(bars,frames,'600519')['results']['filtered']
        self.assertTrue(any('跌停' in b['reason'] for b in r['blocked']))

    def test_initial_loss_counted(self):
        self.assertAlmostEqual(metrics([{'value':90}],100)['max_drawdown'],-.1)

    def test_insufficient_and_invalid(self):
        with self.assertRaises(ValueError):backtest(self.bars[:100],self.frames[:100],'600519')
        with self.assertRaises(ValueError):backtest(self.bars,self.frames,'600519',capital=float('nan'))

if __name__=='__main__':unittest.main()
