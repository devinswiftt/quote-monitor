import json,sqlite3,unittest
from hk_quote.dashboard import read_latest_events

class DailyStateTests(unittest.TestCase):
 def test_legacy_daily_payload_does_not_break_latest_quotes(self):
  with sqlite3.connect(':memory:') as db:
   db.execute('CREATE TABLE latest_state(code TEXT,kind TEXT,payload TEXT)')
   db.execute('INSERT INTO latest_state VALUES (?,?,?)',('HK.02206','daily_history',json.dumps(dict(code='HK.02206',ts=1,bars=[]))))
   db.execute('INSERT INTO latest_state VALUES (?,?,?)',('HK.02206','quote',json.dumps(dict(code='HK.02206',kind='quote',price=82,ts=2))))
   events=read_latest_events(db)
   self.assertEqual([e['kind'] for e in events],['daily_history','quote'])
   self.assertEqual(next(e for e in events if e['kind']=='quote')['price'],82)
 def test_keys_override_payload_metadata(self):
  with sqlite3.connect(':memory:') as db:
   db.execute('CREATE TABLE latest_state(code TEXT,kind TEXT,payload TEXT)')
   db.execute('INSERT INTO latest_state VALUES (?,?,?)',('HK.02206','daily_history',json.dumps(dict(kind='wrong',code='wrong'))))
   self.assertEqual(read_latest_events(db)[0],dict(code='HK.02206',kind='daily_history'))

class SelectedStateTests(unittest.TestCase):
 def test_selected_quote_does_not_load_other_stock_history(self):
  import sqlite3,json
  db=sqlite3.connect(':memory:')
  db.execute('CREATE TABLE latest_state(code TEXT,kind TEXT,payload TEXT)')
  for code in ('HK.02206','US.QQQ'):
   db.execute('INSERT INTO latest_state VALUES (?,?,?)',(code,'quote',json.dumps(dict(price=1,ts=1))))
  selected=read_latest_events(db,'US.QQQ')
  self.assertEqual(len(selected),1);self.assertEqual(selected[0]['code'],'US.QQQ')
  self.assertEqual(len(read_latest_events(db)),2)
