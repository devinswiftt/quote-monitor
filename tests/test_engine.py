import json
import unittest
from hk_quote.engine import Engine, timestamp


class DetectorTests(unittest.TestCase):
    def setUp(self):
        with open('config/settings.json') as f:
            self.c = json.load(f)
        self.c.update(rapid_move={'enabled':False}, min_price_change_pct=0, threshold_mode='legacy', volume_multiple=4, warmup_seconds=10, baseline_seconds=60, min_amount=1000, window_seconds=3)
        self.e = Engine(self.c)
        self.t = timestamp('2026-11-16 10:00:00')

    def tick(self, second, amount=10, direction='BUY', seq=None):
        return dict(kind='tick', code='HK.00700', ts=self.t + second,
                    sequence=str(second if seq is None else seq), price=100, amount=amount, direction=direction)

    def warm(self):
        for i in range(12):
            self.assertIsNone(self.e.process(self.tick(i)))

    def test_burst_and_cooldown(self):
        self.warm()
        a = self.e.process(self.tick(12, 2000))
        self.assertEqual(a['signal'], 'BUY')
        self.assertIsNone(self.e.process(self.tick(13, 2000)))

    def test_unknown_direction_not_buy(self):
        self.warm()
        a = self.e.process(self.tick(12, 2000, 'NEUTRAL'))
        self.assertEqual(a['signal'], 'VOLUME')

    def test_duplicate_and_out_of_order(self):
        self.warm()
        self.assertIsNone(self.e.process(self.tick(11, 999999)))
        self.assertIsNone(self.e.process(self.tick(9, 999999, seq='late')))

    def test_quiet_trading_preserves_baseline(self):
        self.warm()
        self.assertEqual(self.e.process(self.tick(120, 2000))['signal'], 'BUY')

    def test_auction_excluded(self):
        event = self.tick(0, 999999)
        event['ts'] = timestamp('2026-11-16 09:20:00')
        self.assertIsNone(self.e.process(event))

    def test_reset_removes_baseline(self):
        self.warm()
        self.e.process(dict(kind='reset'))
        self.assertIsNone(self.e.process(self.tick(12, 2000)))

    def test_ten_level_book_confirmation(self):
        self.warm()
        for second, ask in [(9, 100), (12, 101)]:
            self.e.process(dict(kind='book', code='HK.00700', ts=self.t + second,
                                bid=[[99-i, 100, 1] for i in range(10)],
                                ask=[[ask+i, 100, 1] for i in range(10)]))
        event = self.tick(12, 2000)
        event['price'] = 101
        a = self.e.process(event)
        self.assertTrue(a['book_confirmed'])
        self.assertEqual(a['level'], '强')

    def test_one_level_book_cannot_confirm(self):
        self.warm()
        for second, ask in [(9, 100), (12, 101)]:
            self.e.process(dict(kind='book', code='HK.00700', ts=self.t + second,
                                bid=[[99, 100, 1]], ask=[[ask, 100, 1]]))
        event = self.tick(12, 2000)
        event['price'] = 101
        a = self.e.process(event)
        self.assertFalse(a['book_confirmed'])
        self.assertEqual(a['depth'], 1)

    def test_storage_replay_matches_live(self):
        import tempfile
        import sqlite3
        from pathlib import Path
        from hk_quote.storage import Storage
        events = [self.tick(i) for i in range(12)] + [self.tick(12, 2000)]
        expected = [a for a in (self.e.process(e) for e in events) if a]
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'test.sqlite3')
            store = Storage(path)
            for event in events:
                store.event(event['ts'], event)
            store.close()
            replay = Engine(self.c)
            with sqlite3.connect(path) as db:
                actual = [a for a in (replay.process(json.loads(row[0])) for row in
                          db.execute('SELECT payload FROM events ORDER BY id')) if a]
            self.assertEqual(actual, expected)
            self.assertEqual(len(actual), 1)

    def test_daily_baseline_raises_threshold_for_active_stock(self):
        self.warm()
        self.e.process(dict(kind='day', code='HK.00700', ts=self.t + 8, turnover=100000000))
        self.assertIsNone(self.e.process(self.tick(12, 2000)))
        a = self.e.process(self.tick(13, 1000000))
        self.assertGreater(a['threshold'], 1000)
        self.assertEqual(a['baseline_source'], 'day_and_rolling')

    def test_low_turnover_allows_sub_million_burst(self):
        self.c['min_amount'] = 20000
        self.warm()
        self.e.process(dict(kind='day', code='HK.00700', ts=self.t + 8, turnover=200000))
        a = self.e.process(self.tick(12, 30000))
        self.assertEqual(a['threshold'], 20000)
        self.assertEqual(a['signal'], 'BUY')

    def test_current_window_daily_quote_does_not_leak_into_baseline(self):
        self.warm()
        self.e.process(dict(kind='day', code='HK.00700', ts=self.t + 12, turnover=999999999))
        self.assertEqual(self.e.process(self.tick(12, 2000))['baseline_source'], 'rolling_only')

    def test_lunch_excluded_from_daily_rate(self):
        from hk_quote.engine import trading_seconds
        self.assertEqual(trading_seconds(timestamp('2026-11-16 13:00:00')), 9000)
        self.assertEqual(trading_seconds(timestamp('2026-11-16 13:30:00')), 10800)

    def test_percentile_engine_can_trigger_below_old_floor(self):
        self.c.update(threshold_mode='percentile', profile_quantile=.95,
                      profile_multiplier=1.1, profile_min_samples=20)
        engine = Engine(self.c)
        for second in range(0, 66, 3):
            self.assertIsNone(engine.process(self.tick(second, 1000)))
        alert = engine.process(self.tick(70, 3000))
        self.assertEqual(alert['threshold_method'], 'percentile')
        self.assertEqual(alert['threshold'], 1100)

    def test_price_gate_rejects_flat_and_small_moves_without_consuming_cooldown(self):
        self.c['min_price_change_pct'] = .1
        self.warm()
        self.assertIsNone(self.e.process(self.tick(12, 2000)))
        small = dict(self.tick(12.1, 2000), price=100.05)
        self.assertIsNone(self.e.process(small))
        alert = self.e.process(dict(self.tick(12.2, 2000), price=100.1))
        self.assertIsNotNone(alert)
        self.assertAlmostEqual(alert['price_change_pct'], .1)
        self.assertEqual(alert['min_price_change_pct'], .1)

    def test_price_gate_accepts_downward_progress_and_unknown_direction(self):
        self.c['min_price_change_pct'] = .1
        self.warm()
        alert = self.e.process(dict(self.tick(12, 2000, 'NEUTRAL'), price=99.8))
        self.assertEqual(alert['signal'], 'VOLUME')
        self.assertAlmostEqual(alert['price_change_pct'], -.2)

    def test_price_gate_rejects_round_trip_and_isolated_print(self):
        self.c['min_price_change_pct'] = .1
        self.warm()
        # A small print moves away, then the burst returns to its starting price.
        self.assertIsNone(self.e.process(dict(self.tick(11.1), price=100.5)))
        self.assertIsNone(self.e.process(self.tick(12, 2000)))
        self.assertIsNone(self.e.process(dict(self.tick(120, 2000), price=102)))

    def test_millisecond_timestamp(self):
        self.assertAlmostEqual(timestamp('2026-11-16 10:00:00:123') - self.t, .123, places=3)


if __name__ == '__main__':
    unittest.main()
