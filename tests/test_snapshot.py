import unittest
from hk_quote.snapshot import snapshot_event
class SnapshotTests(unittest.TestCase):
 def test_keep_original_market_values_and_missing_equity(self):
  row=dict(code='HK.02206',equity_valid=True,total_market_val=5702614837.5,circular_market_val=5702614837.5,update_time='2026-11-18 09:44:27')
  result=snapshot_event(row,1);self.assertEqual(result['data']['total_market_val'],row['total_market_val']);self.assertEqual(result['kind'],'market_snapshot')
  self.assertEqual(result['data']['circular_market_val'],row['circular_market_val'])
  row['equity_valid']=False;self.assertIsNone(snapshot_event(row)['data']['total_market_val'])
 def test_nonfinite_missing_are_not_shown_as_zero(self):
  result=snapshot_event(dict(code='HK.02206',equity_valid=True,total_market_val=float('nan')))
  self.assertIsNone(result['data']['total_market_val']);self.assertIsNone(result['data']['circular_market_val'])
