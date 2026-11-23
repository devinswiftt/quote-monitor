"""Fixed-interval sampling of visible broker queues."""
from bisect import bisect_right
from collections import defaultdict

STEP=10


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
