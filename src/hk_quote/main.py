import argparse
import json
import logging
import queue
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from .engine import Engine, HK, timestamp
from .markets import is_us,timezone
from .storage import Storage
from .depth import DepthMonitor
from .brokers import BrokerCache, normalize
from .instruments import stock_label
from .participation import Participation
from .live import Publisher
from .connection import ConnectionHealth, retry_delay
from .watchlist import Watchlist
from .session import MarketSession
from .broker_archive import start_worker
from .snapshot import snapshot_event,optional_number
from .behavior import LABELS as BEHAVIOR_LABELS, PHASES as BEHAVIOR_PHASES
from .behavior_store import BehaviorMonitor

LOG = logging.getLogger('hk_quote')


def notify(a, desktop=False):
    if is_us(a['code']):
        label=a.get('signal_label') or {'BUY':'疑似集中主动买入','SELL':'疑似集中主动卖出','VOLUME':'异常成交放大'}[a['signal']]
        text=f"{stock_label(a['code'],a.get('name'))} {label} · {datetime.fromtimestamp(a['ts'],timezone(a['code'])):%H:%M:%S} ET · US${a['amount']:,.2f} · 触发价 US${a['price']:.3f}"
        LOG.warning(text)
        if desktop:desktop_notify(text)
        return
    side = a.get('signal_label') or {'BUY': '疑似集中主动买入', 'SELL': '疑似集中主动卖出', 'VOLUME': '异常成交放大'}[a['signal']]
    multiple_text = f"{a['multiple']:.1f}倍" if a['multiple'] is not None else '基线为零'
    threshold_text = f" 门槛 HK${a['threshold']:,.0f}" if 'threshold' in a else ''
    price_text = f"成交价 HK${a['price']:.3f}" if a.get('price') is not None else '成交价未记录'
    if a.get('price_delta_pct') is not None:
        price_text += f"，较上次异动 {a['price_delta']:+.3f}（{a['price_delta_pct']:+.2f}%）"
    else:
        price_text += '，无可比较的上次异动价格'
    text = (f"{stock_label(a['code'], a.get('name'))} {side} [{a['level']}] "
            f"{datetime.fromtimestamp(a['ts'], HK):%H:%M:%S} 香港时间 | "
            f"{price_text} | HK${a['amount']:,.0f} / {multiple_text}{threshold_text} | "
            f"方向集中度 {a['direction_ratio']:.0%} 覆盖率 {a['coverage']:.0%} | "
            f"盘口 {a['depth']}档")
    LOG.warning(text)
    if desktop:
        desktop_notify(text)


NOTIFICATIONS = queue.Queue(maxsize=100)


def desktop_notify(text):
    try:
        NOTIFICATIONS.put_nowait(text)
    except queue.Full:
        LOG.error('通知队列已满，消息仍记录在日志')


def notification_worker():
    while True:
        text = NOTIFICATIONS.get()
        try:
            if sys.platform == 'darwin':
                script = ('on run argv\ndisplay notification (item 1 of argv) '
                          'with title "行情监听" sound name "Glass"\nend run')
                result = subprocess.run(['osascript', '-e', script, text], timeout=5,
                                        capture_output=True, text=True)
                if result.returncode:
                    LOG.error('桌面通知失败: %s', result.stderr.strip())
        except (OSError, subprocess.TimeoutExpired):
            LOG.exception('桌面通知失败')
        finally:
            NOTIFICATIONS.task_done()


def live(c, seconds=None, check=False):
    import futu as ft
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    q = queue.Queue(maxsize=20000)
    overflow = threading.Event()

    publisher = Publisher()
    dark_codes = set()
    dark_candidates = set()
    next_dark_discovery = 0

    def put(event):
        if event.get('code') in dark_codes:
            event['market_session'] = 'HK_DARK'
        if event['kind'] in ('tick', 'quote', 'broker', 'book_snapshot', 'depth', 'auction_tick'):
            event['received_at'] = time.time()
            publisher.send(event)
        try:
            q.put_nowait((time.time(), event))
        except queue.Full:
            overflow.set()

    class Quotes(ft.StockQuoteHandlerBase):
        def on_recv_rsp(self, rsp_pb):
            ret, data = super().on_recv_rsp(rsp_pb)
            if ret == ft.RET_OK:
                for row in data.to_dict('records'):
                    try:
                        put(dict(kind='quote', code=row['code'], dark_status=str(row.get('dark_status','NONE')), price=float(row['last_price']),prev_close_price=optional_number(row.get('prev_close_price')),
                                 ts=timestamp(str(row['data_date'])+' '+str(row['data_time']))))
                    except (KeyError, ValueError, TypeError):
                        LOG.exception('报价推送解析失败')
            return ret, data

    class Ticks(ft.TickerHandlerBase):
        def on_recv_rsp(self, rsp_pb):
            ret, data = super().on_recv_rsp(rsp_pb)
            if ret == ft.RET_OK:
                for row in data.to_dict('records'):
                    try:
                        trade_type=str(row.get('type','AUTO_MATCH'))
                        if trade_type not in ('AUTO_MATCH','AUCTION'):
                            continue
                        put(dict(kind='auction_tick' if trade_type=='AUCTION' else 'tick',trade_type=trade_type, code=str(row['code']), ts=timestamp(row['time']),
                                 sequence=str(row['sequence']), price=float(row['price']),
                                 volume=float(row['volume']), amount=float(row['turnover']), direction=str(row['ticker_direction'])))
                    except (ValueError, KeyError, TypeError):
                        LOG.exception('逐笔数据格式错误')
            else:
                LOG.error('逐笔回调错误: %s', data)
            return ret, data

    class Books(ft.OrderBookHandlerBase):
        def on_recv_rsp(self, rsp_pb):
            ret, data = super().on_recv_rsp(rsp_pb)
            if ret == ft.RET_OK:
                try:
                    times = [timestamp(data[k]) for k in ('svr_recv_time_bid', 'svr_recv_time_ask')
                             if data.get(k) and not str(data[k]).startswith('0')]
                    put(dict(kind='depth', code=data['code'], ts=time.time(),
                             bids=len(data['Bid']), asks=len(data['Ask'])))
                    put(dict(kind='book_snapshot', code=data['code'], ts=time.time(),
                             bid=[list(x[:3]) for x in data['Bid']], ask=[list(x[:3]) for x in data['Ask']],
                             source_bid=data.get('svr_recv_time_bid'), source_ask=data.get('svr_recv_time_ask')))
                    if len(times) == 2:
                        put(dict(kind='book', code=data['code'], ts=min(times),
                                 bid=[list(x[:3]) for x in data['Bid']],
                                 ask=[list(x[:3]) for x in data['Ask']]))
                except (ValueError, TypeError, KeyError):
                    LOG.exception('盘口时间无效，忽略该快照')
            return ret, data

    class Brokers(ft.BrokerHandlerBase):
        def on_recv_rsp(self, rsp_pb):
            ret, code, data = super().on_recv_rsp(rsp_pb)
            if ret == ft.RET_OK:
                try:
                    put(dict(kind='broker', code=code, ts=time.time(), timestamp_basis='local_receive', source='push',
                             bid=normalize(data[0], 'bid'), ask=normalize(data[1], 'ask')))
                except (ValueError, KeyError, TypeError):
                    LOG.exception('经纪队列解析失败')
            else:
                LOG.warning('经纪队列回调不可用: %s', code)
            return ret, code, data

    participation = Participation()
    pending_participation = []
    market_session = MarketSession()
    broker_cache = BrokerCache()
    broker_stats = {}
    engine = Engine(c)
    depth_monitor = DepthMonitor()
    if c['desktop_notifications'] and not check:
        threading.Thread(target=notification_worker, daemon=True).start()
    store = None if check else Storage(c['database'])
    if store and c.get('threshold_mode') == 'percentile':
        # Reload today's ticks: the profile itself expires trading-time windows.
        cutoff = datetime.now(HK).replace(hour=0,minute=0,second=0,microsecond=0).timestamp()
        learned = 0
        for received, payload in store.db.execute('SELECT received,payload FROM events WHERE received >= ? ORDER BY id', (cutoff,)):
            event = json.loads(payload)
            if (event['kind'] == 'tick' and not is_us(event.get('code','')) and -2 <= received - event['ts'] <= c['max_delay_seconds']
                    and event['ts'] >= cutoff):
                engine.learn(event)
                learned += 1
        if c.get('rapid_move',{}).get('enabled'):
            LOG.info('量价共同触发：已加载当日 %d 条港股逐笔；3/15/60秒独立校准，预热 %d 秒，至少 %d 个滚动样本',
                     learned,c['warmup_seconds'],c['rapid_move'].get('min_samples',60))
        else:
            LOG.info('旧分位数门槛：已加载当日 %d 条逐笔；至少 %d 个非空完整窗口',
                     learned,c.get('profile_min_samples',20))

    def behavior_notification(value):
        evidence=value['evidence']
        desktop_notify(f"{stock_label(value['code'],c.get('names',{}).get(value['code']))} "
            f"{BEHAVIOR_LABELS[value['type']]} · {BEHAVIOR_PHASES[value['phase']]} "
            f"[事件 B{value['id']}]；成交价 HK${evidence['price_to']:.3f}；"
            f"{value.get('status_reason') or evidence['reason']}；仅行情表现，非操作意图确认")

    behaviors = BehaviorMonitor(store,c.get('behavior'),behavior_notification if c['desktop_notifications'] else None) if store else None

    if behaviors:
        calibration_start = datetime.now(HK).replace(hour=0,minute=0,second=0,microsecond=0).timestamp()
        for received,payload in store.db.execute('SELECT received,payload FROM events WHERE received>=? ORDER BY id',(calibration_start,)):
            calibration_event=json.loads(payload)
            if (calibration_event.get('kind')=='tick' and calibration_event['ts']>=calibration_start
                    and -2<=received-calibration_event['ts']<=3):
                behaviors.engine.learn(calibration_event)

    def reset(reason):
        if behaviors:behaviors.stop_all(reason,time.time(),participation)
        engine.reset()
        broker_cache.items.clear()
        if store:
            now = time.time()
            event = dict(kind='reset', ts=now, reason=reason)
            store.event(now, event)
            store.db.commit()
            for _, ident, saved in pending_participation:
                saved['participation']=participation.analyze(saved,saved['received_at'],saved['window_seconds'])
                saved['participation']['interrupted']='监控暂停或重新订阅'
                saved['participation']['interrupted']=reason
                store.update_alert(ident,saved)
            pending_participation.clear()
            participation.observe(now, event)

    health = ConnectionHealth(c['host'],c['port'],publisher.send,desktop_notify if c['desktop_notifications'] and not check else None, initial_state='idle')
    watch = Watchlist(c['database'],c['symbols'],c.get('names',{})) if not check else None
    us_worker=None
    if watch:
        start_worker(c,stop)
        from .us_monitor import start_worker as start_us_worker
        us_worker=start_us_worker(c,stop,notify)
    active = {}
    releases = {}
    stock_retries = {}
    previous_phase = None
    retry_at = 0
    ctx = None
    started = time.monotonic()
    next_depth = 0
    next_broker_flow = 0
    next_broker_stats = 0
    next_broker_retry = 0
    next_health = 0
    retry_attempt = 0
    last_commit = time.monotonic()
    try:
        while not stop.is_set() and (seconds is None or time.monotonic() - started < seconds):
            phase=market_session.phase()
            if previous_phase is not None and phase!=previous_phase:reset('market_phase_changed')
            previous_phase=phase
            if watch:
                store.db.commit()
                controls=[r for r in watch.rows(include_deleted=True) if not is_us(r['code'])]
                c['names'].update({r['code']:r['name'] for r in controls if r['name']})
                session_open, session_message = market_session.status()
                local_now = datetime.now(HK)
                dark_hours = 975 <= local_now.hour*60+local_now.minute < 1110
                if not session_open and dark_hours and time.monotonic() >= next_dark_discovery:
                    next_dark_discovery = time.monotonic()+60
                    try:
                        from .stock_search import fetch as fetch_directory
                        ipos = fetch_directory('ipo', c['host'], c['port'])
                        today = local_now.date().isoformat()
                        dark_candidates = {r['code'] for r in ipos if str(r.get('list_time','')) > today and str(r.get('list_time','')) != 'N/A'}
                    except Exception:
                        LOG.warning('暗盘新股名单查询失败，稍后重试')
                if not dark_hours:
                    dark_candidates.clear()
                desired={r['code']:r for r in controls if r['enabled'] and (session_open or r['code'] in dark_candidates)}
                for row in controls:
                    code=row['code']
                    if not row['enabled'] or code not in desired:
                        behaviors.stop(code,'单股停止监控',time.time(),participation)
                        # Gate first: queued callbacks must not trigger after a stop request.
                        if code in active:releases[code]=0
                        active.pop(code,None);dark_codes.discard(code)
                        engine.drop(code);broker_cache.items.pop(code,None)
                        for _, ident, saved in pending_participation:
                            if saved['code']==code:
                                saved['participation']=participation.analyze(saved,saved['received_at'],saved['window_seconds'])
                                saved['participation']['interrupted']='监控暂停或重新订阅'
                                store.update_alert(ident,saved)
                        pending_participation[:]=[item for item in pending_participation if item[2]['code']!=code]
                        participation.events.pop(code,None);participation.clues.events.pop(code,None)
                        store.db.commit()
                        release_error=''
                        if ctx is not None and code in releases and time.monotonic()>=releases[code]:
                            try:
                                ret,detail=ctx.unsubscribe([code],[ft.SubType.TICKER,ft.SubType.ORDER_BOOK,ft.SubType.QUOTE])
                                if ret==ft.RET_OK:
                                    releases.pop(code,None)
                                    for subtype in [ft.SubType.BROKER,ft.SubType.K_1M]:
                                        try:ctx.unsubscribe([code],[subtype])
                                        except Exception:pass
                                else:
                                    releases[code]=time.monotonic()+30
                                    release_error='监控已停止；订阅释放等待重试：'+str(detail)[:160]
                            except Exception:
                                releases[code]=time.monotonic()+30
                                release_error='监控已停止；行情订阅释放等待重试'
                        if row['state']!='stopped' or release_error:
                            watch.acknowledge(row,'waiting_session' if row['enabled'] else 'stopped',release_error)
                c['symbols']=list(active)
                session_open, session_message = market_session.status()
                if desired and not session_open and not dark_hours:
                    behaviors.stop_all('交易时段结束或午休',time.time(),participation)
                    # Finish existing evidence before clearing session caches. No new signals.
                    for _, ident, saved in pending_participation:
                        saved['participation'] = participation.analyze(saved, saved['received_at'], saved['window_seconds'])
                        saved['participation']['interrupted']='session_paused'
                        store.update_alert(ident, saved)
                    pending_participation.clear()
                    if ctx is not None:
                        ctx.close();ctx=None
                        reset('session_paused')
                    active.clear();releases.clear();stock_retries.clear()
                    c['symbols']=[]
                    for row in desired.values():
                        if row['state']!='waiting_session':watch.acknowledge(row,'waiting_session')
                    store.db.commit()
                    health.set('paused',session_message,next_retry=None)
                    stop.wait(.5);continue
                if not desired:
                    if ctx is not None:ctx.close();ctx=None
                    health.set('paused' if any(r['enabled'] for r in controls) else 'idle',session_message if any(r['enabled'] for r in controls) else '所有股票监控已停止')
                    stop.wait(.5);continue
                if ctx is None:
                    for row in desired.values():
                        if row['state'] not in ('pending','error'):watch.acknowledge(row,'pending','等待 OpenD 连接')
                if ctx is None and time.monotonic()<retry_at:
                    stop.wait(.5);continue
            if ctx is None:
                while not q.empty():
                    try:q.get_nowait()
                    except queue.Empty:break
                try:
                    health.set('connecting','正在连接 OpenD')
                    with socket.create_connection((c['host'], c['port']), timeout=3):
                        pass
                    ctx = ft.OpenQuoteContext(host=c['host'], port=c['port'], is_async_connect=True)
                    ctx.set_sync_query_connect_timeout(3)
                    # Installed Futu SDK exposes request timeout internally (default 12s).
                    ctx._query_timeout = 3
                    ret, state = ctx.get_global_state()
                    if ret != ft.RET_OK or not state.get('qot_logined',False):
                        raise RuntimeError('行情服务器未登录或连接失败：'+str(state))
                    LOG.info('OpenD 状态: %s', state)
                    if check:
                        if not state.get('qot_logined', False):
                            raise RuntimeError('OpenD 尚未登录行情服务器')
                        return
                    date = datetime.now(HK).strftime('%Y-%m-%d')
                    if date not in market_session.days:
                        ret, calendar = ctx.request_trading_days(market=ft.TradeDateMarket.HK, start=date, end=date)
                        if ret != ft.RET_OK:
                            raise RuntimeError('无法确认港股交易日历：'+str(calendar))
                        market_session.update(date, calendar)
                    if not market_session.status()[0] and not (dark_hours and desired):
                        ctx.close();ctx=None
                        continue
                    ctx.set_handler(Quotes())
                    ctx.set_handler(Ticks())
                    ctx.set_handler(Books())
                    ctx.set_handler(Brokers())
                    reset('connected')
                    active.clear();stock_retries.clear();releases.clear()
                    next_broker_retry = 0
                    retry_attempt = 0
                    health.failed.clear()
                    health.set('checking','OpenD 已登录，等待逐股订阅验证',checked_at=time.time())
                    next_health = time.monotonic() + 5
                    next_depth = 0
                    LOG.info('OpenD 已登录，开始逐股验证订阅')
                except Exception as exc:
                    health.disconnected('连接或订阅失败：'+str(exc)[:160])
                    LOG.warning('连接或订阅失败: %s',exc)
                    if ctx is not None:
                        ctx.close()
                        ctx = None
                    if check:
                        raise
                    delay=retry_delay(retry_attempt);retry_attempt+=1
                    health.set('disconnected','OpenD 不可用，正在等待重试',next_retry=time.time()+delay)
                    retry_at=time.monotonic()+delay
                    stop.wait(.5)
                    continue
            if watch:
                for code,row in desired.items():
                    if code in active and active[code]['revision']==row['revision']:continue
                    if time.monotonic()<stock_retries.get((code,row['revision']),0):continue
                    try:
                        ret,detail=ctx.subscribe([code],[ft.SubType.TICKER,ft.SubType.ORDER_BOOK,ft.SubType.QUOTE],is_first_push=False)
                        if ret!=ft.RET_OK:raise RuntimeError(str(detail))
                        releases.pop(code,None)
                        if not session_open:
                            ret, dark_quote = ctx.get_stock_quote([code])
                            if ret != ft.RET_OK or dark_quote.empty or dark_quote.iloc[0].get('dark_status') != 'TRADING':
                                ctx.unsubscribe([code],[ft.SubType.TICKER,ft.SubType.ORDER_BOOK,ft.SubType.QUOTE])
                                watch.acknowledge(row,'waiting_session','等待富途确认暗盘开市')
                                stock_retries[(code,row['revision'])]=time.monotonic()+15
                                continue
                            dark_codes.add(code)
                        else:
                            dark_codes.discard(code)
                        name=row['name']
                        try:
                            ret,frame=ctx.get_market_snapshot([code])
                            if ret==ft.RET_OK and len(frame):
                                name=str(frame.iloc[0]['name'])
                                for snapshot_row in json.loads(frame.to_json(orient='records',force_ascii=False)):put(snapshot_event(snapshot_row))
                        except Exception:pass
                        c['names'][code]=name or code
                        until=time.time()+c['warmup_seconds']
                        active[code]=dict(revision=row['revision'],warmup_until=until)
                        for _, ident, saved in pending_participation:
                            if saved['code']==code:
                                saved['participation']=participation.analyze(saved,saved['received_at'],saved['window_seconds'])
                                saved['participation']['interrupted']='监控暂停或重新订阅'
                                store.update_alert(ident,saved)
                        pending_participation[:]=[item for item in pending_participation if item[2]['code']!=code]
                        behaviors.stop(code,'重新订阅',time.time(),participation)
                        participation.events.pop(code,None);participation.clues.events.pop(code,None);broker_cache.items.pop(code,None)
                        engine.drop(code)
                        LOG.info('股票订阅成功 %s %s，预热 %s 秒',code,name,c['warmup_seconds'])
                        watch.acknowledge(row,'warming',warmup_until=until,name=name)
                        next_depth=0;next_broker_retry=0;next_broker_stats=0;next_broker_flow=0
                    except Exception as exc:
                        watch.acknowledge(row,'error',str(exc)[:300])
                        stock_retries[(code,row['revision'])]=time.monotonic()+30
                c['symbols']=list(active)
                with health.lock:previous=health.data['state']
                if active and previous in ('checking','connecting','disconnected','idle','paused'):
                    health.recovered(list(active),c['warmup_seconds'])
                elif not active:health.set('checking','OpenD 已连接，但股票尚未订阅成功',checked_at=time.time())
                for row in controls:
                    if row['code'] in active and time.time()>=active[row['code']]['warmup_until'] and row['state']=='warming':
                        watch.acknowledge(row,'monitoring',warmup_until=active[row['code']]['warmup_until'])
            if health.failed.is_set():
                if ctx is not None:ctx.close()
                ctx=None
                active.clear()
                reset('disconnected')
                while not q.empty():
                    try:q.get_nowait()
                    except queue.Empty:break
                continue
            if overflow.is_set():
                LOG.error('队列溢出，清空积压并重新预热，暂停信号判断')
                while True:
                    try:
                        q.get_nowait()
                    except queue.Empty:
                        break
                reset('overflow')
                overflow.clear()
            try:
                received, event = q.get(timeout=0.5)
                processed = time.time()
                if watch:
                    current = next((r for r in watch.rows() if r['code']==event.get('code')),None)
                    if event.get('code') and (not current or not current['enabled'] or event['code'] not in active or current['revision']!=active[event['code']]['revision']):continue
                event['received_at'] = received
                store.event(processed, event)
                participation.observe(received, event)
                if event.get('market_session') != 'HK_DARK' and event['kind'] in ('tick','book') and -2<=processed-event['ts']<=3:
                    behaviors.process(event,participation)
                if event['kind'] == 'depth' and market_session.phase()=='CONTINUOUS':
                    message = depth_monitor.observe(event['code'], event['bids'], event['asks'])
                    if message:
                        message = message.replace(event['code'], stock_label(event['code'], c.get('names', {}).get(event['code'])))
                        LOG.warning(message)
                        store.alert(dict(kind='depth', ts=processed, code=event['code'], name=c.get('names', {}).get(event['code']), message=message))
                        if c['desktop_notifications']:
                            desktop_notify(message)
                lag = processed - event['ts']
                if event['kind'] == 'broker':
                    broker_cache.update(event)
                elif event['kind'] == 'broker_stats':
                    broker_stats[event['code']] = event
                elif event['kind'] in ('depth', 'auction_tick', 'book_snapshot', 'threshold_status', 'behavior_status', 'quote', 'market_snapshot', 'chart_history'):
                    pass
                elif lag > c['max_delay_seconds'] or lag < -2:
                    if event['kind'] == 'tick':
                        reset('stale_event')
                    LOG.debug('忽略过期或未来事件: %s lag=%.1f', event['code'], lag)
                else:
                    alert = engine.process(event)
                    if alert and event.get('market_session') == 'HK_DARK':
                        alert['market_session']='HK_DARK'
                        alert['signal_label']='暗盘 · '+alert['signal_label']
                    if alert and (not watch or time.time()>=active[event['code']]['warmup_until']):
                        alert['name'] = c.get('names', {}).get(alert['code'])
                        alert = broker_cache.attach(alert)
                        alert['daily_broker_stats'] = broker_stats.get(alert['code'])
                        alert['received_at'] = received
                        alert.setdefault('window_seconds', c['window_seconds'])
                        alert['participation'] = dict(status='pending', valid_samples=0, target_samples=21, bid=[], ask=[], version=2,scope='best_level',note='收集买1/卖1常态对照、异动前后各10秒采样与成交线索')
                        ident = store.alert(alert)
                        pending_participation.append((received + 11, ident, alert))
                        combined=behaviors.link_alert(ident,alert)
                        notify(alert, c['desktop_notifications'] and not combined)
            except queue.Empty:
                pass
            for deadline, ident, saved in list(pending_participation):
                if time.time() >= deadline:
                    saved['participation'] = participation.analyze(saved, saved['received_at'], saved['window_seconds'])
                    store.update_alert(ident, saved)
                    pending_participation.remove((deadline, ident, saved))
                    result = saved['participation']
                    if c['desktop_notifications'] and result['valid_samples'] and not behaviors.linked_confirmed(ident):
                        desktop_notify(saved['notification_summary']['text'])
            behaviors.poll(time.time(),participation)
            now = time.monotonic()
            if now - last_commit >= 1:
                store.db.commit()
                last_commit = now
            if now >= next_broker_stats:
                next_broker_stats = now + 60
                if c['symbols']:
                    try:
                        snapshot_ret,snapshot_frame=ctx.get_market_snapshot(c['symbols'])
                        if snapshot_ret==ft.RET_OK:
                            for snapshot_row in json.loads(snapshot_frame.to_json(orient='records',force_ascii=False)):put(snapshot_event(snapshot_row))
                    except Exception:LOG.exception('市值快照查询失败，保留旧数据')
                for code in c['symbols']:
                    if code in dark_codes:continue
                    try:
                        ret, detail = ctx.subscribe([code], [ft.SubType.K_1M], subscribe_push=False)
                        if ret != ft.RET_OK:
                            LOG.warning('分钟图补取订阅失败 %s: %s',code,detail)
                            continue
                        ret, frame = ctx.get_cur_kline(code, 1000, ktype=ft.KLType.K_1M, autype=ft.AuType.NONE)
                        if ret == ft.RET_OK:
                            today = datetime.now(HK).strftime('%Y-%m-%d')
                            bars=[]
                            for row in frame.to_dict('records'):
                                ts=timestamp(row['time_key'])
                                if str(row['time_key']).startswith(today) and ts < int(time.time()//60)*60:
                                    bars.append(dict(time=int(ts//60)*60,open=float(row['open']),high=float(row['high']),low=float(row['low']),close=float(row['close']),volume=float(row['volume']),source='futu'))
                            put(dict(kind='chart_history',code=code,ts=time.time(),bars=bars))
                    except Exception:
                        LOG.exception('分钟图数据补取失败 %s',code)
            if now >= next_broker_flow:
                next_broker_flow = now + c.get('broker_stats_seconds',10)
                for code in c['symbols']:
                    if code in dark_codes:continue
                    try:
                        ret, frame = ctx.get_top_ten_buy_sell_brokers(code, days_before=0)
                        if ret == ft.RET_OK:
                            rows = json.loads(frame.to_json(orient='records', force_ascii=False))
                            put(dict(kind='broker_stats', code=code, ts=time.time(), rows=rows, error=None))
                            LOG.info('当日净买卖经纪商 %s: %d 条', code, len(rows))
                        else:
                            put(dict(kind='broker_stats', code=code, ts=time.time(), rows=[], error=str(frame)))
                            LOG.warning('当日经纪商统计不可用 %s: %s', code, frame)
                    except Exception as exc:
                        put(dict(kind='broker_stats', code=code, ts=time.time(), rows=[], error=str(exc)))
                        LOG.exception('当日经纪商统计异常 %s', code)
            if now >= next_depth:
                next_depth = now + c.get('depth_check_seconds', 15)
                for code in c['symbols']:
                    put(dict(kind='behavior_status',code=code,ts=time.time(),value=behaviors.status(code,time.time())))
                if c.get('threshold_mode') == 'percentile':
                    for code in c['symbols']:
                        profile = engine.profiles.get(code)
                        value = profile.estimate(time.time(), c['profile_quantile'], c['profile_multiplier'],
                                                 c['profile_min_samples']) if profile else None
                        put(dict(kind='threshold_status', code=code, ts=time.time(), value=value))
                if now >= next_broker_retry:
                    next_broker_retry = now + 60
                    for code in c['symbols']:
                        if code in dark_codes:continue
                        broker_ret, broker_detail = ctx.subscribe([code], [ft.SubType.BROKER], is_first_push=True)
                        if broker_ret != ft.RET_OK:
                            LOG.warning('经纪队列订阅不可用 %s: %s', code, broker_detail)
                for code in c['symbols']:
                    if code in dark_codes:continue
                    try:
                        ret, bids, asks = ctx.get_broker_queue(code)
                        if ret == ft.RET_OK:
                            put(dict(kind='broker', code=code, ts=time.time(), timestamp_basis='local_receive',
                                     bid=normalize(bids, 'bid'), ask=normalize(asks, 'ask')))
                        else:
                            LOG.debug('经纪队列查询不可用 %s: %s', code, bids)
                    except Exception:
                        LOG.exception('经纪队列查询失败 %s', code)
                try:
                    ret, quotes = ctx.get_stock_quote(c['symbols'])
                    if ret == ft.RET_OK:
                        for row in quotes.to_dict('records'):
                            if row['code'] in dark_codes and row.get('dark_status') != 'TRADING':
                                code = row['code']
                                dark_codes.discard(code)
                                active.pop(code,None)
                                ctx.unsubscribe([code],[ft.SubType.TICKER,ft.SubType.ORDER_BOOK,ft.SubType.QUOTE])
                                engine.drop(code)
                                continue
                            if row['code'] in dark_codes:
                                put(dict(kind='quote',code=row['code'],ts=timestamp(str(row['data_date'])+' '+str(row['data_time'])),
                                         price=float(row['last_price']),prev_close_price=float(row['prev_close_price']),dark_status='TRADING'))
                            observed = time.time()
                            if str(row['data_date']) != datetime.fromtimestamp(observed, HK).strftime('%Y-%m-%d'):
                                continue
                            put(dict(kind='day', code=row['code'], ts=observed, turnover=float(row['turnover'])))
                            LOG.info('日内成交基线 %s 累计 HK$%.0f', row['code'], row['turnover'])
                    else:
                        LOG.warning('日内成交额读取失败，暂用滚动基线: %s', quotes)
                except Exception:
                    LOG.exception('日内成交额读取异常，暂用滚动基线')
                for code in c['symbols']:
                    try:
                        ret, book = ctx.get_order_book(code, num=10)
                    except Exception:
                        LOG.exception('盘口检查异常 %s', code)
                        continue
                    if ret == ft.RET_OK:
                        put(dict(kind='book_snapshot', code=code, ts=time.time(),
                                 bid=[list(row[:3]) for row in book['Bid']],
                                 ask=[list(row[:3]) for row in book['Ask']],
                                 source_bid=book.get('svr_recv_time_bid'), source_ask=book.get('svr_recv_time_ask')))
                        bids, asks = len(book['Bid']), len(book['Ask'])
                        LOG.info('盘口检查 %s 买%d／卖%d档', code, bids, asks)
                        put(dict(kind='depth', code=code, ts=time.time(), bids=bids, asks=asks))
                    else:
                        LOG.warning('盘口检查失败 %s: %s', code, book)
            if now >= next_health:
                next_health = now + 5
                try:
                    ret, state = ctx.get_global_state()
                except Exception:
                    LOG.exception('OpenD 健康检查失败')
                    ret, state = ft.RET_ERROR, {}
                if ret != ft.RET_OK or not state.get('qot_logined', False):
                    health.disconnected('行情登录状态检查失败，正在恢复订阅')
                    LOG.error('行情连接不可用，重新连接并预热')
                    ctx.close()
                    ctx = None
                    active.clear()
                    reset('disconnected')
                else:
                    with health.lock:health.data['checked_at']=time.time()
    finally:
        stop.set()
        if us_worker:us_worker.join(timeout=6)
        if behaviors:behaviors.stop_all('监听进程停止',time.time(),participation)
        health.close()
        if ctx is not None:
            ctx.close()
        if store:
            store.close()


def main():
    p = argparse.ArgumentParser(description='港股异常成交监听（不含交易操作）')
    p.add_argument('command', choices=['run', 'check', 'replay', 'alerts'])
    p.add_argument('--config', default='config/settings.json')
    p.add_argument('--symbols', help='覆盖股票列表，例如 HK.00700,HK.09988')
    p.add_argument('--seconds', type=float, help='运行指定秒数后退出')
    p.add_argument('--limit', type=int, default=50, help='历史通知显示数量，默认 50')
    p.add_argument('--database', help='回放数据库或覆盖记录路径')
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    c = json.loads(Path(args.config).read_text())
    if c.get('rapid_move',{}).get('enabled'):
        c['warmup_seconds']=max(c['warmup_seconds'],c['rapid_move'].get('warmup_seconds',180))
    if args.symbols:
        c['symbols'] = args.symbols.split(',')
    if not c['symbols'] or any(not __import__('re').fullmatch(r'(HK\.\d{5}|US\.[A-Z][A-Z0-9.-]{0,19})', x) for x in c['symbols']):
        p.error('股票代码格式应为 HK.00700 或 US.QQQ')
    if not (0 < c['window_seconds'] < c['warmup_seconds'] < c['baseline_seconds']):
        p.error('要求 0 < window_seconds < warmup_seconds < baseline_seconds')
    if args.seconds is not None and args.seconds <= 0:
        p.error('--seconds 必须大于零')
    for key in ('cooldown_seconds', 'max_delay_seconds'):
        if c[key] <= 0:
            p.error(key + ' 必须大于零')
    for key in ('direction_ratio', 'min_direction_coverage'):
        if not 0 < c[key] <= 1:
            p.error(key + ' 必须在 (0, 1] 内')
    if c.get('threshold_mode') == 'percentile':
        if not (0 < c['profile_quantile'] <= 1 and c['profile_multiplier'] > 1 and c['profile_min_samples'] >= 2 and c['profile_seconds'] > c['window_seconds']):
            p.error('分位数门槛参数无效')
    if args.database:
        c['database'] = args.database
    if args.command == 'alerts':
        from .history import read_history
        if args.limit <= 0:
            p.error('--limit 必须大于零')
        print(read_history(c['database'], args.limit))
    elif args.command == 'replay':
        engine = Engine(c)
        replay_brokers = BrokerCache()
        db = sqlite3.connect('file:' + str(Path(c['database']).resolve()) + '?mode=ro', uri=True)
        try:
            for received, payload in db.execute('SELECT received,payload FROM events ORDER BY id'):
                event = json.loads(payload)
                if event['kind'] == 'broker':
                    replay_brokers.update(event)
                    continue
                if event['kind'] == 'reset':
                    replay_brokers.items.clear()
                if event['kind'] in ('depth', 'auction_tick', 'broker_stats', 'book_snapshot', 'threshold_status', 'behavior_status', 'quote', 'market_snapshot', 'chart_history'):
                    continue
                if not -2 <= received - event['ts'] <= c['max_delay_seconds']:
                    engine.reset()
                    continue
                alert = engine.process(event)
                if alert:
                    notify(alert)
        finally:
            db.close()
    else:
        live(c, args.seconds, args.command == 'check')


if __name__ == '__main__':
    main()
