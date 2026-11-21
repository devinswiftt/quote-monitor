#!/usr/bin/env python3
"""Quick read-only OpenD order-book check, with a hard wall-clock timeout."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import time


def worker(args):
    import futu as ft
    started = time.monotonic()
    ctx = None
    try:
        ctx = ft.OpenQuoteContext(host=args.host, port=args.port)
        ret, state = ctx.get_global_state()
        if ret != ft.RET_OK:
            raise RuntimeError(str(state))
        if not state.get('qot_logined'):
            raise RuntimeError('OpenD 尚未登录行情服务器')
        print('市场状态：' + str(state.get('market_hk', '未知')), flush=True)
        ret, result = ctx.subscribe(args.symbols, [ft.SubType.ORDER_BOOK],
                                    is_first_push=False, subscribe_push=False)
        if ret != ft.RET_OK:
            raise RuntimeError('盘口订阅失败：' + str(result))
        failed = False
        for code in args.symbols:
            ret, book = ctx.get_order_book(code, num=10)
            if ret != ft.RET_OK:
                print(f'{code} 获取失败：{book}', flush=True)
                failed = True
                continue
            bids, asks = len(book.get('Bid', [])), len(book.get('Ask', []))
            if bids >= 10 and asks >= 10:
                status = '当前返回十档'
            elif bids == 1 and asks == 1:
                status = '当前仅返回一档'
            else:
                status = '档位不足，不能仅据此判断权限'
            print(f'{code}  买 {bids} 档 / 卖 {asks} 档  → {status}', flush=True)
            print('  盘口源时间：买 {}；卖 {}'.format(
                book.get('svr_recv_time_bid') or '未知',
                book.get('svr_recv_time_ask') or '未知'), flush=True)
        print(f'查询耗时：{time.monotonic() - started:.2f} 秒（不含 SDK 导入）', flush=True)
        print('注：查询结果可能是缓存快照；休市或无成交时不代表实时推送验证。', flush=True)
        return 1 if failed else 0
    except Exception as exc:
        print(f'检查失败：{exc}', file=sys.stderr, flush=True)
        return 1
    finally:
        if ctx is not None:
            ctx.close()


def main():
    parser = argparse.ArgumentParser(description='快速查询港股盘口档数，不等待持续推送')
    parser.add_argument('--symbols', nargs='+', help='例如 HK.00700 HK.09988')
    parser.add_argument('--host')
    parser.add_argument('--port', type=int)
    parser.add_argument('--timeout', type=float, default=10, help='整个检查的最长秒数，默认 10')
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    config = json.loads((Path(__file__).parent / 'config/settings.json').read_text())
    args.symbols = args.symbols or config['symbols']
    args.host = args.host or config['host']
    args.port = args.port or config['port']
    if args.timeout <= 0:
        parser.error('--timeout 必须大于零')
    if any(not re.fullmatch(r'HK\.\d{5}', code) for code in args.symbols):
        parser.error('股票代码应为 HK.00700 格式')
    if args.worker:
        return worker(args)
    command = [sys.executable, '-u', str(Path(__file__).resolve()), '--worker',
               '--host', args.host, '--port', str(args.port), '--symbols', *args.symbols]
    started = time.monotonic()
    try:
        result = subprocess.run(command, timeout=args.timeout)
        print(f'总耗时：{time.monotonic() - started:.2f} 秒', flush=True)
        return result.returncode
    except subprocess.TimeoutExpired:
        print(f'检查超时（{args.timeout:g} 秒），已停止。请检查 OpenD、代理或登录状态。',
              file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    sys.exit(main())
