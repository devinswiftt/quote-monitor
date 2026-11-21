import unittest
from unittest.mock import patch
from hk_quote.broker_profiles import classify

class BrokerProfileTests(unittest.TestCase):
 def test_reviewed_channels_have_sources_and_do_not_claim_customer_identity(self):
  for name,category in [('富途证券','retail'),('微牛','retail'),('摩根士丹利','institutional'),('高盛','institutional'),('凯基','mixed'),('盈透','mixed')]:
   row=classify(name);self.assertEqual(row['category'],category)
   self.assertTrue(row['sources']);self.assertEqual(row['scope'],'broker_channel')
   self.assertIn('不识别',row['notice'])
 def test_unknown_abbreviation_is_not_guessed_and_similar_names_not_matched(self):
  for name in ('荷银','未核实新券商','富途其他公司'):
   self.assertEqual(classify(name)['category'],'unknown')
  self.assertEqual(classify('富途 证券')['category'],'retail')
 def test_missing_evidence_does_not_turn_into_verified_label(self):
  with patch('hk_quote.broker_profiles.catalog',return_value=dict(profiles={'测试':dict(category='institutional',basis='猜测',sources=[])})):
   self.assertEqual(classify('测试')['category'],'unknown')
