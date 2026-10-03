#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模拟盘 · 独立网页版（单用户过渡版）

数据：仓库根目录 snapshot.json，由管线经 git 定时推送（每次打开都是最新）。
操作：暂停/开始、自动/手动、批准/跳过 → 经 GitHub API 写入 commands/pending/，
     服务端每 2 分钟轮询取回执行，约 2 分钟内生效。
"""
import base64
import json
import os
import uuid
from datetime import datetime

import requests
import streamlit as st

BASE = os.path.dirname(os.path.abspath(__file__))
SNAP = os.path.join(BASE, "snapshot.json")
VAL_START_A = "2026-10-08"

st.set_page_config(page_title="模拟盘", page_icon="📈", layout="wide")

CSS = """
<style>
html, body, [class*="css"] { font-variant-numeric: tabular-nums; }
.num, .hero-num { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
                  font-variant-numeric: tabular-nums; }
.hero-label { font-size: 13px; color: #888; margin-bottom: 2px; }
.hero-num { font-size: 36px; font-weight: 800; letter-spacing: -0.5px; line-height: 1.15; }
.hero-note { font-size: 12px; color: #999; margin-top: 4px; }
.up { color: #e5484d; } .down { color: #18a058; } .flat { color: #999; }
.strip { border: 1px solid #f0e6c8; border-left: 3px solid #f5a623; border-radius: 8px;
         padding: 10px 12px; margin: 10px 0; background: #fffdf6; }
.strip-ok { border: 1px solid #f0f0f0; border-radius: 8px; padding: 8px 12px;
            margin: 10px 0; color: #aaa; font-size: 13px; }
.strip-title { font-size: 14px; font-weight: 700; margin-bottom: 6px; }
.badge { display: inline-block; min-width: 22px; text-align: center; padding: 1px 8px;
         border-radius: 999px; background: #f5a623; color: #fff;
         font-size: 12px; font-weight: 700; }
.empty { padding: 14px 2px; }
.empty b { display: block; font-size: 15px; color: #666; margin-bottom: 4px; }
.empty span { font-size: 13px; color: #aaa; }
.pill { display: inline-block; padding: 2px 12px; border-radius: 999px;
        font-size: 12px; background: #f5f5f5; color: #666; margin-right: 6px; }
.pill.run { background: #e6f6ec; color: #18a058; }
.pill.pause { background: #fdeeee; color: #e5484d; }
.sec { font-size: 16px; font-weight: 700; margin: 22px 0 8px; }
.kv { display: flex; justify-content: space-between; padding: 7px 2px;
      border-bottom: 1px solid #f5f5f5; font-size: 14px; }
.kv .k { color: #888; } .kv .v { font-weight: 600; }
.hairline { border: none; border-top: 1px solid #f0f0f0; margin: 18px 0; }
.foot { font-size: 12px; color: #bbb; margin-top: 26px; }
.sig-row { display: flex; align-items: center; justify-content: space-between;
           padding: 8px 2px; border-bottom: 1px solid #f7f7f7; font-size: 14px; }
.chart-label { font-size: 13px; color: #888; margin: 20px 0 6px; }
.chart-legend { font-size: 12px; color: #888; margin-top: 6px; }
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 4px; }
@media (max-width: 768px) {
  div[data-testid="column"] { min-width: 100% !important; }
}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# ---------- 密码门 ----------
def check_auth():
    pw_cfg = st.secrets.get("APP_PASSWORD", "")
    if not pw_cfg:
        st.error("本站尚未配置访问密码（Streamlit Secrets 缺少 APP_PASSWORD）。")
        st.stop()
    if st.session_state.get("authed"):
        return
    st.markdown("### 模拟盘")
    pw = st.text_input("访问密码", type="password")
    if st.button("进入", type="primary"):
        if pw == pw_cfg:
            st.session_state["authed"] = True
            st.rerun()
        else:
            st.error("密码错误")
    st.stop()


check_auth()


# ---------- 数据 ----------
@st.cache_data(ttl=60)
def load_snapshot():
    if not os.path.exists(SNAP):
        return None
    try:
        return json.load(open(SNAP, encoding="utf-8"))
    except Exception:
        return None


snap = load_snapshot()
if not snap:
    st.markdown('<div class="empty"><b>数据尚未同步</b>'
                '<span>管线正在推送第一份快照，稍后刷新重试</span></div>',
                unsafe_allow_html=True)
    st.stop()

accts = {a["account"]: a for a in snap.get("accounts", [])}
pend = snap.get("pending_signals", []) or []
control = snap.get("control", {})
asof = snap.get("asof", "—")


def f2(x):
    return "—" if x is None else f"{x:,.2f}"


def pnl_html(x):
    if x is None:
        return '<span class="num flat">—</span>'
    cls = "up" if x > 0 else ("down" if x < 0 else "flat")
    arrow = "▲" if x > 0 else ("▼" if x < 0 else "")
    return f'<span class="num {cls}">{arrow} {x:+,.2f}</span>'


def pct_html(r):
    if r is None:
        return '<span class="num flat">—</span>'
    return pnl_html(r * 100).replace("+,", "+").replace("- ,", "-")


def side_cn(s):
    return "买入" if s == "BUY" else ("卖出" if s == "SELL" else s)


# ---------- 指令下发（经 GitHub API 写指令文件） ----------
def queue_command(kind, payload):
    token = st.secrets.get("GITHUB_TOKEN", "")
    repo = st.secrets.get("GITHUB_REPO", "")
    if not token or not repo:
        st.error("未配置 GITHUB_TOKEN / GITHUB_REPO，无法提交指令")
        return False
    fid = uuid.uuid4().hex[:10]
    body = {"id": fid, "kind": kind,
            "payload_json": json.dumps(payload, ensure_ascii=False),
            "status": "queued",
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    content = base64.b64encode(
        json.dumps(body, ensure_ascii=False).encode("utf-8")).decode()
    try:
        r = requests.put(
            f"https://api.github.com/repos/{repo}/contents/commands/pending/{fid}.json",
            headers={"Authorization": f"Bearer {token}",
                     "Accept": "application/vnd.github+json"},
            json={"message": f"cmd:{kind}:{fid}", "content": content},
            timeout=20)
    except Exception as e:
        st.error(f"提交失败：{e}")
        return False
    if r.status_code in (200, 201):
        st.toast("指令已提交，约2分钟内生效")
        return True
    st.error(f"提交失败（{r.status_code}）")
    return False


# ---------- 净值走势（起点=100，日期对齐） ----------
def nav_chart_svg(equity):
    series = []
    for aid, label, color in (("sim_hk", "港股", "#1a1a1a"),
                             ("sim_crypto", "加密", "#e5484d")):
        pts = equity.get(aid) or []
        if len(pts) < 2 or not pts[0][1]:
            continue
        base = pts[0][1]
        series.append((label, color, [(d, v / base * 100) for d, v in pts]))
    if not series:
        return
    dates = sorted({d for _, _, pts in series for d, _ in pts})
    W, H, PT, PB = 600, 170, 14, 22
    aligned = []
    for label, color, pts in series:
        m = dict(pts)
        vals, last = [], None
        for d in dates:
            if d in m:
                last = m[d]
            vals.append(last)
        start = next(i for i, v in enumerate(vals) if v is not None)
        aligned.append((label, color, vals[start:], start))
    allv = [v for _, _, vals, _ in aligned for v in vals]
    lo, hi = min(allv), max(allv)
    pad = max((hi - lo) * 0.15, 0.5)
    lo, hi = lo - pad, hi + pad

    def X(i):
        return (i / (len(dates) - 1) * W) if len(dates) > 1 else W / 2

    def Y(v):
        return PT + (1 - (v - lo) / (hi - lo)) * (H - PT - PB)

    parts = []
    if lo < 100 < hi:
        y0 = Y(100)
        parts.append(f'<line x1="0" y1="{y0:.1f}" x2="{W}" y2="{y0:.1f}" '
                     'stroke="#ddd" stroke-dasharray="4 3"/>')
    for label, color, vals, start in aligned:
        pts_str = " ".join(f"{X(start + i):.1f},{Y(v):.1f}"
                           for i, v in enumerate(vals))
        parts.append(f'<polyline points="{pts_str}" fill="none" '
                     f'stroke="{color}" stroke-width="2"/>')
        ex, ey = X(start + len(vals) - 1), Y(vals[-1])
        parts.append(f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="3" fill="{color}"/>')
        parts.append(f'<text x="{ex - 5:.1f}" y="{ey - 8:.1f}" font-size="11" '
                     f'fill="{color}" text-anchor="end">{vals[-1]:.1f}</text>')
    parts.append(f'<text x="2" y="{Y(hi) + 11:.1f}" font-size="10" '
                 f'fill="#aaa">{hi:.1f}</text>')
    parts.append(f'<text x="2" y="{Y(lo) - 3:.1f}" font-size="10" '
                 f'fill="#aaa">{lo:.1f}</text>')
    parts.append(f'<text x="2" y="{H - 6:.1f}" font-size="10" '
                 f'fill="#aaa">{dates[0]}</text>')
    parts.append(f'<text x="{W - 2:.1f}" y="{H - 6:.1f}" font-size="10" '
                 f'fill="#aaa" text-anchor="end">{dates[-1]}</text>')
    svg = (f'<svg viewBox="0 0 {W} {H}" style="width:100%;height:auto">'
           f'{"".join(parts)}</svg>')
    legend = " &nbsp; ".join(
        f'<span class="dot" style="background:{c}"></span>{l}'
        for l, c, _ in series)
    st.markdown('<div class="chart-label">净值走势（起点=100）</div>',
                unsafe_allow_html=True)
    st.markdown(svg, unsafe_allow_html=True)
    st.markdown(f'<div class="chart-legend">{legend}</div>', unsafe_allow_html=True)


# ---------- 页眉 ----------
st.markdown("### 模拟盘")
st.caption(f"数据截至 {asof} · 规则 {snap.get('rule_version', '—')}")
stt, mod = control.get("status"), control.get("mode")
st.markdown(
    f'<span class="pill {"run" if stt == "running" else "pause"}">'
    f'{"运行中" if stt == "running" else "已暂停"}</span>'
    f'<span class="pill">{"自动" if mod == "auto" else "手动"}</span>',
    unsafe_allow_html=True)

# ---------- 控制条 ----------
c1, c2 = st.columns(2)
if c1.button("⏸ 暂停" if stt == "running" else "▶ 开始", width="stretch"):
    if queue_command("set_status", {"status": "paused" if stt == "running" else "running"}):
        st.rerun()
if c2.button("切手动" if mod == "auto" else "切自动", width="stretch"):
    if queue_command("set_mode", {"mode": "manual" if mod == "auto" else "auto"}):
        st.rerun()
st.caption("操作约2分钟内生效")

# ---------- 净值走势（组合锚点） ----------
nav_chart_svg(snap.get("equity", {}) or {})

col_stock, col_crypto = st.columns(2)


# ---------- 通用组件 ----------
def pending_strip(items, zone):
    """非警报式细条：计数 + 行内批准/跳过；零状态收成 hairline。"""
    if not items:
        st.markdown('<div class="strip-ok">暂无待审批信号</div>',
                    unsafe_allow_html=True)
        return
    st.markdown(
        f'<div class="strip"><div class="strip-title">'
        f'<span class="badge">{len(items)}</span> 待审批 · {zone}</div></div>',
        unsafe_allow_html=True)
    for p in items:
        r1, r2, r3 = st.columns([5, 2, 2])
        with r1:
            st.markdown(
                f'<div class="sig-row"><span class="num">{p["date"]} '
                f'{p["symbol"]} {side_cn(p["side"])} @{f2(p.get("price"))}'
                f'</span></div>', unsafe_allow_html=True)
        key = f'{p["account"]}_{p["date"]}_{p["symbol"]}_{p["side"]}'
        if r2.button("批准", key="ap_" + key):
            if queue_command("approve", {"date": p["date"], "account": p["account"],
                                         "symbol": p["symbol"], "side": p["side"]}):
                st.rerun()
        if r3.button("跳过", key="sk_" + key):
            if queue_command("skip", {"date": p["date"], "account": p["account"],
                                      "symbol": p["symbol"], "side": p["side"]}):
                st.rerun()


def account_card(aid, label, not_started_text=None):
    a = accts.get(aid, {})
    ccy = a.get("ccy", "")
    st.markdown(f'<div class="sec">{label} · {ccy}</div>', unsafe_allow_html=True)
    if not_started_text:
        st.markdown(f'<div class="empty"><b>{label}待启动</b>'
                    f'<span>{not_started_text}</span></div>', unsafe_allow_html=True)
        return
    rows = [
        ("总资产", f'<span class="num">{f2(a.get("nav"))}</span>'),
        ("现金", f'<span class="num">{f2(a.get("cash"))}</span>'),
        ("持仓市值", f'<span class="num">{f2(a.get("position_value"))}</span>'),
        ("当日盈亏", pnl_html(a.get("pnl_day"))),
        ("累计回报", pnl_html((a.get("ret_total") or 0) * 100).replace("+.", "+").replace("-.", "-") + " %"
         if a.get("ret_total") is not None else '<span class="num flat">—</span>'),
        ("已实现盈亏", pnl_html(a.get("realized_pnl"))),
    ]
    for k, v in rows:
        st.markdown(f'<div class="kv"><span class="k">{k}</span>'
                    f'<span class="v">{v}</span></div>', unsafe_allow_html=True)
    # 持仓
    poss = [p for p in snap.get("positions", []) if p.get("account") == aid]
    st.markdown('<div class="sec" style="font-size:14px">持仓</div>', unsafe_allow_html=True)
    if not poss:
        st.markdown('<div class="empty"><b>运行中 · 全现金</b>'
                    '<span>暂无持仓，有信号会在顶部出现</span></div>',
                    unsafe_allow_html=True)
    else:
        for p in poss:
            st.markdown(
                f'<div class="kv"><span class="k num">{p["symbol"]} × {p["qty"]:g}</span>'
                f'<span class="v num">{f2(p.get("market_value"))}</span></div>',
                unsafe_allow_html=True)
    # 信号与成交（折叠，保持精简）
    sigs = [s for s in snap.get("signals", []) if s.get("account") == aid][:20]
    fills = [f for f in snap.get("fills", []) if f.get("account") == aid][:20]
    with st.expander(f"近期信号（{len(sigs)}）/ 成交（{len(fills)}）"):
        if sigs:
            st.dataframe(
                [{"日期": s["date"], "标的": s["symbol"],
                  "方向": side_cn(s["side"]), "信号价": s.get("price")}
                 for s in sigs], use_container_width=True, hide_index=True)
        else:
            st.caption("暂无信号")
        if fills:
            st.dataframe(
                [{"日期": f["date"], "标的": f["symbol"], "方向": side_cn(f["side"]),
                  "数量": f.get("qty"), "成交价": f.get("price"),
                  "费用": f.get("fee"), "盈亏": f.get("pnl")}
                 for f in fills], use_container_width=True, hide_index=True)
        else:
            st.caption("暂无成交")


# ---------- 股票 ----------
with col_stock:
    pool = snap.get("stock_pool", {}) or {}
    total = pool.get("total_cny")
    st.markdown('<div class="hero-label">总资产 · CNY</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="hero-num num">{f2(total)}</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="hero-note">港股按当日 HKDCNY {pool.get("hkdcny") or "—"} 折算；'
        '明细仍按原生币种独立记账</div>', unsafe_allow_html=True)
    st.markdown('<hr class="hairline"/>', unsafe_allow_html=True)

    pend_stock = [p for p in pend if p.get("account") in ("sim_a", "sim_hk")]
    pending_strip(pend_stock, "股票队列")

    a_not_started = (asof < VAL_START_A and
                     not [f for f in snap.get("fills", []) if f.get("account") == "sim_a"])
    account_card("sim_a", "A股",
                 not_started_text="验证期 10-08 开始，届时信号会出现在这里"
                 if a_not_started else None)
    account_card("sim_hk", "港股")

# ---------- 加密货币 ----------
with col_crypto:
    a = accts.get("sim_crypto", {})
    st.markdown('<div class="hero-label">总资产 · USDT</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="hero-num num">{f2(a.get("nav"))}</div>', unsafe_allow_html=True)
    st.markdown('<div class="hero-note">每日更新一次（UTC 日K收盘后）</div>',
                unsafe_allow_html=True)
    st.markdown('<hr class="hairline"/>', unsafe_allow_html=True)

    pend_crypto = [p for p in pend if p.get("account") == "sim_crypto"]
    pending_strip(pend_crypto, "加密队列")
    account_card("sim_crypto", "加密账户")

# ---------- 轮动门 / 毕业进度 ----------
col_rg, col_grad = st.columns(2)
with col_rg:
    rg = snap.get("rotation_gate", {}) or {}
    st.markdown(f'<div class="sec">轮动门槛（{rg.get("met", 0)}/{rg.get("total", 3)} 项满足）</div>', unsafe_allow_html=True)
    for it in rg.get("items", []):
        st.markdown(
            f'<div class="kv"><span class="k">{it["label"]} '
            f'<span class="num">{it["value"] if it["value"] is not None else "—"}{it.get("unit", "")}</span></span>'
            f'<span class="v">{it.get("status", "")}</span></div>',
            unsafe_allow_html=True)
    st.caption(rg.get("note", ""))

with col_grad:
    st.markdown('<div class="sec">毕业进度</div>', unsafe_allow_html=True)
    g = snap.get("graduation", {}) or {}
    tg = g.get("targets", {})
    for aid, label in (("sim_a", "A股"), ("sim_hk", "港股"), ("sim_crypto", "加密")):
        ga = (g.get("accounts", {}) or {}).get(aid, {})
        n = ga.get("round_trips") or 0
        wlr = ga.get("win_loss_ratio")
        mdd = ga.get("max_drawdown")
        wlr_ok = wlr is not None and wlr >= (tg.get("win_loss_ratio") or 3.0)
        mdd_ok = mdd is not None and mdd <= (tg.get("max_drawdown") or 0.10)
        st.markdown(
            f'<div class="kv"><span class="k">{label}'
            f'<span class="num">（{n}/{tg.get("sample_min", 20)}–{tg.get("sample_max", 30)}笔）</span></span>'
            f'<span class="v num">盈亏比 '
            f'<span class="{"up" if wlr_ok else "flat"}">{f2(wlr)}</span>'
            f'（硬线≥{tg.get("win_loss_ratio", 3.0):g}） · 回撤 '
            f'<span class="{"up" if mdd_ok else "flat"}">'
            f'{f"{mdd * 100:.1f}%" if mdd is not None else "—"}</span>'
            f'（≤{(tg.get("max_drawdown") or 0.10) * 100:.0f}%）</span></div>',
            unsafe_allow_html=True)
    st.caption(g.get("execution_note", ""))

st.markdown(
    f'<div class="foot">规则版本 {snap.get("rule_version", "—")} · '
    '信号按日收盘价成交 · 滑点 0.2% · 本站为模拟盘，不构成投资建议</div>',
    unsafe_allow_html=True)
