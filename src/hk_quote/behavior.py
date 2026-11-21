"""Deterministic observable order-flow episodes; no claim about intent or identity."""
from collections import deque
from copy import deepcopy
from statistics import median
from .engine import continuous, session
from .profile import TurnoverProfile

LABELS = {'DUMP':'疑似砸盘', 'SUPPORT':'疑似承接护盘', 'LIFT':'疑似主动拉升'}
PHASES = {'observing':'观察中','confirmed':'证据增强','ongoing':'持续发生',
          'cooling':'信号缓解','resolved':'观察结束','failed':'承接失效','interrupted':'监控中断'}
DEFAULTS = dict(enabled=True,warmup_seconds=60,min_profile_samples=8,min_trades=3,
                direction_ratio=.75,min_direction_coverage=.7,confirm_seconds=2,
                continuing_seconds=15,cooling_seconds=10,resolve_seconds=30)


class BehaviorEngine:
    def __init__(self, config=None):
        self.c=dict(DEFAULTS,**(config or {}));self.states={};self.profiles={}

    def _state(self, code, ts):
        return self.states.setdefault(code,dict(start=ts,last=ts,ticks=deque(),books=deque(),
            seen=set(),ids=deque(),profiles=self.profiles.setdefault(code,{w:TurnoverProfile(w,3600) for w in (3,15,60)}),
            cycles=deque(),depletions={},episode=None,proposal=None,breaks=deque(),last_emit=0))

    def learn(self,event):
        """Restore calibration only; never revive old episodes or book evidence."""
        if event.get('kind')!='tick' or not continuous(event['ts']):return
        profiles=self.profiles.setdefault(event['code'],{w:TurnoverProfile(w,3600) for w in (3,15,60)})
        for profile in profiles.values():profile.add(event)

    @staticmethod
    def step(book):
        gaps=[]
        for side in ('bid','ask'):
            levels=book.get(side,[])
            gaps.extend(abs(float(a[0])-float(b[0])) for a,b in zip(levels,levels[1:]) if a[0]!=b[0])
        spread=float(book['ask'][0][0])-float(book['bid'][0][0])
        if spread>0:gaps.append(spread)
        return min(gaps) if gaps else None

    def _book(self,s,event):
        old=s['books'][-1] if s['books'] else None
        if old and event['ts']<old['ts']:return
        s['books'].append(event)
        if not old or event['ts']-old['ts']>3:return
        # Compare shares at an actual price, never the row index of a moving book.
        old_bid={float(r[0]):float(r[1]) for r in old['bid']}
        for row in event['bid']:
            price,shares=float(row[0]),float(row[1])
            if price not in old_bid:continue
            previous=old_bid[price]
            if shares<previous:
                trades=[t for t in s['ticks'] if old['ts']-1<=t['ts']<=event['ts'] and
                        t['direction']=='SELL' and abs(t['price']-price)<1e-8]
                if trades:
                    s['depletions'][price]=dict(ts=event['ts'],loss=previous-shares,
                        volume=sum(t.get('volume',t['amount']/t['price']) for t in trades),
                        sequences={str(t['sequence']) for t in trades})
            elif shares>previous and price in s['depletions']:
                d=s['depletions'].pop(price)
                used=set().union(*(v['sequences'] for v in s['cycles'])) if s['cycles'] else set()
                if 0<event['ts']-d['ts']<=10 and d['sequences']-used:
                    s['cycles'].append(dict(ts=event['ts'],price=price,loss=d['loss'],
                        restored=shares-previous,matched_sell=d['volume'],sequences=d['sequences']))

    def _candidate(self,s,now):
        if now-s['start']<self.c['warmup_seconds'] or not s['books']:return None
        book=s['books'][-1]
        if not (0<=now-book['ts']<=3) or not book['bid'] or not book['ask']:return None
        if min(len(book['bid']),len(book['ask']))<2:return None
        step=self.step(book)
        if not step or step<=0:return None
        spread=book['ask'][0][0]-book['bid'][0][0]
        candidates=[]
        for window in (3,15,60):
            ticks=[t for t in s['ticks'] if now-window<t['ts']<=now]
            if len(ticks)<self.c['min_trades']:continue
            calibration=s['profiles'][window].estimate(now,.75,1.2,self.c['min_profile_samples'])
            if not calibration:continue
            amount=sum(t['amount'] for t in ticks)
            if amount<calibration['threshold']:continue
            buy=sum(t['amount'] for t in ticks if t['direction']=='BUY')
            sell=sum(t['amount'] for t in ticks if t['direction']=='SELL')
            coverage=(buy+sell)/amount if amount else 0
            if coverage<self.c['min_direction_coverage']:continue
            side='BUY' if buy>=sell else 'SELL'
            ratio=max(buy,sell)/(buy+sell) if buy+sell else 0
            if ratio<self.c['direction_ratio']:continue
            prices=[t['price'] for t in ticks]
            older=[t for t in s['ticks'] if now-300<=t['ts']<=now-window]
            deltas=[abs(b['price']-a['price']) for a,b in zip(older,older[1:])]
            move_required=max(step*2,spread,median(deltas)*2 if deltas else 0)
            move=prices[-1]-prices[0]
            evidence=dict(window_seconds=window,amount=round(amount,2),buy_amount=round(buy,2),
                sell_amount=round(sell,2),direction_ratio=ratio,coverage=coverage,trades=len(ticks),
                price_from=prices[0],price_to=prices[-1],price_change=round(move,8),
                observed_price_step=step,spread=spread,move_required=move_required,
                threshold=calibration['threshold'],baseline_samples=calibration['samples'],
                intensity=amount/calibration['threshold'],book_supported=False)
            # Sell pressure absorbed repeatedly at a stable, traded bid price.
            if side=='SELL' and window>=15 and ticks[-1]['ts']-ticks[0]['ts']>=8:
                anchor=float(book['bid'][0][0])
                cycles=[c for c in s['cycles'] if now-window<c['ts']<=now and abs(c['price']-anchor)<1e-8]
                matched=[t for t in ticks if t['direction']=='SELL' and abs(t['price']-anchor)<1e-8]
                if len(cycles)>=2 and len(matched)>=3 and min(prices)>=anchor-step-1e-8 and abs(prices[-1]-anchor)<=step+1e-8:
                    e=dict(evidence,anchor=anchor,replenishment_cycles=len(cycles),book_supported=True,
                        matched_sell_shares=sum(t.get('volume',t['amount']/t['price']) for t in matched),
                        restored_shares=sum(c['restored'] for c in cycles),
                        reason='主动卖出增强，成交价格守在买盘区域；同价真实卖出伴随至少两轮挂盘消耗后恢复')
                    candidates.append(dict(type='SUPPORT',evidence=e))
            if len(set(round(p,8) for p in prices))<3:continue
            if (side=='BUY' and move+1e-8<move_required) or (side=='SELL' and -move+1e-8<move_required):continue
            field='ask' if side=='BUY' else 'bid'
            old=next((b for b in reversed(s['books']) if b['ts']<=ticks[0]['ts']),None)
            e=dict(evidence,reason='主动成交集中并推动成交价格；等待同价盘口消耗证据')
            if old and 0<=ticks[0]['ts']-old['ts']<=3 and old[field]:
                price=float(old[field][0][0]);before=float(old[field][0][1])
                shares={float(r[0]):float(r[1]) for r in book[field]}
                progressed=(book[field][0][0]>price if side=='BUY' else book[field][0][0]<price)
                after=shares.get(price,0 if progressed else before)
                matched=sum(t.get('volume',t['amount']/t['price']) for t in ticks
                            if t['direction']==side and abs(t['price']-price)<1e-8)
                loss=before-after
                supported=loss>0 and matched>0 and .25<=loss/matched<=4
                e.update(book_supported=supported,consumed_price=price,queue_reduction=loss,
                         matched_shares=matched,reason='主动成交集中、成交价推进，并观察到同价挂盘减少与成交相符' if supported else e['reason'])
            candidates.append(dict(type='LIFT' if side=='BUY' else 'DUMP',evidence=e))
        if not candidates:return None
        # Favor corroborated evidence, then absorption; no probability score is fabricated.
        return max(candidates,key=lambda c:(c['evidence']['book_supported'],c['type']=='SUPPORT',c['evidence']['intensity']))

    @staticmethod
    def _snapshot(s):
        value=deepcopy(s['episode']);s['last_emit']=value['updated_at'];return value

    def _phase(self,s,phase,now,reason=None):
        e=s['episode'];e.update(phase=phase,updated_at=now)
        e['history'].append(dict(ts=now,phase=phase,type=e['type'],reason=reason or PHASES[phase]))
        if reason:e['status_reason']=reason
        return self._snapshot(s)

    def process(self,event):
        if not self.c['enabled']:return []
        kind=event.get('kind')
        if kind=='behavior_reset':return self.stop(event['code'],event.get('reason','单股重置'),event['ts'])
        if kind=='reset':return self.stop_all(event.get('reason','数据重置'),event['ts'])
        if kind not in ('tick','book'):return []
        code,now=event['code'],event['ts']
        if not continuous(now):return []
        changes=[]
        old=self.states.get(code)
        if old and session(now)!=session(old['last']):
            changes+=self.stop(code,'交易时段切换',now)
        s=self._state(code,now)
        if now < s['last'] - 3:return changes
        s['last']=max(s['last'],now)
        if kind=='tick':
            if event['sequence'] in s['seen']:return changes
            s['seen'].add(event['sequence']);s['ids'].append((now,event['sequence']));s['ticks'].append(event)
            if len(s['ticks'])>1 and s['ticks'][-2]['ts']>now:
                s['ticks']=deque(sorted(s['ticks'],key=lambda t:t['ts']))
            for profile in s['profiles'].values():profile.add(event)
        else:self._book(s,event)
        for key,horizon in [('ticks',3600),('books',70),('cycles',60)]:
            while s[key] and s[key][0]['ts']<now-horizon:s[key].popleft()
        while s['ids'] and s['ids'][0][0]<now-3600:s['seen'].discard(s['ids'].popleft()[1])
        s['depletions']={p:d for p,d in s['depletions'].items() if now-d['ts']<=10}
        now=s['last']
        candidate=self._candidate(s,now)
        if candidate:
            proposal=s['proposal']
            if not proposal or proposal['type']!=candidate['type'] or now-proposal['last']>3:
                proposal=dict(type=candidate['type'],since=now,last=now);s['proposal']=proposal
            proposal['last']=now
            e=s['episode']
            if not e:
                e=dict(event_key=f"{code}:{now:.6f}:{event.get('sequence','book')}",code=code,
                    started_at=now,updated_at=now,last_match=now,type=candidate['type'],phase='observing',
                    evidence=candidate['evidence'],history=[],version=1)
                s['episode']=e;changes.append(self._phase(s,'observing',now))
            e=s['episode']
            qualified=candidate['evidence']['book_supported'] and now-proposal['since']>=self.c['confirm_seconds']
            if e['type']!=candidate['type']:
                if qualified:
                    s['breaks'].clear()
                    prior=e['type'];e.update(type=candidate['type'],evidence=candidate['evidence'],last_match=now,confirmed_at=now)
                    changes.append(self._phase(s,'confirmed',now,LABELS[prior]+'转为'+LABELS[e['type']]))
            else:
                e.update(evidence=candidate['evidence'],updated_at=now)
                if candidate['evidence']['book_supported'] or e['phase']=='observing':e['last_match']=now
                if e['phase'] in ('observing','cooling') and qualified:
                    e['confirmed_at']=now;changes.append(self._phase(s,'confirmed',now))
                elif e['phase']=='confirmed' and qualified and now-e['confirmed_at']>=self.c['continuing_seconds']:
                    changes.append(self._phase(s,'ongoing',now))
                elif now-s['last_emit']>=3:changes.append(self._snapshot(s))
        else:s['proposal']=None
        # Support failure needs at least two distinct new sell prints below the defended zone.
        e=s['episode']
        if e and e['type']=='SUPPORT' and e['phase'] in ('confirmed','ongoing','cooling') and kind=='tick':
            anchor=e['evidence'].get('anchor');step=e['evidence']['observed_price_step']
            if anchor is not None and event['direction']=='SELL' and event['price']<=anchor-2*step+1e-8:
                s['breaks'].append(now)
            while s['breaks'] and s['breaks'][0]<now-5:s['breaks'].popleft()
            if len(s['breaks'])>=2:
                e['failure_price']=event['price'];changes.append(self._phase(s,'failed',now,'连续主动卖出成交跌破承接区域至少两个观察价位'))
                s['episode']=None;s['breaks'].clear();s['proposal']=None
        changes+=self._advance(s,now)
        return changes

    def _advance(self,s,now):
        e=s['episode']
        if not e:return []
        silent=now-e['last_match']
        if silent>=self.c['resolve_seconds']:
            result=self._phase(s,'resolved',e['last_match']+self.c['resolve_seconds'],'观察窗口内未再满足；未确认操作意图或反向行为')
            s['episode']=None;s['breaks'].clear();s['proposal']=None;return [result]
        if silent>=self.c['cooling_seconds'] and e['phase'] not in ('cooling','observing'):
            return [self._phase(s,'cooling',e['last_match']+self.c['cooling_seconds'],'近期未再满足条件；不等于价格已经反转')]
        return []

    def advance(self,now):
        return [change for s in self.states.values() for change in self._advance(s,now)]

    def stop(self,code,reason,now):
        s=self.states.pop(code,None)
        if s and s['episode']:return [self._phase(s,'interrupted',now,reason)]
        return []

    def stop_all(self,reason,now):
        return [c for code in list(self.states) for c in self.stop(code,reason,now)]
