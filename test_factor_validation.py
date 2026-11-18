import copy
import math
import random
import unittest
from datetime import date, timedelta

from factor_validation import correlation, groups, ranks, factor_validation


def fixture(count=340):
    series = {}
    for k in range(6):
        rng = random.Random(410+k)
        price = 30.
        rows = []
        for i in range(count):
            price *= 1+rng.gauss((k-2)*.0002, .009+k*.001)
            rows.append({'date': (date(2022,1,3)+timedelta(days=i)).isoformat(), 'close': price})
        series[str(600000+k)] = rows
    return series


class FactorValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.series=fixture()
        cls.end=cls.series['600000'][-1]['date']
        cls.result=factor_validation(cls.series, cls.end)

    def test_known_correlations_and_ties(self):
        self.assertEqual(ranks([2,1,2,4]), [1.5,0,1.5,3])
        self.assertAlmostEqual(correlation([1,2,3],[10,20,30]), 1)
        self.assertAlmostEqual(correlation([1,2,3],[30,20,10],True), -1)
        self.assertIsNone(correlation([1,1,1],[1,2,3]))
        self.assertIsNone(correlation([1,2],[2,3],True))
        self.assertIsNone(groups([1,1,1,1,1,1],[1,2,3,4,5,6]))
        self.assertEqual(groups([1,2,3,4,5,6],[2,4,6,8,10,12]), [3,7,11])

    def test_cutoff_invariance(self):
        end=self.series['600000'][289]['date']
        a=factor_validation(self.series,end)
        b=factor_validation({c:r[:290] for c,r in self.series.items()},end)
        self.assertEqual(a,b)
        self.assertTrue(all(r['label_end']<=end for r in a['observations']))
        self.assertTrue(all(f['test_label_end']<=end for f in a['folds']))

    def test_common_calendar_alignment(self):
        changed=copy.deepcopy(self.series)
        removed=changed['600001'].pop(150)['date']
        r=factor_validation(changed,self.end)
        self.assertEqual(r['common_rows'],339)
        self.assertNotIn(removed,[r['date'] for r in r['observations']])

    def test_fold_purge_and_train_only_selection(self):
        self.assertGreaterEqual(len(self.result['folds']),2)
        first=self.result['folds'][0]
        for f in self.result['folds']:
            self.assertLess(f['train_label_end'],f['test_start'])
            self.assertLess(f['train_end'],f['test_start'])
            self.assertLessEqual(f['test_label_end'],self.end)
            obs=f['observations']
            for a,b in zip(obs,obs[1:]):
                self.assertLessEqual(a['label_end'],b['date'])
        changed=copy.deepcopy(self.series)
        for k,rows in enumerate(changed.values()):
            for i,b in enumerate(rows):
                if b['date']>=first['test_start']:
                    b['close'] *= math.exp((k-3)*.005*(i+1))
        altered=factor_validation(changed,self.end)['folds'][0]
        for key in ('factor','direction','train_start','train_end','train_label_end','train_mean_rank_ic'):
            self.assertEqual(first[key],altered[key],key)
        for h in (1,5,20):
            result=factor_validation(self.series,self.end,horizon=h)
            observations=[r for f in result['folds'] for r in f['observations']]
            for a,b in zip(observations,observations[1:]):
                self.assertLessEqual(a['label_end'],b['date'],'test return intervals must not overlap across folds')

    def test_decay_same_signal_dates_and_bounded_rank_ic(self):
        r=self.result
        self.assertEqual(len({d['dates'] for d in r['decay']}),1)
        self.assertEqual(r['summary'],{k:v for k,v in r['decay'][1].items() if k!='horizon'})
        self.assertEqual(r['decay'][0]['dates'],r['decay'][2]['dates'])
        first=r['observations'][0]
        dates=[b['date'] for b in self.series['600000']]
        i=dates.index(first['date'])
        ordered=sorted(self.series,key=lambda c:self.series[c][i]['close']/self.series[c][i-20]['close']-1)
        actual=[self.series[c][i+5]['close']/self.series[c][i]['close']-1 for c in ordered]
        self.assertEqual(first['groups'],[sum(actual[j:j+2])/2 for j in (0,2,4)])
        for row in r['observations']:
            self.assertLess(row['date'],row['label_end'])
            for k in ('ic','rank_ic'):
                if row[k] is not None:self.assertLessEqual(abs(row[k]),1.00000001)

    def test_constant_cross_sections_are_undefined(self):
        same={c:self.series['600000'] for c in self.series}
        r=factor_validation(same,self.end)
        self.assertIsNone(r['summary']['mean_ic'])
        self.assertIsNone(r['summary']['mean_rank_ic'])
        self.assertIsNone(r['summary']['rank_ic_ir'])
        self.assertEqual(r['summary']['group_returns'],[None]*3)
        self.assertEqual(r['folds'],[])

    def test_invalid_inputs_are_rejected(self):
        cases=[({'a':self.series['600000']},'momentum20',5),
               (self.series,'future',5),(self.series,'momentum20',True),
               (self.series,'momentum20',5.5),
               ({c:r[:200] for c,r in self.series.items()},'momentum20',5)]
        for series,factor,h in cases:
            with self.subTest(factor=factor,horizon=h):
                with self.assertRaises(ValueError):factor_validation(series,self.end,factor,h)
        invalid=copy.deepcopy(self.series);invalid['600000'][30]['close']=float('nan')
        with self.assertRaises(ValueError):factor_validation(invalid,self.end)
        invalid=copy.deepcopy(self.series);invalid['600000'].append(invalid['600000'][-1])
        with self.assertRaises(ValueError):factor_validation(invalid,self.end)


if __name__=='__main__':unittest.main()
