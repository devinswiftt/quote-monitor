from datetime import datetime
import json,sqlite3,unittest
from hk_quote.broker_archive import initialize,save
from hk_quote.engine import HK
class ArchiveTests(unittest.TestCase):
 def setUp(self):
  self.db=sqlite3.connect(':memory:');self.db.execute('CREATE TABLE events(id INTEGER PRIMARY KEY,received REAL,payload TEXT)');initialize(self.db)
 def tearDown(self):self.db.close()
 def event(self,date='2026-11-18',stamp='16:15:00'):
  return dict(kind='broker_stats',code='HK.02206',ts=datetime(2026,11,18,16,20,tzinfo=HK).timestamp(),rows=[dict(data_time_str=date+' '+stamp,broker_name='凯基',net_vol=100)])
 def test_source_dates_not_request_date(self):
  save(self.db,self.event('2026-11-17'),True)
  self.assertEqual(self.db.execute('SELECT date,after_close FROM broker_daily').fetchone(),('2026-11-17',0))
 def test_archive_success_and_older_snapshot_cannot_overwrite(self):
  save(self.db,self.event(),True);save(self.db,self.event(stamp='09:00:00'))
  self.assertEqual(self.db.execute('SELECT source_time,after_close FROM broker_daily').fetchone(),('2026-11-18 16:15:00',1))
  event=self.event('2026-11-17');save(self.db,event)
  self.assertEqual(self.db.execute('SELECT COUNT(*) FROM broker_daily').fetchone()[0],2)
 def test_failed_or_undated_rows_do_not_replace_history(self):
  save(self.db,self.event());event=self.event();event['rows']=[];save(self.db,event)
  self.assertEqual(self.db.execute('SELECT COUNT(*) FROM broker_daily').fetchone()[0],1)
 def test_time_series_keeps_revisions_and_deduplicates_unchanged_rows(self):
  from hk_quote.broker_archive import comparison
  event=self.event();save(self.db,event)
  event['ts']+=10;save(self.db,event)
  self.assertEqual(self.db.execute('SELECT COUNT(*) FROM broker_samples').fetchone()[0],1)
  self.assertEqual(self.db.execute('SELECT COUNT(*) FROM broker_captures').fetchone()[0],2)
  event['rows'][0]['net_vol']=-200;event['ts']+=10;save(self.db,event)
  self.assertEqual(self.db.execute('SELECT COUNT(*) FROM broker_samples').fetchone()[0],2)
  result=comparison(self.db,'HK.02206','2026-11-18')
  self.assertEqual(result['changes'][0]['status'],'由净买转净卖')
  self.assertEqual(result['changes'][0]['delta'],-300)
