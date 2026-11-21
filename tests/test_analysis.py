import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from datetime import datetime
from hk_quote.analysis import daily_analysis
from hk_quote.engine import HK

class AnalysisTests(unittest.TestCase):
    def test_live_updates_date_boundary_and_pending(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'data.sqlite3'
            start=datetime(2026,11,16,tzinfo=HK).timestamp()
            a=dict(code='HK.02065',name='一微科技',signal='BUY',ts=start,participation=dict(status='pending',valid_samples=0))
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE alerts (id INTEGER PRIMARY KEY,payload TEXT)')
                db.executemany('INSERT INTO alerts(payload) VALUES (?)',[(json.dumps(dict(a,ts=t)),) for t in (start-1,start,start+86400)])
            result=daily_analysis(path,'2026-11-16')
            self.assertEqual(len(result['rows']),1)
            self.assertEqual(result['rows'][0]['profile']['status'],'pending')
            with sqlite3.connect(path) as db:
                a['participation']=dict(status='ready',valid_samples=21,coverage=1,bid=[],ask=[])
                db.execute('UPDATE alerts SET payload=? WHERE id=2',(json.dumps(a),))
            self.assertEqual(daily_analysis(path,'2026-11-16')['rows'][0]['profile']['status'],'ready')
            with self.assertRaises(ValueError):daily_analysis(path,'invalid')
