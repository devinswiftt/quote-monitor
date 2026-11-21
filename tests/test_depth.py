import unittest
from hk_quote.depth import DepthMonitor


class DepthTests(unittest.TestCase):
    def test_initial_one_level_and_dedupe(self):
        d = DepthMonitor()
        self.assertIn('仅买一', d.observe('HK.02065', 1, 1))
        self.assertIsNone(d.observe('HK.02065', 1, 1))

    def test_drop_and_recover(self):
        d = DepthMonitor()
        self.assertIsNone(d.observe('HK.02065', 10, 10))
        self.assertIn('仅买一', d.observe('HK.02065', 1, 1))
        self.assertIn('恢复', d.observe('HK.02065', 10, 10))
        self.assertIn('仅买一', d.observe('HK.02065', 1, 1))

    def test_empty_or_thin_book_not_downgrade(self):
        d = DepthMonitor()
        self.assertIsNone(d.observe('HK.02065', 0, 0))
        self.assertIsNone(d.observe('HK.02065', 1, 10))
