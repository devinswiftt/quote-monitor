"""Track observed one-level books without claiming a permissions diagnosis."""


class DepthMonitor:
    def __init__(self):
        self.last = {}

    def observe(self, code, bids, asks):
        # Empty or asymmetric thin books may reflect liquidity, not permission.
        if not bids or not asks:
            return None
        previous = self.last.get(code)
        current = (bids, asks)
        self.last[code] = current
        if current == (1, 1) and previous != (1, 1):
            return f'{code} 当前盘口仅买一／卖一，十档确认暂停；请检查代理和行情权限。'
        if min(current) >= 10 and previous == (1, 1):
            return f'{code} 盘口已恢复买卖各十档。'
        return None
