from pathlib import Path
import unittest
from hk_quote.assets import validate_stylesheet

ROOT=Path(__file__).resolve().parents[1]/'src/hk_quote/web'

class WebAssetTests(unittest.TestCase):
    def test_actual_stylesheet_and_feature_styles(self):
        css=(ROOT/'style.css').read_text()
        validate_stylesheet(css)
        for selector in [':root','body','.card','.quote-layout','.monitor-actions','.notice-preview']:
            self.assertIn(selector,css)
        for script in ROOT.glob('*.js'):
            self.assertNotEqual(css,script.read_text(),f'CSS 被 {script.name} 覆盖')

    def test_reject_real_report_script_as_stylesheet(self):
        with self.assertRaises(ValueError):validate_stylesheet((ROOT/'report.js').read_text())

    def test_reject_html_and_broken_css(self):
        for value in ['<!doctype html><html></html>','.card{color:red;','not a stylesheet']:
            with self.assertRaises(ValueError):validate_stylesheet(value)
