"""账户对账自动化：快照 vs 生产 DB（只读），账目必须分毫不差。"""
import json
import os
import sqlite3

WEB_DIR = os.path.join(os.path.dirname(__file__), "..")
SNAP_PATH = os.path.join(WEB_DIR, "snapshot.json")
DB_PATH = os.path.expanduser("~/workspace/paper-trading-sim/db/sim.db")

with open(SNAP_PATH, encoding="utf-8") as f:
    snap = json.load(f)

db = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)


def _snap_acct(aid):
    for a in snap["accounts"]:
        if a["account"] == aid:
            return a
    raise AssertionError(f"快照缺账户 {aid}")


def test_positions_match_db():
    """快照持仓与 DB positions 逐字段一致。"""
    db_pos = {(r[0], r[1]): r[2:] for r in
              db.execute("SELECT account, symbol, qty, avg_cost, market_value FROM positions")}
    snap_pos = {(p["account"], p["symbol"]): (p["qty"], p["avg_cost"], p["market_value"])
                for p in snap.get("positions", [])}
    assert db_pos == snap_pos, f"持仓不一致: DB={db_pos} 快照={snap_pos}"


def test_nav_matches_daily_report():
    """快照净值与 DB daily_report 最新一致。"""
    asof = snap["asof"]
    for aid in ("sim_a", "sim_hk", "sim_crypto"):
        row = db.execute(
            "SELECT nav FROM daily_report WHERE account=? AND symbol='TOTAL' AND date=?",
            (aid, asof)).fetchone()
        assert row is not None, f"DB 缺 {aid} 在 {asof} 的净值"
        assert abs(row[0] - _snap_acct(aid)["nav"]) < 0.01, \
            f"{aid} 净值不一致: DB={row[0]} 快照={_snap_acct(aid)['nav']}"


def test_realized_pnl_matches_fills():
    """快照已实现盈亏 == DB fills 按账户汇总（分毫不差）。"""
    for aid, total in db.execute("SELECT account, SUM(pnl) FROM fills GROUP BY account"):
        snap_val = _snap_acct(aid)["realized_pnl"]
        assert abs((total or 0) - snap_val) < 0.01, \
            f"{aid} 已实现盈亏不一致: DB={total} 快照={snap_val}"


def test_stock_pool_total():
    """股票池 total_cny == 各成分 nav_cny 之和。"""
    sp = snap["stock_pool"]
    calc = sum(c["nav_cny"] for c in sp["components"])
    assert abs(calc - sp["total_cny"]) < 0.01, \
        f"股票池合计不一致: {calc} != {sp['total_cny']}"


def test_fills_count_monotonic():
    """DB 全量 fills 只增不减（本轮只读，记录当前值供下轮对比）。"""
    n = db.execute("SELECT COUNT(*) FROM fills").fetchone()[0]
    # 快照 fills 为 60 天滚动窗口，数量 <= DB 全量
    assert len(snap.get("fills", [])) <= n, "快照 fills 不应超过 DB 全量"
    print(f"\n  [info] DB fills 全量 = {n}，快照窗口 = {len(snap.get('fills', []))}")
