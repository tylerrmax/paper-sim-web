"""执行桥逻辑测试：交易日历、下单指引、滑点（纯函数，不碰 DB）。"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..",
                                "paper-trading-sim"))

from engine.execution import (
    is_stock_trading_day, next_trading_day, is_operable,
    order_guidance, calc_slippage,
)


def test_weekend_not_trading():
    assert not is_stock_trading_day("2026-10-10")  # 周六
    assert not is_stock_trading_day("2026-10-11")  # 周日
    assert is_stock_trading_day("2026-10-12")      # 周一


def test_holiday_not_trading():
    assert not is_stock_trading_day("2026-10-01")  # 国庆
    assert not is_stock_trading_day("2026-02-17")  # 春节


def test_next_trading_day_skips_weekend():
    assert next_trading_day("2026-10-09", "stock") == "2026-10-12"  # 周五→周一


def test_next_trading_day_skips_holiday():
    # 2026-09-30(周三)→国庆休市→10-08(周四)
    assert next_trading_day("2026-09-30", "stock") == "2026-10-08"


def test_crypto_everyday():
    assert next_trading_day("2026-10-10", "crypto") == "2026-10-11"


def test_hk_operable_on_trading_day():
    ok, _ = is_operable("sim_hk", "2026-10-12")
    assert ok


def test_hk_not_operable_on_a_share_holiday():
    ok, reason = is_operable("sim_hk", "2026-10-01")
    assert not ok and "不可操作" in reason


def test_crypto_always_operable():
    ok, _ = is_operable("sim_crypto", "2026-10-01")
    assert ok


def test_guidance_buy_sell():
    g = order_guidance("HK9660", "BUY", 4.123, "2026-10-13", True)
    assert g["operable"] and "买入" in g["advice"]
    g = order_guidance("HK9660", "SELL", 4.123, "2026-10-13", True)
    assert "卖出" in g["advice"]
    g = order_guidance("HK9660", "BUY", 4.123, "2026-10-01", False)
    assert not g["operable"] and g["advice"] == "—"


def test_slippage_direction():
    # BUY: 实际价高于信号价 = 不利滑点(正)
    assert calc_slippage(4.0, 4.04, "BUY") > 0
    # SELL: 实际价低于信号价 = 不利滑点(正)
    assert calc_slippage(4.0, 3.96, "SELL") > 0
    # 有利滑点为负
    assert calc_slippage(4.0, 3.96, "BUY") < 0
