from pathlib import Path
import tempfile,unittest
from hk_quote.stock_search import StockDirectory,merge_watchlist,clean
from hk_quote.watchlist import Watchlist

class StockSearchTests(unittest.TestCase):
 def test_names_codes_cache_and_ambiguous_inputs(self):
  with tempfile.TemporaryDirectory() as directory:
   calls=[]
   def fetch(kind):calls.append(kind);return [dict(code='HK.02065',name='一微科技'),dict(code='HK.02206',name='新荷花')]
   path=Path(directory)/'catalog.json';index=StockDirectory(path,fetch)
   self.assertEqual(index.search('新荷')[0]['code'],'HK.02206')
   self.assertEqual(index.search('02065')[0]['name'],'一微科技')
   self.assertEqual(index.resolve('新荷花')['code'],'HK.02206')
   with self.assertRaises(ValueError):index.resolve('科技')
   self.assertEqual(calls,['catalog'])
   self.assertEqual(StockDirectory(path,lambda _:self.fail('should use cache')).search('新荷花')[0]['code'],'HK.02206')
 def test_code_add_works_without_opend_and_filters_nonstocks(self):
  with tempfile.TemporaryDirectory() as directory:
   def fail(_):raise TimeoutError()
   index=StockDirectory(Path(directory)/'catalog.json',fail)
   self.assertEqual(index.resolve('700')['code'],'HK.00700')
   with self.assertRaises(ValueError):index.search('腾讯')
  self.assertEqual(clean([dict(code='US.AAPL'),dict(code='HK.HSImain'),dict(code='HK.00700',stock_type='WARRANT'),dict(code='HK.02206',delisting=True)]),[])
 def test_merge_preserves_states_and_repeated_import_is_idempotent(self):
  with tempfile.TemporaryDirectory() as directory:
   watch=Watchlist(Path(directory)/'quotes.db',['HK.02065'],{'HK.02065':'一微科技'})
   before=watch.rows()[0]
   incoming=[dict(code='HK.02065',name='一微科技'),dict(code='HK.02206',name='新荷花'),dict(code='US.AAPL',name='苹果')]
   result=merge_watchlist(watch,incoming);self.assertEqual(result,dict(added=1,existing=1,total=2))
   rows={r['code']:r for r in watch.rows()}
   self.assertEqual(rows['HK.02065']['enabled'],before['enabled']);self.assertEqual(rows['HK.02065']['revision'],before['revision'])
   self.assertEqual(rows['HK.02206']['enabled'],0);self.assertEqual(rows['HK.02206']['name'],'新荷花')
   self.assertEqual(merge_watchlist(watch,incoming)['added'],0)
   merge_watchlist(watch,[]);self.assertEqual(len(watch.rows()),2)
