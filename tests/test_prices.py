import tempfile
from pathlib import Path
import unittest
from hk_quote.storage import Storage
from hk_quote.engine import timestamp


class PriceTests(unittest.TestCase):
    def test_price_comparison_is_same_stock_same_day_across_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path=str(Path(directory)/'test.sqlite3')
            s=Storage(path)
            def a(code,price,t='2026-11-16 10:00:00'):
                return dict(code=code,price=price,ts=timestamp(t),signal='BUY',amount=30000,multiple=5)
            first=a('HK.02065',10);s.alert(first)
            self.assertIsNone(first['price_delta'])
            s.alert(a('HK.02206',50))
            s.close();s=Storage(path)
            second=a('HK.02065',10.5);s.alert(second)
            self.assertEqual(second['price_delta'],.5)
            self.assertEqual(second['price_delta_pct'],5)
            self.assertEqual(second['previous_alert_id'],1)
            next_day=a('HK.02065',11,'2026-11-17 10:00:00');s.alert(next_day)
            self.assertIsNone(next_day['price_delta'])
            s.close()
