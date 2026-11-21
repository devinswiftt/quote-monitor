"""Authenticated, loopback-only dashboard. No external assets or data upload."""
import argparse
from datetime import datetime
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import sqlite3
import threading
import time
from .broker_refresh import fetch_brokers, refresh_brokers
from urllib.parse import parse_qs, urlparse

from .stock_search import StockDirectory,fetch as fetch_stock_data,merge_watchlist
from .zhitong import TargetQuotes
from .engine import HK
from .live import Hub
from .connection import read_health
from .participation import summarize
from .watchlist import Watchlist
from .analysis import daily_analysis
from .broker_archive import history as broker_history, initialize as initialize_broker_archive
from .daily import daily_history,fetch_daily,day_summary,validate_history_date
from .session import MarketSession
from .markets import is_us,timezone,day_bounds,us_phase
from .pagination import alert_page
from .behavior_store import read_behaviors, initialize as initialize_behaviors


def read_latest_events(db,code=None):
    # SQLite key columns are authoritative, including for older cached payloads.
    return [dict(json.loads(payload),code=code,kind=kind)
            for code,kind,payload in db.execute('SELECT code,kind,payload FROM latest_state'+(' WHERE code=?' if code else ''), (code,) if code else ())]


def access_allowed(require_password, cookie, session):
    if not require_password:
        return True
    try:
        value = SimpleCookie(cookie).get('hk_session')
        return value is not None and secrets.compare_digest(value.value, session)
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--database', default='data/quotes.sqlite3')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent / 'web'
    database = Path(args.database).resolve()
    keyfile = database.parent / 'dashboard-password.txt'
    if not keyfile.exists():
        fd = os.open(keyfile, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write(secrets.token_urlsafe(24))
    os.chmod(keyfile, 0o600)
    password = keyfile.read_text().strip()
    config_path = Path('config/settings.json')
    config = json.loads(config_path.read_text()) if config_path.exists() else {}
    require_password = config.get('dashboard', {}).get('require_password', True) is not False
    names = config.get('names', {})
    symbols = config.get('symbols', ['HK.02065', 'HK.02206', 'HK.09621'])
    watch=Watchlist(database,symbols,names)
    with sqlite3.connect(database) as db:
        initialize_behaviors(db);initialize_broker_archive(db)
    stock_fetch=lambda kind:fetch_stock_data(kind,config.get('host','127.0.0.1'),config.get('port',11111))
    stock_directory=StockDirectory(database.parent/'stock-directory.json',stock_fetch)
    us_stock_directory=StockDirectory(database.parent/'us-stock-directory.json',lambda kind:stock_fetch('catalog_us' if kind=='catalog' else kind))
    import_lock=threading.Lock()
    target_quotes=TargetQuotes(database.parent/'zhitong-targets.json')
    target_quotes.start()
    session = secrets.token_urlsafe(32)
    hub = Hub()
    allowed = {f'127.0.0.1:{args.port}', f'localhost:{args.port}'}

    refresh_lock=threading.Lock();refresh_busy=set();refresh_last={}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def reply(self, code, body, content_type='application/json; charset=utf-8', cookie=None):
            data = body.encode() if isinstance(body, str) else json.dumps(body, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; form-action 'self'")
            self.send_header('Content-Length', str(len(data)))
            if cookie:
                self.send_header('Set-Cookie', cookie)
            self.end_headers()
            self.wfile.write(data)

        def valid_host(self):
            return self.headers.get('Host') in allowed

        def authorized(self):
            return access_allowed(require_password, self.headers.get('Cookie', ''), session)

        def do_POST(self):
            nonlocal session
            if not self.valid_host() or self.headers.get('Origin') not in {f'http://{host}' for host in allowed}:
                return self.reply(403, {'error': '拒绝跨站请求'})
            if self.path == '/api/futu-import':
                if not self.authorized():return self.reply(401,{'error':'请先登录'})
                if not import_lock.acquire(blocking=False):return self.reply(429,{'error':'正在导入，请稍候'})
                try:
                    length=int(self.headers.get('Content-Length','0'))
                    if not 0<length<=2048:raise ValueError('请求无效')
                    group=json.loads(self.rfile.read(length)).get('group','港股')
                    if not isinstance(group,str) or not group.strip() or len(group)>80:raise ValueError('请选择分组')
                    rows=stock_fetch('watchlist:'+group)
                    result=merge_watchlist(watch,rows,group)
                    return self.reply(200,dict(ok=True,**result))
                except Exception:return self.reply(503,{'error':'读取富途自选失败，请检查 OpenD 连接与登录状态；本地自选未变更'})
                finally:import_lock.release()
            if self.path == '/api/broker-refresh':
                if not self.authorized():return self.reply(401,{'error':'请先登录'})
                try:
                    length=int(self.headers.get('Content-Length','0'))
                    if not 0<length<=1024:raise ValueError('请求无效')
                    code=json.loads(self.rfile.read(length)).get('code')
                    if code not in {r['code'] for r in watch.rows()}:raise ValueError('股票不在自选中')
                except (ValueError,TypeError,AttributeError):return self.reply(400,{'error':'请选择有效的自选股票'})
                with refresh_lock:
                    if code in refresh_busy or time.monotonic()-refresh_last.get(code,float('-inf'))<10:
                        return self.reply(429,{'error':'刷新太频繁，请间隔10秒重试'})
                    refresh_busy.add(code);refresh_last[code]=time.monotonic()
                try:
                    event=refresh_brokers(database,code,lambda c:fetch_brokers(c,config.get('host','127.0.0.1'),config.get('port',11111)))
                    return self.reply(200,{'ok':True,'event':event})
                except Exception as exc:
                    return self.reply(503,{'error':'富途查询失败，保留上次数据：'+str(exc)[:250]})
                finally:
                    with refresh_lock:refresh_busy.discard(code)
            if self.path == '/api/logout':
                if self.authorized():session=secrets.token_urlsafe(32)
                return self.reply(200,{'ok':True},cookie='hk_session=; Max-Age=0; HttpOnly; SameSite=Strict; Path=/')
            if self.path == '/api/watchlist':
                if not self.authorized():return self.reply(401,{'error':'请先登录'})
                try:
                    length=int(self.headers.get('Content-Length','0'))
                    if not 0<length<=2048:raise ValueError('请求格式无效')
                    body=json.loads(self.rfile.read(length));action=body.get('action')
                    if action=='add':
                        stock=stock_directory.resolve(body.get('code',''))
                        code=watch.add(stock['code'])
                        if stock['name']:
                            with watch.connect() as db:db.execute('UPDATE watchlist SET name=? WHERE code=?',(stock['name'],code))
                    elif action=='set_default':watch.set_default(body.get('code',''))
                    elif action=='remove':watch.remove(body.get('code',''))
                    elif action in ('start','stop'):watch.desired(body.get('code',''),action=='start')
                    else:raise ValueError('未知操作')
                    return self.reply(200,{'ok':True,'watchlist':watch.rows(),'default_symbol':watch.default_symbol()})
                except (ValueError,TypeError):return self.reply(400,{'error':'代码无效、股票已存在或操作无效'})
                except sqlite3.Error:return self.reply(503,{'error':'配置暂时忙，请重试'})
            if self.path != '/api/login':
                return self.reply(404, {})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 1024:
                    raise ValueError()
                supplied = json.loads(self.rfile.read(length)).get('password', '')
                if not isinstance(supplied, str) or not secrets.compare_digest(supplied, password):
                    return self.reply(401, {'error': '访问口令不正确'})
                return self.reply(200, {'ok': True}, cookie=f'hk_session={session}; HttpOnly; SameSite=Strict; Path=/')
            except (ValueError, TypeError):
                return self.reply(400, {'error': '无效请求'})

        def do_GET(self):
            if not self.valid_host():
                return self.reply(403, {})
            url = urlparse(self.path)
            if url.path == '/api/broker-history':
                if not self.authorized():return self.reply(401,{'error':'请先登录'})
                args=parse_qs(url.query);code=args.get('code',[''])[0];date=args.get('date',[None])[0]
                try:
                    if date:validate_history_date(date,stock_directory.listing_date(code),MarketSession().days)
                    result=broker_history(database,code,date)
                    if date:
                        with sqlite3.connect(database) as db:
                            known=db.execute('SELECT 1 FROM watchlist WHERE code=?',(code,)).fetchone()
                        if not known:return self.reply(400,{'error':'请选择已有股票'})
                        result['daily_summary']=day_summary(database,code,date,lambda c:fetch_daily(c,config.get('host','127.0.0.1'),config.get('port',11111)))
                    return self.reply(200,result)
                except ValueError as exc:return self.reply(400,{'error':str(exc)})
            if url.path == '/api/daily':
                if not self.authorized():return self.reply(401,{'error':'请先登录'})
                args=parse_qs(url.query);code=args.get('code',[''])[0]
                if code not in {r['code'] for r in watch.rows()}:return self.reply(400,{'error':'请选择当前自选股票'})
                key='daily:'+code
                with refresh_lock:
                    if key in refresh_busy or time.monotonic()-refresh_last.get(key,float('-inf'))<10:return self.reply(429,{'error':'请间隔10秒再查询日K'})
                    refresh_busy.add(key);refresh_last[key]=time.monotonic()
                try:return self.reply(200,daily_history(database,code,lambda c:fetch_daily(c,config.get('host','127.0.0.1'),config.get('port',11111)),force=args.get('refresh')==['1']))
                except Exception as exc:return self.reply(503,{'error':'日K获取失败（请检查OpenD及历史行情权限/额度）：'+str(exc)[:200]})
                finally:
                    with refresh_lock:refresh_busy.discard(key)
            if url.path == '/api/live':
                if not self.authorized(): return self.reply(401, {'error':'请先登录'})
                self.send_response(200)
                self.send_header('Content-Type','text/event-stream')
                self.send_header('Cache-Control','no-store')
                self.send_header('X-Accel-Buffering','no')
                self.end_headers()
                try:
                    after=int(self.headers['Last-Event-ID']) if self.headers.get('Last-Event-ID') else hub.sequence
                    while self.authorized():
                        messages=hub.wait(after)
                        if not self.authorized():break
                        if not messages:
                            self.wfile.write(b': heartbeat\n\n');self.wfile.flush()
                        for seq,event in messages:
                            if seq<=after:continue
                            body=json.dumps(event,ensure_ascii=False)
                            self.wfile.write(f'id: {seq}\ndata: {body}\n\n'.encode());self.wfile.flush()
                            after=seq
                except (BrokenPipeError,ConnectionResetError,ValueError,OSError):
                    pass
                return
            if url.path == '/api/report':
                return self.reply(200, (root/'report.html').read_text(), 'text/html; charset=utf-8')
            if url.path == '/api/report-data':
                if not self.authorized():
                    return self.reply(401, {'error':'请先登录'})
                try:
                    requested=parse_qs(url.query).get('date',[None])[0]
                    current_names=dict(names)
                    current_names.update({r['code']:r['name'] for r in watch.rows() if r['name']})
                    return self.reply(200,daily_analysis(database,requested,current_names))
                except ValueError:return self.reply(400,{'error':'日期格式应为 YYYY-MM-DD'})
                except sqlite3.Error:return self.reply(503,{'error':'分析数据暂时忙，稍后自动重试'})
            if url.path == '/api/futu-groups':
                if not self.authorized():return self.reply(401,{'error':'请先登录'})
                try:return self.reply(200,{'groups':stock_fetch('groups')})
                except Exception:return self.reply(503,{'error':'无法读取富途分组，请检查 OpenD'})
            if url.path == '/api/stock-search':
                if not self.authorized():return self.reply(401,{'error':'请先登录'})
                args=parse_qs(url.query);query=args.get('q',[''])[0].strip()
                if len(query)>80:return self.reply(400,{'error':'搜索内容过长'})
                try:return self.reply(200,{'stocks':(us_stock_directory if args.get('market',['HK'])[0]=='US' or (query[:1].isascii() and query[:1].isalpha() and not query.upper().startswith('HK.')) else stock_directory).search(query)})
                except Exception:return self.reply(503,{'error':'无法读取港股名称，请确认 OpenD 已连接并登录'})
            if url.path == '/api/state':
                if not self.authorized():
                    return self.reply(401, {'error': '请先登录'})
                try:
                    with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=2) as db:
                        args = parse_qs(url.query)
                        quote_code=args.get('quote_symbol',[''])[0]
                        db.execute('BEGIN')
                        page_data=alert_page(db,args)
                        alerts=page_data['alerts'];total=page_data['total']
                        day_start=datetime.now(HK).replace(hour=0,minute=0,second=0,microsecond=0).timestamp()
                        daily=[json.loads(row[0]) for row in db.execute("SELECT payload FROM alerts WHERE json_extract(payload,'$.ts')>=?",(day_start,))]
                        participation_summary=summarize(daily)
                        behavior_date=args.get('behavior_date',[None])[0]
                        behavior_start=datetime.strptime(behavior_date,'%Y-%m-%d').replace(tzinfo=HK).timestamp() if behavior_date else day_start
                        behaviors=read_behaviors(db,behavior_start,behavior_start+86400)
                        status = []
                        us_health=read_health('data/us-connection.json')
                        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                        if 'latest_state' in tables:
                            events = read_latest_events(db,quote_code or None)
                        else:
                            events = [json.loads(r[0]) for r in db.execute('SELECT payload FROM events ORDER BY id DESC LIMIT 6000')]
                        controls=watch.rows()
                        current_symbols=[r['code'] for r in controls]
                        current_names=dict(names,**{r['code']:r['name'] for r in controls if r['name']})
                        filter_names={code:(current_names.get(code) or name or code) for code,name in db.execute("SELECT json_extract(payload,'$.code'),MAX(json_extract(payload,'$.name')) FROM alerts GROUP BY json_extract(payload,'$.code')") if code}
                        filter_names.update({code:current_names.get(code,code) for code, in db.execute('SELECT DISTINCT code FROM behavior_events') if code})
                        filter_names.update({code:current_names.get(code,code) for code in current_symbols})
                        alert_symbols=[dict(code=code,name=name) for code,name in sorted(filter_names.items())]
                        auction_rows=[json.loads(p) for p, in db.execute("SELECT payload FROM events WHERE received>=? AND json_extract(payload,'$.kind')='auction_tick' ORDER BY id DESC LIMIT 1000",(day_start,))]
                        for code in current_symbols:
                            def latest(kind):
                                if quote_code and code!=quote_code:return None
                                matches = [e for e in events if e.get('code') == code and e.get('kind') == kind]
                                return max(matches, key=lambda e:e['ts']) if matches else None
                            control=next(r for r in controls if r['code']==code)
                            us=is_us(code)
                            directory=us_stock_directory if us else stock_directory
                            us_kind=MarketSession('data/us-trading-calendar.json').days.get(datetime.now(timezone(code)).strftime('%Y-%m-%d'),'WHOLE')
                            status.append(dict(code=code,market='US' if us else 'HK',currency='USD' if us else 'HKD',timezone=str(timezone(code)),market_phase=us_phase(datetime.now().timestamp(),us_kind) if us else MarketSession().phase(),connection=us_health if us else read_health(),listing_date=(latest('market_snapshot') or {}).get('data',{}).get('listing_date') if us else directory.listing_date(code),closed_dates=[date for date,kind in MarketSession().days.items() if kind=='CLOSED'],connect_target=None if us else target_quotes.quote(code),auction_ticks=[e for e in auction_rows if e['code']==code][:50],monitoring_enabled=bool(control['enabled']),monitoring_state=control['state'], name=current_names.get(code, code), tick=latest('tick'),
                                fundamentals=latest('market_snapshot'), chart_history=latest('chart_history'), quote=latest('quote'), depth=latest('depth'), broker=latest('broker'), day=latest('day'),
                                threshold_status=latest('threshold_status'), behavior_status=latest('behavior_status'), book=latest('book_snapshot'), broker_stats=latest('broker_stats')))
                        chart_symbols=[code for code in current_symbols if not quote_code or code==quote_code]
                        bounds={code:day_bounds(code) for code in chart_symbols}
                        candles = {code: [] for code in chart_symbols}
                        if 'chart_ticks' in tables:
                            midnight = min([b[0] for b in bounds.values()] or [day_start])
                            bars = {}
                            for code, ts, price, volume, sequence in db.execute('SELECT code,ts,price,volume,sequence FROM chart_ticks WHERE ts>=?'+(' AND code=?' if quote_code else '')+' ORDER BY ts', (midnight,quote_code) if quote_code else (midnight,)):
                                minute = int(ts//60)*60
                                key=(code,minute)
                                if code not in candles or not bounds[code][0]<=ts<bounds[code][1]: continue
                                if key not in bars:bars[key]=dict(time=minute,open=price,high=price,low=price,close=price,volume=0)
                                bar=bars[key];bar['high']=max(bar['high'],price);bar['low']=min(bar['low'],price);bar['close']=price;bar['volume']+=volume;bar['last_sequence']=sequence.rsplit(':',1)[-1]
                            for (code,minute),bar in bars.items():candles[code].append(bar)
                        for stock in status:
                            if stock['code'] not in candles:continue
                            historical=(stock.get('chart_history') or {}).get('bars',[])
                            merged={bar['time']:bar for bar in candles[stock['code']]}
                            for bar in historical:
                                if datetime.fromtimestamp(bar['time'],timezone(stock['code'])).date()==datetime.now(timezone(stock['code'])).date():merged[bar['time']]=bar
                            candles[stock['code']]=sorted(merged.values(),key=lambda bar:bar['time'])
                    if quote_code:
                        for stock in status:stock.pop('chart_history',None)
                    return self.reply(200, dict(password_required=require_password,us_connection=us_health,market_stage=MarketSession().phase(),default_symbol=watch.default_symbol(),alert_symbols=alert_symbols,pagination=page_data['pagination'],behaviors=behaviors,watchlist=controls,connection=read_health(),participation_summary=participation_summary,candles=candles, alerts=alerts, total=total, stocks=status, names=current_names,
                                      generated_at=datetime.now(HK).isoformat()))
                except (sqlite3.Error, ValueError) as exc:
                    return self.reply(503, {'error': '数据库暂不可用，请稍后重试'})
            files = {'/': ('index.html', 'text/html; charset=utf-8'),
                     '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                     '/daily-chart.js': ('daily-chart.js', 'application/javascript; charset=utf-8'),
                     '/chart-hover.js': ('chart-hover.js', 'application/javascript; charset=utf-8'),
                     '/trading-datepicker.js': ('trading-datepicker.js', 'application/javascript; charset=utf-8'),
                     '/behavior.js': ('behavior.js', 'application/javascript; charset=utf-8'),
                     '/broker-analysis.js': ('broker-analysis.js', 'application/javascript; charset=utf-8'), '/report.js': ('report.js', 'text/javascript; charset=utf-8'),
                     '/style.css': ('style.css', 'text/css; charset=utf-8')}
            item = files.get(url.path)
            if not item:
                return self.reply(404, {})
            page_content = (root / item[0]).read_text()
            if url.path == '/' and not require_password:
                page_content = page_content.replace('<div id="login">', '<div id="login" hidden>', 1)
                page_content = page_content.replace('<div id="app" hidden>', '<div id="app">', 1)
                page_content = page_content.replace('<button id="logout"', '<button hidden id="logout"', 1)
            return self.reply(200, page_content, item[1])

    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    print(f'私有本机看板：http://127.0.0.1:{args.port}；'+(f'口令保存在 {keyfile}' if require_password else '当前免密码访问'), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
