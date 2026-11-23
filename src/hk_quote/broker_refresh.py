"""Explicit upstream refresh; preserve the last successful data on failure."""
import json
import sqlite3
import time
from .broker_archive import initialize,save


def fetch_brokers(code,host='127.0.0.1',port=11111):
    import futu as ft
    ctx=ft.OpenQuoteContext(host=host,port=port,is_async_connect=True)
    try:
        ctx.set_sync_query_connect_timeout(3);ctx._query_timeout=3
        ret,frame=ctx.get_top_ten_buy_sell_brokers(code,days_before=0)
        if ret!=ft.RET_OK:raise ValueError(str(frame)[:250])
        return json.loads(frame.to_json(orient='records',force_ascii=False))
    finally:ctx.close()


def refresh_brokers(database,code,fetch=fetch_brokers):
    rows=fetch(code)
    now=time.time();event=dict(kind='broker_stats',code=code,ts=now,received_at=now,rows=rows,error=None,source='manual_refresh')
    payload=json.dumps(event,ensure_ascii=False)
    with sqlite3.connect(database,timeout=5) as db:
        initialize(db);save(db,event)
        db.execute('INSERT OR REPLACE INTO latest_state(code,kind,payload) VALUES (?,?,?)',(code,'broker_stats',payload))
        db.execute('INSERT INTO events(received,payload) VALUES (?,?)',(now,payload))
    return event
