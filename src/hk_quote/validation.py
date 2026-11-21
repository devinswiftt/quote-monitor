"""Day replay and reconstruction of fixed-time broker participation profiles."""
import argparse
from datetime import datetime
import json
from pathlib import Path
from .participation import summarize
from .engine import HK
from .reconstruction import reconstruct


def validate(database,date,destination,update=False):
    results=reconstruct(database,date,update=update)
    reconstructed=[dict(r['alert'],participation=r['profile']) for r in results]
    summary=summarize(reconstructed)
    text=f'# {date} 异动期间券商参与画像回放\n\n每次异动前后各10秒，每秒取最近5秒内的经纪推送；缺失不补造。仅统计买1/卖1，比较触发前70至11秒常态与前后10秒异动。成交线索仅为低置信被动方候选，不能确认成交身份或券商股数。\n\n共 {len(results)} 次异动，{sum(r["profile"]["valid_samples"]>0 for r in results)} 次具有有效采样。采样覆盖不足会影响排名。\n\n## 当日反复出现的券商\n\n|股票|一侧|券商|编号|在场异动次数|明显变化次数|低置信候选次数|\n|---|---|---|---|---|---|---|\n'
    for r in summary:text+=f"|{r['code']}|{'买盘' if r['side']=='bid' else '卖盘'}|{r['name']}|{','.join(r['ids'])}|{r['alerts']}|{r['changed_alerts']}|{r['clue_alerts']}|\n"
    text+='\n## 逐次异动\n\n'
    for r in results:
        a,p=r['alert'],r['profile'];text+=f"\n### #{r['id']} {a.get('name') or a['code']} {datetime.fromtimestamp(a['ts'],HK):%H:%M:%S}\n\n有效采样 {p['valid_samples']}/21（{p['coverage']:.0%}）。\n\n"
        text+=f"常态采样 {p['baseline']['valid_samples']}/60；成交线索：{p['trade_clues']['reason']}。\n\n"
        for v in p['changes']:text+=f"- {v['name']}[{','.join(v['ids'])}] {v['change']}：{v['reason']}\n"
        for side,label in [('bid','买1'),('ask','卖1')]:
            text+=label+'：'+'；'.join(f"{v['name']}[{','.join(v['ids'])}] 出现 {v['presence_ratio']:.0%}，平均 {v['mean_queue_entries']:.2f} 个队列位置" for v in p[side])+'\n\n'
    destination=Path(destination);destination.parent.mkdir(parents=True,exist_ok=True)
    temporary=destination.with_suffix('.tmp');temporary.write_text(text);temporary.replace(destination)
    destination.with_suffix('.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
    return str(destination)


def main():
    p=argparse.ArgumentParser();p.add_argument('--database',default='data/quotes.sqlite3');p.add_argument('--date',required=True);p.add_argument('--output',required=True);p.add_argument('--update',action='store_true');a=p.parse_args();print(validate(a.database,a.date,a.output,a.update))


if __name__=='__main__':main()
