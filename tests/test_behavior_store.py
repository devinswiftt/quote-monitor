import json
from pathlib import Path
import tempfile
import unittest
from hk_quote.storage import Storage
from hk_quote.behavior_store import BehaviorMonitor,read_behaviors
from hk_quote.participation import Participation
from test_behavior import START,CODE,tick,book

class BehaviorStorageTests(unittest.TestCase):
    def prepare(self,monitor,participation):
        for t in range(0,181,3):
            monitor.process(book(t),participation);monitor.process(tick(t),participation)
        for t in range(181,191):
            price=round(10.01+(t-181)*.02,4)
            monitor.process(tick(t,price,6000),participation)
            monitor.process(book(t,bid=price-.01,ask=price+.01),participation)

    def test_link_preserves_original_and_metric_refresh_does_not_repeat_notifications(self):
        with tempfile.TemporaryDirectory() as d:
            store=Storage(str(Path(d)/'q.db'));notices=[];p=Participation()
            m=BehaviorMonitor(store,notify=notices.append);self.prepare(m,p)
            self.assertEqual(len(notices),1)
            a=dict(code=CODE,signal='BUY',ts=START+185,amount=6000,price=10.09,multiple=10,depth=10,coverage=1,direction_ratio=1,level='关注')
            ident=store.alert(a);original=store.db.execute('SELECT payload FROM alerts WHERE id=?',(ident,)).fetchone()[0]
            self.assertTrue(m.link_alert(ident,a));self.assertTrue(m.linked_confirmed(ident))
            m.poll(START+202,p)
            self.assertEqual(store.db.execute('SELECT payload FROM alerts WHERE id=?',(ident,)).fetchone()[0],original)
            rows=read_behaviors(store.db,START,START+86400)
            self.assertEqual(len(rows),1);self.assertEqual(rows[0]['alert_ids'],[ident]);self.assertEqual(rows[0]['signals'][0]['id'],ident)
            self.assertLessEqual(len(notices),2) # only a material cooling transition, not metrics/profile
            m.stop(CODE,'停止测试',START+203,p)
            self.assertEqual(read_behaviors(store.db,START,START+86400)[0]['phase'],'interrupted')
            store.close()

    def test_unclean_restart_closes_stale_active_episode(self):
        with tempfile.TemporaryDirectory() as d:
            path=str(Path(d)/'q.db');store=Storage(path);p=Participation();m=BehaviorMonitor(store);self.prepare(m,p)
            self.assertIn(read_behaviors(store.db,START,START+86400)[0]['phase'],('confirmed','ongoing'))
            store.close();store=Storage(path);BehaviorMonitor(store)
            self.assertEqual(read_behaviors(store.db,START,START+86400)[0]['phase'],'interrupted')
            store.close()

    def test_legacy_database_without_behavior_table_is_readable(self):
        import sqlite3
        with sqlite3.connect(':memory:') as db:self.assertEqual(read_behaviors(db,START,START+86400),[])

    def test_status_reports_calibration_instead_of_silent_readiness(self):
        with tempfile.TemporaryDirectory() as d:
            store=Storage(str(Path(d)/'q.db'));m=BehaviorMonitor(store);p=Participation()
            self.assertEqual(m.status(CODE,START)['state'],'warming')
            m.process(book(0),p);m.process(tick(0),p)
            self.assertEqual(m.status(CODE,START+61)['state'],'collecting')
            store.close()
