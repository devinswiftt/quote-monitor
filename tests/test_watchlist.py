import tempfile
from pathlib import Path
import unittest
from hk_quote.watchlist import Watchlist,normalize_code


class WatchlistTests(unittest.TestCase):
    def test_persist_and_revision_guard(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'db.sqlite3';w=Watchlist(path,['HK.02065'],{'HK.02065':'一微科技'})
            row=w.rows()[0];w.desired('02065',False)
            w.acknowledge(row,'monitoring')
            self.assertEqual(w.rows()[0]['state'],'stopping')
            self.assertFalse(w.rows()[0]['enabled'])
            w.acknowledge(w.rows()[0],'stopped');w.add('700')
            new=Watchlist(path,['HK.09988'])
            self.assertEqual(len(new.rows()),2)
            self.assertFalse(next(r for r in new.rows() if r['code']=='HK.00700')['enabled'])
            with self.assertRaises(ValueError):w.add('HK.00700')
            with self.assertRaises(ValueError):w.desired('HK.09988',True)

    def test_code_validation(self):
        self.assertEqual(normalize_code('700'),'HK.00700')
        with self.assertRaises(ValueError):normalize_code('../abc')

    def test_remove_keeps_worker_stop_and_allows_safe_readdition(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'db.sqlite3';w=Watchlist(path,['HK.02065'])
            original=w.rows()[0];w.remove('02065')
            self.assertEqual(w.rows(),[])
            removed=w.rows(include_deleted=True)[0]
            self.assertFalse(removed['enabled']);self.assertEqual(removed['state'],'stopping')
            w.acknowledge(original,'monitoring')
            self.assertEqual(w.rows(include_deleted=True)[0]['state'],'stopping')
            self.assertEqual(Watchlist(path,['HK.02065']).rows(),[])
            with self.assertRaises(ValueError):w.desired('02065',True)
            w.add('02065');new=w.rows()[0]
            self.assertFalse(new['enabled']);self.assertGreater(new['revision'],removed['revision'])
            w.acknowledge(removed,'error','过期回执')
            self.assertEqual(w.rows()[0]['state'],'stopped')

    def test_default_stock_persistence_and_removal(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'db.sqlite3';w=Watchlist(path,['HK.02065','HK.02206'])
            original=[(r['code'],r['enabled'],r['revision']) for r in w.rows()]
            w.set_default('02206');self.assertEqual(Watchlist(path).default_symbol(),'HK.02206')
            self.assertEqual([(r['code'],r['enabled'],r['revision']) for r in w.rows()],original)
            with self.assertRaises(ValueError):w.set_default('00700')
            w.remove('02206');self.assertEqual(w.default_symbol(),'HK.02065')
            with self.assertRaises(ValueError):w.set_default('02206')
            w.add('02206');self.assertEqual(w.default_symbol(),'HK.02065')
            w.remove('02065');w.remove('02206');self.assertEqual(w.default_symbol(),'')
