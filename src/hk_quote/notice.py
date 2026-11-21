"""One canonical message for the desktop notification and visible web summary."""
from datetime import datetime
from .engine import HK
from .markets import is_us,timezone
from .instruments import stock_label


def make_notice(alert,ident):
    if is_us(alert.get('code')) and alert.get('signal'):
        when=datetime.fromtimestamp(alert['ts'],timezone(alert['code'])).strftime('%m-%d %H:%M:%S ET')
        return dict(text=f"{stock_label(alert['code'],alert.get('name'))} #{ident} · {when}；{alert.get('signal_label') or alert.get('session','')}；成交额 US${alert.get('amount',0):,.2f}；不提供成交券商身份",valid_samples=0,target_samples=0,reconstructed=False)
    p=alert.get('participation') or {}
    if not alert.get('signal') or p.get('status')=='pending' or not p:return None
    parts=[]
    if alert.get('signal_label'):parts.append(alert['signal_label'])
    changes=p.get('changes',[])
    parts.append('明显变化：'+('、'.join(r['name']+' '+r['change'] for r in changes[:3]) or '未观察到／基线不足'))
    for side,label in [('bid','买1在场'),('ask','卖1在场')]:
        if p.get('scope')!='best_level':label='历史买盘在场' if side=='bid' else '历史卖盘在场'
        parts.append(label+'：'+('、'.join(r['name']+f" {r['presence_ratio']:.0%}" for r in p.get(side,[])[:3]) or '无有效在场记录'))
    parts.append('成交线索：'+(p.get('trade_clues') or {}).get('reason','未保存／证据不足'))
    parts.append(f"有效采样 {p.get('valid_samples',0)}/{p.get('target_samples',21)}；比例为采样出现率，非成交概率或成交归属")
    when=datetime.fromtimestamp(alert['ts'],HK).strftime('%m-%d %H:%M:%S HKT')
    return dict(text=f"{stock_label(alert['code'],alert.get('name'))} #{ident} · {when}；"+'；'.join(parts),
                valid_samples=p.get('valid_samples',0),target_samples=p.get('target_samples',21),reconstructed=False)


def with_notice(alert,ident):
    value=dict(alert)
    if not value.get('notification_summary'):
        notice=make_notice(value,ident)
        if notice:
            notice['reconstructed']=True
            value['notification_summary']=notice
    return value
