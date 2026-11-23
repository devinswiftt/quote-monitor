import json
import sqlite3
from pathlib import Path
from .history import export_connection
from datetime import datetime
from .engine import HK
from .markets import timezone
from .broker_archive import initialize as initialize_broker_archive,save as archive_brokers
from .notice import make_notice
from .behavior_store import initialize as initialize_behaviors


class Storage:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, received REAL, payload TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS alerts (id INTEGER PRIMARY KEY, payload TEXT)')
        self.db.execute('CREATE TABLE IF NOT EXISTS latest_state (code TEXT, kind TEXT, payload TEXT, PRIMARY KEY(code,kind))')
        self.db.execute('CREATE TABLE IF NOT EXISTS chart_ticks (code TEXT, sequence TEXT, ts REAL, price REAL, volume REAL, PRIMARY KEY(code,sequence))')
        self.db.execute('CREATE INDEX IF NOT EXISTS chart_ticks_time ON chart_ticks(ts)')
        if not self.db.execute('SELECT 1 FROM chart_ticks LIMIT 1').fetchone():
            start = datetime.now(HK).replace(hour=0,minute=0,second=0,microsecond=0).timestamp()
            rows = self.db.execute("SELECT payload FROM events WHERE received>=? AND json_extract(payload,'$.kind')='tick' ORDER BY id", (start,)).fetchall()
            for row in rows:
                event = json.loads(row[0])
                key = datetime.fromtimestamp(event['ts'],HK).strftime('%Y-%m-%d')+':'+str(event['sequence'])
                self.db.execute('INSERT OR IGNORE INTO chart_ticks VALUES (?,?,?,?,?)',
                    (event['code'],key,event['ts'],event['price'],event.get('volume',event['amount']/event['price'])))
        initialize_broker_archive(self.db)
        initialize_behaviors(self.db)
        self.history_path = Path(path).with_suffix('.alerts.md')
        self.db.commit()
        export_connection(self.db, self.history_path)

    def event(self, received, event):
        if event['kind']=='broker_stats':archive_brokers(self.db,event)
        if event['kind'] == 'tick':
            key = datetime.fromtimestamp(event['ts'], timezone(event['code'])).strftime('%Y-%m-%d') + ':' + str(event['sequence'])
            self.db.execute('INSERT OR IGNORE INTO chart_ticks VALUES (?,?,?,?,?)',
                (event['code'], key, event['ts'], event['price'], event.get('volume',event['amount']/event['price'])))
        if event.get('code') and event['kind'] != 'reset':
            self.db.execute('INSERT OR REPLACE INTO latest_state(code,kind,payload) VALUES (?,?,?)',
                            (event['code'],event['kind'],json.dumps(event)))
        self.db.execute('INSERT INTO events(received,payload) VALUES (?,?)', (received, json.dumps(event)))

    def alert(self, value):
        if value.get('price') is not None and value.get('signal'):
            previous = self.db.execute("SELECT id,payload FROM alerts WHERE json_extract(payload,'$.code')=? AND json_extract(payload,'$.signal') IS NOT NULL ORDER BY id DESC LIMIT 1", (value['code'],)).fetchone()
            value.update(previous_alert_id=None, previous_price=None, price_delta=None, price_delta_pct=None)
            if previous:
                ident, payload = previous
                old = json.loads(payload)
                if datetime.fromtimestamp(old['ts'], timezone(value['code'])).date() == datetime.fromtimestamp(value['ts'], timezone(value['code'])).date():
                    value['previous_alert_id'] = ident
                    value['previous_price'] = old.get('price')
                    value['previous_alert_time'] = old['ts']
                    if old.get('price') and old['price'] > 0:
                        value['price_delta'] = round(value['price'] - old['price'], 6)
                        value['price_delta_pct'] = round((value['price'] / old['price'] - 1) * 100, 4)
        cursor = self.db.execute('INSERT INTO alerts(payload) VALUES (?)', (json.dumps(value),))
        self.db.commit()
        export_connection(self.db, self.history_path)
        return cursor.lastrowid

    def update_alert(self, ident, value):
        notice=make_notice(value,ident)
        if notice:value['notification_summary']=notice
        self.db.execute('UPDATE alerts SET payload=? WHERE id=?', (json.dumps(value), ident))
        self.db.commit()
        export_connection(self.db, self.history_path)

    def close(self):
        self.db.commit()
        self.db.close()
