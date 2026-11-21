"""Event-centered seat changes with presence, persistence and independent evidence gates."""
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime
import math
from .engine import HK

STEP=10
WINDOW=300
MIN_PRESENT=20
MIN_COVERAGE=.8
MIN_SHIFT=.30
MIN_SUSTAINED=120


def session_bounds(ts,start):
    for left,right in ((34200,43200),(46800,57600)):
        if start+left<=ts<start+right:return start+left,start+right
    return None


def sample_queues(events,start,end):
    streams=defaultdict(list)
    for ts,event in events:
        if start<=ts<end and not event.get('error') and isinstance(event.get('bid'),list) and isinstance(event.get('ask'),list):streams[event['code']].append((ts,event))
    sampled={}
    for code,stream in streams.items():
        stream.sort(key=lambda row:row[0]);times=[r[0] for r in stream];rows={}
        for left,right in ((34200,43200),(46800,57600)):
            for ts in range(int(start)+left,int(start)+right,STEP):
                i=bisect_right(times,ts)-1
                if i<0 or ts-times[i]>30:rows[ts]=None;continue
                event=stream[i][1];seats={}
                for side in ('bid','ask'):
                    for seat in event[side]:
                        ident=str(seat.get('id',''))
                        if not ident or ident=='0':continue
                        item=seats.setdefault(ident,dict(name=seat.get('name') or ident,bid=0,ask=0));item[side]=1
                rows[ts]=seats
        sampled[code]=rows
    return sampled


def presence(rows):
    counts={};valid=0
    for ts,seats in rows:
        if seats is None:continue
        valid+=1
        for ident,seat in seats.items():
            item=counts.setdefault(ident,dict(name=seat['name'],bid=0,ask=0,present=0))
            item['bid']+=seat['bid'];item['ask']+=seat['ask'];item['present']+=1
    for item in counts.values():item['share']=item['bid']/(item['bid']+item['ask'])
    return valid,counts


def sustained_seconds(rows,ident,baseline,sign):
    first=previous=None;best=0
    for ts,seats in rows:
        seat=(seats or {}).get(ident)
        good=seat is not None and (seat['bid']/(seat['bid']+seat['ask'])-baseline)*sign>=MIN_SHIFT-1e-9
        if not good:first=previous=None;continue
        if previous is None or ts-previous!=STEP:first=ts
        previous=ts;best=max(best,ts-first)
    return best


def detect_seat_anomalies(events,start,end,related,prices=None,now=None):
    now=min(end,now if now is not None else datetime.now(HK).timestamp())
    sampled=sample_queues(events,start,end);groups={};cache={};evaluated=defaultdict(set);waiting=defaultdict(int)
    for event in related:
        code=event['code'];ts=event.get('started_at',event.get('ts',0));anchor=int(ts//STEP)*STEP
        bounds=session_bounds(anchor,start)
        if not bounds or anchor-WINDOW<bounds[0] or anchor+WINDOW>bounds[1]:continue
        if anchor+WINDOW>now:waiting[code]+=1;continue
        key=(code,anchor);evaluated[code].add(anchor)
        if key not in cache:
            series=sampled.get(code,{})
            before=[(t,series.get(t)) for t in range(anchor-WINDOW,anchor,STEP)]
            after=[(t,series.get(t)) for t in range(anchor,anchor+WINDOW,STEP)]
            valid_before,a=presence(before);valid_after,b=presence(after);candidates=[]
            if min(valid_before,valid_after)/30>=MIN_COVERAGE:
                for ident in a.keys()&b.keys():
                    old,new=a[ident],b[ident]
                    if min(old['present'],new['present'])<MIN_PRESENT:continue
                    if min(old['present']/valid_before,new['present']/valid_after)<.1:continue
                    shift=new['share']-old['share']
                    if abs(shift)<MIN_SHIFT-1e-9:continue
                    sign=1 if shift>0 else -1;duration=sustained_seconds(after,ident,old['share'],sign)
                    if duration<MIN_SUSTAINED:continue
                    direction='BUY' if sign>0 else 'SELL'
                    crossing=(old['share']<.5<new['share']) if sign>0 else (new['share']<.5<old['share'])
                    candidates.append(dict(id=ident,name=new['name'],direction=direction,label=('转向买侧' if sign>0 else '转向卖侧') if crossing else ('买侧明显增强' if sign>0 else '卖侧明显增强'),before=old,after=new,shift=shift,sustained_seconds=duration,before_valid=valid_before,after_valid=valid_after,window_start=anchor-WINDOW,anchor_time=anchor,event_time=ts,window_end=anchor+WINDOW))
            cache[key]=candidates
        for candidate in cache[key]:
            row=dict(candidate);net=event.get('broker_attribution') or {};match=next((r for r in net.get('candidates',[]) if r.get('name')==row['name']),None)
            row['net_evidence']=dict(status='same_direction' if match['delta']*(1 if row['direction']=='BUY' else -1)>0 else 'opposite_direction',delta=match['delta'],from_source=net.get('from_source'),to_source=net.get('to_source'),shared=net.get('status')=='interval') if match else dict(status='unknown',reason=net.get('reason') or '同名券商缺少可比净量数据，未上榜不当作零')
            row['reference']=event.get('reference');row['event_kind']=event.get('type',event.get('signal'));row['event_confirmed']=any(h.get('phase')=='confirmed' for h in event.get('history',[])) if event.get('type') else None
            price_rows=(prices or {}).get(code,[])
            first=next((p for p in reversed(price_rows) if anchor-120<=p['ts']<=anchor-60),None)
            last=next((p for p in reversed(price_rows) if anchor+180<=p['ts']<=anchor+240),None)
            row['price_context']=dict(before=first['price'],after=last['price'],change_pct=(last['price']/first['price']-1)*100,before_ts=first['ts'],after_ts=last['ts']) if first and last and first['price'] else None
            gkey=(code,row['name'],row['direction']);group=groups.setdefault(gkey,dict(code=code,name=row['name'],direction=row['direction'],seats={},references=set(),windows={}))
            group['windows'].setdefault(anchor,set()).add(row['id'])
            if row['reference']:group['references'].add(row['reference'])
            rank=lambda r:(r['net_evidence']['status']=='same_direction',abs(r['shift']),r['sustained_seconds'],r['event_time'])
            if row['id'] not in group['seats'] or rank(row)>rank(group['seats'][row['id']]):group['seats'][row['id']]=row
    output={}
    for code in sampled:
        records=[]
        for group in groups.values():
            if group['code']!=code:continue
            seats=sorted(group['seats'].values(),key=lambda r:(r['net_evidence']['status']!='same_direction',-abs(r['shift']),-r['sustained_seconds']))
            records.append(dict(code=code,name=group['name'],direction=group['direction'],seats=seats,concurrent_seats=max(map(len,group['windows'].values())),references=sorted(group['references']),net_supported=any(r['net_evidence']['status']=='same_direction' for r in seats)))
        records.sort(key=lambda g:(not g['net_supported'],-g['concurrent_seats'],-max(abs(r['shift']) for r in g['seats'])))
        output[code]=dict(top=records[:5],total_groups=len(records),qualified_seats=len({r['id'] for g in records for r in g['seats']}),evaluated_windows=len(evaluated[code]),waiting_events=waiting[code],rules=dict(window_seconds=WINDOW,min_present=MIN_PRESENT,min_presence=.1,min_queue_coverage=MIN_COVERAGE,min_shift=MIN_SHIFT,min_sustained_seconds=MIN_SUSTAINED,limit=5))
    return output
