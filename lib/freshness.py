"""数据新鲜度判定：基于快照**内容**（不依赖文件 mtime）。

纯函数，可独立测试。逻辑与 app.py 内联版本完全一致。
"""
from datetime import timedelta


def data_freshness(snap, now):
    """判定数据新鲜度。

    参数:
        snap: 快照 dict，需含 asof ("YYYY-MM-DD") 和 klines {symbol: [(MM-DD, ...), ...]}
        now: 当前 datetime（用于计算期望的最近交易日）

    返回 (state, detail)：
    - ok: asof == 期望的最近数据日期，且各标的行情最后日期与 asof 一致
    - stale: 可证明数据过期（asof 早于期望日期，或某标的行情形后日期落后）
    - unknown: 无法验证（缺 asof / 无行情数据），显示"未知"比"正常"更安全
    """
    asof = (snap or {}).get("asof")  # "2026-10-09"
    klines = (snap or {}).get("klines", {}) or {}
    if not asof or not klines:
        return "unknown", "缺少 asof 或行情数据，无法验证"
    # 期望的最近数据日期：最近一个交易日；工作日 17:12 跑批前用前一天
    d = now.date()
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    if now.date().weekday() < 5 and now.hour < 17:
        d -= timedelta(days=1)
        while d.weekday() >= 5:
            d -= timedelta(days=1)
    expected = d.strftime("%Y-%m-%d")
    if asof < expected:
        return "stale", f"数据截至 {asof}，期望 {expected}"
    # 各标的行情形后日期：股票应 == asof；BTC 日K按UTC收盘，允许晚一天
    bad = []
    for s, kl in klines.items():
        if not kl:
            bad.append(f"{s}无数据")
            continue
        last = kl[-1][0]  # "MM-DD"
        want = asof[5:]
        if s.upper().endswith("USDT"):
            # BTC：asof 当天的 K 线在北京时间次日 08:00 才收盘
            if last not in (want, (d - timedelta(days=1)).strftime("%m-%d")):
                bad.append(f"{s}截至{last}")
        elif last != want:
            bad.append(f"{s}截至{last}")
    if bad:
        return "stale", "；".join(bad)
    return "ok", f"数据截至 {asof}"
