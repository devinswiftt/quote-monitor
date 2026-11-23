"""Intraday broker comparisons and saved price series."""
from collections import defaultdict
import json
from .broker_periods import broker_periods,volume_snapshots


def intraday_insights(db,start,end,samples):
    tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    queue=[];prices=defaultdict(dict)
    if 'events' in tables:
        for received,payload in db.execute("SELECT received,payload FROM events WHERE received>=? AND received<? AND json_extract(payload,'$.kind')='broker' ORDER BY received,id",(start,end)):
            event=json.loads(payload);queue.append((received,event))
    if 'chart_ticks' in tables:
        for code,ts,price,volume in db.execute('SELECT code,ts,price,volume FROM chart_ticks WHERE ts>=? AND ts<? ORDER BY ts',(start,end)):
            bar=prices[code].setdefault(int(ts//60)*60,dict(ts=int(ts//60)*60,price=price,volume=0))
            bar['price']=price;bar['volume']+=volume or 0
    price_rows={code:list(bars.values()) for code,bars in prices.items()}
    return dict(prices=price_rows,broker_periods=broker_periods(queue,start,end,samples,volumes=volume_snapshots(db,samples)))
