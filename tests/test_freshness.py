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
