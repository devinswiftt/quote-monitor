"""US quote worker: independent calendar, connection and phase-local turnover baseline."""
from datetime import datetime
import json,logging,queue,threading,time,math
from .markets import NY, is_us, parse_time, us_phase
from .engine import Engine
from .storage import Storage
from .watchlist import Watchlist
from .session import MarketSession
from .live import Publisher
from .connection import ConnectionHealth,retry_delay
from .snapshot import snapshot_event
from .notice import make_notice

LOG=logging.getLogger('hk_quote.us')
SOURCE='Nasdaq Basic/TotalView 与 NYSE Arca；以 OpenD 实际权限为准，不代表全市场完整成交及盘口'
VALID_TYPES={'AUTO_MATCH','ODD_LOT','AUCTION','EXTENDED_TRADING_HOURS','T','CROSS_MARKET','ODD_LOT_CROSS_MARKET','MARKET_CENTER_OPENING'}


def tick_event(row):
    code=str(row['code']);kind=str(row.get('type','AUTO_MATCH'))
    if not is_us(code) or kind not in VALID_TYPES:return None
    ts=parse_time(row['time'],code);price=float(row['price']);volume=float(row['volume']);amount=float(row['turnover'])
    if not all(math.isfinite(v) for v in (price,volume,amount)) or price<=0 or volume<0 or amount<0:return None
    return dict(kind='tick',code=code,ts=ts,price=price,volume=volume,amount=amount,sequence=str(row['sequence']),direction=str(row.get('ticker_direction','NEUTRAL')),trade_type=kind,market='US',currency='USD',session=us_phase(ts),trading_date=datetime.fromtimestamp(ts,NY).strftime('%Y-%m-%d'),source_scope=SOURCE)


def start_worker(config,stop,notify):
    config=dict(config,names=dict(config.get('names',{})))
    thread=threading.Thread(target=run,args=(config,stop,notify),daemon=True,name='us-quotes');thread.start();return thread


def run(c,stop,notify):
    import futu as ft
    publisher=Publisher();pending=queue.Queue(maxsize=20000);overflow=threading.Event()
    store=Storage(c['database']);watch=Watchlist(c['database']);calendar=MarketSession('data/us-trading-calendar.json')
    engine=Engine(c);active={};release={};retry={};ctx=None;attempt=0;retry_at=0;phase_previous=None;next_snapshot=next_health=next_bars=0
    health=ConnectionHealth(c['host'],c['port'],publisher.send,path='data/us-connection.json',initial_state='idle',market='US')
    def put(event):
        event['received_at']=time.time()
        try:pending.put_nowait(event)
        except queue.Full:overflow.set()
    class Quotes(ft.StockQuoteHandlerBase):
        def on_recv_rsp(self,rsp):
            ret,frame=super().on_recv_rsp(rsp)
            if ret==ft.RET_OK:
                for row in frame.to_dict('records'):
                    try:put(dict(kind='quote',code=row['code'],ts=parse_time(str(row['data_date'])+' '+str(row['data_time']),row['code']),price=float(row['last_price']),prev_close_price=float(row['prev_close_price']),market='US',currency='USD'))
                    except (ValueError,TypeError,KeyError):LOG.warning('美股报价解析失败')
            return ret,frame
    class Ticks(ft.TickerHandlerBase):
        def on_recv_rsp(self,rsp):
            ret,frame=super().on_recv_rsp(rsp)
            if ret==ft.RET_OK:
                for row in frame.to_dict('records'):
                    try:
                        event=tick_event(row)
                        if event:put(event)
                    except (ValueError,TypeError,KeyError):LOG.warning('美股逐笔解析失败')
            return ret,frame
    class Books(ft.OrderBookHandlerBase):
        def on_recv_rsp(self,rsp):
            ret,book=super().on_recv_rsp(rsp)
            if ret==ft.RET_OK:
                try:
                    event=dict(kind='book_snapshot',code=book['code'],ts=time.time(),bid=[list(x[:3]) for x in book['Bid']],ask=[list(x[:3]) for x in book['Ask']],market='US')
                    put(event)
                except (ValueError,TypeError,KeyError):LOG.warning('美股盘口解析失败')
            return ret,book
    def close_context():
        nonlocal ctx
        if ctx is not None:ctx.close();ctx=None
        active.clear();release.clear();engine.reset()
        while not pending.empty():
            try:pending.get_nowait()
            except queue.Empty:break
    try:
        while not stop.is_set():
            controls=[row for row in watch.rows(include_deleted=True) if is_us(row['code'])]
            now=time.time();date=datetime.fromtimestamp(now,NY).strftime('%Y-%m-%d');kind=calendar.days.get(date)
            phase=us_phase(now,kind or 'WHOLE')
            if phase!=phase_previous:
                engine.reset();phase_previous=phase
            wanted={r['code']:r for r in controls if r['enabled'] and not r['deleted']}
            for row in controls:
                code=row['code']
                if code not in wanted:
                    if code in active:release[code]=0
                    active.pop(code,None);engine.drop(code);engine.profiles.pop(code,None)
                    if row['state']!='stopped':watch.acknowledge(row,'stopped')
            for code in list(active):
                if code not in wanted:active.pop(code,None)
            if not wanted or phase=='CLOSED':
                close_context()
                for row in wanted.values():
                    if row['state']!='waiting_session':watch.acknowledge(row,'waiting_session')
                store.db.commit();health.set('idle' if not wanted else 'paused','美股监控未开启' if not wanted else '美股休市；保留历史行情',checked_at=now,phase=phase)
                stop.wait(.5);continue
            if ctx is None:
                if time.monotonic()<retry_at:stop.wait(.5);continue
                try:
                    health.set('connecting','正在连接美股行情',phase=phase)
                    ctx=ft.OpenQuoteContext(host=c['host'],port=c['port'],is_async_connect=True);ctx.set_sync_query_connect_timeout(3);ctx._query_timeout=3
                    ret,state=ctx.get_global_state()
                    if ret!=ft.RET_OK or not state.get('qot_logined'):raise ValueError('OpenD 行情未登录')
                    if date not in calendar.days:
                        ret,days=ctx.request_trading_days(market=ft.TradeDateMarket.US,start=date,end=date)
                        if ret!=ft.RET_OK:raise ValueError('美股交易日历确认失败：'+str(days))
                        calendar.update(date,days)
                    kind=calendar.days[date];phase=us_phase(now,kind)
                    if phase=='CLOSED':close_context();continue
                    ctx.set_handler(Quotes());ctx.set_handler(Ticks());ctx.set_handler(Books())
                    health.failed.clear();attempt=0;next_snapshot=next_bars=next_health=0
                except Exception as exc:
                    close_context();delay=retry_delay(attempt);attempt+=1;retry_at=time.monotonic()+delay
                    health.set('disconnected','美股行情连接失败：'+str(exc)[:180],checked_at=now,next_retry=now+delay)
                    stop.wait(.5);continue
            if health.failed.is_set():close_context();health.failed.clear();retry_at=time.monotonic()+1;continue
            for code in list(release):
                if time.monotonic()<release[code]:continue
                try:
                    ret,_=ctx.unsubscribe([code],[ft.SubType.QUOTE,ft.SubType.TICKER,ft.SubType.ORDER_BOOK,ft.SubType.K_1M])
                    if ret==ft.RET_OK:release.pop(code,None)
                    else:release[code]=time.monotonic()+10
                except Exception:release[code]=time.monotonic()+10
            for code,row in wanted.items():
                if code in active and active[code]['revision']==row['revision']:continue
                if time.monotonic()<retry.get((code,row['revision']),0):continue
                try:
                    ret,message=ctx.subscribe([code],[ft.SubType.QUOTE,ft.SubType.TICKER],is_first_push=False,session=ft.Session.ETH)
                    if ret!=ft.RET_OK:raise ValueError(str(message))
                    # Optional depth failure must not disable valid quote/ticker monitoring.
                    book_ret,book_error=ctx.subscribe([code],[ft.SubType.ORDER_BOOK],is_first_push=True)
                    minute_ret,minute_error=ctx.subscribe([code],[ft.SubType.K_1M],subscribe_push=False,session=ft.Session.ETH)
                    note='' if book_ret==ft.RET_OK else '盘口权限不可用，继续监控价格和成交'
                    release.pop(code,None);engine.drop(code)
                    name=row['name'] or code;ret,frame=ctx.get_market_snapshot([code])
                    if ret==ft.RET_OK and len(frame):
                        value=json.loads(frame.to_json(orient='records',force_ascii=False))[0];name=value.get('name') or name;put(snapshot_event(value))
                    active[code]=dict(revision=row['revision'],name=name,warmup_until=time.time()+c['warmup_seconds'],note=note,minute=minute_ret==ft.RET_OK)
                    watch.acknowledge(row,'warming',note,warmup_until=active[code]['warmup_until'],name=name)
                    LOG.info('美股订阅完成 %s %s，独立盘前/盘中/盘后基线；%s',code,name,note)
                except Exception as exc:
                    watch.acknowledge(row,'error',str(exc)[:300]);retry[(code,row['revision'])]=time.monotonic()+30
            for row in wanted.values():
                if row['code'] in active and now>=active[row['code']]['warmup_until'] and row['state']=='warming':watch.acknowledge(row,'monitoring',active[row['code']]['note'])
            if overflow.is_set():
                engine.reset();overflow.clear()
                while not pending.empty():
                    try:pending.get_nowait()
                    except queue.Empty:break
                for item in active.values():item['warmup_until']=time.time()+c['warmup_seconds']
                LOG.warning('美股队列溢出，重新预热')
            current_controls={r['code']:r for r in watch.rows()}
            for _ in range(500):
                try:event=pending.get_nowait()
                except queue.Empty:break
                code=event['code'];current=current_controls.get(code)
                if code not in active or not current or not current['enabled'] or current['revision']!=active[code]['revision']:continue
                if datetime.fromtimestamp(event['ts'],NY).strftime('%Y-%m-%d')!=date and event['kind'] not in ('book_snapshot','market_snapshot'):continue
                store.event(time.time(),event)
                if event['kind'] in ('tick','quote','book_snapshot'):publisher.send(event)
                if event['kind']=='book_snapshot':
                    engine.process(dict(event,kind='book'));depth=dict(kind='depth',code=code,ts=event['ts'],bids=len(event['bid']),asks=len(event['ask']),market='US');store.event(now,depth);publisher.send(depth)
                elif event['kind']=='tick' and -2<=time.time()-event['ts']<=c['max_delay_seconds'] and us_phase(event['ts'],kind)==phase:
                    alert=engine.process(event)
                    if alert and time.time()>=active[code]['warmup_until']:
                        alert.update(name=active[code]['name'],market='US',currency='USD',session=phase,trading_date=date,received_at=event['received_at'],window_seconds=alert.get('window_seconds',c['window_seconds']),source_scope=SOURCE)
                        ident=store.alert(alert);alert['notification_summary']=make_notice(alert,ident);store.update_alert(ident,alert)
                        notify(alert,c.get('desktop_notifications',False))
            store.db.commit()
            if time.monotonic()>=next_health:
                next_health=time.monotonic()+5
                try:
                    ret,state=ctx.get_global_state()
                    if ret!=ft.RET_OK or not state.get('qot_logined'):raise ValueError('OpenD 美股连接中断')
                    warming=any(now<v['warmup_until'] for v in active.values())
                    health.set('warming' if warming else 'connected' if active else 'checking','美股已订阅，独立基线预热中' if warming else '美股行情已连接' if active else 'OpenD 已连接，等待美股订阅成功',checked_at=time.time(),warmup_until=max([v['warmup_until'] for v in active.values()] or [0]),phase=phase,symbols=list(active))
                except Exception as exc:health.disconnected(str(exc));close_context();continue
            if time.monotonic()>=next_snapshot:
                next_snapshot=time.monotonic()+60
                if active:
                    try:
                        ret,frame=ctx.get_market_snapshot(list(active))
                        if ret==ft.RET_OK:
                            for row in json.loads(frame.to_json(orient='records',force_ascii=False)):put(snapshot_event(row))
                    except Exception:LOG.warning('美股快照暂不可用')
                for code in active:
                    profile=engine.profiles.get(code);value=profile.estimate(now,c['profile_quantile'],c['profile_multiplier'],c['profile_min_samples']) if profile else None
                    event=dict(kind='threshold_status',code=code,ts=now,value=value,market='US',session=phase);store.event(now,event)
            store.db.commit()
            if time.monotonic()>=next_bars:
                next_bars=time.monotonic()+60
                for code,item in active.items():
                    if not item['minute']:continue
                    try:
                        ret,frame=ctx.get_cur_kline(code,1000,ktype=ft.KLType.K_1M,autype=ft.AuType.NONE)
                        if ret!=ft.RET_OK:continue
                        bars=[]
                        for row in frame.to_dict('records'):
                            ts=parse_time(row['time_key'],code)
                            if str(row['time_key']).startswith(date) and ts<int(now//60)*60 and us_phase(ts,kind)!='CLOSED':bars.append(dict(time=int(ts//60)*60,open=float(row['open']),high=float(row['high']),low=float(row['low']),close=float(row['close']),volume=float(row['volume']),source='futu',market='US'))
                        put(dict(kind='chart_history',code=code,ts=now,bars=bars,market='US'))
                    except Exception:LOG.warning('美股分钟图补取失败 %s',code)
            store.db.commit();stop.wait(.1)
    except Exception:
        LOG.exception('美股监听异常退出');health.set('disconnected','美股监听异常退出，查看本机日志')
        for row in watch.rows():
            if is_us(row['code']) and row['enabled']:watch.acknowledge(row,'error','美股监听异常退出，需重启服务')
    finally:
        close_context();health.close();store.close()
