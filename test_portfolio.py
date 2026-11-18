import unittest
from server import demo
from portfolio import portfolio

class PortfolioTests(unittest.TestCase):
    def setUp(self):self.rows=demo()['bars'][:300]

    def test_shared_date_no_future(self):
        end=self.rows[200]['date']
        a=portfolio([self.rows,self.rows],[.4,.4],end=end)
        b=portfolio([self.rows[:201],self.rows[:201]],[.4,.4],end=end)
        self.assertEqual(a,b)
        self.assertTrue(all(p['date']<=end for p in a['equity']))

    def test_cash_and_accounting(self):
        a=portfolio([self.rows,self.rows],[.3,.4])
        r=self.rows[-1]['close']/self.rows[0]['close']-1
        self.assertAlmostEqual(a['metrics']['return'],r*.7)
        self.assertAlmostEqual(sum(a['current_weights'])+a['cash_weight'],1)
        self.assertAlmostEqual(a['correlation'][0][1],1)
        self.assertAlmostEqual(sum(a['risk_contributions']),1)

    def test_missing_dates_intersection(self):
        missing=self.rows[:50]+self.rows[55:]
        a=portfolio([self.rows,missing],[.5,.5])
        self.assertEqual(a['rows'],len(missing))
        self.assertNotIn(self.rows[51]['date'],[r['date'] for r in a['equity']])

    def test_flat_assets(self):
        rows=[dict(b,close=10) for b in self.rows]
        a=portfolio([rows,rows],[.5,.5])
        self.assertEqual(a['metrics']['return'],0)
        self.assertEqual(a['volatility'],0)
        self.assertIsNone(a['correlation'][0][1])
        self.assertIsNone(a['risk_contributions'][0])

    def test_invalid_weights_and_range(self):
        for weights in ([.8,.8],[float('nan'),.2],[-.1,.2]):
            with self.assertRaises(ValueError):portfolio([self.rows,self.rows],weights)
        with self.assertRaises(ValueError):portfolio([self.rows[:10],self.rows[:10]],[.5,.5])
        with self.assertRaises(ValueError):portfolio([self.rows,self.rows],[.5,.5],start='2026-01-01',end='2025-01-01')

if __name__=='__main__':unittest.main()
