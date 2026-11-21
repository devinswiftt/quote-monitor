from datetime import datetime
import unittest
from hk_quote.engine import HK
from hk_quote.seat_anomalies import detect_seat_anomalies

class SeatAnomalyTests(unittest.TestCase):
 def setUp(self):
  self.start=datetime(2026,11,19,tzinfo=HK).timestamp();self.anchor=self.start+36000
 def stream(self,after=None,ident='8471',name='荷银'):
  result=[]
  for i in range(-30,30):
   bid=i<0 if after is None else (i<0 or after(i))
   seat=dict(id=ident,name=name)
   result.append((self.anchor+i*10,dict(code='HK.02206',bid=[seat,seat] if bid else [],ask=[] if bid else [seat,seat])))
  return result
 def analyze(self,events,related=None,now=None):
  return detect_seat_anomalies(events,self.start,self.start+86400,related if related is not None else [dict(code='HK.02206',ts=self.anchor,signal='SELL',reference='#1')],now=now or self.start+86400)['HK.02206']
 def test_requires_related_event_and_distinct_presence_and_groups_same_broker(self):
  raw=self.stream();self.assertEqual(self.analyze(raw,[])['top'],[])
  result=self.analyze(raw);self.assertEqual(result['qualified_seats'],1)
  seat=result['top'][0]['seats'][0];self.assertEqual(seat['before']['present'],30)
  self.assertEqual(seat['shift'],-1);self.assertGreaterEqual(seat['sustained_seconds'],120)
  second=self.stream(ident='4478')
  merged=[]
  for (ts,a),(_,b) in zip(raw,second):merged.append((ts,dict(code='HK.02206',bid=a['bid']+b['bid'],ask=a['ask']+b['ask'])))
  combined=self.analyze(merged)
  self.assertEqual(combined['qualified_seats'],2);self.assertEqual(len(combined['top']),1)
  self.assertEqual(combined['top'][0]['concurrent_seats'],2)
 def test_flicker_missing_and_sparse_presence_are_rejected(self):
  self.assertEqual(self.analyze(self.stream(after=lambda i:i%3==0))['top'],[])
  self.assertEqual(self.analyze(self.stream()[::6])['top'],[])
  sparse=[]
  for ts,event in self.stream():
   if int((ts-self.anchor)/10)%4:event=dict(code='HK.02206',bid=[],ask=[])
   sparse.append((ts,event))
  self.assertEqual(self.analyze(sparse)['top'],[])
 def test_waits_for_complete_window_and_does_not_cross_lunch(self):
  value=self.analyze(self.stream(),now=self.anchor+120)
  self.assertEqual(value['top'],[]);self.assertEqual(value['waiting_events'],1)
  late=dict(code='HK.02206',ts=self.start+13*3600+60,reference='#2',signal='SELL')
  self.assertEqual(self.analyze(self.stream(),[late])['top'],[])
 def test_net_support_is_auxiliary_and_missing_is_unknown(self):
  related=dict(code='HK.02206',ts=self.anchor,reference='#1',signal='SELL',broker_attribution=dict(status='interval',from_source='a',to_source='b',candidates=[dict(name='荷银',delta=-100)]))
  result=self.analyze(self.stream(),[related]);self.assertTrue(result['top'][0]['net_supported'])
  self.assertTrue(result['top'][0]['seats'][0]['net_evidence']['shared'])
  result=self.analyze(self.stream());self.assertFalse(result['top'][0]['net_supported'])
  self.assertEqual(result['top'][0]['seats'][0]['net_evidence']['status'],'unknown')
 def test_default_list_never_exceeds_five_groups(self):
  raw=self.stream();events=[]
  for ts,event in raw:
   side='bid' if event['bid'] else 'ask'
   rows=[dict(id=str(1000+i),name='券商'+str(i)) for i in range(8)]
   events.append((ts,dict(code='HK.02206',bid=rows if side=='bid' else [],ask=rows if side=='ask' else [])))
  result=self.analyze(events);self.assertEqual(result['total_groups'],8);self.assertEqual(len(result['top']),5)
