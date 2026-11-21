import unittest
from hk_quote.profile import TurnoverProfile


class ProfileTests(unittest.TestCase):
    def test_no_future_window_leak_and_no_cash_floor(self):
        p = TurnoverProfile()
        for i in range(20):
            p.add(dict(ts=i*3+1, sequence=str(i), amount=1000))
        p.add(dict(ts=64, sequence='burst', amount=1000000))
        value=p.estimate(64)
        self.assertEqual(value['threshold'],1200)
        self.assertEqual(value['samples'],20)

    def test_insufficient_samples_and_dedup(self):
        p=TurnoverProfile()
        e=dict(ts=1,sequence='1',amount=500)
        p.add(e);p.add(e)
        self.assertIsNone(p.estimate(100))
        self.assertEqual(p.estimate(100,minimum=1)['threshold'],600)

    def test_old_history_expires(self):
        p=TurnoverProfile(horizon=60)
        p.add(dict(ts=1,sequence='1',amount=10000))
        self.assertIsNone(p.estimate(100,minimum=1))
