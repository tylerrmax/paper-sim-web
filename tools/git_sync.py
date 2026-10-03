#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
双向同步（跑在 Muse VM 的 cron，每 2 分钟）：
1. git pull：取回网页版经 GitHub API 写入的 commands/pending/*.json
2. 有指令 → 组装成数组，pipe 给 apply_commands.py 执行
   （含重算管线 + 刷新 /tmp/sim_snapshot.json）
3. 把 /tmp/sim_snapshot.json 拷为仓库 snapshot.json；有变化则 commit + push
   （Streamlit Cloud 检测到推送会自动刷新页面）

Token 经环境变量 GITHUB_TOKEN 或 ~/.config/paper-sim-web/github_token 传入，
不进仓库、不进日志。
"""
import base64
import glob
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIM = os.path.expanduser("~/workspace/paper-trading-sim")
SNAP_SRC = "/tmp/sim_snapshot.json"
SNAP_DST = os.path.join(REPO, "snapshot.json")
TOKEN_FILE = os.path.expanduser("~/.config/paper-sim-web/github_token")


def get_token():
    t = os.environ.get("GITHUB_TOKEN", "").strip()
    if t:
        return t
    if os.path.exists(TOKEN_FILE):
        return open(TOKEN_FILE, encoding="utf-8").read().strip()
    return ""


def git(*args):
    """带 token 的 git 调用（Basic auth：任意用户名 + PAT 做密码；
    token 只走 http header，不写 git config、不进仓库）。"""
    token = get_token()
    cfg = []
    if token:
        b64 = base64.b64encode(f"x:{token}".encode()).decode()
        cfg = ["-c", f"http.extraHeader=authorization: Basic {b64}"]
    return subprocess.run(["git", *cfg, *args], cwd=REPO,
                          capture_output=True, text=True, timeout=120)


def main():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    os.chdir(REPO)
    r = git("pull", "--rebase", "--autostash")
    if r.returncode != 0 and "no remote" not in (r.stderr or "").lower():
        print(f"[{now}] git pull 失败: {(r.stderr or '').strip()[-200:]}")
        # 无远端（如尚未部署）则继续本地流程
    applied = []
    pend_files = sorted(glob.glob(os.path.join(REPO, "commands", "pending", "*.json")))
    cmds = []
    for f in pend_files:
        try:
            c = json.load(open(f, encoding="utf-8"))
            if c.get("kind") and c.get("id"):
                cmds.append(c)
        except Exception as e:
            print(f"[{now}] 指令文件解析失败 {f}: {e}")
    if cmds:
        # 归档已消费指令（网页展示"指令历史"；pending 仍按原流程消费删除）
        done_dir = os.path.join(REPO, "commands", "done")
        os.makedirs(done_dir, exist_ok=True)
        for c in cmds:
            dst = os.path.join(done_dir, f'{c["id"]}.json')
            if not os.path.exists(dst):
                rec = dict(c)
                rec["done_ts"] = now
                json.dump(rec, open(dst, "w", encoding="utf-8"),
                          ensure_ascii=False)
        p = subprocess.run(
            [sys.executable, os.path.join(SIM, "apply_commands.py")],
            input=json.dumps(cmds, ensure_ascii=False),
            capture_output=True, text=True, timeout=300, cwd=SIM)
        try:
            # stdout 尾部可能带 sync_snapshot 的摘要行，取最后一行可解析的 JSON
            applied = []
            for line in (p.stdout or "").strip().splitlines()[::-1]:
                try:
                    applied = json.loads(line).get("applied_ids", []) or []
                    break
                except Exception:
                    continue
        except Exception:
            print(f"[{now}] apply_commands 输出解析失败: {(p.stdout or '')[-200:]}")
        for f, c in zip(pend_files, cmds):
            if c.get("id") in applied:
                os.remove(f)
        print(f"[{now}] 执行指令 {len(applied)}/{len(cmds)}: {applied}")
    # 快照同步（/tmp 可能被系统清理：若源不存在则直接重建，只读 DB）
    if not os.path.exists(SNAP_SRC):
        r = subprocess.run(
            [sys.executable, os.path.join(SIM, "sync_snapshot.py")],
            capture_output=True, text=True, timeout=300, cwd=SIM)
        if r.returncode != 0 or not os.path.exists(SNAP_SRC):
            print(f"[{now}] 快照重建失败: {(r.stderr or '')[-200:]}")
    changed = False
    if os.path.exists(SNAP_SRC):
        try:
            data = json.load(open(SNAP_SRC, encoding="utf-8"))
        except Exception as e:
            print(f"[{now}] 快照解析失败: {e}")
            data = None
        if data is not None:
            # 公开仓库隐私：去掉实盘镜像（真实持仓），只留模拟盘数据
            data.pop("real_mirror", None)
            # 滚动条：注入全跟踪标的最新收盘价（只读 DB，不改冻结系统）
            try:
                db = sqlite3.connect(os.path.join(SIM, "db", "sim.db"))
                rows = db.execute(
                    "SELECT symbol, close FROM market_data "
                    "WHERE (symbol, date) IN "
                    "(SELECT symbol, MAX(date) FROM market_data GROUP BY symbol)"
                ).fetchall()
                db.close()
                data["tape"] = [{"symbol": s, "price": c}
                                for s, c in sorted(rows)]
            except Exception as e:
                print(f"[{now}] tape 行情注入失败: {e}")
            new = json.dumps(data, ensure_ascii=False,
                             separators=(",", ":")).encode("utf-8")
            old = open(SNAP_DST, "rb").read() if os.path.exists(SNAP_DST) else b""
            if new != old:
                open(SNAP_DST, "wb").write(new)
                changed = True
    else:
        print(f"[{now}] 快照源不存在: {SNAP_SRC}")
    if changed or applied:
        git("add", "-A")
        msg = f"sync {now}" + (f" ({len(applied)} cmds)" if applied else "")
        r = git("commit", "-m", msg)
        if r.returncode == 0 or "nothing to commit" not in (r.stdout + r.stderr):
            r = git("push")
            if r.returncode != 0:
                print(f"[{now}] git push 失败: {(r.stderr or '').strip()[-200:]}")
            else:
                print(f"[{now}] 已推送: {msg}")
    else:
        print(f"[{now}] 无变化")


if __name__ == "__main__":
    main()
