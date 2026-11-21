"""Supplement historical episodes without modifying any raw alert payload."""
import argparse
from datetime import datetime,timedelta
import json
from pathlib import Path
import sqlite3
from .engine import HK
from .participation import Participation
from .behavior_store import BehaviorMonitor


def replay(database,date,config=None):
    day=datetime.strptime(date,'%Y-%m-%d').replace(tzinfo=HK)
    start,end=day.timestamp(),(day+timedelta(days=1)).timestamp()
    with sqlite3.connect(Path(database).resolve().as_uri()+'?mode=ro',uri=True) as db:
        events=[(received,json.loads(payload)) for received,payload in db.execute(
            'SELECT received,payload FROM events WHERE received>=? AND received<? ORDER BY id',(start,end))]
    class Store:
        pass
    store=Store();store.db=sqlite3.connect(database,timeout=10)
    monitor=BehaviorMonitor(store,config,source='replay');participation=Participation()
    last=start
    try:
        for processed,event in events:
            received=event.get('received_at',processed)
            if received<last:continue
            monitor.poll(received,participation)
            if event['kind']=='reset':
                monitor.stop_all(event.get('reason','历史连接重置'),received,participation)
            elif event['kind']=='behavior_reset':
                monitor.stop(event['code'],event.get('reason','历史单股重置'),received,participation)
            participation.observe(received,event)
            if event['kind'] in ('book','tick') and -2<=processed-event['ts']<=3:
                monitor.process(event,participation)
            last=received
        monitor.stop_all('历史采样结束，后续情况未知',last,participation)
        store.db.commit()
        return store.db.execute("SELECT COUNT(*) FROM behavior_events WHERE event_key LIKE 'replay:%' AND started>=? AND started<?",(start,end)).fetchone()[0]
    finally:store.db.close()


def main():
    p=argparse.ArgumentParser();p.add_argument('--database',default='data/quotes.sqlite3');p.add_argument('--date',required=True);p.add_argument('--config',default='config/settings.json')
    a=p.parse_args();config=json.loads(Path(a.config).read_text()).get('behavior',{})
    print('历史行为观察事件：',replay(a.database,a.date,config))


if __name__=='__main__':main()
