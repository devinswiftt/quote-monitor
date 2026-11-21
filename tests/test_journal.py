import json,sqlite3,unittest
from hk_quote.pagination import alert_page
from hk_quote.behavior_store import initialize
from hk_quote.engine import timestamp

class JournalTests(unittest.TestCase):
 def setUp(self):
  self.db=sqlite3.connect(':memory:');self.db.execute('CREATE TABLE alerts(id INTEGER PRIMARY KEY,payload TEXT)');initialize(self.db)
  self.ts=timestamp('2026-11-19 14:00')
 def tearDown(self):self.db.close()
 def add_behavior(self,ident,offset=1,kind='DUMP'):
  r=dict(code='HK.02206',name='新荷花',type=kind,started_at=self.ts+offset,updated_at=self.ts+offset+30,phase='resolved',history=[dict(ts=self.ts+offset,type=kind,phase='confirmed')],participation=dict(ask=[dict(name='凯基',id='2338')]))
  self.db.execute('INSERT INTO behavior_events VALUES (?,?,?,?,?,?)',(ident,str(ident),r['code'],r['started_at'],r['updated_at'],json.dumps(r)))
 def test_standalone_behavior_and_alert_have_distinct_ids_and_time_order(self):
  self.db.execute('INSERT INTO alerts VALUES (1,?)',(json.dumps(dict(code='HK.02206',ts=self.ts,signal='BUY')),));self.add_behavior(1)
  result=alert_page(self.db,{})
  self.assertEqual([r['id'] for r in result['alerts']],['B1',1]);self.assertEqual(result['total'],2)
  self.assertEqual(result['alerts'][0]['behavior']['alert_ids'],[])
  for args in ({'signal':['DUMP']},{'symbol':['02206'],'search':['凯基'],'date':['2026-11-19']}):
   self.assertEqual(alert_page(self.db,args)['alerts'][0]['id'],'B1')
  self.assertEqual(alert_page(self.db,{'signal':['LIFT']})['total'],0)
 def test_frozen_two_source_pagination_and_status_update(self):
  for i in range(1,26):self.add_behavior(i,i)
  first=alert_page(self.db,{})
  args={'page':['2'],'anchor':[str(first['pagination']['anchor'])],'behavior_anchor':[str(first['pagination']['behavior_anchor'])]}
  expected=[r['id'] for r in alert_page(self.db,args)['alerts']]
  self.add_behavior(26,26);self.db.execute('INSERT INTO alerts VALUES (99,?)',(json.dumps(dict(code='HK.02206',ts=self.ts+99,signal='BUY')),))
  self.assertEqual([r['id'] for r in alert_page(self.db,args)['alerts']],expected)
  self.db.execute("UPDATE behavior_events SET updated=updated+100,payload=json_set(payload,'$.phase','ongoing') WHERE id=1")
  self.assertEqual([r['id'] for r in alert_page(self.db,args)['alerts']],expected)
  self.assertEqual(alert_page(self.db,{})['total'],27)
 def test_associated_alert_stays_linked_without_extra_behavior_rows(self):
  self.add_behavior(21)
  self.db.execute('INSERT INTO alerts VALUES (158,?)',(json.dumps(dict(code='HK.02206',ts=self.ts,signal='SELL',price=110)),))
  self.db.execute('INSERT INTO behavior_links VALUES (21,158)')
  result=alert_page(self.db,{})
  self.assertEqual(result['total'],2)
  event=next(r['behavior'] for r in result['alerts'] if r['entry_type']=='behavior')
  self.assertEqual(event['alert_ids'],[158]);self.assertEqual(event['signals'][0]['id'],158)

 def test_group_filters_links_and_date_scope(self):
  self.add_behavior(21)
  self.add_behavior(22,kind='LIFT')
  for ident,kind in enumerate(('BUY','SELL','VOLUME','depth'),1):
   self.db.execute('INSERT INTO alerts VALUES (?,?)',(ident,json.dumps(dict(code='HK.02206',ts=self.ts,kind=kind))))
  self.db.execute('INSERT INTO behavior_links VALUES (21,2)')
  trade=alert_page(self.db,{'signal':['trade'],'date':['2026-11-19'],'symbol':['02206']})
  self.assertEqual(trade['total'],3)
  self.assertTrue(all(r['entry_type']=='alert' for r in trade['alerts']))
  sell=next(r for r in trade['alerts'] if r['id']==2)
  self.assertEqual(sell['related_behaviors'],[dict(id=21,type='DUMP')])
  behavior=alert_page(self.db,{'signal':['behavior'],'date':['2026-11-19'],'symbol':['02206']})
  self.assertEqual(behavior['total'],2)
  self.assertTrue(all(r['entry_type']=='behavior' for r in behavior['alerts']))
  self.assertEqual(alert_page(self.db,{'signal':['behavior'],'date':['2026-11-18']})['total'],0)
  self.assertEqual(alert_page(self.db,{'signal':['behavior'],'symbol':['02065']})['total'],0)
  self.assertEqual(alert_page(self.db,{'signal':['trade'],'behavior_anchor':['20']})['alerts'][1]['related_behaviors'],[])
