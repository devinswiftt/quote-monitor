"""Reviewed business-channel labels, never identification of underlying investors."""
from functools import lru_cache
from pathlib import Path
import json
import unicodedata

LABELS={'retail':'零售平台渠道','institutional':'机构业务渠道','mixed':'综合渠道','unknown':'待核实'}
NOTICE='标签仅描述券商业务渠道，不识别具体席位的最终客户；个人、机构、资管或转接订单可能共用同一券商。'


def key(name):
    return ''.join(unicodedata.normalize('NFKC',str(name)).split())


@lru_cache(maxsize=1)
def catalog():
    try:
        value=json.loads((Path(__file__).resolve().parents[2]/'config/broker-channels.json').read_text())
        return dict(reviewed_on=value.get('reviewed_on'),profiles={key(name):item for name,item in value.get('profiles',{}).items()})
    except (OSError,ValueError,TypeError):return dict(profiles={})


def classify(name):
    data=catalog();entry=data['profiles'].get(key(name),{})
    category=entry.get('category','unknown')
    if category not in LABELS:category='unknown'
    # Unsupported classifications do not silently become verified labels.
    sources=[dict(title=s.get('title','官方资料'),url=s['url']) for s in entry.get('sources',[]) if isinstance(s,dict) and isinstance(s.get('url'),str) and s['url'].startswith('https://')]
    if category!='unknown' and not sources:category='unknown'
    return dict(category=category,label=LABELS[category],basis=entry.get('basis') or '尚未核实该简称对应的业务渠道，不依据名称、成交量或买卖方向猜测客户身份。',sources=sources,reviewed_on=data.get('reviewed_on'),notice=NOTICE,scope='broker_channel')
