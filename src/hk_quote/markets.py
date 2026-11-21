"""Market-local dates and supported quote sessions; UTC instants in storage."""
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo

HK=ZoneInfo('Asia/Hong_Kong')
NY=ZoneInfo('America/New_York')


def is_us(code):return str(code).startswith('US.')
def timezone(code):return NY if is_us(code) else HK
def currency(code):return 'USD' if is_us(code) else 'HKD'
def day_bounds(code,date=None,now=None):
    zone=timezone(code)
    day=datetime.strptime(date,'%Y-%m-%d').replace(tzinfo=zone) if date else (now or datetime.now(zone)).astimezone(zone).replace(hour=0,minute=0,second=0,microsecond=0)
    return day.timestamp(),(day+timedelta(days=1)).timestamp()
def us_phase(ts,kind='WHOLE'):
    dt=datetime.fromtimestamp(ts,NY);minute=dt.hour*60+dt.minute
    if dt.weekday()>=5 or kind=='CLOSED':return 'CLOSED'
    close=780 if kind=='MORNING' else 960
    if 240<=minute<570:return 'PRE'
    if 570<=minute<close:return 'REGULAR'
    # Early-close extended sessions depend on the venue; first version pauses safely.
    if kind!='MORNING' and close<=minute<1200:return 'POST'
    return 'CLOSED'
def us_period(ts):
    return datetime.fromtimestamp(ts,NY).date(),{'CLOSED':-1,'PRE':0,'REGULAR':1,'POST':2}[us_phase(ts)]
def parse_time(value,code):
    value=str(value)
    if value.count(':')==3:
        position=value.rfind(':');value=value[:position]+'.'+value[position+1:]
    dt=datetime.fromisoformat(value)
    return dt.replace(tzinfo=timezone(code)).timestamp() if dt.tzinfo is None else dt.timestamp()
