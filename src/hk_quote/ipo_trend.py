"""Track each stock's listing-day CCASS top ten against later snapshots."""
from datetime import date, datetime
import json
from pathlib import Path
import re
import sqlite3

from .ccass_cli import fetch
from .engine import HK

REFERENCE_FILE = Path('config/ipo-reference.json')
EXCLUDED = 'A00005'


def reference_data():
    if not REFERENCE_FILE.exists():
        return {}
    return json.loads(REFERENCE_FILE.read_text())


def reference_for(code):
    return reference_data().get(code, {})


def participant_names(references):
    names = {}
    for reference in references.values():
        snapshots = [reference.get('baseline', [])]
        snapshots.extend(snapshot['rows'] for snapshot in reference.get('snapshots', {}).values())
        for snapshot in snapshots:
            for row in snapshot:
                name = row['name']
                if re.search(r'[㐀-鿿]', name):
                    names.setdefault(row['id'], name)
    return names


def offering_ratio(reference, shares):
    public = reference.get('public_shares')
    international = reference.get('international_shares')
    if shares is None or public is None or international is None:
        return None
    total = public + international
    return 100 * shares / total if total > 0 else None


def top_ten(rows):
    return [row for row in rows if row['id'] != EXCLUDED][:10]


def first_day_rows(db, code, baseline, reference, tables):
    if reference.get('listing_date') == baseline and reference.get('baseline'):
        return sorted(reference['baseline'], key=lambda row: (-row['shares'], row['id']))
    if 'ccass_cli_cache' in tables and baseline:
        row = db.execute(
            "SELECT payload FROM ccass_cli_cache WHERE code=? AND broker='' AND day=?",
            (code, baseline),
        ).fetchone()
        if row:
            return [dict(id=item['broker_code'], name=item['broker_name'])
                    for item in json.loads(row[0])['items']]
    return []


def refresh(database, code, listing_date=None):
    fetch(database, code)
    report = trend(database, code, listing_date=listing_date)
    if not report['rows']:
        raise ValueError('缺少上市首日持股分布，已保存最新分布，暂不能确定首日前十')
    failed = []
    brokers = dict.fromkeys(row['id'] for row in report['rows'] + report.get('selected_ranking', []))
    for broker in brokers:
        try:
            fetch(database, code, broker)
        except (ValueError, TypeError, KeyError):
            failed.append(broker)
    return failed


def trend(database, code, as_of=None, listing_date=None):
    cutoff = date.fromisoformat(as_of).isoformat() if as_of else datetime.now(HK).date().isoformat()
    references = reference_data()
    reference = references.get(code, {})
    chinese_names = participant_names(references)
    baseline = reference.get('listing_date') or listing_date
    if not baseline:
        return dict(rows=[], days=[], message='缺少上市日期及首日 CCASS 快照。')
    if cutoff < baseline:
        return dict(rows=[], days=[], message='所选日期早于上市首日。')

    holdings, prices, rankings, sources = {}, {}, {}, {}
    with sqlite3.connect(database) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        initial = first_day_rows(db, code, baseline, reference, tables)
        tracked = top_ten(initial)
        if not tracked:
            return dict(rows=[], days=[], message=f'缺少 {baseline} 的首日 CCASS 持仓分布，暂不能确定首日前十。')
        rankings[baseline] = tracked
        sources[baseline] = reference.get('baseline_source') or '富途 CLI'
        for day, snapshot in reference.get('snapshots', {}).items():
            if baseline <= day <= cutoff:
                rankings[day] = top_ten(sorted(snapshot['rows'], key=lambda row: (-row['shares'], row['id'])))
                sources[day] = snapshot['source']
                for row in snapshot['rows']:
                    holdings[row['id'], day] = row['shares']
        for row in initial:
            if 'shares' in row:
                holdings[row['id'], baseline] = row['shares']
        if 'ccass_cli_cache' in tables:
            for broker, day, payload in db.execute(
                "SELECT broker,day,payload FROM ccass_cli_cache WHERE code=? AND day BETWEEN ? AND ?",
                (code, baseline, cutoff),
            ):
                value = json.loads(payload)
                if broker:
                    shares = str(value.get('hold_shares'))
                    if shares.isdecimal():
                        holdings.setdefault((broker, day), int(shares))
                elif day not in rankings:
                    rankings[day] = top_ten([dict(id=item['broker_code'], name=item['broker_name'])
                                             for item in value['items']])
                    sources[day] = '富途 CLI'
        if 'latest_state' in tables:
            row = db.execute("SELECT payload FROM latest_state WHERE code=? AND kind='daily_history'", (code,)).fetchone()
            if row:
                for bar in json.loads(row[0]).get('bars', []):
                    day = datetime.fromtimestamp(bar['time'], HK).date().isoformat()
                    if baseline <= day <= cutoff:
                        prices[day] = dict(close=bar.get('close'), turnover=bar.get('turnover'))

    ids = {row['id'] for row in tracked}
    holding_days = sorted({day for broker, day in holdings if broker in ids})
    days = sorted(set(prices) | set(holding_days) | {baseline})
    latest = holding_days[-1] if holding_days else baseline
    previous = holding_days[-2] if len(holding_days) > 1 else None
    rank_day = max(rankings)
    public = reference.get('public_shares')
    international = reference.get('international_shares')
    issued = reference.get('issued_shares')
    excluded_shares = holdings.get((EXCLUDED, baseline))
    # Size is only an inference under this reconciliation, never an allocation label.
    pool_matches = all(value is not None for value in (public, international, issued, excluded_shares)) and (
        issued - excluded_shares == public + international
    )
    rows = []
    for participant in tracked:
        broker = participant['id']
        first = holdings.get((broker, baseline))
        current = holdings.get((broker, latest))
        prior = holdings.get((broker, previous))
        possible = pool_matches and first is not None and first > public
        rows.append(dict(id=broker, name=chinese_names.get(broker, participant['name']),
                         label='可能涉及国配 · 首日持仓超过公发总量' if possible else '发售归属待核实',
                         possible=bool(possible), initial=first, current=current,
                         change=current-first if first is not None and current is not None else None,
                         previous_change=current-prior if prior is not None and current is not None else None,
                         remaining=current/first if first and current is not None else None,
                         values=[holdings[broker, day]-first if first is not None and (broker, day) in holdings else None
                                 for day in days]))
    groups = {}
    for label, members in (
        ('首日前十合计', rows),
        ('可能涉及国配渠道', [row for row in rows if row['possible']]),
    ):
        if not members:
            continue
        values = []
        for index in range(len(days)):
            known = [row['values'][index] for row in members if row['values'][index] is not None]
            values.append(dict(change=sum(known) if len(known)==len(members) else None, covered=len(known)))
        groups[label] = dict(size=len(members), values=values)
    newcomers = [dict(row, name=chinese_names.get(row['id'], row['name']),
                      shares=holdings.get((row['id'], rank_day)))
                 for row in rankings[rank_day] if row['id'] not in ids]
    selected_day = as_of or rank_day
    selected_ranking = []
    for index, participant in enumerate(rankings.get(selected_day, []), 1):
        broker = participant['id']
        first = holdings.get((broker, baseline))
        possible = bool(pool_matches and first is not None and first > public)
        shares = holdings.get((broker, selected_day))
        selected_ranking.append(dict(
            id=broker, name=chinese_names.get(broker, participant['name']), rank=index,
            shares=shares, ratio=offering_ratio(reference, shares), possible=possible,
            label='可能涉及国配 · 首日持仓超过公发总量' if possible else '发售归属待核实',
            newcomer=broker not in ids,
        ))
    return dict(selected_day=selected_day, selected_ranking=selected_ranking,
                selected_source=sources.get(selected_day),
                baseline=baseline, latest=latest, days=days, prices=[prices.get(day) for day in days],
                groups=groups, rows=rows, newcomers=newcomers, rank_day=rank_day,
                rank_source=sources[rank_day], baseline_source=sources[baseline],
                announcement=reference.get('announcement'), public_shares=public,
                international_shares=international, pool_matches=pool_matches)

def participant_history(database, code, broker, listing_date=None):
    reference = reference_for(code)
    baseline = reference.get('listing_date') or listing_date
    today = datetime.now(HK).date().isoformat()
    entries = {}

    def add(day, shares):
        raw = str(shares)
        if raw.isdecimal() and day <= today and (not baseline or day >= baseline):
            shares = int(raw)
            entries[day] = dict(date=day, hold_shares=shares,
                                hold_ratio=offering_ratio(reference, shares))

    with sqlite3.connect(database) as db:
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='ccass_cli_cache'").fetchone():
            for day, payload in db.execute(
                "SELECT day,payload FROM ccass_cli_cache WHERE code=? AND broker=?", (code, broker)
            ):
                value = json.loads(payload)
                add(day, value.get('hold_shares'))
    if baseline:
        for row in reference.get('baseline', []):
            if row['id'] == broker:
                add(baseline, row['shares'])
    for day, snapshot in reference.get('snapshots', {}).items():
        for row in snapshot['rows']:
            if row['id'] == broker:
                add(day, row['shares'])
    return dict(baseline=baseline, items=[entries[day] for day in sorted(entries)])
