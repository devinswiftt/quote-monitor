"""One-pass replay with the same analyzer and cutoffs as live processing."""
from datetime import datetime, timedelta
import json
from pathlib import Path
import sqlite3
from .engine import HK
from .participation import Participation


def reconstruct(database, date, update=False):
    day=datetime.strptime(date,'%Y-%m-%d').replace(tzinfo=HK)
    start,end=day.timestamp(),(day+timedelta(days=1)).timestamp()
    with sqlite3.connect(Path(database).resolve().as_uri()+'?mode=ro',uri=True) as db:
        alerts=[(ident,json.loads(p),p) for ident,p in db.execute(
            "SELECT id,payload FROM alerts WHERE json_extract(payload,'$.ts')>=? AND json_extract(payload,'$.ts')<? ORDER BY id",(start,end))]
        # An unfinished live record belongs to the collector, not replay.
        alerts=[r for r in alerts if r[1].get('signal') and r[1].get('participation',{}).get('status')!='pending']
        events=[]
        for received,payload in db.execute('SELECT received,payload FROM events WHERE received>=? AND received<? ORDER BY id',(start-80,end+12)):
            event=json.loads(payload)
            events.append((event.get('received_at',received),event))
    alerts.sort(key=lambda r:r[1].get('received_at',r[1]['ts']))
    events.sort(key=lambda r:r[0])
    analyzer=Participation();pending=[];index=0;results=[]
    def finish(row):
        ident,alert,original=row
        profile=analyzer.analyze(alert,alert.get('received_at',alert['ts']),alert.get('window_seconds',3))
        profile['replayed']=True
        results.append(dict(id=ident,alert=alert,profile=profile,original=original))
    for received,event in events:
        while index<len(alerts) and alerts[index][1].get('received_at',alerts[index][1]['ts'])<=received:
            pending.append(alerts[index]);index+=1
        for row in list(pending):
            if received>row[1].get('received_at',row[1]['ts'])+11 or event['kind']=='reset':
                finish(row);pending.remove(row)
        analyzer.observe(received,event)
    for row in pending+alerts[index:]:finish(row)
    if update:
        with sqlite3.connect(database,timeout=10) as db:
            for row in results:
                # Preserve concurrent changes; modify only the analyzed profile.
                value=dict(row['alert'],participation=row['profile'])
                db.execute('UPDATE alerts SET payload=? WHERE id=? AND payload=?',
                    (json.dumps(value,ensure_ascii=False),row['id'],row['original']))
    for row in results:row.pop('original')
    return sorted(results,key=lambda r:r['id'])
