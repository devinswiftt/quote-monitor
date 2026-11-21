import json,tempfile,unittest
from pathlib import Path
from hk_quote.notice import make_notice,with_notice
from hk_quote.storage import Storage

class NoticeTests(unittest.TestCase):
 def alert(self):
  return dict(code='HK.02206',name='新荷花',ts=1794880000,signal='BUY',amount=1000,multiple=1,
   participation=dict(version=2,scope='best_level',status='ready',valid_samples=21,target_samples=21,
     bid=[dict(name='凯基',presence_ratio=15/21)],ask=[],changes=[],trade_clues=dict(reason='证据不足')))
 def test_same_percentage_and_identity(self):
  notice=make_notice(self.alert(),52)
  self.assertIn('凯基 71%',notice['text']);self.assertIn('#52',notice['text']);self.assertIn('21/21',notice['text'])
 def test_history_marked_and_saved_original_preserved(self):
  alert=self.alert();value=with_notice(alert,52)
  self.assertTrue(value['notification_summary']['reconstructed']);self.assertNotIn('notification_summary',alert)
  alert['notification_summary']=dict(text='原通知原文',reconstructed=False)
  self.assertEqual(with_notice(alert,52)['notification_summary']['text'],'原通知原文')
 def test_pending_and_depth_not_labeled_as_finished(self):
  a=self.alert();a['participation']['status']='pending';self.assertIsNone(make_notice(a,52))
  self.assertIsNone(make_notice(dict(kind='depth'),52))
 def test_summary_persisted_in_same_update(self):
  with tempfile.TemporaryDirectory() as d:
   s=Storage(str(Path(d)/'q.db'));a=self.alert();ident=s.alert(a);s.update_alert(ident,a)
   saved=json.loads(s.db.execute('SELECT payload FROM alerts WHERE id=?',(ident,)).fetchone()[0])
   self.assertEqual(saved['notification_summary']['text'],a['notification_summary']['text']);self.assertFalse(saved['notification_summary']['reconstructed']);s.close()
