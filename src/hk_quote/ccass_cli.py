"""Read-only CCASS queries through the official Futu CLI."""
import json
from pathlib import Path
import re
import sqlite3
import subprocess

from .watchlist import normalize_code


def query(*args):
    binary = Path.home() / '.futu/bin/futu'
    try:
        result = subprocess.run([str(binary), *args, '--format', 'json'],
                                capture_output=True, text=True, timeout=12, check=True)
        return json.loads(result.stdout)
    except FileNotFoundError as error:
        raise ValueError('未安装富途 CLI') from error
    except (subprocess.SubprocessError, ValueError) as error:
        raise ValueError('富途 CLI 查询失败，请检查行情授权与连接') from error


def fetch(database, code, broker=None):
    code = normalize_code(code)
    if not code.startswith('HK.'):
        raise ValueError('CCASS 仅支持港股')
    if broker is not None and not re.fullmatch(r'[A-Z][0-9]{5}', broker):
        raise ValueError('CCASS 参与者编号无效')

    if broker:
        result = query('broker-hold-detail', code, '--broker-code', broker, '--count', '90')
        if result.get('broker_code') != broker or not isinstance(result.get('items'), list):
            raise ValueError('富途返回的历史持仓格式有误')
    else:
        rows, cursors, cursor, holding_date = [], set(), None, None
        for _ in range(30):
            args = ['broker-hold-ratio', code, '--page-size', '50']
            if cursor:
                args.extend(['--page-flag', cursor])
            page = query(*args)
            data = page.get('data', {})
            day = data.get('data_date')
            if not day or (holding_date and holding_date != day) or not isinstance(data.get('items'), list):
                raise ValueError('富途返回的持股分布日期或格式有误')
            holding_date = day
            rows.extend(data['items'])
            pagination = page.get('pagination', {})
            if pagination.get('completed', not pagination):
                break
            cursor = pagination.get('page_flag')
            if not cursor or cursor in cursors:
                raise ValueError('富途分页未完成，请重试')
            cursors.add(cursor)
        else:
            raise ValueError('富途分页超过读取上限')
        result = dict(date=holding_date, items=rows)

    with sqlite3.connect(database) as db:
        db.execute('''CREATE TABLE IF NOT EXISTS ccass_cli_cache (
            code TEXT, broker TEXT, day TEXT, payload TEXT, PRIMARY KEY(code, broker, day))''')
        if broker:
            records = [(code, broker, item['date'], json.dumps(item)) for item in result['items']]
        else:
            records = [(code, '', result['date'], json.dumps(result))]
        db.executemany('INSERT OR REPLACE INTO ccass_cli_cache VALUES (?,?,?,?)', records)
    return result
