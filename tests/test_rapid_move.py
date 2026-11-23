import json
from pathlib import Path
import unittest
from hk_quote.engine import Engine,timestamp
from hk_quote.markets import parse_time
from hk_quote.rapid_move import RapidProfile,RapidDetector,STRATEGY

class RapidMoveTests(unittest.TestCase):
 def setUp(self):
  self.config=json.loads(Path('config/settings.json').read_text())
  self.config['rapid_move']['enabled']=True
  self.config['rapid_move']['windows']=[3]
  self.code='HK.02206';self.start=timestamp('2026-11-19 10:00:00')
 def event(self,t,price=100,amount=10):
  return dict(kind='tick',code=self.code,ts=self.start+t,sequence=str(t),price=price,amount=amount,direction='NEUTRAL')
 def warm(self,engine):
  for i in range(361):self.assertIsNone(engine.process(self.event(i*.5,100+(i%2)*.001)))
 def burst(self,engine,prices,amount=1000):
  results=[]
  for i,p in enumerate(prices):
   a=engine.process(self.event(180.5+i*.5,p,amount))
   if a:results.append(a)
  return results
 def test_volume_without_price_progress_does_not_alert(self):
  e=Engine(self.config);self.warm(e)
  self.assertEqual(self.burst(e,[100,100,100,100]),[])
 def test_single_jump_and_bid_ask_bounce_do_not_alert(self):
  for prices in ([101,101,101,101],[100.1,99.9,100.1,99.9,100.1]):
   e=Engine(self.config);self.warm(e);self.assertEqual(self.burst(e,prices),[])
 def test_price_without_abnormal_volume_does_not_alert(self):
  e=Engine(self.config);self.warm(e)
  self.assertEqual(self.burst(e,[100.1,100.2,100.3,100.4],amount=10),[])
 def test_both_markets_and_directions_use_price_not_unknown_trade_side(self):
  for code in ('HK.02206','US.QQQ'):
   self.code=code;self.start=parse_time('2026-11-20 10:00:00',code)
   for sign in (-1,1):
    e=Engine(self.config);self.warm(e)
    rows=self.burst(e,[100+sign*x for x in (.1,.2,.3,.4)])
    self.assertEqual(len(rows),1)
    a=rows[0];self.assertEqual(a['strategy'],STRATEGY)
    self.assertEqual(a['signal'],'BUY' if sign>0 else 'SELL')
    self.assertEqual(a['coverage'],0)
    self.assertGreaterEqual(a['motion']['efficiency'],.8)
    self.assertLessEqual(a['threshold_profile']['baseline_end'],a['ts']-3)
 def test_fresh_spread_can_block_small_price_progress(self):
  e=Engine(self.config);self.warm(e)
  e.process(dict(kind='book',code=self.code,ts=self.start+180,bid=[[99.8,10,1]],ask=[[100.2,10,1]]))
  self.assertEqual(self.burst(e,[100.1,100.2,100.3,100.4]),[])
 def test_current_burst_cannot_inflate_own_baseline_and_duplicates_do_not_count(self):
  p=RapidProfile(self.code,self.config['rapid_move'])
  for i in range(361):p.add(self.event(i*.5,100+(i%2)*.001))
  before=p.estimate(self.start+181)
  event=self.event(181,101,1000000);p.add(event);p.add(event)
  after=p.estimate(self.start+181)
  self.assertEqual(before,after)
  self.assertEqual(sum(t['amount'] for t in p.recent),p.amount)
 def test_ordinary_large_normal_volatility_sets_its_own_price_threshold(self):
  e=Engine(self.config)
  for i in range(361):
   # Baseline is volatile: a later smooth 0.3% move is ordinary by size.
   self.assertIsNone(e.process(self.event(i*.5,100+(i%7)*.2)))
  self.assertEqual(self.burst(e,[100.1,100.2,100.3,100.4]),[])
 def test_drop_and_reset_require_new_continuous_evidence(self):
  e=Engine(self.config);self.warm(e);e.drop(self.code)
  self.assertEqual(self.burst(e,[100.1,100.2,100.3,100.4]),[])
  e.reset();self.assertEqual(e.profiles[self.code].profiles[0].recent.__len__(),0)
 def test_phase_change_clears_calibration_and_expired_samples_do_not_fill_gaps(self):
  p=RapidProfile(self.code,self.config['rapid_move'])
  for i in range(361):p.add(self.event(i*.5,100+(i%2)*.001))
  self.assertIsNotNone(p.estimate(self.start+181))
  self.assertIsNone(p.estimate(self.start+2000))
  new=self.event(0);new['ts']=timestamp('2026-11-19 13:00:00');p.add(new)
  self.assertIsNone(p.estimate(new['ts']+180))

 def test_longer_window_detects_sustained_move_without_three_second_turnover_burst(self):
  c=dict(self.config['rapid_move'],windows=[3,15,60]);d=RapidDetector(self.code,c)
  for i in range(721):d.add(self.event(i*.5,100+(i%2)*.001,60 if i%20<2 else 10))
  found=[]
  for i in range(1,41):
   t=365+i*.5;d.add(self.event(t,100+i*.02,25))
   a=d.detect(self.start+t)
   if a:found.append(a)
  self.assertTrue(found)
  self.assertTrue(any(a['window_seconds']>3 for a in found))
  self.assertEqual(len(found),1)

 def test_book_ahead_of_trade_does_not_hide_previous_fresh_spread(self):
  e=Engine(self.config);self.warm(e)
  e.process(dict(kind='book',code=self.code,ts=self.start+180,bid=[[99.99,10,1]],ask=[[100.01,10,1]]))
  e.process(dict(kind='book',code=self.code,ts=self.start+182,bid=[[99.99,10,1]],ask=[[100.01,10,1]]))
  rows=self.burst(e,[100.1,100.2,100.3])
  self.assertEqual(len(rows),1)
  self.assertTrue(rows[0]['motion']['spread_available'])


class DarkSessionTests(unittest.TestCase):
 def test_explicit_dark_session_receives_same_detector_and_unmarked_closed_ticks_do_not(self):
  config=json.loads(Path('config/settings.json').read_text())
  start=timestamp('2026-11-23 16:15:00')
  engine=Engine(config)
  def tick(t,price=52,amount=100):
   return dict(kind='tick',code='HK.09941',ts=start+t,sequence=str(t),
               price=price,amount=amount,direction='NEUTRAL',market_session='HK_DARK')
  for i in range(361):
   engine.process(tick(i*.5,52+(i%2)*.001))
  self.assertIn('HK.09941',engine.profiles)
  alerts=[]
  for i in range(8):
   alert=engine.process(tick(181+i*.5,52+i*.2,10000))
   if alert:alerts.append(alert)
  self.assertTrue(alerts)
  ordinary=Engine(config)
  value=tick(1);value.pop('market_session')
  self.assertIsNone(ordinary.process(value))
  self.assertNotIn('HK.09941',ordinary.profiles)
