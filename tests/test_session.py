from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from hk_quote.session import MarketSession
from hk_quote.engine import HK

class SessionTests(unittest.TestCase):
    def test_session_boundaries_and_timezone(self):
        with tempfile.TemporaryDirectory() as d:
            s=MarketSession(Path(d)/'calendar.json')
            s.update('2026-11-16',[dict(time='2026-11-16',trade_date_type='WHOLE')])
            for hour,minute,opened in [(9,29,True),(9,30,True),(11,59,True),(12,0,False),(12,59,False),(13,0,True),(15,59,True),(16,0,True)]:
                now=datetime(2026,11,16,hour,minute,tzinfo=HK)
                self.assertEqual(s.status(now)[0],opened)
                self.assertEqual(s.status(now.astimezone(timezone.utc))[0],opened)

    def test_closed_half_day_and_persistence(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'calendar.json';s=MarketSession(p)
            s.update('2026-12-24',[dict(time='2026-12-24',trade_date_type='MORNING')])
            self.assertTrue(s.status(datetime(2026,12,24,10,tzinfo=HK))[0])
            self.assertFalse(MarketSession(p).status(datetime(2026,12,24,14,tzinfo=HK))[0])
            s.update('2026-12-25',[])
            self.assertFalse(s.status(datetime(2026,12,25,10,tzinfo=HK))[0])
            self.assertFalse(s.status(datetime(2026,11,21,10,tzinfo=HK))[0])

    def test_unknown_day_requires_verification_before_subscription(self):
        with tempfile.TemporaryDirectory() as d:
            s=MarketSession(Path(d)/'calendar.json')
            opened,message=s.status(datetime(2026,11,16,10,tzinfo=HK))
            self.assertTrue(opened)
            self.assertIn('确认',message)


    def test_auction_bounds_and_half_day(self):
        with tempfile.TemporaryDirectory() as d:
            s=MarketSession(Path(d)/'calendar.json')
            s.update('2026-11-16',[dict(time='2026-11-16',trade_date_type='WHOLE')])
            for hour,minute,phase in [(8,59,'CLOSED'),(9,0,'PRE_AUCTION'),(9,29,'PRE_AUCTION'),(9,30,'CONTINUOUS'),(12,0,'BREAK'),(16,0,'CLOSE_AUCTION'),(16,9,'CLOSE_AUCTION'),(16,10,'AUCTION_SETTLING'),(16,11,'CLOSED')]:
                self.assertEqual(s.phase(datetime(2026,11,16,hour,minute,tzinfo=HK)),phase)
            s.update('2026-12-24',[dict(time='2026-12-24',trade_date_type='MORNING')])
            self.assertEqual(s.phase(datetime(2026,12,24,12,5,tzinfo=HK)),'CLOSE_AUCTION')
            self.assertEqual(s.phase(datetime(2026,12,24,12,11,tzinfo=HK)),'CLOSED')
