"""Source-dated broker snapshots and independent after-close collection."""
from datetime import datetime
import json,logging,sqlite3,threading,time,hashlib
from .engine import HK


def initialize(db):
    db.execute('CREATE TABLE IF NOT EXISTS broker_daily(code TEXT,date TEXT,payload TEXT,observed REAL,source_time TEXT,after_close INTEGER DEFAULT 0,PRIMARY KEY(code,date))')
    db.execute('CREATE TABLE IF NOT EXISTS broker_archive_meta(key TEXT PRIMARY KEY)')
    db.execute('CREATE TABLE IF NOT EXISTS broker_samples(id INTEGER PRIMARY KEY,code TEXT,source_time TEXT,observed REAL,last_seen REAL,signature TEXT,payload TEXT,after_close INTEGER,UNIQUE(code,source_time,signature))')
    db.execute('CREATE INDEX IF NOT EXISTS broker_samples_time ON broker_samples(code,source_time)')
    db.execute('CREATE TABLE IF NOT EXISTS broker_captures(code TEXT,observed REAL,sample_id INTEGER,after_close INTEGER,PRIMARY KEY(code,observed,sample_id))')
    if not db.execute("SELECT 1 FROM broker_archive_meta WHERE key='timeseries_v1'").fetchone():
        for received,payload in db.execute("SELECT received,payload FROM events WHERE json_extract(payload,'$.kind')='broker_stats' ORDER BY id").fetchall():
            save(db,json.loads(payload))
        db.execute("INSERT OR IGNORE INTO broker_archive_meta VALUES ('timeseries_v1')")


def save(db,event,after_close=False):
    groups={}
    for row in event.get('rows',[]):
        stamp=str(row.get('data_time_str') or '')
        try:date=datetime.strptime(stamp[:10],'%Y-%m-%d').strftime('%Y-%m-%d')
        except ValueError:continue
        groups.setdefault(date,[]).append(row)
    for date,rows in groups.items():
        source=max(str(r['data_time_str']) for r in rows)
        captured=datetime.fromtimestamp(event['ts'],HK).strftime('%Y-%m-%d')
        post=bool(after_close and captured==date)
        price_context=None
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='latest_state'").fetchone():
            quotes=[json.loads(r[0]) for r in db.execute("SELECT payload FROM latest_state WHERE code=? AND kind IN ('quote','tick')",(event['code'],))]
            quotes=[q for q in quotes if q.get('price') is not None and q.get('ts',0)<=event['ts'] and datetime.fromtimestamp(q.get('ts',0),HK).strftime('%Y-%m-%d')==date]
            if quotes:
                q=max(quotes,key=lambda q:q['ts']);price_context=dict(price=q['price'],ts=q['ts'],basis='latest_observed_trade_at_capture')
        source_price_context=None
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='chart_ticks'").fetchone():
            try:source_ts=datetime.fromisoformat(source).replace(tzinfo=HK).timestamp()
            except ValueError:source_ts=None
            if source_ts:
                price_row=db.execute('SELECT ts,price FROM chart_ticks WHERE code=? AND ts<=? AND ts>=? ORDER BY ts DESC LIMIT 1',(event['code'],source_ts,source_ts-60)).fetchone()
                if price_row:source_price_context=dict(ts=price_row[0],price=price_row[1],basis='last_saved_trade_within_60s_before_source_time')
        value=dict(event,rows=rows,archive_date=date,after_close=post,price_context=price_context,source_price_context=source_price_context)
        ordered=sorted(rows,key=lambda r:(str(r.get('broker_name','')),str(r.get('buy_sell_type',''))))
        signature=hashlib.sha256(json.dumps(ordered,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        db.execute('INSERT OR IGNORE INTO broker_samples(code,source_time,observed,last_seen,signature,payload,after_close) VALUES (?,?,?,?,?,?,?)',(event['code'],source,event['ts'],event['ts'],signature,json.dumps(value,ensure_ascii=False),int(post)))
        ident=db.execute('SELECT id FROM broker_samples WHERE code=? AND source_time=? AND signature=?',(event['code'],source,signature)).fetchone()[0]
        db.execute('UPDATE broker_samples SET last_seen=MAX(last_seen,?),after_close=MAX(after_close,?) WHERE id=?',(event['ts'],int(post),ident))
        db.execute('INSERT OR IGNORE INTO broker_captures VALUES (?,?,?,?)',(event['code'],event['ts'],ident,int(post)))
        old=db.execute('SELECT source_time,after_close FROM broker_daily WHERE code=? AND date=?',(event['code'],date)).fetchone()
        if old and source<old[0]:continue
        value['after_close']=post or bool(old and old[1])
        db.execute('INSERT OR REPLACE INTO broker_daily VALUES (?,?,?,?,?,?)',(event['code'],date,json.dumps(value,ensure_ascii=False),event['ts'],source,int(value['after_close'])))
    return list(groups)


def comparison(db,code,date):
    query="SELECT source_time,payload FROM broker_samples WHERE code=? AND source_time LIKE ? ORDER BY source_time,id"
    samples=db.execute(query,(code,date+'%')).fetchall()
    if not samples:return dict(sample_count=0,changes=[])
    first,last=json.loads(samples[0][1]),json.loads(samples[-1][1])
    def grouped(rows):
        result={}
        for r in rows:
            name=r.get('broker_name');volume=r.get('net_vol')
            if name and isinstance(volume,(int,float)):result[str(name)]=result.get(str(name),0)+volume
        return result
    a,b=grouped(first['rows']),grouped(last['rows']);changes=[]
    for name in sorted(set(a)|set(b)):
        delta=b[name]-a[name] if name in a and name in b else None
        if name not in a:label='后续上榜，不代表首次交易'
        elif name not in b:label='末次未上榜，不代表清仓'
        elif a[name]>0 and b[name]<0:label='由净买转净卖'
        elif a[name]<0 and b[name]>0:label='由净卖转净买'
        elif delta>0:label='净买量增加／净卖量减少'
        elif delta<0:label='净买量减少／净卖量增加'
        else:label='净量未变'
        changes.append(dict(name=name,first_net=a.get(name),last_net=b.get(name),delta=delta,status=label))
    return dict(sample_count=len(samples),first_source_time=samples[0][0],last_source_time=samples[-1][0],changes=changes,
                first_price=first.get('price_context'),last_price=last.get('price_context'),note='首末已保存快照对照，非完整开盘至收盘资金；按展示名称合并。不能识别庄家或真实成交客户。')


def history(database,code,date=None):
    with sqlite3.connect(database,timeout=5) as db:
        dates=[r[0] for r in db.execute('SELECT date FROM broker_daily WHERE code=? ORDER BY date DESC',(code,))]
        row=db.execute('SELECT payload FROM broker_daily WHERE code=? AND date=?',(code,date)).fetchone() if date else None
        summary=comparison(db,code,date) if date else None
    return dict(dates=dates,date=date,event=json.loads(row[0]) if row else None,comparison=summary)


def start_worker(config,stop):
    def run():
        from .session import MarketSession
        from .watchlist import Watchlist
        import futu as ft
        known_days={}
        while not stop.is_set():
            now=datetime.now(HK);date=now.strftime('%Y-%m-%d');kind=MarketSession().days.get(date,known_days.get(date))
            minute=now.hour*60+now.minute
            first_close=735 if kind in (None,'MORNING') else 975
            due=minute>=first_close
            slot=max((v for v in [first_close,first_close+15,first_close+45] if v<=minute),default=first_close)
            target=now.replace(hour=slot//60,minute=slot%60,second=0,microsecond=0).timestamp()
            if now.weekday()<5 and due and kind!='CLOSED':
                stocks=[s for s in Watchlist(config['database']).rows() if s['code'].startswith('HK.')]
                with sqlite3.connect(config['database'],timeout=5) as db:
                    stocks=[s for s in stocks if not db.execute('SELECT 1 FROM broker_daily WHERE code=? AND date=? AND after_close=1 AND observed>=?',(s['code'],date,target)).fetchone()]
                if not stocks:
                    stop.wait(300);continue
                ctx=None
                try:
                    ctx=ft.OpenQuoteContext(host=config['host'],port=config['port'],is_async_connect=True)
                    ctx.set_sync_query_connect_timeout(3);ctx._query_timeout=3
                    if kind is None:
                        ret,days=ctx.request_trading_days(market=ft.TradeDateMarket.HK,start=date,end=date)
                        if ret!=ft.RET_OK:raise RuntimeError(str(days))
                        kind=next((r['trade_date_type'] for r in days if r['time']==date),'CLOSED')
                        known_days[date]=kind
                    if kind!='CLOSED' and now.hour*60+now.minute >= (735 if kind=='MORNING' else 975):
                        for stock in stocks:
                            if stop.is_set():break
                            code=stock['code']
                            with sqlite3.connect(config['database'],timeout=5) as db:
                                done=db.execute('SELECT after_close,observed FROM broker_daily WHERE code=? AND date=?',(code,date)).fetchone()
                            if done and done[0] and done[1]>=target:continue
                            ret,frame=ctx.get_top_ten_buy_sell_brokers(code,days_before=0)
                            if ret!=ft.RET_OK:continue
                            event=dict(kind='broker_stats',code=code,ts=time.time(),rows=json.loads(frame.to_json(orient='records',force_ascii=False)),error=None)
                            with sqlite3.connect(config['database'],timeout=5) as db:save(db,event,after_close=True)
                except Exception as exc:logging.getLogger('hk_quote').warning('收盘经纪商留档等待重试：%s',exc)
                finally:
                    if ctx:ctx.close()
            stop.wait(300)
    thread=threading.Thread(target=run,daemon=True);thread.start();return thread
