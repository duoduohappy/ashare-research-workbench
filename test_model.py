import unittest
from unittest.mock import patch
from datetime import datetime
from model import analyze,validate_bars
from server import demo,symbol_for,quote

class ModelTests(unittest.TestCase):
    def test_no_lookahead(self):
        bars=demo()['bars'];cut=400
        self.assertEqual(analyze(bars)[cut-1],analyze(bars[:cut])[-1])
        altered=bars[:cut]+[dict(b,close=b['close']*100) for b in bars[cut:]]
        self.assertEqual(analyze(bars)[:cut],analyze(altered)[:cut])

    def test_probabilities_and_stationarity(self):
        for frame in analyze(demo()['bars'])[::30]:
            p=frame['matrix'];pi=frame['stationary']
            for row in p:
                self.assertAlmostEqual(sum(row),1)
                self.assertTrue(all(0<v<1 for v in row))
            self.assertAlmostEqual(sum(pi),1)
            for j in range(3):
                self.assertAlmostEqual(sum(pi[i]*p[i][j] for i in range(3)),pi[j],places=7)

    def test_unobserved_state(self):
        bars=[dict(b,close=100) for b in demo()['bars'][:80]]
        f=analyze(bars)[-1]
        self.assertEqual(f['state'],1)
        self.assertAlmostEqual(sum(f['matrix'][0]),1)
        self.assertEqual(f['signal'],0)

    def test_validation(self):
        bars=demo()['bars'][:50]
        self.assertEqual(validate_bars(list(reversed(bars))+bars),bars)
        with self.assertRaises(ValueError):validate_bars([dict(b,close=0) for b in bars])
        with self.assertRaises(ValueError):analyze(bars,0)
        with self.assertRaises(ValueError):analyze(bars,20,float('nan'))
        with self.assertRaises(ValueError):symbol_for('../etc')

    def test_quote_adapter(self):
        fields=['0']*40
        fields[1]='测试股票';fields[3]='10.20';fields[30]='20261118143000';fields[32]='1.2'
        with patch('server.request',return_value='v_sz000001="'+'~'.join(fields)+'";'):
            q=quote('000001')
        self.assertEqual(q['name'],'测试股票');self.assertEqual(q['price'],10.2)

if __name__=='__main__':unittest.main()
