import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from datetime import datetime
from hk_quote.engine import HK
from hk_quote.participation import Participation
from hk_quote.reconstruction import reconstruct

class ReconstructionTests(unittest.TestCase):
    def test_replay_matches_live_even_when_next_event_arrives_after_retention(self):
        start=datetime(2026,11,16,tzinfo=HK).timestamp()
        trigger=start+100
        alert=dict(code='HK.02065',ts=trigger,received_at=trigger,signal='BUY')
        live=Participation();events=[]
        for second in range(30,111):
            e=dict(kind='broker',source='push',code=alert['code'],received_at=start+second,
                   bid=[dict(id='1001',name='甲',position=1 if second>=90 else 2)],ask=[])
            events.append((start+second,e));live.observe(start+second,e)
        expected=live.analyze(alert,trigger)
        # A later event must not evict evidence before pending records are finalized.
        events.append((start+1000,dict(kind='broker',source='push',code=alert['code'],bid=[],ask=[])))
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'q.sqlite3'
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE alerts(id INTEGER PRIMARY KEY,payload TEXT)')
                db.execute('CREATE TABLE events(id INTEGER PRIMARY KEY,received REAL,payload TEXT)')
                db.execute('INSERT INTO alerts VALUES (1,?)',(json.dumps(alert),))
                db.execute('INSERT INTO alerts VALUES (2,?)',(json.dumps(dict(alert,participation=dict(status='pending'))),))
                db.executemany('INSERT INTO events(received,payload) VALUES (?,?)',[(t,json.dumps(e)) for t,e in events])
            result=reconstruct(path,'2026-11-16',update=True)
            self.assertEqual(len(result),1)
            actual=result[0]['profile'];actual.pop('replayed')
            self.assertEqual(actual,expected)
            with sqlite3.connect(path) as db:
                stored=json.loads(db.execute('SELECT payload FROM alerts WHERE id=1').fetchone()[0])
                self.assertEqual(stored['participation']['version'],2)
                pending=json.loads(db.execute('SELECT payload FROM alerts WHERE id=2').fetchone()[0])
                self.assertEqual(pending['participation']['status'],'pending')
