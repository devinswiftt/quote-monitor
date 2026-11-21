import json,tempfile,unittest
from pathlib import Path
from hk_quote.zhitong import collect,TargetQuotes

class ZhitongTests(unittest.TestCase):
 def get(self,path,args):
  if path=='index.html':return dict(date='2026-11-18',cycle='2026-12-31期',inMarketValue='93.33亿',outMarketValue='58.34亿')
  self.assertEqual(args['status'],1)
  return dict(count=1,list=[dict(SecuCode='09621' if args['child_status']==2 else '02065',SecuAbbr='远信储能',TradingDay='2026-11-18 00:00:00',DbPrice='23.46' if args['child_status']==2 else '--')])
 def test_targets_use_entry_subgroups_and_source_calculation(self):
  result=collect(self.get,now=100)
  self.assertEqual(result['targets']['HK.09621']['target_price'],23.46)
  self.assertIsNone(result['targets']['HK.02065']['target_price'])
  self.assertEqual(result['fetched_at'],100)
  self.assertEqual(result['source_date'],'2026-11-18')
 def test_failed_update_retains_original_timestamp_and_reload(self):
  with tempfile.TemporaryDirectory() as directory:
   path=Path(directory)/'targets.json';q=TargetQuotes(path);q.update(self.get)
   old=q.quote('HK.09621')
   def fail(*args):raise TimeoutError()
   q.update(fail);current=q.quote('HK.09621')
   self.assertEqual(current['target_price'],23.46)
   self.assertEqual(current['fetched_at'],old['fetched_at'])
   self.assertTrue(current['error']);self.assertTrue(q.quote('HK.09621',now=old['fetched_at']+181)['stale'])
   self.assertEqual(TargetQuotes(path).quote('HK.09621')['target_price'],23.46)
 def test_success_without_target_does_not_keep_removed_price(self):
  with tempfile.TemporaryDirectory() as directory:
   q=TargetQuotes(Path(directory)/'targets.json');q.update(self.get)
   def empty(path,args):return self.get(path,args) if path=='index.html' else dict(count=0,list=[])
   q.update(empty)
   self.assertIsNone(q.quote('HK.09621').get('target_price'))
