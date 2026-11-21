"""Broker-level morning/afternoon net changes with separately labelled queue presence."""
from datetime import datetime
import unicodedata
import json
import math
from .engine import HK
from .broker_profiles import classify
from .seat_anomalies import sample_queues


def name_key(name):
    return ''.join(unicodedata.normalize('NFKC',str(name)).split())


def volume_snapshots(db,samples):
    """Keep only volume fields from the exact canonical net snapshot IDs."""
    selected={row['id'] for rows in samples.values() for row in rows}
    if not selected:return {}
    minimum=min(row['source'] for rows in samples.values() for row in rows)
    maximum=max(row['source'] for rows in samples.values() for row in rows)
    result={}
    for ident,code,source,payload in db.execute('SELECT id,code,source_time,payload FROM broker_samples WHERE source_time>=? AND source_time<=?',(minimum,maximum)):
        if ident not in selected:continue
        values={};conflicts=set()
        for row in json.loads(payload).get('rows',[]):
            volume=row.get('total_vol');name=row.get('broker_name')
            if not name or row.get('is_real_time') is not True or isinstance(volume,bool) or not isinstance(volume,(int,float)) or not math.isfinite(volume) or volume<0:continue
            key=name_key(name)
            if key in values and values[key]!=volume:conflicts.add(key)
            values[key]=volume
        for key in conflicts:values.pop(key,None)
        result.setdefault(code,{})[source]=values
    return result


def broker_periods(events,start,end,samples,now=None,volumes=None):
    now=min(end,now if now is not None else datetime.now(HK).timestamp())
    queues=sample_queues(events,start,end);result={}
    for code in set(queues)|set(samples):
        names={};periods={key:dict(valid=0,expected=0) for key in ('morning','afternoon')}
        def entry(name):
            key=name_key(name)
            return names.setdefault(key,dict(name=name,ids=set(),morning=dict(bid=0,ask=0,present=0),afternoon=dict(bid=0,ask=0,present=0)))
        for ts,seats in queues.get(code,{}).items():
            if ts>=now:continue
            key='morning' if ts<start+43200 else 'afternoon';periods[key]['expected']+=1
            if seats is None:continue
            periods[key]['valid']+=1;present={}
            for ident,seat in seats.items():
                broker=entry(seat['name']);broker['ids'].add(ident)
                row=present.setdefault(name_key(seat['name']),dict(bid=0,ask=0))
                row['bid']=max(row['bid'],seat['bid']);row['ask']=max(row['ask'],seat['ask'])
            for name,value in present.items():
                target=names[name][key];target['bid']+=value['bid'];target['ask']+=value['ask'];target['present']+=1
        rows=sorted(samples.get(code,[]),key=lambda row:row['ts'])
        morning=next((r for r in reversed(rows) if start+34200<=r['ts']<=start+43200 and r['ts']<=now),None)
        noon=next((r for r in reversed(rows) if start+42900<=r['ts']<=start+46800 and r['ts']<=now),None)
        afternoon=next((r for r in reversed(rows) if start+46800<=r['ts']<=start+57600 and r['ts']<=now),None)
        # Cumulative net_vol at the morning endpoint includes all trades that morning.
        snapshots={label:({name_key(n):v for n,v in row['brokers'].items()} if row else {}) for label,row in (('morning',morning),('noon',noon),('afternoon',afternoon))}
        for row in rows:
            if row['ts']<=now:
                for name in row['brokers']:entry(name)
        latest=next((r for r in reversed(rows) if r['ts']<=now),None)
        volume_values=(volumes or {}).get(code,{}).get(latest['source'],{}) if latest else {}
        output=[]
        for key,broker in names.items():
            broker['ids']=sorted(broker['ids'])
            broker['channel_profile']=classify(broker['name'])
            broker['total_volume']=volume_values.get(key)
            broker['volume_source']=latest['source'] if broker['total_volume'] is not None else None
            for label in periods:
                target=broker[label];total=target['bid']+target['ask']
                target['share']=target['bid']/total if total else None
                target['coverage']=target['present']/periods[label]['valid'] if periods[label]['valid'] else None
                if label=='morning':
                    net=snapshots['morning'].get(key);first=None;last=morning
                    reason='上午源快照未覆盖该券商' if net is None else None
                else:
                    before=snapshots['noon'].get(key);after=snapshots['afternoon'].get(key)
                    net=after-before if before is not None and after is not None and noon['ts']<afternoon['ts'] else None
                    first=noon;last=afternoon
                    reason='缺少午间基准或下午端点，不能推算下午净买卖' if net is None else None
                target.update(net=net,net_direction='buy' if net is not None and net>0 else 'sell' if net is not None and net<0 else 'flat' if net==0 else 'unknown',from_source=first['source'] if first else None,to_source=last['source'] if last else None,reason=reason)
            output.append(broker)
        output.sort(key=lambda r:(r['total_volume'] is None,-(r['total_volume'] or 0),-sum(abs(r[k]['net'] or 0) for k in periods),r['name']))
        summary={key:{direction:[dict(name=r['name'],net=r[key]['net'],channel_profile=r['channel_profile']) for r in sorted(output,key=lambda r:abs(r[key]['net'] or 0),reverse=True) if r[key]['net_direction']==direction] for direction in ('buy','sell')} for key in periods}
        result[code]=dict(brokers=output,summary=summary,periods=periods,morning_source=morning['source'] if morning else None,noon_source=noon['source'] if noon else None,afternoon_source=afternoon['source'] if afternoon else None,volume_source=latest['source'] if latest else None,sort='total_volume_desc')
    return result
