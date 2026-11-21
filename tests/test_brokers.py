import unittest
from hk_quote.brokers import BrokerCache


class BrokerTests(unittest.TestCase):
    def test_snapshot_preserved_and_staleness_exposed(self):
        cache = BrokerCache()
        event = dict(code='HK.02065', ts=100, bid=[dict(id='1234', name='测试券商', position=1)], ask=[])
        cache.update(event)
        saved = cache.attach(dict(code='HK.02065', ts=105))
        event['bid'][0]['name'] = 'changed'
        self.assertEqual(saved['broker_context']['bid'][0]['name'], '测试券商')
        self.assertEqual(saved['broker_context']['status'], 'nearby')
        self.assertEqual(cache.attach(dict(code='HK.02065', ts=150))['broker_context']['status'], 'stale')
        self.assertEqual(cache.attach(dict(code='HK.09988', ts=150))['broker_context']['status'], 'unavailable')
