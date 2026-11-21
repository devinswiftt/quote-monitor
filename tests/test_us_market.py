from datetime import datetime
from pathlib import Path
import json,sqlite3,tempfile,unittest
from hk_quote.markets import NY,HK,parse_time,day_bounds,us_phase
from hk_quote.watchlist import normalize_code,Watchlist
from hk_quote.profile import TurnoverProfile
from hk_quote.engine import Engine
from hk_quote.storage import Storage
from hk_quote.pagination import alert_page
from hk_quote.stock_search import clean
from hk_quote.us_monitor import tick_event

class USMarketTests(unittest.TestCase):
 def test_codes_keep_hk_and_support_us_stock_and_etf(self):
  for a,b in [('HK.00700','HK.00700'),('700','HK.00700'),('QQQ','US.QQQ'),('us.nvda','US.NVDA'),('US.BRK.B','US.BRK.B')]:self.assertEqual(normalize_code(a),b)
  for a in ('../abc','US..QQQ','US.QQQ/xx','invalid'):
   with self.assertRaises(ValueError):normalize_code(a)
  self.assertEqual(clean([dict(code='US.QQQ',stock_type='ETF')],market='US')[0]['code'],'US.QQQ')
 def test_ny_dst_and_hk_midnight_do_not_change_us_date(self):
  winter=parse_time('2026-11-20 09:30:00','US.QQQ');summer=parse_time('2026-07-01 09:30:00','US.QQQ')
  self.assertEqual(datetime.fromtimestamp(winter,HK).hour,22);self.assertEqual(datetime.fromtimestamp(summer,HK).hour,21)
  start,end=day_bounds('US.QQQ','2026-11-20');late=parse_time('2026-11-20 23:55:00','US.QQQ')
  self.assertTrue(start<late<end);self.assertEqual(datetime.fromtimestamp(late,HK).day,21)
 def test_sessions_regular_has_no_lunch_and_half_day_stops_early(self):
  for clock,phase in [('04:00','PRE'),('09:30','REGULAR'),('12:30','REGULAR'),('16:00','POST'),('20:00','CLOSED')]:self.assertEqual(us_phase(parse_time('2026-11-20 '+clock,'US.QQQ')),phase)
  self.assertEqual(us_phase(parse_time('2026-11-20 13:01','US.QQQ'),'MORNING'),'CLOSED')
  self.assertEqual(us_phase(parse_time('2026-11-20 10:00','US.QQQ'),'CLOSED'),'CLOSED')
 def test_profiles_reset_at_us_session_boundary(self):
  profile=TurnoverProfile(3,3600,market='US');start=parse_time('2026-11-20 09:27:00','US.QQQ')
  for i in range(40):profile.add(dict(ts=start+i*3,sequence=i,amount=100))
  self.assertIsNotNone(profile.estimate(start+125,minimum=20))
  opening=parse_time('2026-11-20 09:30:00','US.QQQ');self.assertIsNone(profile.estimate(opening,minimum=20))
  profile.add(dict(ts=opening,sequence=999,amount=100));self.assertIsNone(profile.estimate(opening+3,minimum=20))
 def test_engine_detects_us_during_hk_closed_hours(self):
  config=json.loads((Path(__file__).resolve().parents[1]/'config/settings.json').read_text());config['rapid_move']={'enabled':False};engine=Engine(config)
  start=parse_time('2026-11-20 12:28:00','US.QQQ')
  for i in range(40):engine.process(dict(kind='tick',code='US.QQQ',ts=start+i*3,sequence=str(i),amount=100,price=100,volume=1,direction='BUY'))
  engine.process(dict(kind='tick',code='US.QQQ',ts=start+122,sequence='before-big',amount=100,price=100,volume=1,direction='BUY'))
  alert=engine.process(dict(kind='tick',code='US.QQQ',ts=start+123,sequence='big',amount=10000,price=101,volume=100,direction='BUY'))
  self.assertIsNotNone(alert);self.assertEqual(alert['signal'],'BUY')
 def test_storage_and_pagination_use_new_york_trading_date(self):
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'db';store=Storage(path)
   first=parse_time('2026-11-20 23:55:00','US.QQQ');second=parse_time('2026-11-21 00:05:00','US.QQQ')
   a=dict(code='US.QQQ',signal='BUY',amount=300,price=100,ts=first)
   store.alert(a);b=dict(a,ts=second,price=101);store.alert(b)
   self.assertIsNone(b['previous_alert_id'])
   with sqlite3.connect(path) as db:
    result=alert_page(db,{'symbol':['US.QQQ'],'date':['2026-11-20']})
    self.assertEqual(result['total'],1)
    self.assertEqual(alert_page(db,{'date':['2026-11-20']})['total'],1)
   store.event(first,dict(kind='tick',code='US.QQQ',ts=first,sequence='1',price=100,amount=100,volume=1));store.db.commit()
   self.assertTrue(store.db.execute('SELECT sequence FROM chart_ticks').fetchone()[0].startswith('2026-11-20:'))
   store.close()
 def test_ticker_filters_late_prints_and_parses_ny_extended_hours(self):
  row=dict(code='US.QQQ',time='2026-11-20 17:05:00',type='EXTENDED_TRADING_HOURS',sequence=1,price=100,volume=2,turnover=200,ticker_direction='NEUTRAL')
  event=tick_event(row);self.assertEqual(event['session'],'POST');self.assertEqual(event['currency'],'USD')
  self.assertIsNone(tick_event(dict(row,type='LATE')))
  self.assertIsNone(tick_event(dict(row,price=float('nan'))))
