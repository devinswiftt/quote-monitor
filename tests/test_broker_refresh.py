import json,tempfile,unittest
from pathlib import Path
from hk_quote.storage import Storage
from hk_quote.broker_refresh import refresh_brokers

class BrokerRefreshTests(unittest.TestCase):
 def test_queries_requested_stock_and_persists_returned_rows(self):
  with tempfile.TemporaryDirectory() as d:
   path=str(Path(d)/'q.db');store=Storage(path);calls=[]
   def fetch(code):calls.append(code);return [dict(broker_name='凯基',net_vol=7100,buy_sell_type=1)]
   result=refresh_brokers(path,'HK.02206',fetch)
   self.assertEqual(calls,['HK.02206'])
   self.assertEqual(result['rows'][0]['net_vol'],7100)
   saved=json.loads(store.db.execute("SELECT payload FROM latest_state WHERE code='HK.02206' AND kind='broker_stats'").fetchone()[0])
   self.assertEqual(saved,result);self.assertEqual(saved['source'],'manual_refresh');store.close()
 def test_failure_does_not_replace_previous_good_data(self):
  with tempfile.TemporaryDirectory() as d:
   path=str(Path(d)/'q.db');store=Storage(path)
   refresh_brokers(path,'HK.02206',lambda code:[dict(broker_name='旧数据')])
   before=store.db.execute('SELECT payload FROM latest_state').fetchone()[0]
   def fail(code):raise RuntimeError('OpenD不可用')
   with self.assertRaises(RuntimeError):refresh_brokers(path,'HK.02206',fail)
   self.assertEqual(store.db.execute('SELECT payload FROM latest_state').fetchone()[0],before);store.close()
