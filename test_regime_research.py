import copy
import itertools
import math
import random
import unittest
from datetime import date,timedelta
import numpy as np
from threadpoolctl import threadpool_limits
from regime_research import (emission_logpdf,forward,filter_step,fit_hmm,transition_matrix,regime_experiment)


def fixture(count=230):
    rng=random.Random(55);price=100.;rows=[]
    for i in range(count):
        s=(i//30)%3
        price*=1+rng.gauss([-.0015,0,.0015][s],[.006,.01,.016][s])
        rows.append({'date':(date(2022,1,3)+timedelta(days=i)).isoformat(),'close':price})
    return rows


class RegimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows=fixture();cls.end=cls.rows[-1]['date']
        with threadpool_limits(limits=1):cls.result=regime_experiment(cls.rows,cls.end)

    def test_forward_matches_exhaustive_paths(self):
        emissions=np.array([[.1,.4,.5],[.6,.3,.1],[.2,.3,.5]])
        a=np.array([[.7,.2,.1],[.1,.7,.2],[.2,.1,.7]]);pi=np.array([.2,.3,.5])
        total=0.;last=np.zeros(3)
        for path in itertools.product(range(3),repeat=3):
            p=pi[path[0]]*emissions[0,path[0]]
            for t in (1,2):p*=a[path[t-1],path[t]]*emissions[t,path[t]]
            total+=p;last[path[-1]]+=p
        filtered,ll,_=forward(np.log(emissions),a,pi)
        self.assertAlmostEqual(ll,math.log(total),places=12)
        np.testing.assert_allclose(filtered[-1],last/total,atol=1e-12)

    def test_filter_does_not_smooth_with_future(self):
        model={'means':np.array([[-1.,0,0],[0,0,0],[1,0,0]]),'variances':np.ones((3,3)),
               'transition':np.array([[.8,.1,.1],[.1,.8,.1],[.1,.1,.8]]),'initial':np.ones(3)/3}
        x=np.array([[-1.,0,0],[0.,0,0],[1.,0,0]])
        short,_,_=forward(emission_logpdf(x[:2],model['means'],model['variances']),model['transition'],model['initial'])
        long,_,_=forward(emission_logpdf(x,model['means'],model['variances']),model['transition'],model['initial'])
        np.testing.assert_allclose(short,long[:2],atol=1e-14)
        np.testing.assert_allclose(filter_step(x[2],model,short[-1]),long[-1],atol=1e-14)

    def test_em_parameters_and_nonconvergence_flag(self):
        rng=np.random.default_rng(20)
        x=np.vstack([rng.normal(loc=[s,s,.5],scale=.2,size=(20,3)) for s in (-2.,0.,2.)])
        with threadpool_limits(limits=1):m=fit_hmm(x,max_iter=1)
        self.assertFalse(m['converged']);self.assertEqual(m['iterations'],1)
        self.assertTrue(np.isfinite(m['log_likelihood']))
        self.assertTrue(np.all(m['variances']>=.001))
        self.assertTrue(np.all(np.diff(m['means'][:,1])>=0))
        np.testing.assert_allclose(m['transition'].sum(axis=1),1)
        np.testing.assert_allclose(m['filtered'].sum(axis=1),1)
        self.assertTrue(np.all(m['transition']>0))

    def test_cutoff_and_historical_predictions_are_stable(self):
        end=self.rows[-11]['date']
        with threadpool_limits(limits=1):
            a=regime_experiment(self.rows,end)
            b=regime_experiment(self.rows[:-10],end)
        self.assertEqual(a,b)
        for k,v in a['results'].items():
            later={r['date']:r for r in self.result['results'][k]['observations']}
            for r in v['observations']:
                for field in ('state','current_probabilities','next_state_probabilities','prediction','up_probability','train_end','anchor'):
                    self.assertEqual(r[field],later[r['date']][field])
        self.assertIsNone(a['results']['hmm']['observations'][-1]['actual'])

    def test_perturbing_test_cannot_change_earlier_filters(self):
        changed=copy.deepcopy(self.rows)
        day=self.result['results']['hmm']['observations'][10]['date']
        for r in changed:
            if r['date']>day:r['close']*=1.1
        with threadpool_limits(limits=1):b=regime_experiment(changed,self.end)
        for k in self.result['results']:
            for a,z in zip(self.result['results'][k]['observations'],b['results'][k]['observations']):
                if a['date']<=day:
                    self.assertEqual(a['prediction'],z['prediction'])
                    self.assertEqual(a['current_probabilities'],z['current_probabilities'])

    def test_scores_labels_and_probability_budgets(self):
        counts=[]
        for v in self.result['results'].values():
            valid=[r for r in v['observations'] if r['actual'] is not None];m=v['metrics'];counts.append(m['samples'])
            self.assertEqual(m['samples'],len(valid))
            self.assertEqual(sum(c['count'] for c in m['calibration']),len(valid))
            self.assertAlmostEqual(m['brier'],sum((r['up_probability']-(r['actual']>0))**2 for r in valid)/len(valid))
            for r in v['observations']:
                self.assertLess(r['train_end'],r['date'])
                self.assertAlmostEqual(sum(r['current_probabilities']),1)
                self.assertAlmostEqual(sum(r['next_state_probabilities']),1)
                self.assertTrue(0<=r['up_probability']<=1)
                if r['label_end'] is not None:self.assertLess(r['date'],r['label_end'])
        self.assertEqual(len(set(counts)),1)

    def test_training_scaler_and_fold_boundaries(self):
        f=self.result['folds'][0]
        prices=np.array([r['close'] for r in self.rows]);ret=prices[1:]/prices[:-1]-1
        expected=np.array([[ret[i-1],prices[i]/prices[i-20]-1,np.std(ret[i-20:i],ddof=1)] for i in range(20,146)])
        np.testing.assert_allclose(f['scaler_mean'],expected.mean(axis=0),atol=1e-14)
        for fold in self.result['folds']:
            self.assertLess(fold['train_end'],fold['test_start'])
            self.assertLessEqual(fold['test_end'],self.end)

    def test_exported_parameters_reproduce_prediction(self):
        fold=self.result['folds'][0];model=fold['model_parameters']['hmm']
        price=np.array([r['close'] for r in self.rows]);ret=price[1:]/price[:-1]-1
        i=[r['date'] for r in self.rows].index(fold['test_start'])
        raw=np.array([ret[i-1],price[i]/price[i-20]-1,np.std(ret[i-20:i],ddof=1)])
        feature=(raw-fold['scaler_mean'])/fold['scaler_scale']
        numerical={k:np.array(model[k]) for k in ('means','variances','transition','initial')}
        p=filter_step(feature,numerical,np.array(model['train_end_filtered']))
        row=self.result['results']['hmm']['observations'][0]
        np.testing.assert_allclose(p,row['current_probabilities'],atol=1e-14)
        self.assertAlmostEqual(float(p@numerical['transition']@np.array(model['state_return_means'])),row['prediction'])
        self.assertAlmostEqual(float(p@numerical['transition']@np.array(model['state_up_probabilities'])),row['up_probability'])

    def test_smoothing_and_invalid_inputs(self):
        a=transition_matrix([1,1,1]);np.testing.assert_allclose(a.sum(axis=1),1)
        np.testing.assert_allclose(a[0],[1/3]*3)
        for kwargs in ({'lookback':True},{'lookback':125},{'threshold':float('nan')},{'threshold':.9}):
            with self.assertRaises(ValueError):regime_experiment(self.rows,self.end,**kwargs)
        with self.assertRaises(ValueError):regime_experiment(self.rows[:180],self.end)
        with self.assertRaises(ValueError):regime_experiment([dict(r,close=100) for r in self.rows],self.end)
        with self.assertRaises(ValueError):regime_experiment(self.rows+[self.rows[-1]],self.end)
        invalid=copy.deepcopy(self.rows);invalid[20]['close']=float('inf')
        with self.assertRaises(ValueError):regime_experiment(invalid,self.end)


if __name__=='__main__':unittest.main()
