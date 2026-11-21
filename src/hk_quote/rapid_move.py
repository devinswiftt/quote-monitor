"""Causal rolling-window volume AND price-progress detector.

Samples are finalized once per event-time second, using the same rolling
window as detection. No future prints, zero filling, or directional guesses.
"""
from collections import deque
import math
from .markets import is_us, us_period
from datetime import datetime
from zoneinfo import ZoneInfo

STRATEGY = 'volume_price_v2'
HK = ZoneInfo('Asia/Hong_Kong')


def phase_key(code, ts):
    if is_us(code):
        return us_period(ts)
    d = datetime.fromtimestamp(ts, HK)
    return d.date(), d.hour >= 13


def quantile(values, q):
    values = sorted(values)
    return values[max(0, math.ceil(q * len(values)) - 1)]


def motion(ticks, window=3):
    # Use interval closes to suppress print-to-print bid/ask bounce. Keep the
    # actual endpoints so a final retracement cannot disappear in smoothing.
    raw=list(ticks)
    bins={}
    spacing=max(.25, window/12)
    for t in raw:bins[int(t['ts']/spacing)]=t
    sampled=[raw[0]] if raw else []
    sampled.extend(t for t in bins.values() if not sampled or t['ts']>sampled[0]['ts'])
    ticks=sampled
    prices = [t['price'] for t in ticks]
    if len(prices) < 2 or prices[0] <= 0:
        return None
    differences = [b-a for a,b in zip(prices, prices[1:])]
    steps = [abs(d) for d in differences if abs(d) > 1e-10]
    path = sum(steps)
    change = prices[-1]-prices[0]
    net = abs(change)
    return dict(change=change, change_pct=change/prices[0]*100,
                efficiency=net/path if path else 0,
                steps=len(steps), largest_step_share=max(steps)/path if path else 1,
                span=ticks[-1]['ts']-ticks[0]['ts'],
                range_retention=net/(max(prices)-min(prices)) if max(prices)>min(prices) else 0)


class RapidProfile:
    def __init__(self, code, config, window=3):
        self.code=code; self.c=config; self.window=window
        self.horizon=config.get('profile_seconds',900)
        self.key=None; self.recent=deque(); self.samples=deque()
        self.seen=set(); self.ids=deque(); self.amount=0.; self.last=None
        self.started=None; self.alerts={}; self.cache=None; self.cache_key=None

    def reset(self):
        self.recent.clear(); self.amount=0.; self.last=None; self.started=None
        self.cache=None; self.cache_key=None

    def add(self, event):
        ts=event['ts']; key=phase_key(self.code,ts)
        if self.key is not None and key < self.key:return
        if key != self.key:
            self.reset(); self.samples.clear(); self.seen.clear(); self.ids.clear()
            self.alerts.clear(); self.key=key
        if self.last is not None and ts < self.last:return
        seq=str(event['sequence'])
        if seq in self.seen:return
        self.seen.add(seq); self.ids.append((ts,seq))
        while self.ids and self.ids[0][0] < ts-self.horizon:
            self.seen.discard(self.ids.popleft()[1])
        # Close the previous second BEFORE adding any of this second's prints.
        if self.last is not None and int(ts)>int(self.last) and self.recent:
            m=motion(self.recent,self.window)
            if m and m['span'] >= max(self.c.get('min_span_seconds',1),self.window*.5):
                self.samples.append((self.last,self.amount,abs(m['change_pct'])))
        while self.samples and self.samples[0][0] < ts-self.horizon:
            self.samples.popleft()
        while self.recent and self.recent[0]['ts'] <= ts-self.window:
            self.amount-=self.recent.popleft()['amount']
        self.recent.append(event); self.amount+=event['amount']; self.last=ts
        if self.started is None:self.started=ts

    def estimate(self, ts, *unused):
        if self.key != phase_key(self.code,ts):return None
        # Cache only within the same second. All baseline windows finish before
        # the detection window begins, including cached estimates.
        cache_key=(int(ts),self.key)
        if self.cache_key==cache_key:return self.cache
        end=int(ts)-self.window
        samples=[s for s in self.samples if ts-self.horizon <= s[0] <= end]
        self.cache_key=cache_key
        if len(samples)<self.c.get('min_samples',60):
            self.cache=None;return None
        amount_q=quantile([s[1] for s in samples],self.c.get('amount_quantile',.95))
        move_q=quantile([s[2] for s in samples],self.c.get('price_quantile',.99))
        self.cache=dict(threshold=amount_q*self.c.get('amount_multiplier',1.1),
                        quantile_amount=amount_q,samples=len(samples),
                        price_threshold_pct=move_q*self.c.get('price_multiplier',1.25),
                        price_quantile_pct=move_q,
                        baseline_start=samples[0][0],baseline_end=samples[-1][0],
                        mean_amount=sum(s[1] for s in samples)/len(samples),
                        window_seconds=self.window, sampling='rolling_once_per_second')
        return self.cache

    def detect(self, ts, book=None, cooldown=60):
        if self.started is None or ts-self.started < self.c.get('warmup_seconds',180):return None
        baseline=self.estimate(ts)
        if not baseline or self.amount < baseline['threshold']:return None
        m=motion(self.recent,self.window)
        if not m or m['span']<max(self.c.get('min_span_seconds',1),self.window*.5):return None
        # Reject a solitary jump, bid/ask bouncing, and a move that retraced.
        if (m['steps'] < self.c.get('min_price_steps',3) or
            m['efficiency'] < self.c.get('min_efficiency',.8) or
            m['largest_step_share'] > self.c.get('max_step_share',.6) or
            m['range_retention'] < self.c.get('min_range_retention',.8)):return None
        spread_pct=None
        if book and 0<=ts-book['ts']<=self.window and book.get('bid') and book.get('ask'):
            bid,ask=book['bid'][0][0],book['ask'][0][0]
            if 0 < bid < ask:spread_pct=(ask-bid)/((ask+bid)/2)*100
        threshold=max(baseline['price_threshold_pct'],
                      (spread_pct or 0)*self.c.get('spread_multiple',2))
        # No fixed percentage floor. Must strictly exceed the learned noise
        # and, when available, the contemporaneous bid/ask spread floor.
        if abs(m['change_pct']) <= threshold+1e-12:return None
        side='BUY' if m['change']>0 else 'SELL'
        if ts-self.alerts.get(side,float('-inf'))<cooldown:return None
        self.alerts[side]=ts
        buy=sum(t['amount'] for t in self.recent if t.get('direction')=='BUY')
        sell=sum(t['amount'] for t in self.recent if t.get('direction')=='SELL')
        known=buy+sell
        depth=min(len(book['bid']),len(book['ask'])) if book and 0<=ts-book['ts']<=self.window else 0
        evidence=dict(m, price_threshold_pct=threshold,baseline_price_threshold_pct=baseline['price_threshold_pct'],
                      spread_pct=spread_pct,spread_available=spread_pct is not None,
                      price_quantile=self.c.get('price_quantile',.99),price_multiplier=self.c.get('price_multiplier',1.25),
                      min_efficiency=self.c.get('min_efficiency',.8))
        return dict(code=self.code,ts=ts,signal=side,strategy=STRATEGY,
                    signal_label='放量快速拉升' if side=='BUY' else '放量快速下跌',
                    amount=round(self.amount,2),threshold=round(baseline['threshold'],2),
                    multiple=round(self.amount/baseline['mean_amount'],2) if baseline['mean_amount'] else None,
                    threshold_method='rolling_joint',threshold_profile=baseline,
                    threshold_quantile=self.c.get('amount_quantile',.95),threshold_multiplier=self.c.get('amount_multiplier',1.1),
                    window_seconds=self.window,baseline_expected=baseline['mean_amount'],baseline_source='same_phase_rolling',day_turnover=None,
                    price=self.recent[-1]['price'],trigger_sequence=self.recent[-1]['sequence'],
                    price_change=m['change'],price_change_pct=m['change_pct'],motion=evidence,
                    ticks=len(self.recent),coverage=known/self.amount if self.amount else 0,
                    direction_ratio=max(buy,sell)/known if known else 0,
                    depth=depth,book_confirmed=False,level='量价共振')


class RapidDetector:
    """Multiple observation windows, one shared directional notification cooldown."""
    def __init__(self,code,config,window=3):
        windows=config.get('windows',[window])
        self.profiles=[RapidProfile(code,config,w) for w in windows]
        self.alerts={};self.key=None;self.c=config
    def reset(self):
        for p in self.profiles:p.reset()
    def add(self,event):
        key=phase_key(event['code'],event['ts'])
        if key!=self.key:
            self.alerts.clear();self.key=key
        for p in self.profiles:p.add(event)
    def estimate(self,ts,*unused):
        return self.profiles[0].estimate(ts)
    def detect(self,ts,book=None,cooldown=60):
        candidates=[]
        for p in self.profiles:
            a=p.detect(ts,book,cooldown)
            if a:candidates.append(a)
        # One alert even if the same push meets more than one time scale.
        candidates.sort(key=lambda a:abs(a['price_change_pct'])/max(a['motion']['price_threshold_pct'],1e-9),reverse=True)
        for a in candidates:
            if ts-self.alerts.get(a['signal'],float('-inf'))<cooldown:continue
            self.alerts[a['signal']]=ts
            return a
        return None
