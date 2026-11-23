"""Filtered, anchored pagination; new alerts do not shift historical pages."""
import json
import math
from .markets import day_bounds
from .notice import with_notice
from .watchlist import normalize_code


def alert_page(db,args):
    page=max(1,int(args.get('page',['1'])[0]));size=int(args.get('page_size',['20'])[0])
    if size not in (20,50,100):raise ValueError('无效分页大小')
    newest=db.execute('SELECT COALESCE(MAX(id),0) FROM alerts').fetchone()[0]
    anchor=max(0,min(newest,int(args.get('anchor',[str(newest)])[0])))
    has_behaviors=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='behavior_events'").fetchone() is not None
    newest_behavior=db.execute('SELECT COALESCE(MAX(id),0) FROM behavior_events').fetchone()[0] if has_behaviors else 0
    behavior_anchor=max(0,min(newest_behavior,int(args.get('behavior_anchor',[str(newest_behavior)])[0])))
    source="SELECT id,payload,'alert' AS entry_type FROM alerts WHERE id<=?"
    values=[anchor]
    if has_behaviors:
        source+=" UNION ALL SELECT id,json_set(payload,'$.ts',started,'$.kind',json_extract(payload,'$.type')),'behavior' FROM behavior_events WHERE id<=?"
        values.append(behavior_anchor)
    cte='WITH journal AS ('+source+') '
    where=['1=1']
    code=args.get('symbol',[''])[0]
    if code:
        where.append("json_extract(payload,'$.code')=?");values.append(normalize_code(code))
    signal=args.get('signal',[''])[0]
    if signal:
        if signal not in ('BUY','SELL','VOLUME','depth','DUMP','SUPPORT','LIFT','trade','behavior'):raise ValueError('无效信号')
        if signal=='trade':
            where.append("entry_type='alert' AND COALESCE(json_extract(payload,'$.kind'),json_extract(payload,'$.signal')) IN ('BUY','SELL','VOLUME')")
        elif signal=='behavior':
            where.append("entry_type='behavior'")
        else:
            where.append("COALESCE(json_extract(payload,'$.kind'),json_extract(payload,'$.signal'))=?");values.append(signal)
    date=args.get('date',[''])[0]
    if date:
        if code:
            begin,finish=day_bounds(normalize_code(code),date)
            where.extend(["json_extract(payload,'$.ts')>=?","json_extract(payload,'$.ts')<?"]);values.extend([begin,finish])
        else:
            hk_begin,hk_end=day_bounds('HK',date);us_begin,us_end=day_bounds('US.QQQ',date)
            where.append("((json_extract(payload,'$.code') LIKE 'US.%' AND json_extract(payload,'$.ts')>=? AND json_extract(payload,'$.ts')<?) OR (json_extract(payload,'$.code') NOT LIKE 'US.%' AND json_extract(payload,'$.ts')>=? AND json_extract(payload,'$.ts')<?))")
            values.extend([us_begin,us_end,hk_begin,hk_end])
    search=args.get('search',[''])[0].strip()
    if len(search)>200:raise ValueError('搜索内容过长')
    if search:
        where.append("EXISTS(SELECT 1 FROM json_tree(journal.payload) WHERE type='text' AND instr(lower(CAST(value AS TEXT)),lower(?))>0)");values.append(search)
    clause=' WHERE '+' AND '.join(where)
    total=db.execute(cte+'SELECT COUNT(*) FROM journal'+clause,values).fetchone()[0]
    pages=max(1,math.ceil(total/size));page=min(page,pages)
    rows=db.execute(cte+"SELECT id,payload,entry_type FROM journal"+clause+" ORDER BY json_extract(payload,'$.ts') DESC,id DESC,entry_type DESC LIMIT ? OFFSET ?",values+[size,(page-1)*size]).fetchall()
    entries=[]
    for ident,payload,entry_type in rows:
        record=json.loads(payload)
        if entry_type=='alert':
            related=[]
            if has_behaviors:
                related=[dict(id=i,type=kind) for i,kind in db.execute("SELECT b.id,json_extract(b.payload,'$.type') FROM behavior_events b JOIN behavior_links l ON b.id=l.behavior_id WHERE l.alert_id=? AND b.id<=? ORDER BY b.id",(ident,behavior_anchor))]
            entries.append(dict(with_notice(record,ident),id=ident,entry_type='alert',related_behaviors=related))
            continue
        record['id']=ident
        record['alert_ids']=[row[0] for row in db.execute('SELECT alert_id FROM behavior_links WHERE behavior_id=? ORDER BY alert_id',(ident,))]
        record['signals']=[dict(json.loads(p),id=i) for i,p in db.execute('SELECT a.id,a.payload FROM alerts a JOIN behavior_links l ON a.id=l.alert_id WHERE l.behavior_id=? ORDER BY a.id',(ident,))]
        entries.append(dict(id='B'+str(ident),entry_type='behavior',code=record['code'],ts=record['started_at'],kind=record['type'],behavior=record))
    return dict(alerts=entries,total=total,
                pagination=dict(page=page,page_size=size,pages=pages,anchor=anchor,newest_id=newest,behavior_anchor=behavior_anchor))
