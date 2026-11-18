import copy
import random
import unittest
from datetime import date,timedelta
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
from threadpoolctl import threadpool_limits
from portfolio_optimization import (METHODS,estimate_covariance,solve_weights,rebalance,portfolio_experiment)


def fixture(count=285):
    market=random.Random(700)
    common=[market.gauss(.0001,.006) for _ in range(count)]
    out={}
    for k in range(3):
        rng=random.Random(350+k);price=30.;rows=[]
        for i in range(count):
            opening=price*(1+rng.gauss(0,.002))
            price*=1+common[i]+rng.gauss(.0002,.004+k*.003)
            rows.append({'date':(date(2022,1,3)+timedelta(days=i)).isoformat(),
                'close':price,'raw_close':price,'raw_open':opening,'volume':10000})
        out[str(600000+k)]=rows
    return out


class AllocationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.series=fixture()
        cls.end=cls.series['600000'][-1]['date']
        with threadpool_limits(limits=1):
            cls.result=portfolio_experiment(cls.series,cls.end,lookback=63)

    def test_analytical_diagonal_optima(self):
        q=np.diag([1.,4.,9.])
        inv=np.array([1.,.5,1/3]);inv/=inv.sum()
        minvar=np.array([1.,.25,1/9]);minvar/=minvar.sum()
        np.testing.assert_allclose(solve_weights(q,'risk_parity')['weights'],inv,atol=1e-6)
        np.testing.assert_allclose(solve_weights(q,'min_variance')['weights'],minvar,atol=1e-6)
        np.testing.assert_allclose(solve_weights(q,'inverse_vol')['weights'],inv,atol=1e-12)

    def test_risk_parity_uses_correlation(self):
        q=np.array([[.04,.012,.008],[.012,.09,.03],[.008,.03,.16]])
        risk=solve_weights(q,'risk_parity',.5)
        inverse=solve_weights(q,'inverse_vol',.5)
        self.assertTrue(risk['equal_risk_achieved'])
        self.assertLess(risk['risk_parity_residual'],1e-5)
        self.assertGreater(np.max(np.abs(np.array(risk['weights'])-inverse['weights'])),.01)

    def test_caps_and_inexact_equal_risk_are_disclosed(self):
        q=np.diag([1.,4.,9.])
        for cap in (1/3,.4,.5,1.):
            for m in METHODS:
                r=solve_weights(q,m,cap)
                self.assertAlmostEqual(sum(r['weights']),1,places=7)
                self.assertGreaterEqual(min(r['weights']),-1e-9)
                self.assertLessEqual(max(r['weights']),cap+1e-8)
                self.assertAlmostEqual(sum(r['risk_contributions']),1)
        capped=solve_weights(q,'risk_parity',.4)
        self.assertFalse(capped['equal_risk_achieved'])
        self.assertGreater(capped['risk_parity_residual'],.01)
        np.testing.assert_allclose(solve_weights(np.diag([1.,4.]),'min_variance',.6)['weights'],[.6,.4],atol=1e-7)
        with self.assertRaises(ValueError):solve_weights(q,'risk_parity',.3)

    def test_shrinkage_and_singular_covariance(self):
        rng=np.random.default_rng(10);x=rng.normal(0,.01,(100,3))
        cov,meta=estimate_covariance(x)
        self.assertTrue(0<=meta['shrinkage']<=1)
        self.assertGreater(np.linalg.eigvalsh(cov)[0],0)
        singular=np.tile(x[:,0,None],(1,3))
        cov,meta=estimate_covariance(singular,'sample')
        self.assertGreater(meta['diagonal_jitter'],0)
        self.assertGreater(np.linalg.eigvalsh(cov)[0],0)
        for m in METHODS:solve_weights(cov,m,.5)
        with self.assertRaises(ValueError):estimate_covariance(np.zeros((100,3)))

    def test_solver_failure_is_not_silent_fallback(self):
        failed=SimpleNamespace(success=False,x=np.array([.5,.5]),message='forced failure')
        with patch('portfolio_optimization.minimize',return_value=failed):
            with self.assertRaisesRegex(ValueError,'未收敛'):solve_weights(np.diag([1.,4.]),'min_variance')

    def test_self_financing_cost_and_two_sided_turnover(self):
        units,cash,trade=rebalance([0,0],1000,[10,20],[.5,.5],.01)
        self.assertAlmostEqual(trade['nav_after'],1000/1.01)
        self.assertAlmostEqual(trade['nav_after']+trade['cost'],1000)
        self.assertAlmostEqual(float(units@np.array([10,20]))+cash,trade['nav_after'])
        _,_,sale=rebalance([50,0],500,[10,10],[0,1],.01)
        self.assertAlmostEqual(sale['nav_after'],995/1.01)
        self.assertGreater(sale['gross_turnover'],1.)
        self.assertAlmostEqual(sale['cost'],sale['traded_notional']*.01)
        self.assertAlmostEqual(sale['nav_after']+sale['cost'],1000)

    def test_past_only_training_and_future_cutoff(self):
        end=self.series['600000'][239]['date']
        with threadpool_limits(limits=1):
            full=portfolio_experiment(self.series,end,lookback=63)
            prefix=portfolio_experiment({c:r[:240] for c,r in self.series.items()},end,lookback=63)
        self.assertEqual(full,prefix)
        for event in full['schedule']:
            self.assertEqual(event['training_returns'],63)
            self.assertEqual(event['train_end'],event['signal_date'])
            self.assertLess(event['signal_date'],event['execution_date'])
        self.assertIsNone(full['latest']['execution_date'])
        for r in full['results'].values():
            self.assertTrue(all(p['date']<=end for p in r['equity']))
            self.assertAlmostEqual(sum(r['current_weights'])+r['cash_weight'],1)
            self.assertAlmostEqual(sum(t['cost'] for t in r['trades']),r['total_cost'])

    def test_overnight_gap_cannot_be_earned_before_first_buy(self):
        changed=copy.deepcopy(self.series)
        first=self.result['schedule'][0]
        for rows in changed.values():
            for b in rows:
                if b['date']>=first['execution_date']:
                    for key in ('close','raw_close','raw_open'):b[key]*=2
        with threadpool_limits(limits=1):
            altered=portfolio_experiment(changed,self.end,lookback=63)
        self.assertEqual(first['methods'],altered['schedule'][0]['methods'])
        for m in METHODS:
            self.assertAlmostEqual(self.result['results'][m]['equity'][1]['value'],altered['results'][m]['equity'][1]['value'])

    def test_higher_cost_reduces_net_nav_and_budget_checks(self):
        with threadpool_limits(limits=1):
            free=portfolio_experiment(self.series,self.end,lookback=63,cost_bps=0)
        for m in METHODS:
            costed=self.result['results'][m]
            self.assertLess(costed['equity'][-1]['value'],free['results'][m]['equity'][-1]['value'])
            for t in costed['trades']:
                self.assertAlmostEqual(t['nav_before'],t['nav_after']+t['cost'],places=6)

    def test_invalid_data_and_parameters(self):
        for kwargs in ({'cap':.2},{'lookback':True},{'lookback':64},{'interval':1},
                       {'cost_bps':float('nan')},{'capital':-1},{'cost_bps':101},
                       {'start':'2021-01-01'},{'start':self.end},{'estimator':'made_up'}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):portfolio_experiment(self.series,self.end,**kwargs)
        missing=copy.deepcopy(self.series);del missing['600000'][100]['raw_open']
        with self.assertRaises(ValueError):portfolio_experiment(missing,self.end,lookback=63)
        duplicated=copy.deepcopy(self.series);duplicated['600000'].append(duplicated['600000'][-1])
        with self.assertRaises(ValueError):portfolio_experiment(duplicated,self.end,lookback=63)


if __name__=='__main__':unittest.main()
