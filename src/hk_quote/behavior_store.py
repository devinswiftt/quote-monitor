"""Persistent episodes and links; raw alerts remain unchanged."""
from copy import deepcopy
import json
import sqlite3
from .behavior import BehaviorEngine, LABELS, PHASES


def initialize(db):
    db.execute('CREATE TABLE IF NOT EXISTS behavior_events (id INTEGER PRIMARY KEY,event_key TEXT UNIQUE,code TEXT,started REAL,updated REAL,payload TEXT)')
    db.execute('CREATE INDEX IF NOT EXISTS behavior_date ON behavior_events(started)')
    db.execute('CREATE TABLE IF NOT EXISTS behavior_links (behavior_id INTEGER,alert_id INTEGER,PRIMARY KEY(behavior_id,alert_id))')


def read_behaviors(db,start,end,code=None):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='behavior_events'").fetchone():return []
    sql='SELECT id,payload FROM behavior_events WHERE started<? AND updated>=?'
    args=[end,start]
    if code:sql+=' AND code=?';args.append(code)
    rows=[]
    for ident,payload in db.execute(sql+' ORDER BY started DESC',args):
        value=dict(json.loads(payload),id=ident)
        value['alert_ids']=[r[0] for r in db.execute('SELECT alert_id FROM behavior_links WHERE behavior_id=? ORDER BY alert_id',(ident,))]
        value['signals']=[dict(json.loads(p),id=aid) for aid,p in db.execute('SELECT a.id,a.payload FROM alerts a JOIN behavior_links l ON a.id=l.alert_id WHERE l.behavior_id=? ORDER BY a.id',(ident,))]
        value['signals']=[{k:a.get(k) for k in ('id','ts','signal','amount','price','threshold')} for a in value['signals']]
        rows.append(value)
    return rows


class BehaviorMonitor:
    def __init__(self,store,config=None,notify=None,source='live'):
        self.store=store;self.db=store.db;initialize(self.db);self.db.commit()
        self.engine=BehaviorEngine(config);self.notify=notify;self.source=source
        self.profiles={};self.notified={}
        if source=='live':
            for ident,payload in self.db.execute("SELECT id,payload FROM behavior_events WHERE event_key LIKE 'live:%'").fetchall():
                value=json.loads(payload)
                if value['phase'] not in ('resolved','failed','interrupted'):
                    value.update(phase='interrupted',status_reason='监听重启，连续证据中断')
                    value['history'].append(dict(ts=value['updated_at'],phase='interrupted',type=value['type'],reason=value['status_reason']))
                    self.db.execute('UPDATE behavior_events SET payload=? WHERE id=?',(json.dumps(value,ensure_ascii=False),ident))
            self.db.commit()

    def _save(self,value,participation,now):
        record=deepcopy(value);key=self.source+':'+record['event_key']
        profile=self.profiles.get(key)
        terminal=record['phase'] in ('resolved','failed','interrupted')
        if not profile or profile.get('status')=='pending':
            if terminal or now>=record['started_at']+11:
                signal={'DUMP':'SELL','LIFT':'BUY','SUPPORT':'SELL'}[record['history'][0]['type']]
                profile=participation.analyze(dict(code=record['code'],signal=signal),record['started_at'],3)
                if terminal and now<record['started_at']+11:profile['interrupted']='行为观察提前结束'
            else:profile=dict(status='pending',version=2,valid_samples=0)
            self.profiles[key]=profile
        record.update(source=self.source,participation=profile)
        self.db.execute('INSERT INTO behavior_events(event_key,code,started,updated,payload) VALUES (?,?,?,?,?) ON CONFLICT(event_key) DO UPDATE SET updated=excluded.updated,payload=excluded.payload',
            (key,record['code'],record['started_at'],record['updated_at'],json.dumps(record,ensure_ascii=False)))
        ident=self.db.execute('SELECT id FROM behavior_events WHERE event_key=?',(key,)).fetchone()[0]
        self.db.execute("INSERT OR IGNORE INTO behavior_links SELECT ?,id FROM alerts WHERE json_extract(payload,'$.code')=? AND json_extract(payload,'$.signal') IS NOT NULL AND json_extract(payload,'$.ts')>=? AND json_extract(payload,'$.ts')<=?",
            (ident,record['code'],record['started_at']-3,record['updated_at']+3))
        self.db.commit()
        history=record['history'][-1]
        token=(history['ts'],history['phase'],history['type'])
        # Observations and metric-only refreshes never produce desktop notifications.
        confirmed=any(h['phase']=='confirmed' for h in record['history'])
        if self.notify and confirmed and record['phase'] in ('confirmed','ongoing','cooling','failed','resolved') and self.notified.get(key)!=token:
            self.notified[key]=token;self.notify(dict(record,id=ident))
        if terminal:self.profiles.pop(key,None);self.notified.pop(key,None)
        return ident

    def status(self,code,now):
        s=self.engine.states.get(code)
        if not self.engine.c['enabled']:return dict(state='off',message='行为监控未启用')
        if not s:return dict(state='warming',message='等待行情和连续采样')
        if now-s['start']<self.engine.c['warmup_seconds']:
            return dict(state='warming',message='行为监控预热中')
        samples={}
        for window,profile in s['profiles'].items():
            value=profile.estimate(now,.75,1.2,1)
            samples[window]=value['samples'] if value else 0
        if max(samples.values(),default=0)<self.engine.c['min_profile_samples']:
            return dict(state='collecting',message='行为监控动态基线采样中',samples=samples)
        book=s['books'][-1] if s['books'] else None
        if not book or now-book['ts']>3:
            return dict(state='awaiting_book',message='行为监控等待新鲜盘口佐证',samples=samples)
        if min(len(book['bid']),len(book['ask']))<2:
            return dict(state='awaiting_depth',message='盘口不足2档，暂停行为确认',samples=samples)
        return dict(state='ready',message='行为监控采样就绪',samples=samples)

    def process(self,event,participation):
        return [self._save(v,participation,event['ts']) for v in self.engine.process(event)]

    def poll(self,now,participation):
        values=self.engine.advance(now)
        for s in self.engine.states.values():
            record=s['episode']
            if record:
                key=self.source+':'+record['event_key']
                if self.profiles.get(key,{}).get('status')=='pending' and now>=record['started_at']+11:
                    values.append(record)
        for value in values:self._save(value,participation,now)

    def stop(self,code,reason,now,participation):
        existed=code in self.engine.states
        for value in self.engine.stop(code,reason,now):self._save(value,participation,now)
        if existed and self.source=='live':
            self.store.event(now,dict(kind='behavior_reset',code=code,ts=now,reason=reason))
            self.db.commit()

    def stop_all(self,reason,now,participation):
        for code in list(self.engine.states):self.stop(code,reason,now,participation)

    def link_alert(self,ident,alert):
        rows=self.db.execute("SELECT id,payload FROM behavior_events WHERE code=? AND started<=? AND updated>=? AND event_key LIKE 'live:%'",
            (alert['code'],alert['ts']+3,alert['ts']-3)).fetchall()
        suppress=False
        for bid,payload in rows:
            value=json.loads(payload)
            self.db.execute('INSERT OR IGNORE INTO behavior_links VALUES (?,?)',(bid,ident))
            suppress |= value['phase'] in ('confirmed','ongoing')
        self.db.commit();return suppress

    def linked_confirmed(self,ident):
        for payload, in self.db.execute('SELECT e.payload FROM behavior_events e JOIN behavior_links l ON e.id=l.behavior_id WHERE l.alert_id=?',(ident,)):
            if any(h['phase']=='confirmed' for h in json.loads(payload)['history']):return True
        return False
