"""Read-only CCASS queries through the official Futu HTTP API."""
import json
from pathlib import Path
import re
import sqlite3
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request

from .futu_oauth import managed_token, opener

from .watchlist import normalize_code


def access_token(database):
    token = managed_token(database) or os.environ.get('FUTU_ACCESS_TOKEN', '').strip()
    if not token:
        path = Path(database).parent / 'futu-access-token'
        try:
            if path.stat().st_mode & 0o077:
                raise ValueError('富途令牌文件权限需设为仅本人可读写（chmod 600）')
            token = path.read_text().strip()
        except FileNotFoundError:
            pass
        except (OSError, UnicodeError) as error:
            raise ValueError('无法读取本地富途令牌文件') from error
    if not token or not token.isascii() or any(ord(char) <= 32 or ord(char) >= 127 for char in token):
        raise ValueError('请先在看板点击「授权富途」')
    return token


def query(code, endpoint, token, **params):
    url = f'https://webapi.futunn.com/api/v1.0/quote/{code}/{endpoint}?{urlencode(params)}'
    request = Request(url, headers={'Authorization': f'Bearer {token}', 'Accept': 'application/json'})
    try:
        with opener.open(request, timeout=10) as response:
            result = json.load(response)
    except HTTPError as error:
        if error.code in (401, 403):
            raise ValueError('富途 HTTP 授权无效、已过期或缺少行情权限') from None
        raise ValueError(f'富途 CCASS 请求失败（HTTP {error.code}）') from None
    except (URLError, OSError, ValueError):
        raise ValueError('富途 CCASS 连接或响应异常，请稍后重试') from None
    if not isinstance(result, dict):
        raise ValueError('富途返回的 CCASS 响应格式有误')
    ret = result.get('ret_code')
    if ret != 0:
        raise ValueError({-9: '富途账户缺少 CCASS 行情权限', -10: '富途暂无该标的 CCASS 数据',
                          -11: '富途 CCASS 查询频率过高，请稍后重试'}.get(ret, '富途 CCASS 查询失败，请检查行情授权'))
    if not isinstance(result.get('data'), dict):
        raise ValueError('富途返回的 CCASS 数据格式有误')
    return result


def fetch(database, code, broker=None):
    code = normalize_code(code)
    if not code.startswith('HK.'):
        raise ValueError('CCASS 仅支持港股')
    if broker is not None and not re.fullmatch(r'[A-Z][0-9]{5}', broker):
        raise ValueError('CCASS 参与者编号无效')

    token = access_token(database)
    if broker:
        result = query(code, 'broker-hold-detail', token, broker_code=broker, count=90)['data']
        if result.get('broker_code') != broker or not isinstance(result.get('items'), list):
            raise ValueError('富途返回的历史持仓格式有误')
    else:
        rows, cursors, cursor, holding_date = [], set(), None, None
        for _ in range(30):
            params = {'page_size': 50}
            if cursor:
                params['page_flag'] = cursor
            page = query(code, 'broker-hold-ratio', token, **params)
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
        result = dict(date=holding_date, items=rows, source='富途 HTTP')

    with sqlite3.connect(database) as db:
        db.execute('''CREATE TABLE IF NOT EXISTS ccass_cache (
            code TEXT, broker TEXT, day TEXT, payload TEXT, PRIMARY KEY(code, broker, day))''')
        if broker:
            records = [(code, broker, item['date'], json.dumps(item)) for item in result['items']]
        else:
            records = [(code, '', result['date'], json.dumps(result))]
        db.executemany('INSERT OR REPLACE INTO ccass_cache VALUES (?,?,?,?)', records)
    return result
