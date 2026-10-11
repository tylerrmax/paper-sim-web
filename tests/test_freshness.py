"""data_freshness 三态逻辑测试：ok / stale / unknown。"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.freshness import data_freshness


def _snap(asof, klines):
    return {"asof": asof, "klines": klines}


def _kl(*symbols, last="10-09"):
    return {s: [(last, 100.0)] for s in symbols}


# 周六 2026-10-10 12:00，期望最近交易日 = 周五 2026-10-09
SAT_NOON = datetime(2026, 10, 10, 12, 0)


def test_ok():
    snap = _snap("2026-10-09", _kl("002446", "688305", "HK0354"))
    state, detail = data_freshness(snap, SAT_NOON)
    assert state == "ok", detail


def test_ok_btc_one_day_grace():
    # BTC 允许晚一天（UTC 收盘）：asof=10-09 时 BTC 最后日期为 10-08 也算 ok
    snap = _snap("2026-10-09", {"BTCUSDT": [("10-08", 80000.0)]})
    state, detail = data_freshness(snap, SAT_NOON)
    assert state == "ok", detail


def test_stale_asof_behind():
    snap = _snap("2026-10-08", _kl("002446"))
    state, detail = data_freshness(snap, SAT_NOON)
    assert state == "stale", detail
    assert "2026-10-08" in detail


def test_stale_symbol_lagging():
    snap = _snap("2026-10-09", {"002446": [("10-08", 7.5)]})
    state, detail = data_freshness(snap, SAT_NOON)
    assert state == "stale", detail
    assert "002446" in detail


def test_stale_empty_klines_for_symbol():
    snap = _snap("2026-10-09", {"002446": []})
    state, _ = data_freshness(snap, SAT_NOON)
    assert state == "stale"


def test_unknown_missing_asof():
    snap = _snap(None, _kl("002446"))
    state, detail = data_freshness(snap, SAT_NOON)
    assert state == "unknown", detail


def test_unknown_empty_klines():
    snap = _snap("2026-10-09", {})
    state, detail = data_freshness(snap, SAT_NOON)
    assert state == "unknown", detail


def test_weekday_before_batch_uses_prev_day():
    # 周一 2026-10-12 10:00（17 点前），期望 = 上周五 2026-10-09
    monday_morning = datetime(2026, 10, 12, 10, 0)
    snap = _snap("2026-10-09", _kl("002446"))
    state, _ = data_freshness(snap, monday_morning)
    assert state == "ok"
    # 若 asof 停在更早，则为 stale
    snap2 = _snap("2026-10-08", _kl("002446"))
    state2, _ = data_freshness(snap2, monday_morning)
    assert state2 == "stale"


# ---- 多市场日历：周末加密先行是正常现象，不应误报 stale ----

# 周日 2026-10-11 15:45（北京时间）：BTC 10-10 bar 已收盘入库，
# asof 仍为周五 10-09 —— 数据正常
SUN_1545 = datetime(2026, 10, 11, 15, 45)


def test_ok_btc_ahead_of_asof_on_weekend():
    klines = _kl("002446", "688305", "HK0354", "HK9660")
    klines["BTCUSDT"] = [("10-10", 82912.7)]
    snap = _snap("2026-10-09", klines)
    state, detail = data_freshness(snap, SUN_1545)
    assert state == "ok", detail


def test_ok_sunday_night_asof_advanced_by_crypto():
    # 周日 17:12 跑批后：asof 被加密推到 10-10，股票仍停在周五 —— 正常
    night = datetime(2026, 10, 11, 20, 0)
    klines = _kl("002446", "688305", "HK0354", "HK9660")
    klines["BTCUSDT"] = [("10-10", 82912.7)]
    snap = _snap("2026-10-10", klines)
    state, detail = data_freshness(snap, night)
    assert state == "ok", detail


def test_ok_monday_preopen_after_sunday_batch():
    # 周一 09:00 盘前：asof=10-10（周日加密），股票=周五 —— 正常
    monday = datetime(2026, 10, 12, 9, 0)
    klines = _kl("002446", "688305", "HK0354", "HK9660")
    klines["BTCUSDT"] = [("10-10", 82912.7)]
    snap = _snap("2026-10-10", klines)
    state, detail = data_freshness(snap, monday)
    assert state == "ok", detail


def test_stale_btc_two_days_behind():
    # BTC 行情落后两天（接口真挂了）—— 必须报 stale
    snap = _snap("2026-10-09", {"BTCUSDT": [("10-08", 80000.0)]})
    state, detail = data_freshness(snap, SUN_1545)
    assert state == "stale", detail
    assert "BTCUSDT" in detail


def test_stale_stock_vendor_gap_after_batch():
    # 周三 18:00（跑批后）：某股票缺了当天 bar —— 真过期，必须报 stale
    wed = datetime(2026, 10, 14, 18, 0)
    klines = {"002446": [("10-13", 7.5)], "BTCUSDT": [("10-13", 83000.0)]}
    snap = _snap("2026-10-14", klines)
    state, detail = data_freshness(snap, wed)
    assert state == "stale", detail
    assert "002446" in detail
