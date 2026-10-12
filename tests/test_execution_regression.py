"""执行桥回归测试（用户 2026-10-12 审查要求步骤 3-6）。
隔离数据：只调纯函数，不碰 DB/账户/策略。
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..",
                                "paper-trading-sim"))
from engine.execution import (
    is_stock_trading_day, next_trading_day, is_operable,
    order_guidance, calc_slippage,
)

# ---- 3. 执行日期：A股/港股/加密 × 各类假期 ----
def test_weekend_normal():
    # 普通周末：周五信号→周一执行
    assert next_trading_day("2026-10-09", "stock") == "2026-10-12"

def test_statutory_holiday():
    # 法定节假日：9-30(周三)→国庆→10-08
    assert next_trading_day("2026-09-30", "stock") == "2026-10-08"

def test_makeup_workday_weekend():
    # 调休工作日：即使周六被定为工作日，股市仍休市
    # 2026-10-10(周六)为国庆调休工作日，但交易所休市
    assert not is_stock_trading_day("2026-10-10")
    assert next_trading_day("2026-10-09", "stock") == "2026-10-12"

def test_newyear_long_holiday():
    # 跨年：2025-12-31(周三)→元旦(1-01周四~1-03周六)+周日→2026-01-05(周一)
    assert next_trading_day("2025-12-31", "stock") == "2026-01-05"

def test_hk_independent_holiday():
    # 港股独立休市日：2026-04-03 耶稣受难日（港股休、A股开）
    # sim_hk 信号的执行日必须跳过（取交集）
    assert next_trading_day("2026-04-02", "stock", "sim_hk") == "2026-04-08"
    # sim_a 不受港股假日影响
    assert next_trading_day("2026-04-02", "stock", "sim_a") == "2026-04-03"

def test_hk_christmas():
    # 2026-12-24(周四)→圣诞12-25(周五)+周末+12-28(周一港股休)→12-29
    assert next_trading_day("2026-12-24", "stock", "sim_hk") == "2026-12-29"

def test_crypto_ignores_all_holidays():
    assert next_trading_day("2026-10-01", "crypto") == "2026-10-02"
    assert next_trading_day("2026-10-10", "crypto") == "2026-10-11"

# ---- 4. 下单指引 ----
def test_guidance_reference_price():
    g = order_guidance("002446", "BUY", 7.55, "2026-10-13", True)
    assert "7.55" in g["advice"]  # 参考价=信号价

def test_guidance_limit_calc():
    g = order_guidance("002446", "BUY", 10.00, "2026-10-13", True)
    assert "上浮1%" in g["advice"]
    g = order_guidance("002446", "SELL", 10.00, "2026-10-13", True)
    assert "下浮1%" in g["advice"]

def test_guidance_price_precision():
    g = order_guidance("HK9660", "BUY", 4.12323, "2026-10-13", True)
    assert "4.123" in g["advice"]  # 港股3位
    g = order_guidance("BTCUSDT", "BUY", 83109.5478, "2026-10-13", True)
    assert "83109.5" in g["advice"]  # 加密1位
    g = order_guidance("002446", "BUY", 7.555, "2026-10-13", True)
    assert "7.56" in g["advice"] or "7.55" in g["advice"]  # A股2位

def test_guidance_not_real_order():
    # 指引必须与真实下单状态区分：文案不得暗示已下单
    g = order_guidance("002446", "BUY", 7.55, "2026-10-13", True)
    for bad in ["已下单", "已成交", "已委托", "订单号"]:
        assert bad not in g["advice"], f"指引文案含'{bad}'，易误读为真实下单"
    assert "或开盘市价" in g["advice"]  # 明确是建议

# ---- 5. 滑点 ----
def test_slippage_pct():
    s = calc_slippage(100.0, 101.0, "BUY")
    assert abs(s - 0.01) < 1e-9

def test_slippage_missing_ref():
    assert calc_slippage(0, 101.0, "BUY") is None
    assert calc_slippage(None, 101.0, "BUY") is None

def test_slippage_batch_note():
    # 分批成交：当前 schema 按(signal,side)唯一，无法记录第二批
    # 此测试记录该限制（修复后应支持加权平均）
    print("\n  分批成交：当前 real_fills 按(signal_date,account,symbol,side)去重，"
          "第二批录入会被拦截——待修复")
