# -*- coding: utf-8 -*-
"""
发布门禁·轻量版（release_gate_light.py）常驻回归测试。

覆盖：基线通过+水位推进、DB 笔数回退拒绝、快照笔数回退拒绝、
账本不一致拒绝、拒绝日志只追加且字段齐全、check-only 不推进水位。
全部跑在临时 fixture 上，不碰生产库与远端。
"""
import json
import os
import sqlite3
import sys

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
FILLS = [
    (1, "2026-10-20", "sim_a", "600150", "BUY", 100.0, 10.0, 1.0, 0.0),
    (2, "2026-10-20", "sim_a", "002472", "BUY", 200.0, 20.0, 1.0, 0.0),
    (3, "2026-10-21", "sim_a", "600150", "SELL", 100.0, 11.0, 1.0, 100.0),
    (4, "2026-10-21", "sim_hk", "HK0354", "BUY", 1000.0, 5.0, 2.0, 0.0),
    (5, "2026-10-22", "sim_a", "600150", "BUY", 50.0, 12.0, 1.0, 0.0),
]
POSITIONS = [("sim_a", "600150", 50.0), ("sim_a", "002472", 200.0),
             ("sim_hk", "HK0354", 1000.0)]


def make_db(path, fills=FILLS, positions=POSITIONS):
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    con.executemany(
        "INSERT INTO fills (id,date,account,symbol,side,qty,price,fee,pnl,"
        "signal_date,strategy_version) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [f + (f[1], "v1.1") for f in fills])
    con.executemany("INSERT INTO positions VALUES (?,?,?)", positions)
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


def test_baseline_passes_and_state_advances(sim_dir, db):
    res = lgate.check_snapshot_gate(sim_dir, db, 13, 13)
    assert res["ok"], res
    state = lgate.load_light_state(sim_dir)
    assert state["fills_count"] == 5


def test_db_count_rollback_refused(sim_dir, db):
    assert lgate.check_snapshot_gate(sim_dir, db, 13, 13)["ok"]
    con = sqlite3.connect(db)
    con.execute("DELETE FROM fills WHERE id = 5")
    con.execute("UPDATE positions SET qty = 0 WHERE symbol = '600150'")
    con.commit()
    con.close()
    res = lgate.check_snapshot_gate(sim_dir, db, 13, 13)
    assert not res["ok"] and res["check"] == "db_fills"
    assert "回退" in res["reason"]


def test_snapshot_fills_decrease_refused(sim_dir, db):
    res = lgate.check_snapshot_gate(sim_dir, db, 12, 13)
    assert not res["ok"] and res["check"] == "snapshot_fills"


def test_ledger_inconsistency_refused(sim_dir, tmp_path):
    bad_db = make_db(tmp_path / "bad.db",
                     positions=[("sim_a", "600150", 999.0)])
    res = lgate.check_snapshot_gate(sim_dir, bad_db, 13, 13)
    assert not res["ok"] and res["check"] == "ledger"


def test_check_only_does_not_advance(sim_dir, db):
    res = lgate.check_snapshot_gate(sim_dir, db, 13, 13, advance=False)
    assert res["ok"]
    assert lgate.load_light_state(sim_dir) is None


def test_refusal_log_append_only_with_fields(sim_dir):
    lgate.record_refusal(sim_dir, "db_fills", "主库 fills 笔数回退：5 → 4")
    fp = os.path.join(sim_dir, "reports", "release_gate_refusals.jsonl")
    assert os.path.exists(fp)
    lgate.record_refusal(sim_dir, "ledger", "账本一致性快速核对失败")
    lines = open(fp, encoding="utf-8").read().strip().splitlines()
    assert len(lines) == 2, "只许追加"
    e = json.loads(lines[0])
    for key in ("ts", "script", "path", "check", "reason"):
        assert e.get(key), f"拒绝日志缺字段 {key}"
    assert e["script"] == "tools/git_sync.py" and e["path"] == "A"
    # 与路径 B 共用同一份拒绝日志（相对路径常量必须一致）
    assert lgate.REFUSAL_LOG_REL.replace(os.sep, "/") == \
        "reports/release_gate_refusals.jsonl"


def test_bypass_audit_written(sim_dir):
    lgate.record_bypass(sim_dir, "用户下令紧急同步")
    fp = os.path.join(sim_dir, "reports", "release_gate_log.jsonl")
    e = json.loads(open(fp, encoding="utf-8").read().strip().splitlines()[-1])
    assert e["event"] == "bypass" and e["path"] == "A"
    assert e["reason"] == "用户下令紧急同步"
