import tempfile,unittest
from pathlib import Path
from hk_quote.storage import Storage
from hk_quote.daily import daily_history,daily_bar
class DailyTests(unittest.TestCase):
 def test_cache_and_forced_query(self):
  with tempfile.TemporaryDirectory() as d:
   path=str(Path(d)/'q.db');store=Storage(path);calls=[]
   def fetch(code):calls.append(code);return [dict(time=1,open=1,high=2,low=1,close=2,volume=100,turnover=200,source='daily')]
   first=daily_history(path,'HK.02206',fetch);second=daily_history(path,'HK.02206',fetch)
   self.assertEqual(len(calls),1);self.assertTrue(second['cached']);self.assertEqual(first['adjustment'],'NONE')
   daily_history(path,'HK.02206',fetch,True);self.assertEqual(len(calls),2)
   self.assertEqual(store.db.execute('SELECT COUNT(*) FROM alerts').fetchone()[0],0);store.close()

 def test_official_turnover_not_reconstructed_from_close_and_volume(self):
  row=dict(time_key='2026-11-17',open=10,high=12,low=9,close=11,volume=100,turnover=1025)
  bar=daily_bar(row);self.assertEqual(bar['turnover'],1025)
  row.pop('turnover');self.assertIsNone(daily_bar(row)['turnover'])
