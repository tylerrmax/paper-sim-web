"""快照结构校验：snapshot.json 必需字段、数据类型、日期一致性。"""
import json
import os
import re

SNAP_PATH = os.path.join(os.path.dirname(__file__), "..", "snapshot.json")

with open(SNAP_PATH, encoding="utf-8") as f:
    snap = json.load(f)


def test_top_level_keys():
    required = {"asof", "accounts", "klines", "signals", "fills",
                "positions", "graduation", "control", "stock_pool"}
    missing = required - set(snap.keys())
    assert not missing, f"缺少顶层字段: {missing}"


def test_asof_format():
    asof = snap["asof"]
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", asof), f"asof 格式错误: {asof}"


def test_accounts_structure():
    accts = snap["accounts"]
    assert isinstance(accts, list) and len(accts) == 3
    ids = set()
    for a in accts:
        assert a["account"] in ("sim_a", "sim_hk", "sim_crypto")
        ids.add(a["account"])
        for k in ("cash", "nav", "position_value", "realized_pnl", "ret_total"):
            assert isinstance(a[k], (int, float)), f"{a['account']}.{k} 非数字"
        # 现金 + 持仓 == 净值（允许 0.01 浮点误差）
        assert abs(a["cash"] + a["position_value"] - a["nav"]) < 0.01, \
            f"{a['account']} 现金+持仓 != 净值"
    assert ids == {"sim_a", "sim_hk", "sim_crypto"}


def test_klines_symbols_and_dates():
    klines = snap["klines"]
    asof = snap["asof"]
    want = asof[5:]  # "MM-DD"
    for sym in ("002446", "688305", "BTCUSDT", "HK0354", "HK9660"):
        assert sym in klines, f"缺少 {sym} 的 K 线"
        bars = klines[sym]
        assert len(bars) > 0, f"{sym} K 线为空"
        last_date = bars[-1][0]
        if sym.upper().endswith("USDT"):
            # BTC 允许晚一天（UTC 收盘）
            assert last_date in (want, _prev_day(want)), \
                f"{sym} 最后日期 {last_date} 与 asof {asof} 不一致"
        else:
            assert last_date == want, f"{sym} 最后日期 {last_date} != {want}"


def _prev_day(mm_dd):
    from datetime import datetime, timedelta
    d = datetime.strptime(f"2026-{mm_dd}", "%Y-%m-%d") - timedelta(days=1)
    return d.strftime("%m-%d")


def test_signals_fields():
    for s in snap.get("signals", []):
        for k in ("account", "date", "symbol", "side", "price"):
            assert k in s, f"信号缺字段 {k}: {s}"
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", s["date"])
        assert s["side"] in ("BUY", "SELL")


def test_fills_fields():
    for fl in snap.get("fills", []):
        for k in ("account", "date", "symbol", "side", "qty", "price", "fee", "pnl"):
            assert k in fl, f"成交缺字段 {k}: {fl}"
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", fl["date"])


def test_graduation_caliber():
    g = snap["graduation"]
    for aid, a in g["accounts"].items():
        assert "val_start" in a and "val_return" in a, f"{aid} 缺验证期字段"
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", a["val_start"] or ""), \
            f"{aid} val_start 格式错误"
    # 验证期起点：A股/港股 2026-10-08，加密 2026-10-03
    assert g["accounts"]["sim_a"]["val_start"] == "2026-10-08"
    assert g["accounts"]["sim_hk"]["val_start"] == "2026-10-08"
    assert g["accounts"]["sim_crypto"]["val_start"] == "2026-10-03"
