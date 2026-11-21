"""Hong Kong continuous sessions, verified against the Futu trading calendar."""
from datetime import datetime
import json
from pathlib import Path
from .engine import HK


class MarketSession:
    def __init__(self, path='data/trading-calendar.json'):
        self.path = Path(path)
        try:
            self.days = json.loads(self.path.read_text())
        except (OSError, ValueError):
            self.days = {}

    def update(self, date, rows):
        kind = next((r['trade_date_type'] for r in rows if r['time'] == date), 'CLOSED')
        if kind not in ('WHOLE', 'MORNING', 'AFTERNOON', 'CLOSED'):
            raise ValueError('未知交易日类型：' + str(kind))
        self.days[date] = kind
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix('.tmp')
        temp.write_text(json.dumps(self.days))
        temp.replace(self.path)

    def status(self, now=None):
        now = (now or datetime.now(HK)).astimezone(HK)
        date = now.strftime('%Y-%m-%d')
        minute = now.hour * 60 + now.minute
        kind = self.days.get(date)
        if now.weekday() >= 5 or kind == 'CLOSED':
            return False, '港股休市；网页可查看历史数据'
        phase=self.phase(now)
        if phase not in ('CLOSED','BREAK'):
            return True, phase if kind else '等待确认港股交易日历'
        return False, '港股休市或午休；网页可查看历史数据'

    def phase(self,now=None):
        now=(now or datetime.now(HK)).astimezone(HK)
        kind=self.days.get(now.strftime('%Y-%m-%d'))
        if now.weekday()>=5 or kind=='CLOSED':return 'CLOSED'
        minute=now.hour*60+now.minute
        if kind!='AFTERNOON' and 540<=minute<570:return 'PRE_AUCTION'
        if kind!='AFTERNOON' and 570<=minute<720:return 'CONTINUOUS'
        if kind=='MORNING':
            if 720<=minute<730:return 'CLOSE_AUCTION'
            if minute==730:return 'AUCTION_SETTLING'
        elif kind in (None,'WHOLE','AFTERNOON'):
            if 780<=minute<960:return 'CONTINUOUS'
            if 960<=minute<970:return 'CLOSE_AUCTION'
            if minute==970:return 'AUCTION_SETTLING'
        return 'BREAK' if kind!='MORNING' and 720<=minute<780 else 'CLOSED'
