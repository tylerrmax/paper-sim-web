"""快照结构校验：snapshot.json 必需字段、数据类型、日期一致性。"""
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lib.freshness import check_klines

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
    # 各标的最后 bar 对齐各自市场日历（lib/freshness.check_klines）：
    # 股票=最近交易日，BTC=最新已收盘 UTC 日K（允许晚一天）。
    # 周末/假期加密先行导致 asof 比股票新是正常的，不在此报错。
    klines = snap["klines"]
    for sym in ("002446", "688305", "BTCUSDT", "HK0354", "HK9660",
                "300827", "002639", "600150"):
        assert sym in klines, f"缺少 {sym} 的 K 线"
        bars = klines[sym]
        assert len(bars) > 0, f"{sym} K 线为空"
    now_bjk = datetime.now(timezone.utc) + timedelta(hours=8)
    bad = check_klines(klines, now_bjk.replace(tzinfo=None))
    assert not bad, f"K线最后日期与市场日历不一致: {bad}"


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
