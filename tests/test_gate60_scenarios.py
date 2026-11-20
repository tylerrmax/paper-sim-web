# -*- coding: utf-8 -*-
"""
60 天滚动门禁修正（2026-11-21，用户批准口径·路径 A）三场景回归测试。

场景：
  (a) 老成交滚出 60 天窗口 → 快照笔数较上轮下降，门禁通过；
  (b) 窗口内真实删行 → 门禁拒绝（分两种：快照缺窗口内成交；
      主库删窗口内成交被全量水位拦截）；
  (c) 无变化 → 门禁通过。
全部跑在临时 fixture 上，不碰生产库与远端。窗口基准日经 today 注入，
与生产同口径（cutoff = today - 60d，含起点）。
"""
import os
import sqlite3
import sys
from datetime import date

import pytest

TOOLS = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "tools")
sys.path.insert(0, TOOLS)

import release_gate_light as lgate  # noqa: E402

SCHEMA = """
CREATE TABLE fills (
    id INTEGER PRIMARY KEY, date TEXT, account TEXT, symbol TEXT,
    side TEXT, qty REAL, price REAL, fee REAL, pnl REAL,
    signal_date TEXT, strategy_version TEXT);
CREATE TABLE positions (account TEXT, symbol TEXT, qty REAL);
"""
# id=1 为老成交：2026-11-01 窗口（起点 2026-09-02）内，
# 2026-11-20 窗口（起点 2026-09-21）外——天然的滚出样本。
FILLS = [
    (1, "2026-09-10", "sim_a", "002472", "BUY", 200.0, 20.0, 1.0, 0.0),
    (2, "2026-10-20", "sim_a", "600150", "BUY", 100.0, 10.0, 1.0, 0.0),
    (3, "2026-10-21", "sim_a", "600150", "SELL", 100.0, 11.0, 1.0, 100.0),
    (4, "2026-10-21", "sim_hk", "HK0354", "BUY", 1000.0, 5.0, 2.0, 0.0),
    (5, "2026-10-22", "sim_a", "600150", "BUY", 50.0, 12.0, 1.0, 0.0),
]
POSITIONS = [("sim_a", "600150", 50.0), ("sim_a", "002472", 200.0),
             ("sim_hk", "HK0354", 1000.0)]
EARLIER = date(2026, 11, 1)   # 窗口起点 2026-09-02：5 笔全在窗口内
TODAY = date(2026, 11, 20)    # 窗口起点 2026-09-21：窗口内 4 笔


def make_db(path):
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    con.executemany(
        "INSERT INTO fills (id,date,account,symbol,side,qty,price,fee,pnl,"
        "signal_date,strategy_version) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [f + (f[1], "v1.1") for f in FILLS])
    con.executemany("INSERT INTO positions VALUES (?,?,?)", POSITIONS)
    con.commit()
    con.close()
    return str(path)


@pytest.fixture()
def sim_dir(tmp_path):
    d = tmp_path / "sim"
    d.mkdir()
    return str(d)


@pytest.fixture()
def db(sim_dir):
    return make_db(os.path.join(sim_dir, "sim.db"))


def test_a_rollout_passes(sim_dir, db):
    """(a) 老成交滚出窗口：快照 5 → 4（低于上轮），门禁通过。"""
    res1 = lgate.check_snapshot_gate(sim_dir, db, 5, 5, today=EARLIER)
    assert res1["ok"], res1
    # id=1（2026-09-10）滚出窗口后，快照按新窗口重建为 4 笔
    res2 = lgate.check_snapshot_gate(sim_dir, db, 4, 5, today=TODAY)
    assert res2["ok"], res2
    assert "60 天窗口 4" in res2["detail"]


def test_b_window_deletion_refused(sim_dir, db):
    """(b1) 窗口内真实删行（快照缺一笔窗口内成交）：拒绝。"""
    res = lgate.check_snapshot_gate(sim_dir, db, 3, 4, today=TODAY)
    assert not res["ok"] and res["check"] == "snapshot_fills", res
    assert "60 天窗口不一致" in res["reason"]


def test_b_db_deletion_refused(sim_dir, db):
    """(b2) 主库删窗口内成交：全量水位拦截，拒绝。"""
    assert lgate.check_snapshot_gate(sim_dir, db, 4, 4, today=TODAY)["ok"]
    con = sqlite3.connect(db)
    con.execute("DELETE FROM fills WHERE id = 5")
    con.execute("UPDATE positions SET qty = 0 WHERE symbol = '600150'")
    con.commit()
    con.close()
    res = lgate.check_snapshot_gate(sim_dir, db, 3, 4, today=TODAY)
    assert not res["ok"] and res["check"] == "db_fills", res


def test_c_no_change_passes(sim_dir, db):
    """(c) 无变化：快照笔数 == 主库窗口笔数 == 上轮，通过。"""
    res = lgate.check_snapshot_gate(sim_dir, db, 4, 4, today=TODAY)
    assert res["ok"], res
