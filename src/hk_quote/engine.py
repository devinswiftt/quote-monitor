"""Deterministic event-time detector shared by live and replay."""
from collections import deque
from datetime import datetime
from zoneinfo import ZoneInfo
from .profile import TurnoverProfile
from .rapid_move import RapidDetector
from .markets import is_us, us_phase, us_period

HK = ZoneInfo("Asia/Hong_Kong")


def timestamp(value):
    # Futu tick timestamps sometimes use a colon before milliseconds.
    value = str(value)
    if value.count(":") == 3:
        pos = value.rfind(":")
        value = value[:pos] + "." + value[pos + 1:]
    dt = datetime.fromisoformat(value)
    return dt.replace(tzinfo=HK).timestamp() if dt.tzinfo is None else dt.timestamp()


def continuous(ts,code="HK"):
    if is_us(code):return us_phase(ts)!='CLOSED'
    dt = datetime.fromtimestamp(ts, HK)
    minute = dt.hour * 60 + dt.minute
    return dt.weekday() < 5 and (570 <= minute < 720 or 780 <= minute < 960)


def trading_seconds(ts):
    """Elapsed continuous trading seconds today; lunch is excluded."""
    dt = datetime.fromtimestamp(ts, HK)
    seconds = dt.hour * 3600 + dt.minute * 60 + dt.second + dt.microsecond / 1e6
    return max(0, min(seconds - 9.5 * 3600, 2.5 * 3600)) + max(0, min(seconds - 13 * 3600, 3 * 3600))


def session(ts,code="HK"):
    if is_us(code):return us_period(ts)
    dt = datetime.fromtimestamp(ts, HK)
    return dt.date(), dt.hour >= 13


class Engine:
    def __init__(self, config):
        self.c = config
        self.states = {}
        self.daily = {}
        self.profiles = {}

    def learn(self, event):
        if event['kind'] == 'tick' and (continuous(event['ts'],event['code']) or event.get('market_session')=='HK_DARK'):
            if self.c.get('rapid_move', {}).get('enabled'):
                profile = self.profiles.setdefault(event['code'], RapidDetector(
                    event['code'], self.c['rapid_move'], self.c['window_seconds']))
                profile.add(event)
                return
            profile = self.profiles.setdefault(event['code'], TurnoverProfile(
                self.c['window_seconds'], self.c.get('profile_seconds', 3600),market='US' if is_us(event['code']) else 'HK'))
            profile.add(event)

    def reset(self):
        self.states.clear()
        for profile in self.profiles.values():
            if isinstance(profile, RapidDetector):profile.reset()

    def drop(self, code):
        self.states.pop(code, None)
        profile = self.profiles.get(code)
        if isinstance(profile, RapidDetector):profile.reset()

    def process(self, event):
        if event['kind'] == 'reset':
            self.reset()
            return None
        code, ts = event['code'], event['ts']
        if event['kind'] == 'day':
            points = self.daily.setdefault(code, deque(maxlen=100))
            if not points or ts >= points[-1]['ts']:
                points.append(event)
            return None
        s = self.states.setdefault(code, dict(ticks=deque(), seen=set(), ids=deque(),
                    start=ts, last=ts, book=None, books=deque(), alerts={}))
        if event['kind'] == 'book':
            if s['book'] is None or ts >= s['book']['ts']:
                s['book'] = event
                s['books'].append(event)
                while s['books'] and s['books'][0]['ts'] < ts - 10:
                    s['books'].popleft()
            return None
        if ts < s['last'] or not (continuous(ts,code) or event.get('market_session')=='HK_DARK'):
            return None
        # Quiet trading is valid data, not evidence of a feed outage.
        if session(ts,code) != session(s['last'],code):
            self.states.pop(code)
            return self.process(event)
        key = event['sequence']
        if key in s['seen']:
            return None
        s['seen'].add(key)
        s['ids'].append((ts, key))
        s['last'] = ts
        self.learn(event)
        if self.c.get('rapid_move', {}).get('enabled'):
            # The joint detector owns a bounded 3-second rolling window; do not
            # scan the legacy 5-minute tick list on every US print.
            while s['ids'] and s['ids'][0][0] < ts-self.c['baseline_seconds']:
                s['seen'].discard(s['ids'].popleft()[1])
            reference_book = next((b for b in reversed(s['books']) if b['ts'] <= ts), None)
            return self.profiles[code].detect(ts, reference_book, self.c['cooldown_seconds'])
        s['ticks'].append(event)
        cutoff = ts - self.c['baseline_seconds']
        while s['ticks'] and s['ticks'][0]['ts'] < cutoff:
            s['ticks'].popleft()
        while s['ids'] and s['ids'][0][0] < cutoff:
            s['seen'].discard(s['ids'].popleft()[1])
        if ts - s['start'] < self.c['warmup_seconds']:
            return None
        boundary = ts - self.c['window_seconds']
        recent = [t for t in s['ticks'] if t['ts'] > boundary]
        history = [t for t in s['ticks'] if t['ts'] <= boundary]
        amount = sum(t['amount'] for t in recent)
        duration = boundary - max(s['start'], cutoff)
        expected = sum(t['amount'] for t in history) / max(duration, 1) * self.c['window_seconds']
        day = next((point for point in reversed(self.daily.get(code, []))
                    if point['ts'] <= boundary and session(point['ts'],code)[0] == session(ts,code)[0]), None)
        day_expected = 0
        if day and not is_us(code) and trading_seconds(day['ts']) > 0:
            day_expected = day['turnover'] / trading_seconds(day['ts']) * self.c['window_seconds']
        reference = max(expected, day_expected)
        calibration = None
        if self.c.get('threshold_mode') == 'percentile':
            calibration = self.profiles[code].estimate(ts,
                self.c.get('profile_quantile', .99), self.c.get('profile_multiplier', 1.2),
                self.c.get('profile_min_samples', 20))
            if calibration is None:
                return None
            threshold = calibration['threshold']
        else:
            threshold = max(self.c['min_amount'], reference * self.c['volume_multiple'])
        if amount < threshold:
            return None
        # Turnover alone is insufficient: require net price progress in the
        # same detection window, before consuming the per-signal cooldown.
        change = recent[-1]['price'] - recent[0]['price']
        first_price = recent[0]['price']
        price_change_pct = change / first_price * 100 if first_price > 0 else None
        min_price_change_pct = self.c.get('min_price_change_pct', 0)
        if min_price_change_pct > 0 and (price_change_pct is None or
                abs(price_change_pct) + 1e-12 < min_price_change_pct):
            return None
        # A zero baseline is possible for thinly traded stocks: the cash floor still applies.
        multiple = amount / reference if reference > 0 else None
        buy = sum(t['amount'] for t in recent if t['direction'] == 'BUY')
        sell = sum(t['amount'] for t in recent if t['direction'] == 'SELL')
        known = buy + sell
        coverage = known / amount if amount else 0
        side = 'BUY' if buy >= sell else 'SELL'
        ratio = max(buy, sell) / known if known else 0
        directional = coverage >= self.c['min_direction_coverage'] and ratio >= self.c['direction_ratio']
        label = side if directional else 'VOLUME'
        if ts - s['alerts'].get(label, float('-inf')) < self.c['cooldown_seconds']:
            return None
        s['alerts'][label] = ts
        book = s['book']
        depth = min(len(book['bid']), len(book['ask'])) if book and 0 <= ts - book['ts'] <= 3 else 0
        previous = next((b for b in reversed(s['books']) if b['ts'] <= boundary), None)
        confirmed = False
        if directional and depth >= 10 and previous and 0 <= boundary - previous['ts'] <= 3:
            field = 'ask' if side == 'BUY' else 'bid'
            old, new = previous[field], book[field]
            if old and new:
                moved = new[0][0] > old[0][0] if side == 'BUY' else new[0][0] < old[0][0]
                confirmed = moved and (change > 0 if side == 'BUY' else change < 0)
        return dict(code=code, ts=ts, signal=label, amount=round(amount, 2),
                    multiple=round(multiple, 2) if multiple is not None else None,
                    threshold=round(threshold, 2), threshold_method='percentile' if calibration else 'legacy',
                    threshold_profile=calibration, threshold_quantile=self.c.get('profile_quantile'),
                    threshold_multiplier=self.c.get('profile_multiplier'), baseline_expected=round(reference, 2),
                    day_turnover=day['turnover'] if day else None,
                    baseline_source='day_and_rolling' if day else 'rolling_only', direction_ratio=round(ratio, 3),
                    coverage=round(coverage, 3), ticks=len(recent), depth=depth,
                    price=event['price'], trigger_sequence=event['sequence'], price_change=change, price_change_pct=price_change_pct,
                    min_price_change_pct=min_price_change_pct, book_confirmed=confirmed,
                    level='强' if confirmed else ('较强' if directional else '关注'))
