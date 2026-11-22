"""Intraday comparisons of saved queues, delayed broker net positions and prices."""
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime
import json
import math
from .engine import HK
from .broker_periods import broker_periods,volume_snapshots

STEP=10
MAX_AGE=30


def describe_seat(seat):
    """Independent afternoon/tail comparisons; labels may overlap."""
    morning=seat['morning'];tags=[];comparisons=[]
    for key,label in (('afternoon','下午'),('tail','尾盘')):
        target=seat[key]
        delta=target['share']-morning['share'] if target['share'] is not None and morning['share'] is not None else None
        enough=morning['observations']>=20 and target['observations']>=20
        comparison=dict(period=key,delta=delta,enough=enough,from_share=morning['share'],to_share=target['share'])
        if not enough:
            comparison['summary']=label+'与上午的在场记录不足，暂不判断转向'
        else:
            a,b=morning['share'],target['share']
            # A crossing of the midpoint must also move at least 15 percentage points.
            if a>.5 and b<.5 and delta<=-.15:
                tags.extend(['buy_to_sell',key+'_buy_to_sell'])
                comparison['summary']=('上午略偏买' if a<.6 else '上午偏买')+'，'+label+'转向卖侧'
            elif a<.5 and b>.5 and delta>=.15:
                tags.extend(['sell_to_buy',key+'_sell_to_buy'])
                comparison['summary']=('上午略偏卖' if a>.4 else '上午偏卖')+'，'+label+'转向买侧'
            elif delta<=-.15:
                comparison['summary']=label+('仍偏买，但买侧明显减弱' if b>.5 else '买卖接近平衡，买侧较上午减弱' if b==.5 else '卖侧进一步增强')
            elif delta>=.15:
                comparison['summary']=label+('仍偏卖，但买侧明显增强' if b<.5 else '买卖接近平衡，买侧较上午增强' if b==.5 else '买侧进一步增强')
            else:
                comparison['summary']=label+'买卖侧分布与上午接近'
            if delta<=-.15:tags.extend(['sell_strengthening',key+'_sell_strengthening'])
            if delta>=.15:tags.extend(['buy_strengthening',key+'_buy_strengthening'])
            if key=='tail' and abs(delta)>=.2:tags.append('tail_change')
            if target['bid']==0 and target['ask']>0:
                tags.append(key+'_only_sell');comparison['summary']+='；只在卖侧出现'
            elif target['ask']==0 and target['bid']>0:
                tags.append(key+'_only_buy');comparison['summary']+='；只在买侧出现'
        comparisons.append(comparison)
    seat['tags']=list(dict.fromkeys(tags));seat['comparisons']=comparisons
    seat['shift']=comparisons[0]['delta'];seat['tail_shift']=comparisons[1]['delta']
    seat['category']=next((tag for tag in ('buy_to_sell','sell_to_buy','tail_change','sell_strengthening','buy_strengthening') if tag in tags),'other')
    return seat


def queue_analysis(events,start,end):
    """Fixed-time presence sampling, never push counts or executed volume."""
    streams=defaultdict(list)
    for ts,event in events:
        if not start<=ts<end or event.get('error') or not isinstance(event.get('bid'),list) or not isinstance(event.get('ask'),list):continue
        streams[event['code']].append((ts,event))
    now=min(end,datetime.now(HK).timestamp())
    output={}
    for code,stream in streams.items():
        stream.sort(key=lambda item:item[0]);times=[item[0] for item in stream]
        periods={};seats={}
        for key,begin,finish in [('morning',9.5,12),('afternoon',13,16),('tail',15,16)]:
            left=start+begin*3600;right=min(start+finish*3600,now)
            count=valid=0
            for index in range(max(0,math.ceil((right-left)/STEP))):
                ts=left+index*STEP;count+=1;position=bisect_right(times,ts)-1
                if position<0 or ts-times[position]>MAX_AGE:continue
                valid+=1;event=stream[position][1];active=set()
                for side in ('bid','ask'):
                    present={}
                    for row in event[side]:
                        ident=str(row.get('id',''))
                        if ident and ident!='0':present[ident]=row.get('name') or ident
                    for ident,name in present.items():
                        seat=seats.setdefault(ident,dict(id=ident,name=name,morning=dict(bid=0,ask=0,samples=0),afternoon=dict(bid=0,ask=0,samples=0),tail=dict(bid=0,ask=0,samples=0)))
                        seat[key][side]+=1;active.add(ident)
                for ident in active:seats[ident][key]['samples']+=1
            periods[key]=dict(expected=count,valid=valid,coverage=valid/count if count else None)
        rows=[]
        for seat in seats.values():
            for key in periods:
                value=seat[key];n=value['bid']+value['ask'];value['share']=value['bid']/n if n else None;value['observations']=n
            rows.append(describe_seat(seat))
        rows.sort(key=lambda row:(row['category']=='other',-max(abs(row['shift'] or 0),abs(row['tail_shift'] or 0)),-sum(row[k]['observations'] for k in periods)))
        output[code]=dict(periods=periods,seats=rows,step_seconds=STEP,max_age_seconds=MAX_AGE,scope='完整可见经纪队列；席位每次采样在同侧最多计一次，双侧可同时出现；不是成交买卖笔数。',counts={key:sum((key in r['tags']) if key!='other' else not r['tags'] for r in rows) for key in ('buy_to_sell','sell_to_buy','tail_change','sell_strengthening','buy_strengthening','other')})
    return output


def intraday_insights(db,start,end,samples,related=None):
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
    return dict(queues=queue_analysis(queue,start,end),prices=price_rows,broker_periods=broker_periods(queue,start,end,samples,volumes=volume_snapshots(db,samples)))
