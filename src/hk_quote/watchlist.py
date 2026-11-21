"""Durable per-stock desired configuration and worker-confirmed runtime state."""
import json
import re
import sqlite3
import time


def normalize_code(value):
    value=str(value).strip().upper()
    if value.startswith('US.') or (not value.startswith('HK.') and re.fullmatch(r'[A-Z]{1,6}(?:[.-][A-Z0-9]{1,2})?',value)):
        symbol=value.removeprefix('US.')
        if not re.fullmatch(r'[A-Z][A-Z0-9.-]{0,19}',symbol) or '..' in symbol or symbol.endswith(('.', '-')):raise ValueError('请输入有效美股代码，例如 US.QQQ')
        return 'US.'+symbol
    value=value.removeprefix('HK.')
    if not re.fullmatch(r'\d{1,5}',value):raise ValueError('请输入港股代码00700或美股代码US.QQQ')
    return 'HK.'+value.zfill(5)


class Watchlist:
    def __init__(self,database,defaults=(),names=None):
        self.database=str(database)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS watchlist(code TEXT PRIMARY KEY,name TEXT,enabled INTEGER,revision INTEGER,state TEXT,error TEXT,updated_at REAL,warmup_until REAL)')
            if 'deleted' not in {r[1] for r in db.execute('PRAGMA table_info(watchlist)')}:
                db.execute('ALTER TABLE watchlist ADD COLUMN deleted INTEGER NOT NULL DEFAULT 0')
            db.execute('CREATE TABLE IF NOT EXISTS watchlist_meta(key TEXT PRIMARY KEY,value TEXT)')
            if not db.execute("SELECT 1 FROM watchlist_meta WHERE key='initialized'").fetchone():
                for code in defaults:
                    db.execute('INSERT OR IGNORE INTO watchlist(code,name,enabled,revision,state,error,updated_at,warmup_until) VALUES (?,?,1,1,?,?,?,0)',(code,(names or {}).get(code,''),'pending','',time.time()))
                db.execute("INSERT INTO watchlist_meta VALUES ('initialized','1')")

    def connect(self):
        db=sqlite3.connect(self.database,timeout=5);db.row_factory=sqlite3.Row;return db

    def rows(self,include_deleted=False):
        query='SELECT * FROM watchlist'+('' if include_deleted else ' WHERE deleted=0')+' ORDER BY code'
        with self.connect() as db:
            saved=db.execute("SELECT value FROM watchlist_meta WHERE key='futu_groups'").fetchone()
            groups=json.loads(saved[0]) if saved else {}
            return [dict(r,groups=[name for name,codes in groups.items() if r['code'] in codes]) for r in db.execute(query)]

    def add(self,value):
        code=normalize_code(value)
        with self.connect() as db:
            old=db.execute('SELECT deleted FROM watchlist WHERE code=?',(code,)).fetchone()
            if old and not old['deleted']:raise ValueError('该股票已在列表中')
            if old:
                db.execute("UPDATE watchlist SET deleted=0,enabled=0,revision=revision+1,state='stopped',error='',updated_at=?,warmup_until=0 WHERE code=?",(time.time(),code))
            else:
                db.execute("INSERT INTO watchlist(code,name,enabled,revision,state,error,updated_at,warmup_until) VALUES (?, '',0,1,'stopped','',?,0)",(code,time.time()))
        return code

    def desired(self,value,enabled):
        code=normalize_code(value)
        with self.connect() as db:
            row=db.execute('SELECT enabled FROM watchlist WHERE code=? AND deleted=0',(code,)).fetchone()
            if row is None:raise ValueError('股票不在列表中')
            if bool(row['enabled'])==enabled:return
            db.execute('UPDATE watchlist SET enabled=?,revision=revision+1,state=?,error=?,updated_at=?,warmup_until=0 WHERE code=?',
                       (int(enabled),'pending' if enabled else 'stopping','',time.time(),code))

    def remove(self,value):
        code=normalize_code(value)
        with self.connect() as db:
            row=db.execute('SELECT deleted FROM watchlist WHERE code=?',(code,)).fetchone()
            if row is None:raise ValueError('股票不在列表中')
            if row['deleted']:return
            db.execute("UPDATE watchlist SET deleted=1,enabled=0,revision=revision+1,state='stopping',error='',updated_at=?,warmup_until=0 WHERE code=?",(time.time(),code))
            db.execute("DELETE FROM watchlist_meta WHERE key='default_symbol' AND value=?",(code,))

    def set_default(self,value):
        code=normalize_code(value)
        with self.connect() as db:
            if not db.execute('SELECT 1 FROM watchlist WHERE code=? AND deleted=0',(code,)).fetchone():
                raise ValueError('只能设置当前自选股票为默认')
            db.execute("INSERT INTO watchlist_meta(key,value) VALUES ('default_symbol',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(code,))

    def default_symbol(self):
        with self.connect() as db:
            row=db.execute("SELECT w.code FROM watchlist w JOIN watchlist_meta m ON m.value=w.code WHERE m.key='default_symbol' AND w.deleted=0").fetchone()
            if not row:row=db.execute('SELECT code FROM watchlist WHERE deleted=0 ORDER BY code LIMIT 1').fetchone()
            return row['code'] if row else ''

    def acknowledge(self,row,state,error='',warmup_until=0,name=None):
        with self.connect() as db:
            db.execute('UPDATE watchlist SET state=?,error=?,updated_at=?,warmup_until=?,name=COALESCE(?,name) WHERE code=? AND revision=?',
                       (state,error,time.time(),warmup_until,name,row['code'],row['revision']))
