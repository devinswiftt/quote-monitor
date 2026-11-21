"""Delayed cumulative broker evidence; not identification of individual trades."""
from collections import defaultdict
from datetime import datetime
import json,math
from .engine import HK,timestamp

VERSION=1

def grouped(rows):
    result={}
    for row in rows:
        name=row.get('broker_name');number=row.get('net_vol')
        if not name or isinstance(number,bool) or not isinstance(number,(int,float)) or not math.isfinite(number):continue
        if name in result and result[name]!=number:return None
        result[name]=number
    return result

class BrokerAttribution:
    def __init__(self,db,start,end,events):
        self.events=events;self.samples=defaultdict(list)
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='broker_samples'").fetchone():return
        date=datetime.fromtimestamp(start,HK).strftime('%Y-%m-%d')
        canonical={}
        for ident,code,source,observed,payload,post in db.execute('SELECT id,code,source_time,observed,payload,after_close FROM broker_samples WHERE source_time>=? AND source_time<? ORDER BY id',(date,datetime.fromtimestamp(end,HK).strftime('%Y-%m-%d'))):
            try:
                value=json.loads(payload);ts=timestamp(source)
                # Mixed source times cannot be treated as a simultaneous snapshot.
                if any(str(r.get('data_time_str',''))!=source for r in value.get('rows',[])):continue
                brokers=grouped(value.get('rows',[]))
                if not brokers:continue
                key=(code,source);revisions=canonical.get(key,{}).get('revisions',0)
                canonical[key]=dict(id=ident,code=code,ts=ts,source=source,observed=observed,brokers=brokers,after_close=bool(post),revisions=revisions+1)
            except (ValueError,TypeError):continue
        for sample in canonical.values():self.samples[sample['code']].append(sample)
        for rows in self.samples.values():rows.sort(key=lambda r:r['ts'])

    def analyze(self,event):
        code=event['code'];begin=event.get('started_at',event.get('ts',0)-event.get('window_seconds',3));finish=event.get('updated_at',event.get('ts',0))
        base=dict(version=VERSION,status='waiting',candidates=[],unmatched=[],note='净量变化是区间线索，净买增加也可能是卖出减少；榜外不是零交易，不确认具体成交归属或庄家身份。')
        samples=self.samples.get(code,[])
        before=next((s for s in reversed(samples) if s['ts']<=begin),None)
        after=next((s for s in samples if s['ts']>=finish+10),None)
        if not before:return dict(base,status='insufficient',reason='缺少异动前同日经纪商快照，无法计算净量变化')
        if not after:return dict(base,reason='等待源更新时间覆盖异动结束后至少10秒的新快照；获取时间不作为成交时间')
        interval=after['ts']-before['ts']
        if interval>300:return dict(base,status='insufficient',reason='前后源快照间隔超过5分钟，不能用于单次异动归因',from_source=before['source'],to_source=after['source'])
        related=[]
        for other in self.events:
            if other['code']!=code:continue
            first=other.get('started_at',other.get('ts',0)-other.get('window_seconds',3));last=other.get('updated_at',other.get('ts',0))
            if first<=after['ts'] and last>=before['ts']:related.append(other.get('reference'))
        shared=len(set(related))>1
        candidates=[];unmatched=[]
        for name in sorted(set(before['brokers'])|set(after['brokers'])):
            a=before['brokers'].get(name);b=after['brokers'].get(name)
            if a is None or b is None:
                unmatched.append(dict(name=name,status='后续上榜，起点未知' if a is None else '后续未上榜，终点未知'));continue
            delta=b-a
            if not delta:continue
            direction='BUY' if delta>0 else 'SELL'
            candidates.append(dict(name=name,before_net=a,after_net=b,delta=delta,direction=direction,meaning='净买量增加／净卖量减少' if delta>0 else '净卖量增加／净买量减少',aligned=direction==event.get('signal',{'LIFT':'BUY','DUMP':'SELL'}.get(event.get('type')))))
        candidates.sort(key=lambda c:abs(c['delta']),reverse=True)
        profile=event.get('participation') or {}
        for candidate in candidates:
            name=candidate['name']
            candidate['queue_context']=[side for side in ('bid','ask') if any(row.get('name')==name for row in profile.get(side,[]))]
        closing=next((sample for sample in reversed(samples) if sample['after_close'] and sample['ts']>=after['ts']),None)
        closing_review=None
        if closing:
            closing_review=dict(id=closing['id'],source=closing['source'],observed=closing['observed'],changes=[dict(name=c['name'],event_after_net=c['after_net'],closing_net=closing['brokers'].get(c['name']),delta_since_event=(closing['brokers'][c['name']]-c['after_net'] if c['name'] in closing['brokers'] else None)) for c in candidates[:12]])
        return dict(base,status='interval' if shared else 'available',reason='同一更新区间覆盖多条事件，只能共同参考，不能逐条分配' if shared else '已取得异动前后源快照；仅提供低置信区间候选',from_source=before['source'],to_source=after['source'],before_id=before['id'],after_id=after['id'],before_observed=before['observed'],after_observed=after['observed'],before_delay=round(before['observed']-before['ts'],2),after_delay=round(after['observed']-after['ts'],2),interval_seconds=interval,related=sorted(set(r for r in related if r)),closing_review=closing_review,candidates=candidates[:12],unmatched=unmatched,after_close_review=after['after_close'],same_time_revisions=before['revisions']+after['revisions']-2)
