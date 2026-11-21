"""Keep market capitalization in the original Futu snapshot definitions."""
import math
import time
from .markets import parse_time,is_us


def snapshot_event(row,now=None):
    values={}
    for key in ['prev_close_price','last_price','total_market_val','circular_market_val','issued_shares','outstanding_shares','turnover','volume','turnover_rate','amplitude']:
        value=row.get(key)
        values[key]=value if isinstance(value,(int,float)) and math.isfinite(value) and value>=0 else None
    if not row.get('equity_valid'):
        values['total_market_val']=values['circular_market_val']=None
    try:values['update_timestamp']=parse_time(row['update_time'],row['code'])
    except (KeyError,ValueError,TypeError):values['update_timestamp']=None
    return dict(kind='market_snapshot',code=row['code'],ts=time.time() if now is None else now,
                data=dict(values,listing_date=row.get('listing_date'),update_time=row.get('update_time'),equity_valid=bool(row.get('equity_valid'))))


def optional_number(value):
    try:value=float(value)
    except (TypeError,ValueError):return None
    return value if math.isfinite(value) else None
