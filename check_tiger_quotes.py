#!/usr/bin/env python3
"""Read-only Tiger quote permission and HK grey-market availability check."""
import argparse
import json
import logging
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True, help='本机老虎开发者配置文件')
    parser.add_argument('--symbol', default='09941')
    args = parser.parse_args()
    if not args.symbol.isdigit() or len(args.symbol) > 5:
        parser.error('请输入港股数字代码')
    if not args.config.is_file():
        parser.error('配置文件不存在')
    try:
        from tigeropen.common.consts import Market, TradingSession
        from tigeropen.quote.quote_client import QuoteClient
        from tigeropen.tiger_open_config import TigerOpenClientConfig
    except ImportError:
        parser.error('测试需要官方 tigeropen SDK，可安装在独立测试环境')

    logger = logging.getLogger('tiger-readonly-check')
    logger.addHandler(logging.NullHandler())
    logger.propagate = False
    logger.setLevel(logging.CRITICAL)
    config = TigerOpenClientConfig(props_path=str(args.config.expanduser().resolve()))
    config.timeout = 8
    config.log_path = None
    config.log_level = 'CRITICAL'
    client = QuoteClient(config, logger=logger)
    symbol = args.symbol.zfill(5)

    def check(label, operation):
        try:
            value = operation()
            if value is None:
                result = {'rows': 0}
            elif hasattr(value, 'to_dict'):
                records = value.to_dict('records')
                result = {'rows': len(records),
                          'nonzero_volume_rows': sum((row.get('volume') or 0) > 0 for row in records),
                          'last': records[-1:]}
            else:
                result = value
            print(label, json.dumps(result, default=str, ensure_ascii=False))
        except Exception as error:
            # SDK exceptions may embed signed requests. Print only the type.
            print(label, '查询失败', type(error).__name__)

    check('行情权限', client.get_quote_permission)
    check('实时报价', lambda: client.get_stock_briefs([symbol], include_hour_trading=True))
    for session in (TradingSession.All, TradingSession.AfterHours):
        check('逐笔 '+session.value, lambda: client.get_trade_ticks([symbol], trade_session=session, limit=5))
        check('盘口 '+session.value, lambda: client.get_depth_quote([symbol], Market.HK, trade_session=session))
        check('分时 '+session.value, lambda: client.get_timeline([symbol], include_hour_trading=True, trade_session=session))


if __name__ == '__main__':
    main()
