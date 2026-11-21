"""Conservative passive-side hypotheses, never verified trade identities."""
from collections import Counter, defaultdict, deque


class Attribution:
    def __init__(self):
        self.events = defaultdict(deque)

    def observe(self, received, event):
        if event['kind'] == 'reset':
            self.events.clear()
            return
        code = event.get('code')
        if code and event['kind'] in ('tick', 'book', 'broker'):
            self.events[code].append((received, event))
            while self.events[code] and self.events[code][0][0] < received - 120:
                self.events[code].popleft()

    def infer(self, alert, received, window=3):
        result = dict(status='unknown', confidence='不可判定', candidates=[], active_side='未知',
                      note='撤单、补单及非同步推送均可能造成相同变化；不是已确认成交归属')
        if alert.get('signal') not in ('BUY', 'SELL'):
            result['reason'] = '成交方向不集中'
            return result
        side = 'ask' if alert['signal'] == 'BUY' else 'bid'
        result['passive_side'] = '疑似被动卖方' if side == 'ask' else '疑似被动买方'
        result['reason'] = '缺少足够新鲜的成交前后连续推送'
        data = list(self.events[alert['code']])
        start = received - window
        def pair(kind):
            rows = [(t,e) for t,e in data if e['kind']==kind and
                    (kind!='broker' or e.get('source')=='push')]
            before = [(t,e) for t,e in rows if start-1 <= t <= start]
            after = [(t,e) for t,e in rows if received < t <= received+2]
            return (before[-1] if before else None, after[0] if after else None)
        oldb,newb=pair('book');oldq,newq=pair('broker')
        if not all((oldb,newb,oldq,newq)):
            return result
        if any(abs(t-e['ts'])>2 for t,e in (oldb,newb)):
            result['reason']='盘口源时间与接收时间偏差过大'
            return result
        if abs(oldb[0]-oldq[0])>1 or abs(newb[0]-newq[0])>1:
            result['reason']='盘口与经纪队列接收相差超过1秒'
            return result
        old,new=oldb[1][side],newb[1][side]
        if not old or not new or old[0][0]!=new[0][0]:
            result['reason']='最优价格变动，队列档位无法可靠对应'
            return result
        price=old[0][0]
        if any(e[side] and e[side][0][0]!=price for t,e in data
               if e['kind']=='book' and oldb[0]<=t<=newb[0]):
            result['reason']='窗口内最优价格曾变化，不能把队列条目减少对应到成交'
            return result
        depletion=old[0][1]-new[0][1]
        seen=set();volume=0
        for t,e in data:
            if e['kind']=='tick' and start<t<=received and e['sequence'] not in seen:
                seen.add(e['sequence'])
                if e['direction']==alert['signal'] and e['price']==price and abs(t-e['ts'])<=2:
                    volume+=e.get('volume',e['amount']/e['price'])
        result['evidence']=dict(price=price, queue_reduction=depletion, matched_volume=volume,
            before_book_received=oldb[0],after_book_received=newb[0],
            before_queue_received=oldq[0],after_queue_received=newq[0])
        if volume<=0 or not .5<=depletion/volume<=1.5:
            result['reason']='挂单减少量与同价同方向成交量不一致'
            return result
        oldrows=[r for r in oldq[1][side] if r['position']==1]
        newcounts=Counter(r['id'] for r in newq[1][side] if r['position']==1)
        removed=Counter(r['id'] for r in oldrows)-newcounts
        candidates=[dict(id=ident,name=next(r['name'] for r in oldrows if r['id']==ident),
                         removed_queue_entries=count) for ident,count in removed.items()]
        # Keep each broker's IDs, but do not mistake multiple IDs for independent firms.
        grouped={}
        for row in candidates:
            v=grouped.setdefault(row['name'],dict(name=row['name'],ids=[],removed_queue_entries=0))
            v['ids'].append(row['id']);v['removed_queue_entries']+=row['removed_queue_entries']
        candidates=[dict(v,id=v['ids'][0]) for v in grouped.values()]
        result['candidates']=candidates
        result['limitations']=['队列条目不是委托股数','撤单、补单和不同步推送仍可能产生相同变化','主动成交方未知，无法验证真实成交身份']
        if not candidates:
            result['reason']='未观察到买一／卖一经纪队列条目减少'
        elif len(candidates)>1:
            result.update(status='ambiguous',confidence='很低',reason='多家券商队列条目减少，无法区分成交与撤单')
        else:
            result.update(status='hypothesis',confidence='低',reason='同价挂单减少与成交量接近，且仅一家经纪条目减少；仍无法排除撤单')
        return result
