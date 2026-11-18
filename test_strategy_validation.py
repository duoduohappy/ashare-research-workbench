import copy
import unittest
import numpy as np
from model import analyze
from research import backtest
from server import demo
from strategy_validation import strategy_validation,block_bootstrap,paired_returns


class StrategyValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows=demo()['bars'][:650];cls.end=cls.rows[-1]['date']
        cls.options={'periods':[20,60],'momenta':[10,20]}
        cls.result=strategy_validation(cls.rows,cls.end,'600519',**cls.options)

    def test_train_selection_and_independent_accounts(self):
        r=self.result
        self.assertGreaterEqual(len(r['folds']),2)
        for f in r['folds']:
            self.assertLess(f['train_end'],f['test_start'])
            self.assertEqual(f['selected'],max(f['cells'],key=lambda c:c['score']))
            self.assertEqual(len(f['test']['results'][r['strategy']]['equity']),63)
            self.assertEqual(f['test']['params']['capital'],r['capital'])
            self.assertEqual(f['test']['start'],f['test_start'])
        expected=np.mean([f['test']['results'][r['strategy']]['metrics']['return'] for f in r['folds']])
        self.assertAlmostEqual(r['summary']['mean_fold_return'],expected)

    def test_cutoff_and_completed_fold_stability(self):
        end=self.rows[589]['date']
        a=strategy_validation(self.rows,end,'600519',**self.options)
        b=strategy_validation(self.rows[:590],end,'600519',**self.options)
        self.assertEqual(a,b)
        self.assertEqual(a['folds'],self.result['folds'])
        self.assertEqual(a['bootstrap'],self.result['bootstrap'])
        self.assertEqual(a['tail_observations'],2)

    def test_test_prices_cannot_change_training_choice(self):
        changed=copy.deepcopy(self.rows);first=self.result['folds'][0]
        for i,b in enumerate(changed):
            if b['date']>=first['test_start']:
                scale=1.1 if i%7<4 else .9
                for k in ('close','raw_open','raw_close','raw_high','raw_low'):b[k]*=scale
        other=strategy_validation(changed,self.end,'600519',**self.options)
        self.assertEqual(first['cells'],other['folds'][0]['cells'])
        self.assertEqual(first['selected'],other['folds'][0]['selected'])

    def test_parameter_tie_break_is_deterministic(self):
        flat=[dict(b,close=10,raw_open=10,raw_close=10,raw_high=10,raw_low=10) for b in self.rows]
        r=strategy_validation(flat,self.end,'600519',periods=[60,20],momenta=[20,10])
        for f in r['folds']:
            self.assertEqual((f['selected']['ma'],f['selected']['momentum']),(20,10))

    def test_cost_scenarios_freeze_selected_parameters(self):
        r=self.result;f=r['folds'][0];ma,mom=f['selected']['ma'],f['selected']['momentum']
        stop=next(i for i,b in enumerate(self.rows) if b['date']==f['test_end'])
        bars=self.rows[:stop+1]
        manual=backtest(bars,analyze(bars),'600519',start=f['test_start'],end=f['test_end'],capital=r['capital'],commission=.0006,slippage=.003,trend_period=ma,momentum_period=mom)
        scenario=next(x for x in f['stress'] if x['commission_bps']==6 and x['slippage_bps']==30)
        self.assertAlmostEqual(scenario['return'],manual['results'][r['strategy']]['metrics']['return'])
        base=next(x for x in f['stress'] if x['commission_bps']==3 and x['slippage_bps']==10)
        self.assertEqual(base['return'],f['test']['results'][r['strategy']]['metrics']['return'])

    def test_extra_lag_uses_older_signal_and_actual_execution_day(self):
        bars=[dict(b,close=10+i*.01,raw_close=10+i*.01,raw_open=10+i*.01,raw_high=10+i*.01,raw_low=10+i*.01) for i,b in enumerate(self.rows[:320])]
        frames=analyze(bars)
        for f in frames:f['signal']=-1
        frames[300]['signal']=1
        a=backtest(bars,frames,'600519',start=bars[301]['date'])['results']['filtered']
        b=backtest(bars,frames,'600519',start=bars[301]['date'],signal_lag=2)['results']['filtered']
        self.assertEqual(a['trades'][0]['date'],bars[301]['date'])
        self.assertEqual(b['trades'][0]['date'],bars[302]['date'])
        self.assertEqual(b['trades'][0]['signal_date'],bars[300]['date'])
        self.assertAlmostEqual(b['trades'][0]['price'],bars[302]['raw_open']*1.001)
        with self.assertRaises(ValueError):backtest(bars,frames,'600519',signal_lag=True)

    def test_bootstrap_preserves_constant_and_is_reproducible(self):
        a=block_bootstrap([np.full(63,.001),np.full(63,.001)])
        self.assertEqual(a,block_bootstrap([np.full(63,.001),np.full(63,.001)]))
        np.testing.assert_allclose(a['interval'],[.001]*3)
        np.testing.assert_allclose(a['samples'],.001)
        self.assertEqual(sum(a['histogram']['counts']),500)
        with self.assertRaises(ValueError):block_bootstrap([[1,2]],block=5)

    def test_paired_returns_include_first_cost_and_match_export(self):
        np.testing.assert_allclose(paired_returns([{'value':99},{'value':100}],100),[-.01,100/99-1])
        r=self.result
        for f in r['folds']:
            expected=paired_returns(f['test']['results'][r['strategy']]['equity'],r['capital'])-paired_returns(f['test']['results']['hold']['equity'],r['capital'])
            np.testing.assert_allclose(expected,f['paired_daily_excess'])
        self.assertAlmostEqual(r['bootstrap']['mean_daily_excess'],np.concatenate([f['paired_daily_excess'] for f in r['folds']]).mean())

    def test_invalid_inputs_and_short_history(self):
        for kwargs in ({'lookback':True},{'lookback':125},{'window':True},{'periods':[20,20]},
                       {'momenta':[7]},{'capital':float('nan')},{'filtered':'yes'},
                       {'periods':[10,20,30,60],'momenta':[10,20,60]}):
            with self.assertRaises(ValueError):strategy_validation(self.rows,self.end,'600519',**kwargs)
        with self.assertRaises(ValueError):strategy_validation(self.rows[:500],self.end,'600519')
        invalid=copy.deepcopy(self.rows);del invalid[300]['raw_open']
        with self.assertRaises(ValueError):strategy_validation(invalid,self.end,'600519')
        with self.assertRaises(ValueError):strategy_validation(self.rows+[self.rows[-1]],self.end,'600519')


if __name__=='__main__':unittest.main()
