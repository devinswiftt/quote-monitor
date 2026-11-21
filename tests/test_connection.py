import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from hk_quote.connection import read_health,retry_delay


class ConnectionTests(unittest.TestCase):
    def test_stopped_heartbeat_is_not_web_connection(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'health.json'
            p.write_text(json.dumps(dict(state='connected',heartbeat=100,checked_at=100)))
            self.assertEqual(read_health(p,112)['state'],'stopped')

    def test_missing_health_and_stale_checks(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'health.json';self.assertEqual(read_health(p,100)['state'],'stopped')
            p.write_text(json.dumps(dict(state='connected',heartbeat=100,checked_at=80)))
            self.assertEqual(read_health(p,101)['state'],'checking')

    def test_recovery_warmup_and_bounded_retry(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'health.json'
            p.write_text(json.dumps(dict(state='warming',heartbeat=100,checked_at=100,warmup_until=102)))
            self.assertEqual(read_health(p,101)['state'],'warming')
            self.assertEqual(read_health(p,103)['state'],'connected')
        with patch('hk_quote.connection.random.uniform',return_value=1):
            self.assertEqual([retry_delay(i) for i in range(8)],[1,2,4,8,15,30,30,30])
