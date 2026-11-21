import unittest
import tempfile
from pathlib import Path
from hk_quote.storage import Storage


class ChartTests(unittest.TestCase):
    def test_chart_source_retains_prices_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Storage(str(Path(directory)/'quotes.sqlite3'))
            tick=dict(kind='tick',code='HK.02065',sequence='1',ts=1794800000,price=10,amount=1000,volume=100)
            store.event(tick['ts'],tick);store.event(tick['ts'],tick)
            self.assertEqual(store.db.execute('SELECT count(*) FROM chart_ticks').fetchone()[0],1)
            self.assertEqual(store.db.execute('SELECT price,volume FROM chart_ticks').fetchone(),(10,100))
            store.close()
