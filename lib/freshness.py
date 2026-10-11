"""数据新鲜度判定：基于快照**内容**（不依赖文件 mtime）。

纯函数，可独立测试。app.py 直接引用本实现（单点真相源）。

约定：now 为北京时间（naive datetime）。多市场日历分别校验：
- 股票（A股/港股）：最新 bar 应为最近一个股票交易日
  （周末回退；工作日 17:12 跑批前用前一天）；
- BTC：7×24 交易，日K按 UTC 自然日收盘；在北京时间 T，
  最新已收盘 bar 的日期为 (T - 8h).date() - 1 天，允许再晚一天（接口滞后）。

asof 为引擎模拟的最大日期（多市场取 max）：周末/假期加密先行时
asof 会比股票交易日新，这是正常的——只要 asof 不落后于期望交易日、
且各标的分别对齐各自市场日历，就判 ok。
"""
from datetime import timedelta

_BEIJING_OFFSET = timedelta(hours=8)


def _expected_trading_day(now):
    """最近一个股票交易日（date）。"""
    d = now.date()
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    if now.date().weekday() < 5 and now.hour < 17:
        d -= timedelta(days=1)
        while d.weekday() >= 5:
            d -= timedelta(days=1)
    return d


def _btc_expected_last(now):
    """BTC 最新已收盘日K的日期（date，按 UTC 自然日）。

    bar D 覆盖 [D 00:00, D+1 00:00) UTC，在 D+1 00:00 UTC（=北京时间 D+1 08:00）
    收盘。因此在北京时间 T，能拿到的最新完整 bar 是 (T-8h).date() - 1 天。
    """
    return (now - _BEIJING_OFFSET).date() - timedelta(days=1)


def check_klines(klines, now):
    """逐标的校验最后 bar 日期是否对齐各自市场日历。

    返回异常描述列表；空列表表示全部一致。
    """
    expected = _expected_trading_day(now)
    btc_exp = _btc_expected_last(now)
    btc_ok = {btc_exp.strftime("%m-%d"),
              (btc_exp - timedelta(days=1)).strftime("%m-%d")}
    want_stock = expected.strftime("%m-%d")
    bad = []
    for s, kl in (klines or {}).items():
        if not kl:
            bad.append(f"{s}无数据")
            continue
        last = kl[-1][0]  # "MM-DD"
        if s.upper().endswith("USDT"):
            if last not in btc_ok:
                bad.append(f"{s}截至{last}")
        elif last != want_stock:
            bad.append(f"{s}截至{last}")
    return bad


def data_freshness(snap, now):
    """判定数据新鲜度。

    参数:
        snap: 快照 dict，需含 asof ("YYYY-MM-DD") 和 klines {symbol: [(MM-DD, ...), ...]}
        now: 北京时间（naive datetime），用于计算期望的最近交易日

    返回 (state, detail)：
    - ok: asof 不落后于期望交易日，且各标的行情形后日期对齐各自市场日历
    - stale: 可证明数据过期（asof 早于期望日期，或某标的行情形后日期落后）
    - unknown: 无法验证（缺 asof / 无行情数据），显示"未知"比"正常"更安全
    """
    asof = (snap or {}).get("asof")  # "2026-10-09"
    klines = (snap or {}).get("klines", {}) or {}
    if not asof or not klines:
        return "unknown", "缺少 asof 或行情数据，无法验证"
    # 第一层：asof（引擎模拟的最大日期）不得落后于期望的股票交易日
    expected = _expected_trading_day(now)
    if asof < expected.strftime("%Y-%m-%d"):
        return "stale", f"数据截至 {asof}，期望 {expected}"
    # 第二层：各标的分别对齐各自市场日历
    bad = check_klines(klines, now)
    if bad:
        return "stale", "；".join(bad)
    return "ok", f"数据截至 {asof}"
