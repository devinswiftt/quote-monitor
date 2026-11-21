"""Read-only Futu discovery and explicit local watchlist import."""
import json
from pathlib import Path
import re
import threading
import time
import unicodedata
from .watchlist import normalize_code


def clean(rows,market="HK"):
    unique={}
    for row in rows:
        code=str(row.get('code',''))
        if not re.fullmatch(r'US\.[A-Z][A-Z0-9.-]{0,19}' if market=='US' else r'HK\.\d{5}',code) or row.get('stock_type','STOCK') not in (('STOCK','ETF') if market=='US' else ('STOCK',)) or row.get('delisting',False):continue
        unique[code]=dict(code=code,name=str(row.get('name') or code))
        if row.get('listing_date'):unique[code]['listing_date']=str(row['listing_date'])[:10]
    return list(unique.values())


def fetch(kind,host='127.0.0.1',port=11111):
    import futu as ft
    ctx=ft.OpenQuoteContext(host=host,port=port,is_async_connect=True)
    try:
        ctx.set_sync_query_connect_timeout(3);ctx._query_timeout=3
        if kind=='catalog_us':
            records=[]
            for security_type in (ft.SecurityType.STOCK,ft.SecurityType.ETF):
                ret,frame=ctx.get_stock_basicinfo(ft.Market.US,security_type)
                if ret!=ft.RET_OK:raise ValueError('美股目录读取失败')
                records.extend(json.loads(frame.to_json(orient='records',force_ascii=False)))
            return clean(records,market='US')
        if kind=='catalog':ret,frame=ctx.get_stock_basicinfo(ft.Market.HK,ft.SecurityType.STOCK)
        elif kind=='groups':ret,frame=ctx.get_user_security_group()
        else:ret,frame=ctx.get_user_security(kind.split(':',1)[1] if ':' in kind else '港股')
        if ret!=ft.RET_OK:raise ValueError('富途读取失败，请检查 OpenD 连接和登录状态')
        records=json.loads(frame.to_json(orient='records',force_ascii=False))
        return records if kind=='groups' else clean(records,market='US' if kind=='catalog_us' else 'HK')
    finally:ctx.close()


def key(value):return unicodedata.normalize('NFKC',str(value)).strip().casefold()

class StockDirectory:
    def __init__(self,path,get):
        self.path=Path(path);self.get=get;self.lock=threading.Lock();self.retry_at=0
        try:self.cache=json.loads(self.path.read_text())
        except (OSError,ValueError):self.cache={}

    def rows(self):
        with self.lock:
            now=time.time()
            if (self.cache.get('schema_version')!=2 or now-self.cache.get('updated_at',0)>86400) and now>=self.retry_at:
                try:
                    rows=self.get('catalog')
                    if not rows:raise ValueError('富途未返回股票目录')
                    cache=dict(schema_version=2,updated_at=now,rows=rows)
                    temporary=self.path.with_suffix('.json.tmp');temporary.write_text(json.dumps(cache,ensure_ascii=False));temporary.replace(self.path);self.cache=cache
                except Exception:
                    self.retry_at=now+60
                    if not self.cache.get('rows'):raise ValueError('无法读取港股名称，请确认 OpenD 已连接并登录')
            if not self.cache.get('rows'):raise ValueError('港股目录暂不可用，请稍后重试')
            return self.cache['rows']

    def listing_date(self,code):
        try:return next((row.get('listing_date') for row in self.rows() if row['code']==code),None)
        except Exception:return None

    def search(self,query):
        query=key(query)
        if not query:return []
        rows=[row for row in self.rows() if query in key(row['name']) or query in key(row['code'])]
        return sorted(rows,key=lambda r:(key(r['name'])!=query,not key(r['name']).startswith(query),r['code']))[:20]

    def resolve(self,value):
        try:
            code=normalize_code(value)
        except ValueError:
            exact=[r for r in self.rows() if key(r['name'])==key(value)]
            if len(exact)!=1:raise ValueError('请选择搜索结果中的股票代码后添加')
            return exact[0]
        # Preserve code-based additions when OpenD is unavailable.
        with self.lock:rows=self.cache.get('rows',[])
        return next((r for r in rows if r['code']==code),dict(code=code,name=''))


def merge_watchlist(watch,rows,group=None):
    rows=clean(rows);added=existing=0
    with watch.connect() as db:
        for row in rows:
            code,name=row['code'],row['name'];old=db.execute('SELECT deleted FROM watchlist WHERE code=?',(code,)).fetchone()
            if old and not old['deleted']:
                existing+=1
                db.execute('UPDATE watchlist SET name=? WHERE code=?',(name,code))
            elif old:
                db.execute("UPDATE watchlist SET name=?,deleted=0,enabled=0,revision=revision+1,state='stopped',error='',updated_at=?,warmup_until=0 WHERE code=?",(name,time.time(),code));added+=1
            else:
                db.execute("INSERT INTO watchlist(code,name,enabled,revision,state,error,updated_at,warmup_until,deleted) VALUES (?,?,0,1,'stopped','',?,0,0)",(code,name,time.time()));added+=1
        if group:
            previous=db.execute("SELECT value FROM watchlist_meta WHERE key='futu_groups'").fetchone()
            groups=json.loads(previous[0]) if previous else {}
            groups[group]=[row['code'] for row in rows]
            db.execute("INSERT OR REPLACE INTO watchlist_meta VALUES ('futu_groups',?)",(json.dumps(groups,ensure_ascii=False),))
    return dict(added=added,existing=existing,total=len(rows))
