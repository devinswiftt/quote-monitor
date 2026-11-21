import unittest
from hk_quote.attribution import Attribution


class AttributionTests(unittest.TestCase):
    def sample(self, extra=False, source='push'):
        engine=Attribution()
        rows=[dict(id='1234',name='甲券商',position=1)]
        if extra:rows.append(dict(id='5678',name='乙券商',position=1))
        for received,kind in [(96.5,'book'),(96.6,'broker'),(99,'tick'),(101,'book'),(101.1,'broker')]:
            e=dict(kind=kind,code='HK.02065',ts=received)
            if kind=='book':e.update(bid=[[9,1000,2]],ask=[[10,1000 if received<100 else 900,2]])
            if kind=='broker':e.update(source=source,bid=[],ask=rows if received<100 else [])
            if kind=='tick':e.update(sequence='1',direction='BUY',price=10,amount=1000,volume=100)
            engine.observe(received,e)
        return engine

    def test_only_passive_side_with_low_confidence(self):
        r=self.sample().infer(dict(code='HK.02065',signal='BUY'),100)
        self.assertEqual(r['status'],'hypothesis')
        self.assertEqual(r['confidence'],'低')
        self.assertEqual(r['active_side'],'未知')
        self.assertEqual(r['candidates'][0]['id'],'1234')

    def test_multiple_candidates_are_ambiguous(self):
        r=self.sample(extra=True).infer(dict(code='HK.02065',signal='BUY'),100)
        self.assertEqual(r['status'],'ambiguous')

    def test_polled_queue_is_not_fresh_push_evidence(self):
        r=self.sample(source='snapshot').infer(dict(code='HK.02065',signal='BUY'),100)
        self.assertEqual(r['status'],'unknown')

    def test_reset_invalidates_evidence(self):
        e=self.sample();e.observe(102,dict(kind='reset'))
        self.assertEqual(e.infer(dict(code='HK.02065',signal='BUY'),100)['status'],'unknown')

class ConservativeClueTests(AttributionTests):
    def test_temporary_price_move_invalidates_clue_even_if_it_returns(self):
        p=self.sample()
        p.events['HK.02065'].insert(2,(98,dict(kind='book',code='HK.02065',ts=98,bid=[[9,1000,1]],ask=[[11,1000,1]])))
        r=p.infer(dict(code='HK.02065',signal='BUY'),100)
        self.assertEqual(r['status'],'unknown')
        self.assertIn('曾变化',r['reason'])
        self.assertEqual(r['candidates'],[])

    def test_delayed_ticks_do_not_support_trade_volume(self):
        p=self.sample()
        for _,e in p.events['HK.02065']:
            if e['kind']=='tick':e['ts']=90
        self.assertEqual(p.infer(dict(code='HK.02065',signal='BUY'),100)['status'],'unknown')

    def test_duplicate_tick_sequence_does_not_inflate_volume(self):
        p=self.sample();tick=next(e for _,e in p.events['HK.02065'] if e['kind']=='tick')
        p.events['HK.02065'].insert(3,(99.1,dict(tick)))
        self.assertEqual(p.infer(dict(code='HK.02065',signal='BUY'),100)['evidence']['matched_volume'],100)

    def test_queues_must_be_aligned_with_books(self):
        p=self.sample()
        p.events['HK.02065']=type(p.events['HK.02065'])((t+.95 if e['kind']=='broker' else t,e) for t,e in p.events['HK.02065'])
        self.assertEqual(p.infer(dict(code='HK.02065',signal='BUY'),100)['status'],'unknown')
