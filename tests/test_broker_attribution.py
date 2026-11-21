import unittest,sqlite3,json
from hk_quote.broker_attribution import BrokerAttribution
from hk_quote.engine import timestamp

class DelayedBrokerTests(unittest.TestCase):
 def setUp(self):
  self.db=sqlite3.connect(':memory:');self.db.execute('CREATE TABLE broker_samples(id INTEGER PRIMARY KEY,code TEXT,source_time TEXT,observed REAL,payload TEXT,after_close INTEGER)');self.start=timestamp('2026-11-19 00:00');self.event=dict(code='HK.02206',ts=timestamp('2026-11-19 10:00:30'),signal='BUY',reference='#1')
 def tearDown(self):self.db.close()
 def sample(self,source,rows,delay=30):
  values=[dict(broker_name=name,net_vol=amount,data_time_str=source) for name,amount in rows.items()]
  self.db.execute('INSERT INTO broker_samples(code,source_time,observed,payload,after_close) VALUES (?,?,?,?,0)',('HK.02206',source,timestamp(source)+delay,json.dumps(dict(rows=values))))
 def analyze(self,others=()):return BrokerAttribution(self.db,self.start,self.start+86400,[self.event]+list(others)).analyze(self.event)
 def test_source_time_not_received_time_and_wait_for_coverage(self):
  self.sample('2026-11-19 10:00:00',{'凯基':100},delay=300)
  self.assertEqual(self.analyze()['status'],'waiting')
  self.sample('2026-11-19 10:01:00',{'凯基':600})
  r=self.analyze();self.assertEqual(r['candidates'][0]['delta'],500);self.assertEqual(r['before_delay'],300)
 def test_shared_interval_and_absent_broker_is_not_zero(self):
  self.sample('2026-11-19 10:00:00',{'凯基':100,'荷银':50})
  self.sample('2026-11-19 10:01:00',{'凯基':600,'富途':1000})
  r=self.analyze([dict(self.event,ts=self.event['ts']+10,reference='#2')]);self.assertEqual(r['status'],'interval');self.assertEqual(len(r['candidates']),1);self.assertEqual(len(r['unmatched']),2)
 def test_same_source_revision_is_not_new_interval_and_prior_day_is_excluded(self):
  self.sample('2026-11-18 10:00:00',{'凯基':1})
  self.assertEqual(self.analyze()['status'],'insufficient')
  self.sample('2026-11-19 10:00:00',{'凯基':100});self.sample('2026-11-19 10:00:00',{'凯基':200})
  self.assertEqual(self.analyze()['status'],'waiting')
  self.sample('2026-11-19 10:01:00',{'凯基':600});r=self.analyze();self.assertEqual(r['candidates'][0]['delta'],400);self.assertEqual(r['same_time_revisions'],1)
 def test_large_gap_not_attributed(self):
  self.sample('2026-11-19 09:40:00',{'凯基':1});self.sample('2026-11-19 10:01:00',{'凯基':600});self.assertEqual(self.analyze()['status'],'insufficient')
