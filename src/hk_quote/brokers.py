"""Broker queue context; never trade attribution."""
import copy
import math


def normalize(frame, side):
    rows = []
    for row in frame.to_dict('records'):
        ident = int(row[f'{side}_broker_id'])
        if ident <= 0:
            continue
        raw = row.get('order_volume')
        try:
            volume = float(raw)
            volume = volume if math.isfinite(volume) and volume >= 0 else None
        except (ValueError, TypeError):
            volume = None
        rows.append(dict(order_volume=volume, id=str(ident).zfill(4), name=str(row[f'{side}_broker_name']),
                         position=int(row[f'{side}_broker_pos'])))
    return rows


class BrokerCache:
    def __init__(self):
        self.items = {}

    def update(self, event):
        self.items[event['code']] = event

    def attach(self, alert):
        result = copy.deepcopy(alert)
        event = self.items.get(alert['code'])
        if not event:
            result['broker_context'] = dict(status='unavailable', note='未采集到经纪队列，非逐笔成交券商')
        else:
            age = alert['ts'] - event['ts']
            result['broker_context'] = dict(status='nearby' if 0 <= age <= 30 else 'stale',
                captured_at=event['ts'], age_seconds=round(age, 3),
                timestamp_basis=event.get('timestamp_basis', 'local_receive'),
                bid=copy.deepcopy(event['bid']), ask=copy.deepcopy(event['ask']),
                note='异动前最近接收的挂单经纪队列，并非该笔成交的实际买卖券商；时间为本机接收时间')
        return result
