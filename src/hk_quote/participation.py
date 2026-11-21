"""Best-level broker presence, baseline changes, and conservative trade clues."""
from collections import defaultdict, deque
from .attribution import Attribution

VERSION = 2


class Participation:
    def __init__(self):
        self.events = defaultdict(deque)
        self.clues = Attribution()

    def observe(self, received, event):
        self.clues.observe(received, event)
        if event['kind'] == 'reset':
            self.events.clear()
            return
        if event['kind'] != 'broker' or event.get('source') != 'push':
            return
        q = self.events[event['code']]
        q.append((received, event))
        while q and q[0][0] < received - 180:
            q.popleft()

    @staticmethod
    def sample(snapshots, targets):
        result = []
        for target in targets:
            candidates = [(at, e) for at, e in snapshots if at <= target and target-at <= 5]
            result.append(candidates[-1][1] if candidates else None)
        return result

    @staticmethod
    def grouped(samples, side):
        values = {}
        for event in samples:
            if event is None:
                continue
            groups = defaultdict(list)
            for row in event[side]:
                if row['position'] == 1:
                    groups[row['name']].append(row)
            for name, rows in groups.items():
                v = values.setdefault(name, dict(name=name, ids=set(), present=0, entries=0))
                v['ids'].update(r['id'] for r in rows)
                v['present'] += 1
                v['entries'] += len(rows)
        return values

    def analyze(self, alert, received, window=3):
        snapshots = list(self.events[alert['code']])
        samples = self.sample(snapshots, [received+i for i in range(-10, 11)])
        baseline = self.sample(snapshots, [received+i for i in range(-70, -10)])
        valid = sum(e is not None for e in samples)
        base_valid = sum(e is not None for e in baseline)
        enough = valid >= 10 and base_valid >= 30
        result = dict(version=VERSION, scope='best_level',
            status='ready' if valid >= 17 else ('partial' if valid else 'unavailable'),
            sample_interval_seconds=1, window_before_seconds=10, window_after_seconds=10,
            target_samples=21, valid_samples=valid, coverage=valid/21,
            baseline=dict(target_samples=60, valid_samples=base_valid, coverage=base_valid/60,
                          window_before_seconds=[70,11], sufficient=enough),
            change_rules=dict(min_baseline_samples=30, min_event_samples=10,
                              min_presence_delta=.20, min_present_samples=3),
            timestamp_basis='local_receive', bid=[], ask=[], changes=[],
            note='仅买1/卖1；异动前70至11秒为常态对照，前后各10秒为异动窗口。每秒取最近5秒内推送；缺失不计入分母。变化是观察规则，不是成交概率。')
        trigger = self.sample(snapshots, [received])[0]
        for side in ('bid', 'ask'):
            current = self.grouped(samples, side)
            normal = self.grouped(baseline, side)
            for name in sorted(set(current) | set(normal)):
                a = current.get(name, dict(ids=set(), present=0, entries=0))
                b = normal.get(name, dict(ids=set(), present=0, entries=0))
                ratio = a['present']/valid if valid else 0
                base_ratio = b['present']/base_valid if base_valid else None
                mean = a['entries']/valid if valid else 0
                base_mean = b['entries']/base_valid if base_valid else None
                delta = ratio-base_ratio if base_ratio is not None else None
                instant = [r for r in (trigger or {}).get(side, []) if r['position']==1 and r['name']==name]
                if a['present']:
                    result[side].append(dict(name=name, ids=sorted(a['ids']), present_samples=a['present'],
                        presence_ratio=ratio, best_level_ratio=ratio, mean_queue_entries=mean,
                        mean_best_position=1, trigger_queue_entries=len(instant), baseline_ratio=base_ratio,
                        baseline_mean_queue_entries=base_mean, presence_delta=delta))
                change = None
                if enough:
                    if delta >= .20-1e-9 and a['present'] >= 3:
                        change = '新出现' if not b['present'] else '出现增加'
                    elif delta <= -.20+1e-9 and b['present'] >= 3:
                        change = '退出最优档' if not a['present'] else '出现减少'
                    elif a['present'] >= 3 and b['present'] >= 3 and abs(mean-base_mean) >= max(1, base_mean*.5):
                        change = '队列条目增加' if mean > base_mean else '队列条目减少'
                if change:
                    result['changes'].append(dict(name=name, ids=sorted(a['ids'] | b['ids']), side=side,
                        change=change, baseline_ratio=base_ratio, presence_ratio=ratio, presence_delta=delta,
                        baseline_mean_queue_entries=base_mean, mean_queue_entries=mean,
                        reason=f'最优档出现比例 {base_ratio:.0%} → {ratio:.0%}；平均队列条目 {base_mean:.2f} → {mean:.2f}'))
            result[side].sort(key=lambda r: (-r['presence_ratio'], -r['mean_queue_entries'], r['name']))
        result['changes'].sort(key=lambda r: (-abs(r['presence_delta']), r['side'], r['name']))
        result['trade_clues'] = self.clues.infer(alert, received, window)
        return result


def summarize(alerts):
    groups = {}
    eligible = defaultdict(int)
    for alert in alerts:
        p = alert.get('participation') or {}
        if p.get('version') != VERSION or p.get('status') not in ('ready','partial'):
            continue
        eligible[alert['code']] += 1
        changed = {(r['side'],r['name']):r for r in p.get('changes', [])}
        for side in ('bid','ask'):
            # Include brokers which exited; they have no event-window presence.
            rows = {r['name']:r for r in p.get(side, [])}
            for r in p.get('changes', []):
                if r['side']==side: rows.setdefault(r['name'],r)
            for name,row in rows.items():
                key = (alert['code'],side,name)
                v = groups.setdefault(key,dict(code=alert['code'],side=side,name=name,ids=set(),alerts=0,
                    changed_alerts=0,clue_alerts=0,buy_alerts=0,sell_alerts=0))
                v['ids'].update(row['ids'])
                if (side,name) in changed:v['ids'].update(changed[(side,name)]['ids'])
                if row['presence_ratio']>0:
                    v['alerts'] += 1
                    v['buy_alerts'] += alert.get('signal')=='BUY'
                    v['sell_alerts'] += alert.get('signal')=='SELL'
                v['changed_alerts'] += (side,name) in changed
                clues=p.get('trade_clues',{})
                passive='ask' if alert.get('signal')=='BUY' else 'bid'
                if side==passive:
                    v['clue_alerts'] += any(c['name']==name for c in clues.get('candidates',[]))
    return [dict(v,ids=sorted(v['ids']),eligible_alerts=eligible[v['code']]) for v in
            sorted(groups.values(),key=lambda r:(-r['changed_alerts'],-r['alerts'],r['code'],r['side'],r['name']))]
