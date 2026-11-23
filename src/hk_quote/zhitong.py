"""Poll the same public forecasts used by Zhitong's Stock Connect page."""
import json
import math
from pathlib import Path
import threading
import time
from urllib.parse import urlencode
from urllib.request import Request,urlopen

BASE='https://betaapi.zhitongcaijing.com/hkmarket/v3/ggt-ctb/'

def fetch(path,params):
    request=Request(BASE+path+'?'+urlencode(params),headers={'User-Agent':'Mozilla/5.0','Referer':'https://data.zhitongcaijing.com/'})
    with urlopen(request,timeout=6) as response:value=json.load(response)
    if value.get('status')!='success':raise ValueError('智通暂未返回有效数据')
    return value['data']

def price(value):
    try:
        number=float(value)
        return number if math.isfinite(number) and number>0 else None
    except (ValueError,TypeError):return None

def collect(get=fetch,now=None):
    overview=get('index.html',{'type':1})
    targets={}
    for child in (1,2):
        for page in range(1,11):
            data=get('list.html',dict(status=1,child_status=child,page=page,page_size=100))
            rows=data['list']
            for row in rows:
                code=str(row.get('SecuCode',''))
                if len(code)!=5 or not code.isdigit():continue
                targets['HK.'+code]=dict(target_price=price(row.get('DbPrice')),name=row.get('SecuAbbr'),source_date=str(row.get('TradingDay',''))[:10],raw=row)
            if page*100>=int(data['count']):break
        else:raise ValueError('智通列表超过分页限制，保留之前的完整数据')
    return dict(targets=targets,fetched_at=time.time() if now is None else now,source_date=overview.get('date'),cycle=overview.get('cycle'),in_market_value=overview.get('inMarketValue'),out_market_value=overview.get('outMarketValue'),error=None)

class TargetQuotes:
    def __init__(self,path):
        self.path=Path(path);self.lock=threading.Lock();self.stop=threading.Event()
        try:self.value=json.loads(self.path.read_text())
        except (OSError,ValueError):self.value={}

    def update(self,get=fetch):
        try:
            value=collect(get)
            temporary=self.path.with_suffix('.json.tmp')
            temporary.write_text(json.dumps(value,ensure_ascii=False));temporary.replace(self.path)
            with self.lock:self.value=value
        except Exception:
            with self.lock:self.value=dict(self.value,error='智通更新失败，保留上次结果',checked_at=time.time())

    def quote(self,code,now=None):
        with self.lock:
            snapshot=self.value
            row=dict(snapshot.get('targets',{}).get(code,{}))
            for key in ('fetched_at','cycle','in_market_value','out_market_value','error'):
                row[key]=snapshot.get(key)
            row['source_date']=row.get('source_date') or snapshot.get('source_date')
        clock=time.time() if now is None else now
        row['stale']=not row.get('fetched_at') or clock-row['fetched_at']>180
        row['refresh_seconds']=60
        return row

    def start(self):
        def run():
            while not self.stop.is_set():
                self.update()
                # Remains active outside Futu sessions, including every morning.
                self.stop.wait(60)
        threading.Thread(target=run,name='zhitong-targets',daemon=True).start()
