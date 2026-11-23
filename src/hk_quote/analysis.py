"""Live daily analysis from finalized and pending persisted alerts."""
from datetime import datetime, timedelta
import json
import sqlite3
from pathlib import Path
from .broker_attribution import BrokerAttribution
from .insights import intraday_insights
from .engine import HK
from .markets import is_us
from .notice import with_notice
from .participation import summarize
from .behavior_store import read_behaviors


def daily_analysis(database, date=None, names=None):
    day = datetime.strptime(date, '%Y-%m-%d').replace(tzinfo=HK) if date else datetime.now(HK).replace(hour=0, minute=0, second=0, microsecond=0)
    start, end = day.timestamp(), (day + timedelta(days=1)).timestamp()
    result = []
    labels = {code:name for code,name in (names or {}).items() if not is_us(code)}
    with sqlite3.connect(Path(database).resolve().as_uri()+'?mode=ro', uri=True, timeout=2) as db:
        behaviors=read_behaviors(db,start,end)
        for ident, payload in db.execute("SELECT id,payload FROM alerts WHERE json_extract(payload,'$.ts')>=? AND json_extract(payload,'$.ts')<? ORDER BY id DESC", (start,end)):
            alert = with_notice(json.loads(payload),ident)
            if not alert.get('signal') or is_us(alert['code']):
                continue
            labels[alert['code']] = alert.get('name') or labels.get(alert['code']) or alert['code']
            profile = alert.get('participation') or dict(status='unavailable', valid_samples=0, target_samples=21, coverage=0, bid=[], ask=[])
            result.append(dict(id=ident, alert=alert, profile=profile))
        evidence_events=[dict(r['alert'],reference='#'+str(r['id'])) for r in result]+[dict(b,reference='B'+str(b['id'])) for b in behaviors]
        analyzer=BrokerAttribution(db,start,end,evidence_events)
        for row in result:row['broker_attribution']=analyzer.analyze(row['alert'])
        for behavior in behaviors:behavior['broker_attribution']=analyzer.analyze(behavior)
        insights=intraday_insights(db,start,end,analyzer.samples)
    return dict(insights=insights,behaviors=behaviors,date=day.strftime('%Y-%m-%d'), names=labels, rows=result, summary=summarize([r['alert'] for r in result]), updated_at=datetime.now(HK).timestamp())
