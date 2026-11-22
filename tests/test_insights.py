from datetime import datetime
import unittest
from hk_quote.engine import HK
from hk_quote.insights import queue_analysis,describe_seat

class InsightTests(unittest.TestCase):
 def setUp(self):self.start=datetime(2026,11,19,tzinfo=HK).timestamp()
 def event(self,ts,side='bid'):
  seat=dict(id='8471',name='荷银')
  return ts,dict(code='HK.02206',bid=[seat,seat] if side=='bid' else [],ask=[seat,seat] if side=='ask' else [])
 def test_fixed_samples_deduplicate_seats_and_pushes_and_exclude_gaps(self):
  events=[self.event(self.start+9.5*3600+i*10) for i in range(25)]
  events += [self.event(self.start+13*3600+i*10,'ask') for i in range(25)]
  events += [self.event(self.start+15*3600+i*10,'ask') for i in range(25)]
  base=queue_analysis(events,self.start,self.start+86400)['HK.02206']
  repeated=queue_analysis(events+[self.event(self.start+9.5*3600+.1)]*100,self.start,self.start+86400)['HK.02206']
  self.assertEqual(base,repeated)
  seat=base['seats'][0];self.assertEqual(seat['category'],'buy_to_sell')
  self.assertEqual(seat['morning']['bid'],base['periods']['morning']['valid'])
  self.assertEqual(seat['morning']['share'],1)
  self.assertEqual(seat['afternoon']['share'],0)
  self.assertLess(base['periods']['morning']['coverage'],.1)
  self.assertGreater(seat['afternoon']['ask'],seat['tail']['ask'])
 def test_missing_period_is_not_zero_share(self):
  result=queue_analysis([self.event(self.start+9.5*3600)],self.start,self.start+86400)['HK.02206']
  seat=result['seats'][0]
  self.assertIsNone(seat['afternoon']['share']);self.assertIsNone(seat['shift'])
  self.assertEqual(seat['category'],'other')
 def seat(self,morning,afternoon,tail):
  value={}
  for key,pair in zip(('morning','afternoon','tail'),(morning,afternoon,tail)):
   bid,ask=pair;n=bid+ask
   value[key]=dict(bid=bid,ask=ask,observations=n,share=bid/n if n else None)
  return describe_seat(value)
 def test_tail_reversals_remain_visible_when_whole_afternoon_is_still_buy_biased(self):
  for morning,afternoon,tail in (((662,165),(834,622),(246,346)),((678,204),(692,680),(171,345)),((378,27),(311,184),(44,93))):
   seat=self.seat(morning,afternoon,tail)
   self.assertIn('buy_to_sell',seat['tags']);self.assertIn('tail_buy_to_sell',seat['tags'])
   self.assertIn('tail_change',seat['tags']);self.assertIn('afternoon_sell_strengthening',seat['tags'])
   self.assertIn('尾盘转向卖侧',seat['comparisons'][1]['summary'])
   self.assertNotEqual(seat['comparisons'][0]['delta'],seat['comparisons'][1]['delta'])
 def test_slight_morning_buy_and_afternoon_only_sell_is_included(self):
  for pair in ((70,62),(53,43)):
   seat=self.seat(pair,(0,79),(0,22))
   self.assertIn('afternoon_buy_to_sell',seat['tags'])
   self.assertIn('tail_buy_to_sell',seat['tags'])
   self.assertIn('上午略偏买',seat['comparisons'][0]['summary'])
   self.assertIn('只在卖侧出现',seat['comparisons'][0]['summary'])
 def test_opposite_direction_is_explained_and_sparse_or_tiny_shifts_not_classified(self):
  seat=self.seat((38,310),(35,202),(35,1))
  self.assertIn('tail_sell_to_buy',seat['tags'])
  self.assertNotIn('buy_to_sell',seat['tags'])
  self.assertIn('尾盘转向买侧',seat['comparisons'][1]['summary'])
  tiny=self.seat((51,49),(49,51),(48,52))
  self.assertFalse(tiny['tags'])
  sparse=self.seat((1,0),(0,1),(0,1))
  self.assertFalse(sparse['tags']);self.assertFalse(sparse['comparisons'][1]['enough'])
