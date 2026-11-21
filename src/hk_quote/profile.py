"""Positive turnover windows measured in same-day continuous trading time."""
from collections import deque
from datetime import datetime
from zoneinfo import ZoneInfo
import math

HK = ZoneInfo('Asia/Hong_Kong')
from .markets import NY,us_period


def trading_clock(ts,market="HK"):
    if market=="US":return ts
    """Pause the horizon during lunch; keep calendar days separate."""
    dt = datetime.fromtimestamp(ts, HK)
    seconds = dt.hour*3600 + dt.minute*60 + dt.second + dt.microsecond/1e6
    return ts - min(3600, max(0, seconds - 12*3600))


class TurnoverProfile:
    def __init__(self, window=3, horizon=3600, market="HK"):
        self.market=market
        self.window = window
        self.horizon = horizon
        self.buckets = {}
        self.seen = set()
        self.ids = deque()
        self.day = None

    def add(self, event):
        ts = event['ts']
        day = us_period(ts) if self.market=='US' else datetime.fromtimestamp(ts, HK).date()
        if self.day is not None and day < self.day:
            return
        if day != self.day:
            self.buckets.clear(); self.seen.clear(); self.ids.clear()
            self.day = day
        clock = trading_clock(ts,self.market)
        key = (day, event['sequence'])
        if key in self.seen:
            return
        self.seen.add(key)
        self.ids.append((clock, key))
        bucket = int(clock // self.window)
        self.buckets[bucket] = self.buckets.get(bucket, 0) + event['amount']
        cutoff = clock - self.horizon
        # Bounded out-of-order prints may arrive after a newer book or trade.
        if len(self.ids)>1 and self.ids[-2][0]>clock:
            self.ids = deque(sorted(self.ids))
        while self.ids and self.ids[0][0] < cutoff:
            self.seen.discard(self.ids.popleft()[1])
        self.buckets = {b: value for b, value in self.buckets.items()
                        if (b + 1) * self.window > cutoff}

    def estimate(self, ts, quantile=.99, multiplier=1.2, minimum=20):
        if (us_period(ts) if self.market=='US' else datetime.fromtimestamp(ts, HK).date()) != self.day:
            return None
        clock = trading_clock(ts,self.market)
        boundary = clock - self.window
        values = sorted(value for b, value in self.buckets.items()
                        if clock - self.horizon <= b * self.window
                        and (b + 1) * self.window <= boundary and value > 0)
        if len(values) < minimum:
            return None
        q = values[max(0, math.ceil(quantile * len(values)) - 1)]
        return dict(threshold=q * multiplier, quantile_amount=q, samples=len(values))
