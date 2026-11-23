"""Human-readable exports of persisted notifications."""
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import threading
from .markets import timezone,is_us
EXPORT_LOCK=threading.RLock()

from .instruments import stock_label

LABELS = {'BUY': '疑似集中主动买入', 'SELL': '疑似集中主动卖出', 'VOLUME': '异常成交放大'}


def cell(value):
    return str(value).replace('|', '／').replace('\n', ' ')


def render(rows):
    lines = ['# 港美股异动通知记录', '', '港股使用香港时间、美股使用纽约时间；所有历史通知保留，最新在前。疑似买卖压力不代表已确认主力行为。', '',
             '| 编号 | 时间 | 股票 | 通知 | 成交额 HK$ | 触发门槛 HK$ | 详情 |',
             '| --- | --- | --- | --- | ---: | ---: | --- |']
    count = 0
    for ident, payload in rows:
        a = json.loads(payload)
        when = datetime.fromtimestamp(a['ts'], timezone(a['code'])).strftime('%Y-%m-%d %H:%M:%S')
        if a.get('kind') == 'depth':
            label, amount, threshold, detail = '盘口变化', '—', '—', a['message']
        else:
            label = a.get('signal_label') or LABELS.get(a.get('signal'), a.get('signal', '异动'))
            amount = f"{a['amount']:,.0f}"
            threshold = f"{a['threshold']:,.0f}" if 'threshold' in a else '—'
            multiple = f"{a['multiple']:.1f}倍" if a.get('multiple') is not None else '无有效倍数'
            detail = (f"{a.get('level', '')}；{multiple}；方向集中度 {a.get('direction_ratio', 0):.0%}；"
                      f"方向覆盖率 {a.get('coverage', 0):.0%}；盘口 {a.get('depth', 0)}档")
        if a.get('price') is not None:
            detail += f"；触发成交价 {'US$' if is_us(a['code']) else 'HK$'}{a['price']:.3f}"
            if a.get('price_delta_pct') is not None:
                detail += f"；较上次异动 {a['price_delta']:+.3f} 港元（{a['price_delta_pct']:+.2f}%）"
        broker = a.get('broker_context', {})
        if broker.get('bid') or broker.get('ask'):
            for side, label_side in [('bid', '买盘挂单经纪'), ('ask', '卖盘挂单经纪')]:
                detail += '；' + label_side + '：' + '、'.join(f"{r['name']}[{r['id']}]@{r['position']}档" for r in broker.get(side, []))
            detail += '（非成交归属）'
        lines.append('| ' + ' | '.join(cell(v) for v in (ident, when, stock_label(a['code'], a.get('name')), label, (amount+' USD' if is_us(a['code']) else amount), (threshold+' USD' if is_us(a['code']) else threshold), detail)) + ' |')
        count += 1
    if not count:
        lines += ['', '尚无异动通知。']
    return '\n'.join(lines) + '\n'


def export_connection(db, destination):
    with EXPORT_LOCK:
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        text = render(db.execute('SELECT id,payload FROM alerts ORDER BY id DESC'))
        temporary = destination.with_suffix(destination.suffix + '.tmp')
        temporary.write_text(text, encoding='utf-8')
        temporary.replace(destination)
        return text


def read_history(database, limit=50):
    path = Path(database).resolve()
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
        return render(db.execute('SELECT id,payload FROM alerts ORDER BY id DESC LIMIT ?', (limit,)))
