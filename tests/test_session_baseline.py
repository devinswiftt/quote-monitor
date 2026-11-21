import json
import unittest
from hk_quote.profile import TurnoverProfile
from hk_quote.engine import Engine, timestamp
from hk_quote.behavior import BehaviorEngine

CODE='HK.02065'
def tick(when,seq,amount=100,price=13):
    return dict(kind='tick',code=CODE,ts=timestamp(when),sequence=str(seq),amount=amount,price=price,volume=amount/price,direction='BUY')
def book(ts):
    return dict(kind='book',code=CODE,ts=ts,bid=[[12.99,1000,1],[12.98,1000,1]],ask=[[13.01,1000,1],[13.02,1000,1]])

class SessionBaselineTests(unittest.TestCase):
    def test_lunch_preserves_windows_but_trading_time_expires_them(self):
        p=TurnoverProfile()
        for i in range(20):p.add(tick(f'2026-11-19 11:50:{i*3:02d}',i))
        self.assertEqual(p.estimate(timestamp('2026-11-19 13:16:00'))['samples'],20)
        self.assertIsNone(p.estimate(timestamp('2026-11-19 13:51:00')))
        self.assertIsNone(p.estimate(timestamp('2026-11-20 09:30:00')))
        p.add(tick('2026-11-20 09:30:01','next'))
        self.assertIsNone(p.estimate(timestamp('2026-11-20 09:31:00')))

    def test_afternoon_burst_uses_morning_reference_without_future_leak(self):
        with open('config/settings.json') as config_file:cfg=json.load(config_file)
        cfg['rapid_move']={'enabled':False}
        e=Engine(cfg)
        for i in range(20):e.process(tick(f'2026-11-19 11:50:{i*3:02d}',i))
        e.process(dict(kind='reset'))
        e.process(tick('2026-11-19 13:02:00','afternoon'))
        e.process(tick('2026-11-19 13:15:59','before-burst'))
        a=e.process(tick('2026-11-19 13:16:00','burst',243060,13.52))
        self.assertIsNotNone(a)
        self.assertEqual(a['threshold'],110)
        self.assertEqual(a['signal'],'BUY')

    def test_book_ahead_by_milliseconds_does_not_drop_real_trades(self):
        e=BehaviorEngine();base=timestamp('2026-11-19 13:16:00')
        e.process(book(base+.004))
        a=tick('2026-11-19 13:16:00','a',202500,13.5)
        e.process(a);e.process(a)
        self.assertEqual(len(e.states[CODE]['ticks']),1)
        self.assertEqual(e.states[CODE]['ticks'][0]['amount'],202500)
        # Small trade-to-trade disorder is retained in event-time order.
        e.process(tick('2026-11-19 13:15:59.999','b'))
        self.assertEqual([t['sequence'] for t in e.states[CODE]['ticks']],['b','a'])
        e.process(tick('2026-11-19 13:15:50','stale'))
        self.assertEqual(len(e.states[CODE]['ticks']),2)

    def test_behavior_preserves_profiles_on_pause_but_resets_evidence(self):
        e=BehaviorEngine()
        for i in range(10):e.process(tick(f'2026-11-19 11:50:{i*3:02d}',i))
        e.stop_all('lunch',timestamp('2026-11-19 12:00:00'))
        e.process(tick('2026-11-19 13:02:00','afternoon'))
        s=e.states[CODE]
        self.assertEqual(len(s['ticks']),1)
        self.assertEqual(s['profiles'][3].estimate(timestamp('2026-11-19 13:02:10'),minimum=8)['samples'],11)

    def test_restoring_behavior_calibration_does_not_replay_old_signals(self):
        e=BehaviorEngine()
        for i in range(10):e.learn(tick(f'2026-11-19 11:50:{i*3:02d}',i))
        self.assertFalse(e.states)
        e.process(book(timestamp('2026-11-19 13:16:00')))
        s=e.states[CODE]
        self.assertEqual(s['profiles'][3].estimate(timestamp('2026-11-19 13:16:00'),minimum=8)['samples'],10)
        self.assertFalse(s['ticks'])
        self.assertIsNone(s['episode'])
