import json
from pathlib import Path
import tempfile
import unittest
from hk_quote.storage import Storage
from hk_quote.behavior_replay import replay
from hk_quote.behavior_store import read_behaviors
from test_behavior import START,CODE,tick,book

class BehaviorReplayTests(unittest.TestCase):
    def test_replay_is_labeled_and_does_not_relabel_raw_alerts(self):
        with tempfile.TemporaryDirectory() as d:
            path=str(Path(d)/'q.db');s=Storage(path)
            for t in range(0,181,3):
                s.event(START+t,book(t));s.event(START+t,tick(t))
            for t in range(181,191):
                price=round(10.01+(t-181)*.02,4)
                s.event(START+t,tick(t,price,6000));s.event(START+t,book(t,bid=price-.01,ask=price+.01))
            a=dict(code=CODE,signal='BUY',ts=START+185,amount=6000,price=10.09,multiple=10,depth=10,coverage=1,direction_ratio=1,level='关注')
            aid=s.alert(a);before=s.db.execute('SELECT payload FROM alerts').fetchall()
            self.assertEqual(replay(path,'2026-11-16'),1)
            rows=read_behaviors(s.db,START,START+86400)
            self.assertEqual(rows[0]['source'],'replay')
            self.assertEqual(rows[0]['phase'],'interrupted')
            self.assertTrue(any(h['phase']=='confirmed' for h in rows[0]['history']))
            self.assertEqual(rows[0]['alert_ids'],[aid])
            self.assertEqual(s.db.execute('SELECT payload FROM alerts').fetchall(),before)
            self.assertEqual(replay(path,'2026-11-16'),1)
            self.assertEqual(s.db.execute('SELECT payload FROM alerts').fetchall(),before)
            s.close()
