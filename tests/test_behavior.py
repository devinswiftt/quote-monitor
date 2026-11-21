from datetime import datetime
import unittest
from hk_quote.engine import HK
from hk_quote.behavior import BehaviorEngine

CODE='HK.02065'
START=datetime(2026,11,16,9,30,tzinfo=HK).timestamp()

def tick(t,price=10,amount=100,direction='BUY',sequence=None):
    return dict(kind='tick',code=CODE,ts=START+t,sequence=str(t if sequence is None else sequence),
                price=price,amount=amount,volume=amount/price,direction=direction)

def book(t,bid=9.99,ask=10.01,shares=1000):
    return dict(kind='book',code=CODE,ts=START+t,
                bid=[[round(bid,5),shares,3],[round(bid-.01,5),1000,3]],
                ask=[[round(ask,5),shares,3],[round(ask+.01,5),1000,3]])

def warm(engine):
    for t in range(0,181,3):
        engine.process(book(t))
        engine.process(tick(t))


def pressure(engine,side='BUY'):
    changes=[]
    for t in range(181,191):
        p=round(10.01+(t-181)*.02,4) if side=='BUY' else round(9.99-(t-181)*.02,4)
        changes+=engine.process(tick(t,p,6000,side))
        changes+=engine.process(book(t,bid=p if side=='BUY' else p-.02,ask=p+.02 if side=='BUY' else p))
    return changes


class BehaviorTests(unittest.TestCase):
    def test_independent_pressure_confirmed_and_stored_as_one_episode(self):
        e=BehaviorEngine();warm(e);changes=pressure(e)
        self.assertTrue(any(c['type']=='LIFT' and c['phase']=='confirmed' for c in changes))
        self.assertEqual(len({c['event_key'] for c in changes}),1)
        self.assertTrue(any(c['evidence']['book_supported'] for c in changes))

    def test_dump_requires_actual_selling_and_price_progress(self):
        e=BehaviorEngine();warm(e);changes=pressure(e,'SELL')
        self.assertTrue(any(c['type']=='DUMP' and c['phase']=='confirmed' for c in changes))

    def test_no_trade_price_jump_or_static_buy_wall_is_not_support(self):
        e=BehaviorEngine();warm(e)
        for t in range(181,200):
            self.assertEqual(e.process(book(t,bid=10,ask=10.01,shares=100000)),[])
        self.assertIsNone(e.states[CODE]['episode'])

    def test_two_prints_and_unknown_direction_do_not_trigger(self):
        e=BehaviorEngine();warm(e)
        for t,p in [(181,10.02),(182,10.10)]:
            self.assertFalse(any(c['phase']=='confirmed' for c in e.process(tick(t,p,100000))))
            self.assertFalse(any(c['phase']=='confirmed' for c in e.process(book(t,bid=p-.01,ask=p+.01))))
        e=BehaviorEngine();warm(e)
        for t in range(181,191):
            self.assertEqual(e.process(tick(t,10+t/100,100000,'NEUTRAL')),[])
            self.assertEqual(e.process(book(t,bid=10+t/100-.01,ask=10+t/100+.01)),[])

    def test_duplicate_prints_are_not_additional_sell_evidence(self):
        e=BehaviorEngine();warm(e)
        event=tick(181,10,10000,'SELL')
        for _ in range(10):e.process(event)
        self.assertEqual(sum(t['sequence']==event['sequence'] for t in e.states[CODE]['ticks']),1)

    def test_absorption_requires_repeated_same_price_cycles_and_can_fail(self):
        e=BehaviorEngine();warm(e);changes=[]
        for t in range(181,202):
            changes+=e.process(tick(t,10,10000,'SELL'))
            changes+=e.process(book(t,bid=10,ask=10.01,shares=500 if t%2 else 1000))
        self.assertTrue(any(c['type']=='SUPPORT' and c['phase']=='confirmed' for c in changes),[(c['type'],c['phase']) for c in changes])
        changes=[]
        changes+=e.process(tick(202,9.97,10000,'SELL'))
        self.assertFalse(any(c['phase']=='failed' for c in changes))
        changes+=e.process(tick(203,9.97,10000,'SELL'))
        self.assertTrue(any(c['phase']=='failed' for c in changes))

    def test_end_and_reset_do_not_claim_price_reversal(self):
        e=BehaviorEngine();warm(e);pressure(e)
        changes=e.advance(START+205)
        self.assertTrue(any(c['phase']=='cooling' for c in changes))
        changes=e.advance(START+225)
        self.assertTrue(any(c['phase']=='resolved' for c in changes))
        self.assertIsNone(e.states[CODE]['episode'])
        e=BehaviorEngine();warm(e);pressure(e)
        changes=e.stop(CODE,'单股停止',START+192)
        self.assertEqual(changes[-1]['phase'],'interrupted')
        self.assertNotIn(CODE,e.states)

    def test_one_level_or_stale_book_never_confirms(self):
        e=BehaviorEngine();warm(e)
        changes=[]
        for t in range(181,191):changes+=e.process(tick(t,10+t/100,10000))
        self.assertFalse(any(c['phase']=='confirmed' for c in changes))
        e=BehaviorEngine();warm(e)
        for t in range(181,191):
            b=book(t,bid=10,ask=10.01);b['bid']=b['bid'][:1];b['ask']=b['ask'][:1]
            e.process(b)
            self.assertEqual(e.process(tick(t,10+t/100,10000)),[])

class PriceAnchoringTests(unittest.TestCase):
    def test_row_reordering_is_not_a_replenishment_cycle(self):
        e=BehaviorEngine();warm(e)
        e.process(tick(181,9.99,10000,'SELL'))
        e.process(book(181,bid=9.98,ask=10,shares=1000))
        e.process(book(182,bid=9.99,ask=10.01,shares=1000))
        self.assertEqual(len(e.states[CODE]['cycles']),0)

    def test_resuming_same_episode_does_not_reset_event_key(self):
        e=BehaviorEngine();warm(e);changes=pressure(e)
        key=changes[0]['event_key'];e.advance(START+201)
        # The persisted timeline remains the same event until its quiet timeout.
        self.assertEqual(e.states[CODE]['episode']['event_key'],key)

class IndependentBehaviorTests(unittest.TestCase):
    def test_regular_small_flow_can_trigger_below_legacy_p95_burst_threshold(self):
        e=BehaviorEngine()
        for t in range(0,181,3):
            e.process(book(t));e.process(tick(t,amount=1000000 if t%18==0 else 100))
        legacy=e.states[CODE]['profiles'][3].estimate(START+190,.95,1.1,8)
        changes=pressure(e)
        confirmed=[c for c in changes if c['phase']=='confirmed']
        self.assertTrue(confirmed)
        self.assertGreater(legacy['threshold'],confirmed[0]['evidence']['amount'])

    def test_behavior_transition_reuses_episode_and_keeps_original_history(self):
        from unittest.mock import patch
        e=BehaviorEngine();warm(e);changes=pressure(e);key=changes[0]['event_key']
        evidence=dict(e.states[CODE]['episode']['evidence'],anchor=10,replenishment_cycles=2,book_supported=True)
        with patch.object(e,'_candidate',return_value=dict(type='SUPPORT',evidence=evidence)):
            changes=[]
            for t in (191,192,193):changes+=e.process(book(t,bid=10,ask=10.01))
        self.assertTrue(any(c['type']=='SUPPORT' and c['phase']=='confirmed' for c in changes))
        record=e.states[CODE]['episode']
        self.assertEqual(record['event_key'],key)
        self.assertEqual(record['history'][0]['type'],'LIFT')
        self.assertEqual(record['history'][-1]['type'],'SUPPORT')
