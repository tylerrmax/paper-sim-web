#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
发布门禁·轻量版（路径 A：paper-sim-web/tools/git_sync.py 每 2 分钟同步）。

秒级检查，位于快照发布（写 snapshot.json / commit / push）之前；指令的
拉取与执行在门禁之前完成，不受门禁影响。检查项：
  1. db_fills：主库 fills COUNT 不得低于轻量水位（上次通过时见到的 COUNT，
     存主仓库根 .release_gate_light_state.json，不在任何推送白名单内）；
  2. snapshot_fills：新快照 fills 笔数不得少于上轮已推快照的笔数；
  3. ledger：纯 SQL 快速核对 positions == fills 净额汇总（<1 秒）。
任一不过 → git_sync 打印「发布门禁拒绝：<原因>」、本轮不发布快照、以
exit 3 结束，并把拒绝写入与路径 B 共用的持久拒绝日志：
  <主仓库>/reports/release_gate_refusals.jsonl（只追加；该目录不在
  sync_8502_github.py 的 FILES 白名单内，也不在 paper-sim-web 仓库内，
  不会被任何同步推送或覆盖）。
--force-bypass 时跳过检查，但必须打印醒目行并写审计日志（同目录
release_gate_log.jsonl），且不推进轻量水位。
"""
import json
import os
import sqlite3
from datetime import datetime

REJECT_LINE = "发布门禁拒绝"
BYPASS_LINE = "发布门禁已被绕过"
LIGHT_STATE_NAME = ".release_gate_light_state.json"
REFUSAL_LOG_REL = os.path.join("reports", "release_gate_refusals.jsonl")
AUDIT_LOG_REL = os.path.join("reports", "release_gate_log.jsonl")
SCRIPT_NAME = "tools/git_sync.py"


def _ro(db_path):
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def db_fills_count(db_path):
    con = _ro(db_path)
    try:
        return con.execute("SELECT COUNT(*) FROM fills").fetchone()[0]
    finally:
        con.close()


def ledger_errors(db_path):
    """check_ledger_consistency 的等价纯 SQL 版（只读、秒级）。"""
    con = _ro(db_path)
    try:
        pos = {(a, s): q for a, s, q in con.execute(
            "SELECT account, symbol, qty FROM positions")}
        net = {(a, s): (q or 0) for a, s, q in con.execute(
            "SELECT account, symbol, "
            "SUM(CASE WHEN side='BUY' THEN qty ELSE -qty END) "
            "FROM fills GROUP BY account, symbol")}
    finally:
        con.close()
    errs = []
    for key in sorted(set(pos) | set(net)):
        if abs(pos.get(key, 0) - net.get(key, 0)) > 1e-6:
            errs.append(f"分叉 {key}: positions={pos.get(key, 0)} "
                        f"vs fills净值={net.get(key, 0)}")
    for key, q in net.items():
        if q < -1e-9:
            errs.append(f"负持仓 {key}: fills净值={q}")
    return errs


def _state_path(sim_dir):
    return os.path.join(sim_dir, LIGHT_STATE_NAME)


def load_light_state(sim_dir):
    p = _state_path(sim_dir)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _save_light_state(sim_dir, count):
    state = {"version": 1, "fills_count": count,
             "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    tmp = _state_path(sim_dir) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _state_path(sim_dir))
    return state


def _append_jsonl(sim_dir, rel, entry):
    entry = dict(entry)
    entry.setdefault("ts", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    try:
        fp = os.path.join(sim_dir, rel)
        os.makedirs(os.path.dirname(fp), exist_ok=True)
        with open(fp, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"警告：门禁日志写入失败：{type(e).__name__}: {e}")
    return entry


def record_refusal(sim_dir, check, reason):
    """把一次轻量门禁拒绝写入共用的持久拒绝日志（只追加）。"""
    return _append_jsonl(sim_dir, REFUSAL_LOG_REL, {
        "script": SCRIPT_NAME, "path": "A", "check": check,
        "reason": reason})


def record_bypass(sim_dir, reason):
    """绕过留痕：写审计日志（调用方同时打印醒目行）。"""
    return _append_jsonl(sim_dir, AUDIT_LOG_REL, {
        "script": SCRIPT_NAME, "path": "A", "event": "bypass",
        "reason": reason, "skipped": ["db_fills", "snapshot_fills",
                                      "ledger"]})


def record_pass(sim_dir, detail, event="pass"):
    """门禁通过留痕：写审计日志（与拒绝/绕过共用同一份审计文件），
    使每一次门禁判定（通过/拒绝/绕过，含 check-only）在审计日志里都可查。"""
    return _append_jsonl(sim_dir, AUDIT_LOG_REL, {
        "script": SCRIPT_NAME, "path": "A", "event": event,
        "detail": detail})


def check_snapshot_gate(sim_dir, db_path, new_snapshot_fills,
                        last_snapshot_fills, advance=True):
    """
    执行轻量门禁。返回 {"ok", "check", "reason", "detail"}：
    ok=False 时 check/reason 给出失败项与原因（调用方负责打印拒绝行、
    落拒绝日志、跳过发布）。advance=True 且通过时推进轻量水位
    （--gate-check-only 时传 False）。
    """
    def refuse(check, reason):
        return {"ok": False, "check": check, "reason": reason,
                "detail": None}

    try:
        db_count = db_fills_count(db_path)
    except Exception as e:
        return refuse("db_fills", f"主库 fills 读取失败："
                                  f"{type(e).__name__}: {e}")
    state = load_light_state(sim_dir)
    if state is not None and db_count < state["fills_count"]:
        return refuse(
            "db_fills",
            f"主库 fills 笔数回退：水位 {state['fills_count']} → 实查 "
            f"{db_count}（疑似旧库/回滚库，拒绝用其快照覆盖线上）")
    if (last_snapshot_fills is not None and new_snapshot_fills is not None
            and new_snapshot_fills < last_snapshot_fills):
        return refuse(
            "snapshot_fills",
            f"快照 fills 笔数回退：上轮已推 {last_snapshot_fills} → 本轮 "
            f"{new_snapshot_fills}")
    errs = ledger_errors(db_path)
    if errs:
        return refuse("ledger",
                      "账本一致性快速核对失败：" + "；".join(errs))
    if advance:
        prev = (state or {}).get("fills_count", 0)
        if db_count > prev:
            _save_light_state(sim_dir, db_count)
    return {"ok": True, "check": None, "reason": None,
            "detail": f"db_fills={db_count}，snapshot_fills="
                      f"{new_snapshot_fills}（上轮 {last_snapshot_fills}），"
                      f"账本一致"}
