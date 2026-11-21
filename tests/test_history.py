import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from hk_quote.storage import Storage
from hk_quote.history import read_history


class HistoryTests(unittest.TestCase):
    def test_backfill_old_notifications_and_persist_new_ones(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'quotes.sqlite3'
            old = dict(code='HK.02065', ts=1794800000, signal='BUY', amount=30000,
                       multiple=5, direction_ratio=.9, coverage=.95, depth=10, level='较强')
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE alerts(id INTEGER PRIMARY KEY,payload TEXT)')
                db.execute('INSERT INTO alerts(payload) VALUES (?)', (json.dumps(old),))
            store = Storage(str(path))
            report = path.with_suffix('.alerts.md')
            self.assertIn('疑似集中主动买入', report.read_text())
            store.alert(dict(kind='depth', code='HK.02065', ts=1794800100, message='一档提醒'))
            store.close()
            text = report.read_text()
            self.assertIn('一档提醒', text)
            self.assertIn('30,000', text)
            latest = read_history(str(path), limit=1)
            self.assertIn('一档提醒', latest)
            self.assertNotIn('30,000', latest)
