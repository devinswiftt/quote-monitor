from datetime import datetime
import json,sqlite3,unittest
from hk_quote.pagination import alert_page
from hk_quote.engine import HK

class PaginationTests(unittest.TestCase):
 def setUp(self):
  self.db=sqlite3.connect(':memory:');self.db.execute('CREATE TABLE alerts(id INTEGER PRIMARY KEY,payload TEXT)')
  self.ts=datetime(2026,11,17,10,tzinfo=HK).timestamp()
  for i in range(65):
   value=dict(code='HK.02206',ts=self.ts,signal='BUY' if i%2==0 else 'SELL',broker_context=dict(bid=[dict(name='越秀',id='8297')]))
   self.db.execute('INSERT INTO alerts(payload) VALUES (?)',(json.dumps(value),))
 def tearDown(self):self.db.close()
 def test_pages_and_frozen_anchor(self):
  first=alert_page(self.db,{});self.assertEqual(len(first['alerts']),20);self.assertEqual(first['pagination']['pages'],4)
  second=alert_page(self.db,{'page':['2'],'anchor':['65']});ids=[a['id'] for a in second['alerts']]
  self.db.execute('INSERT INTO alerts VALUES (66,?)',(json.dumps(dict(code='HK.02206',ts=self.ts,signal='BUY')),))
  self.assertEqual([a['id'] for a in alert_page(self.db,{'page':['2'],'anchor':['65']})['alerts']],ids)
  self.assertEqual(alert_page(self.db,{})['alerts'][0]['id'],66)
 def test_search_filters_and_empty(self):
  result=alert_page(self.db,{'search':['越秀'],'signal':['BUY'],'date':['2026-11-17'],'page_size':['50']})
  self.assertEqual(result['total'],33)
  self.assertEqual(alert_page(self.db,{'search':['不存在']})['total'],0)
  self.assertEqual(alert_page(self.db,{'date':['2026-11-16']})['total'],0)
 def test_bounds(self):
  self.assertEqual(alert_page(self.db,{'page':['999']})['pagination']['page'],4)
  with self.assertRaises(ValueError):alert_page(self.db,{'page_size':['999']})
 def test_stock_combined_with_filters_and_pagination(self):
  self.db.execute('INSERT INTO alerts(payload) VALUES (?)',(json.dumps(dict(code='HK.02065',name='一微科技',ts=self.ts,signal='BUY')),))
  result=alert_page(self.db,{'symbol':['02065'],'signal':['BUY'],'date':['2026-11-17'],'search':['一微']})
  self.assertEqual(result['total'],1);self.assertEqual(result['alerts'][0]['code'],'HK.02065')
  other=alert_page(self.db,{'symbol':['HK.02206'],'page':['2'],'page_size':['20']})
  self.assertEqual(other['total'],65);self.assertEqual(len(other['alerts']),20)
  self.assertTrue(all(a['code']=='HK.02206' for a in other['alerts']))
  self.assertEqual(alert_page(self.db,{'symbol':['HK.09988']})['total'],0)
  with self.assertRaises(ValueError):alert_page(self.db,{'symbol':['invalid']})
