import json
from pathlib import Path
import tempfile
import unittest
from hk_quote.storage import Storage


class LatestStateTests(unittest.TestCase):
    def test_snapshots_keep_history_and_latest_quantities(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Storage(str(Path(directory) / 'test.sqlite3'))
            for ts, volume in [(1, 500), (2, 1000)]:
                store.event(ts, dict(kind='book_snapshot', code='HK.02065', ts=ts,
                                     bid=[[10, volume, 2]], ask=[[11, 3000, 4]]))
            store.event(2, dict(kind='broker_stats', code='HK.02065', ts=2,
                        rows=[dict(broker_name='测试', net_vol=-100, buy_sell_type=2)]))
            self.assertEqual(store.db.execute('SELECT count(*) FROM events').fetchone()[0], 3)
            rows = dict(store.db.execute('SELECT kind,payload FROM latest_state'))
            self.assertEqual(json.loads(rows['book_snapshot'])['bid'][0][1], 1000)
            self.assertEqual(json.loads(rows['broker_stats'])['rows'][0]['net_vol'], -100)
            store.close()
