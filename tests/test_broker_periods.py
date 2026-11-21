from datetime import datetime
import unittest
from hk_quote.engine import HK
from hk_quote.broker_periods import broker_periods

class BrokerPeriodTests(unittest.TestCase):
 def setUp(self):self.start=datetime(2026,11,19,tzinfo=HK).timestamp()
 def sample(self,hour,minute,brokers):
  ts=self.start+hour*3600+minute*60
  return dict(ts=ts,source=f'2026-11-19 {hour:02}:{minute:02}:00',brokers=brokers)
 def test_cumulative_morning_and_afternoon_difference_and_unknown_names(self):
  samples=[self.sample(9,31,{'富途证券':100,'甲':30}),self.sample(11,59,{'富途证券':500,'甲':50}),self.sample(15,59,{'富途证券':200,'乙':80})]
  result=broker_periods([],self.start,self.start+86400,{'HK.02206':samples},now=self.start+86400)['HK.02206']
  rows={r['name']:r for r in result['brokers']}
  self.assertEqual(rows['富途证券']['morning']['net'],500)
  self.assertEqual(rows['富途证券']['afternoon']['net'],-300)
  self.assertEqual(rows['富途证券']['afternoon']['net_direction'],'sell')
  self.assertIsNone(rows['甲']['afternoon']['net']);self.assertIsNone(rows['乙']['morning']['net'])
  self.assertIsNone(rows['乙']['afternoon']['net'])
  self.assertEqual([(r['name'],r['net']) for r in result['summary']['afternoon']['sell']],[('富途证券',-300)])
  self.assertEqual(result['summary']['afternoon']['sell'][0]['channel_profile']['category'],'retail')
 def test_multiple_ids_are_one_broker_and_once_per_side_per_sample(self):
  seats=[dict(id='2453',name='富途证券'),dict(id='8308',name='富途证券'),dict(id='2453',name='富途证券')]
  event=dict(code='HK.02206',bid=seats,ask=seats)
  result=broker_periods([(self.start+34200,event)],self.start,self.start+86400,{},now=self.start+86400)['HK.02206']
  self.assertEqual(len(result['brokers']),1)
  row=result['brokers'][0];self.assertEqual(row['ids'],['2453','8308'])
  self.assertEqual(row['morning']['bid'],4);self.assertEqual(row['morning']['ask'],4)
  self.assertEqual(row['morning']['present'],4);self.assertEqual(row['morning']['share'],.5)
  self.assertIsNone(row['morning']['net'])
 def test_afternoon_requires_noon_baseline_and_does_not_use_future_snapshot(self):
  samples=[self.sample(10,0,{'甲':100}),self.sample(15,0,{'甲':200})]
  value=broker_periods([],self.start,self.start+86400,{'HK.02206':samples},now=self.start+14*3600)['HK.02206']
  row=value['brokers'][0];self.assertIsNone(row['afternoon']['net'])
  self.assertIsNone(value['afternoon_source'])
 def test_same_name_with_unicode_spacing_merges_but_different_names_remain_distinct(self):
  seats=[dict(id='1',name='富途证券'),dict(id='2',name='富途 证券'),dict(id='3',name='富途其他公司')]
  event=dict(code='HK.02206',bid=seats,ask=[])
  rows=broker_periods([(self.start+34200,event)],self.start,self.start+86400,{},now=self.start+86400)['HK.02206']['brokers']
  self.assertEqual(len(rows),2)
  self.assertEqual(next(r for r in rows if r['name']=='富途证券')['ids'],['1','2'])

 def test_volume_sort_uses_exact_latest_source_and_keeps_missing_last(self):
  samples=[self.sample(11,59,{'甲':500,'乙':10,'丙':20,'丁':30}),self.sample(15,59,{'甲':1000,'乙':20,'丙':30,'丁':40})]
  volumes={'HK.02206':{samples[0]['source']:{'甲':999999},samples[1]['source']:{'乙':10000,'丙':5000,'丁':0}}}
  value=broker_periods([],self.start,self.start+86400,{'HK.02206':samples},now=self.start+86400,volumes=volumes)
  rows=value['HK.02206']['brokers']
  self.assertEqual([r['name'] for r in rows],['乙','丙','丁','甲'])
  self.assertIsNone(rows[-1]['total_volume']);self.assertIsNone(rows[-1]['volume_source'])
  self.assertEqual(rows[0]['volume_source'],samples[1]['source'])
