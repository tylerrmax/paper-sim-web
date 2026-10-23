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


# ---------- GitHub API 降级传输（2026-10-23：VM 到 github.com 的 git 协议
# 频繁被重置，api.github.com 正常。git pull/push 失败时走 API，保证同步不断） ----------
API_BASE = "https://api.github.com"
GH_OWNER, GH_REPO = "tylerrmax", "paper-sim-web"
GH_BRANCH = "main"


def _api(method, path, data=None):
    """最小 GitHub REST 调用，返回解析后的 JSON。"""
    import urllib.request
    token = get_token()
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(API_BASE + path, data=body, method=method,
                                 headers={"Accept": "application/vnd.github+json",
                                          "Content-Type": "application/json",
                                          "Authorization": f"Bearer {token}",
                                          "User-Agent": "paper-sim-git-sync"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
        return json.loads(raw.decode()) if raw else {}


def api_pull_pending():
    """经 API 拉回 commands/pending/*.json 到本地。成功返回 {文件名: blob_sha}，
    失败返回 None。"""
    try:
        items = _api("GET", f"/repos/{GH_OWNER}/{GH_REPO}/contents/"
                            f"commands/pending?ref={GH_BRANCH}")
    except Exception as e:
        print(f"API 拉取 pending 失败: {e}")
        return None
    if not isinstance(items, list):
        return None
    shas = {}
    for it in items:
        name = it.get("name", "")
        if not name.endswith(".json") or it.get("type") != "file":
            continue
        try:
            blob = _api("GET", f"/repos/{GH_OWNER}/{GH_REPO}/git/blobs/"
                               f"{it['sha']}")
            content = base64.b64decode(blob["content"]).decode("utf-8")
        except Exception as e:
            print(f"API 下载 {name} 失败: {e}")
            return None
        dst = os.path.join(REPO, "commands", "pending", name)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "w", encoding="utf-8") as f:
            f.write(content)
        shas[name] = it["sha"]
    return shas


def api_push(changes, message):
    """经 API 一次提交推送 changes：[(path, bytes|None)]，None=删除。
    成功返回 True。"""
    try:
        ref = _api("GET", f"/repos/{GH_OWNER}/{GH_REPO}/git/refs/heads/{GH_BRANCH}")
        base_sha = ref["object"]["sha"]
        base_tree = _api("GET", f"/repos/{GH_OWNER}/{GH_REPO}/git/commits/{base_sha}")["tree"]["sha"]
        tree_items = []
        for path, content in changes:
            if content is None:
                tree_items.append({"path": path, "mode": "100644",
                                   "type": "blob", "sha": None})
            else:
                blob = _api("POST", f"/repos/{GH_OWNER}/{GH_REPO}/git/blobs",
                            {"content": base64.b64encode(content).decode(),
                             "encoding": "base64"})
                tree_items.append({"path": path, "mode": "100644",
                                   "type": "blob", "sha": blob["sha"]})
        tree = _api("POST", f"/repos/{GH_OWNER}/{GH_REPO}/git/trees",
                    {"base_tree": base_tree, "tree": tree_items})
        commit = _api("POST", f"/repos/{GH_OWNER}/{GH_REPO}/git/commits",
                      {"message": message, "tree": tree["sha"],
                       "parents": [base_sha]})
        _api("PATCH", f"/repos/{GH_OWNER}/{GH_REPO}/git/refs/heads/{GH_BRANCH}",
             {"sha": commit["sha"]})
        return True
    except Exception as e:
        print(f"API 推送失败: {e}")
        return False


def main():
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    os.chdir(REPO)
    r = git("pull", "--rebase", "--autostash")
    pull_ok = (r.returncode == 0)
    api_shas = None
    if not pull_ok and "no remote" not in (r.stderr or "").lower():
        print(f"[{now}] git pull 失败: {(r.stderr or '').strip()[-200:]}，改走 API 拉取")
        api_shas = api_pull_pending()
        if api_shas is not None:
            print(f"[{now}] API 拉取 pending 完成（{len(api_shas)} 个文件）")
        # 无远端（如尚未部署）则继续本地流程
    applied = []
    applied_ids = []
    # 只有远端读取成功才消费指令，避免用陈旧本地文件重复执行
    if pull_ok or api_shas is not None:
        pend_files = sorted(glob.glob(os.path.join(REPO, "commands", "pending", "*.json")))
    else:
        pend_files = []
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
                applied_ids.append(os.path.basename(f))
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
            # 滚动条 + K线：注入全跟踪标的最新收盘/涨跌幅 + 近60根日K（只读 DB，不改冻结系统）
            try:
                db = sqlite3.connect(os.path.join(SIM, "db", "sim.db"))
                latest = db.execute(
                    "SELECT symbol, date, close FROM market_data "
                    "WHERE (symbol, date) IN "
                    "(SELECT symbol, MAX(date) FROM market_data GROUP BY symbol)"
                ).fetchall()
                tape, klines = [], {}
                for s, d, c in sorted(latest):
                    prev = db.execute(
                        "SELECT close FROM market_data "
                        "WHERE symbol=? AND date<? ORDER BY date DESC LIMIT 1",
                        (s, d)).fetchone()
                    chg = (c / prev[0] - 1) * 100 if prev and prev[0] else None
                    tape.append({"symbol": s, "price": c, "change_pct": chg})
                    krows = db.execute(
                        "SELECT date, open, high, low, close FROM market_data "
                        "WHERE symbol=? ORDER BY date DESC LIMIT 60",
                        (s,)).fetchall()
                    klines[s] = [[r[0][5:], r[1], r[2], r[3], r[4]]
                                 for r in reversed(krows)]
                db.close()
                data["tape"] = tape
                data["klines"] = klines
            except Exception as e:
                print(f"[{now}] tape/K线注入失败: {e}")
            new = json.dumps(data, ensure_ascii=False,
                             separators=(",", ":")).encode("utf-8")
            old = open(SNAP_DST, "rb").read() if os.path.exists(SNAP_DST) else b""
            if new != old:
                open(SNAP_DST, "wb").write(new)
                changed = True
    else:
        print(f"[{now}] 快照源不存在: {SNAP_SRC}")
    if changed or applied:
        msg = f"sync {now}" + (f" ({len(applied)} cmds)" if applied else "")
        git("add", "-A")
        r = git("commit", "-m", msg)
        push_done = False
        if r.returncode == 0 or "nothing to commit" not in (r.stdout + r.stderr):
            r = git("push")
            if r.returncode != 0:
                print(f"[{now}] git push 失败: {(r.stderr or '').strip()[-200:]}，改走 API 推送")
            else:
                push_done = True
                print(f"[{now}] 已推送: {msg}")
        if not push_done:
            # API 降级推送：snapshot.json + 新归档 done 文件 + 删除已消费 pending
            changes = []
            if changed and os.path.exists(SNAP_DST):
                changes.append(("snapshot.json", open(SNAP_DST, "rb").read()))
            done_dir = os.path.join(REPO, "commands", "done")
            for cid in applied:
                for ff in glob.glob(os.path.join(done_dir, f"{cid}.json")):
                    rel = os.path.relpath(ff, REPO)
                    changes.append((rel, open(ff, "rb").read()))
            for name in applied_ids:
                changes.append((f"commands/pending/{name}", None))
            if changes and api_push(changes, msg):
                print(f"[{now}] 已经 API 推送: {msg}")
            else:
                print(f"[{now}] 推送失败：git 与 API 均不可用，下轮重试")
    else:
        print(f"[{now}] 无变化")


if __name__ == "__main__":
    main()
