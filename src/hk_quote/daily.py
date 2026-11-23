"""On-demand unadjusted daily candles, cached independently of live monitoring."""
from datetime import datetime,timedelta
import json,sqlite3,time,math
from .engine import HK
from .markets import timezone, parse_time


def daily_bar(row,code="HK"):
    value=row.get('turnover')
    turnover=float(value) if value is not None else None
    if turnover is not None and (not math.isfinite(turnover) or turnover<0):turnover=None
    return dict(time=parse_time(str(row['time_key'])[:10]+' 00:00:00',code),
                **{key:float(row[key]) for key in ('open','high','low','close','volume')},
                turnover=turnover,change_rate=(float(row['change_rate']) if row.get('change_rate') is not None and math.isfinite(float(row['change_rate'])) else None),source='daily')


def fetch_daily(code,host='127.0.0.1',port=11111):
    import futu as ft
    now=datetime.now(timezone(code));ctx=ft.OpenQuoteContext(host=host,port=port,is_async_connect=True)
    try:
        ctx.set_sync_query_connect_timeout(3);ctx._query_timeout=5
        ret,frame,key=ctx.request_history_kline(code,start=(now-timedelta(days=365)).strftime('%Y-%m-%d'),end=now.strftime('%Y-%m-%d'),ktype=ft.KLType.K_DAY,autype=ft.AuType.NONE,max_count=1000)
        if ret!=ft.RET_OK:raise ValueError(str(frame)[:250])
        return [daily_bar(row,code) for row in frame.to_dict('records')][-250:]
    finally:ctx.close()


def daily_history(database,code,fetch=fetch_daily,force=False):
    with sqlite3.connect(database,timeout=5) as db:
        row=db.execute("SELECT payload FROM latest_state WHERE code=? AND kind='daily_history'",(code,)).fetchone()
    if row and not force:
        cached=json.loads(row[0])
        if cached.get('schema_version')==3 and time.time()-cached['ts']<300:return dict(cached,cached=True)
    bars=fetch(code)
    result=dict(schema_version=3,kind='daily_history',code=code,ts=time.time(),bars=bars,adjustment='NONE',cached=False)
    with sqlite3.connect(database,timeout=5) as db:db.execute('INSERT OR REPLACE INTO latest_state VALUES (?,?,?)',(code,'daily_history',json.dumps(result)))
    return result


def day_summary(database,code,date,fetch=fetch_daily):
    """Use only the selected day's actual daily candle; never infer from broker prints."""
    selected=datetime.strptime(date,'%Y-%m-%d').date()
    if selected>datetime.now(timezone(code)).date():return dict(date=date,available=False,message='该日期尚未产生行情')
    with sqlite3.connect(database,timeout=5) as db:
        row=db.execute("SELECT payload FROM latest_state WHERE code=? AND kind='daily_history'",(code,)).fetchone()
    def find(payload):
        return next((bar for bar in payload.get('bars',[]) if datetime.fromtimestamp(bar['time'],timezone(code)).date()==selected),None)
    cache=json.loads(row[0]) if row else {}
    bar=find(cache)
    try:
        if not bar or cache.get('schema_version')!=3 or selected==datetime.now(timezone(code)).date():
            bar=find(daily_history(database,code,fetch))
    except Exception:
        if not bar:return dict(date=date,available=False,message='该日日K暂不可用，请检查OpenD及历史行情权限')
    if not bar:return dict(date=date,available=False,message='该日期无日K记录（可能休市或尚未上市）')
    return dict(date=date,available=True,high=bar['high'],low=bar['low'],close=bar['close'],change_rate=bar.get('change_rate'),source='富途不复权日K',completed=selected<datetime.now(timezone(code)).date())


def validate_history_date(date,listing_date=None,calendar=None,today=None):
    selected=datetime.strptime(date,'%Y-%m-%d').date()
    current=today or datetime.now(HK).date()
    if selected>current:raise ValueError('不能选择未来日期')
    if listing_date and selected<datetime.strptime(listing_date,'%Y-%m-%d').date():
        raise ValueError('该股票于'+listing_date+'上市，不能选择上市前日期')
    if selected.weekday()>=5 or (calendar or {}).get(date)=='CLOSED':
        raise ValueError('该日期港股休市，请选择交易日')
    return date
