#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模拟盘 · 独立网页版（单用户过渡版）

数据：仓库根目录 snapshot.json，由管线经 git 定时推送（每次打开都是最新）。
操作：暂停/开始、自动/手动、批准/跳过 → 经 GitHub API 写入 commands/pending/，
     服务端每 2 分钟轮询取回执行，约 2 分钟内生效。
"""
import base64
import glob
import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime, timedelta, date

import requests
import streamlit as st

BASE = os.path.dirname(os.path.abspath(__file__))
SNAP = os.path.join(BASE, "snapshot.json")
VAL_START_A = "2026-10-08"

st.set_page_config(page_title="验证终端", page_icon="📈", layout="wide")

CSS = """
<style>
html, body, [class*="css"] { font-variant-numeric: tabular-nums; }
.num, .hero-num { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
                  font-variant-numeric: tabular-nums; }
.hero-label { font-size: 12px; color: #7a7f8c; margin-bottom: 2px; letter-spacing: 1px; }
.hero-num { font-size: 34px; font-weight: 800; letter-spacing: -0.5px; line-height: 1.15; }
.hero-note { font-size: 12px; color: #5f6572; margin-top: 4px; }
.en-tag { font-size: 12px; color: #4a4f5c; letter-spacing: 3px; font-weight: 400;
          margin-left: 10px; vertical-align: middle; }
.up { color: #f6465d; } .down { color: #2ebd85; } .flat { color: #5f6572; }
.strip { border: 1px solid rgba(240,185,11,.35); border-left: 3px solid #f0b90b; border-radius: 6px;
         padding: 8px 12px; margin: 10px 0; background: rgba(240,185,11,.06); }
.strip-ok { border: 1px solid #1e232e; border-radius: 6px; padding: 7px 12px;
            margin: 10px 0; color: #7a7f8c; font-size: 13px; background: #10141b; }
.strip-title { font-size: 14px; font-weight: 700; margin-bottom: 6px; }
.badge { display: inline-block; min-width: 22px; text-align: center; padding: 1px 8px;
         border-radius: 999px; background: #f0b90b; color: #0b0e11;
         font-size: 12px; font-weight: 700; }
.empty { padding: 12px 2px; }
.empty b { display: block; font-size: 14px; color: #aab; margin-bottom: 4px; }
.empty span { font-size: 13px; color: #5f6572; }
.pill { display: inline-block; padding: 2px 12px; border-radius: 4px;
        font-size: 12px; background: #1e232e; color: #aab; margin-right: 6px; }
.pill.run { background: rgba(46,189,133,.12); color: #2ebd85; }
.pill.pause { background: rgba(246,70,93,.12); color: #f6465d; }
.sec { font-size: 14px; font-weight: 700; margin: 16px 0 6px; letter-spacing: .5px; color: #c9cdd6; }
.kv { display: flex; justify-content: space-between; padding: 5px 2px;
      border-bottom: 1px solid #161b24; font-size: 13px; }
.kv .k { color: #7a7f8c; } .kv .v { font-weight: 600; }
table.pos { width: 100%; border-collapse: collapse; font-size: 12.5px; margin: 2px 0 8px; }
table.pos th { text-align: right; color: #5f6572; font-weight: 400; padding: 4px 2px;
               border-bottom: 1px solid #1e232e; white-space: nowrap; }
table.pos th:first-child { text-align: left; }
table.pos td { text-align: right; padding: 5px 2px; border-bottom: 1px solid #161b24;
               white-space: nowrap; }
table.pos td:first-child { text-align: left; color: #c9cdd6; font-weight: 600; }
.hairline { border: none; border-top: 1px solid #161b24; margin: 14px 0; }
.foot { font-size: 12px; color: #4a4f5c; margin-top: 26px; }
.sig-row { display: flex; align-items: center; justify-content: space-between;
           padding: 6px 2px; border-bottom: 1px solid #161b24; font-size: 13px; }
.chart-label { font-size: 12px; color: #7a7f8c; margin: 16px 0 6px; letter-spacing: 1px; }
.chart-legend { font-size: 12px; color: #7a7f8c; margin-top: 6px; }
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 4px; }
.livedot { display: inline-block; width: 8px; height: 8px; border-radius: 50%;
           background: #2ebd85; margin-right: 6px; animation: pulse 2s infinite; }
@keyframes pulse {
  0% { box-shadow: 0 0 0 0 rgba(46,189,133,.45); }
  70% { box-shadow: 0 0 0 8px rgba(46,189,133,0); }
  100% { box-shadow: 0 0 0 0 rgba(46,189,133,0); }
}
.tape { overflow: hidden; white-space: nowrap; border-top: 1px solid #161b24;
        border-bottom: 1px solid #161b24; padding: 7px 0; margin: 0 0 14px;
        background: #0e1218; container-type: inline-size; }
.tape-inner { display: inline-block; animation: tapesway 18s ease-in-out infinite alternate; }
@keyframes tapesway {
  from { transform: translateX(0); }
  to { transform: translateX(min(0px, calc(100cqw - 100%))); }
}
.tape-item { display: inline-block; margin-right: 42px; font-size: 13px; color: #7a7f8c; }
.tape-item:last-child { margin-right: 0; }
.tape-item .num { color: #c9cdd6; }
.ev-row { display: flex; align-items: baseline; padding: 6px 2px;
          border-bottom: 1px solid #161b24; font-size: 13px; }
.ev-date { color: #5f6572; margin-right: 8px; white-space: nowrap; }
.etag { display: inline-block; padding: 1px 8px; border-radius: 4px;
        font-size: 12px; margin-right: 8px; white-space: nowrap; }
.etag-sig { background: rgba(240,185,11,.14); color: #f0b90b; }
.etag-fill { background: rgba(46,189,133,.14); color: #2ebd85; }
.etag-cmd { background: rgba(122,127,140,.16); color: #8b93a5; }
#MainMenu { visibility: hidden; }
footer { visibility: hidden; }
@media (max-width: 768px) {
  div[data-testid="column"] { min-width: 100% !important; }
}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# ---------- 密码门（含 30 天记住我） ----------
REMEMBER_COOKIE = "vterm_remember"
REMEMBER_DAYS = 30


def _remember_token():
    pw_cfg = st.secrets.get("APP_PASSWORD", "")
    if not pw_cfg:
        return None
    return hmac.new(pw_cfg.encode("utf-8"), b"vterm-remember-v1",
                    hashlib.sha256).hexdigest()


def _cookie_mgr():
    try:
        from extra_streamlit_components import CookieManager
        return CookieManager()
    except Exception:
        return None


def check_auth():
    pw_cfg = st.secrets.get("APP_PASSWORD", "")
    if not pw_cfg:
        st.error("本站尚未配置访问密码（Streamlit Secrets 缺少 APP_PASSWORD）。")
        st.stop()
    if st.session_state.get("authed"):
        return
    # 记住我：本机 cookie 命中则免登（换密码后旧 cookie 自动失效）
    mgr = _cookie_mgr()
    if mgr is not None:
        try:
            cookies = mgr.get_all() or {}
        except Exception:
            cookies = {}
        tok = _remember_token()
        if tok and hmac.compare_digest(cookies.get(REMEMBER_COOKIE) or "", tok):
            st.session_state["authed"] = True
            return
    st.markdown("### 验证终端")
    pw = st.text_input("访问密码", type="password")
    if st.button("进入", type="primary"):
        if pw == pw_cfg:
            st.session_state["authed"] = True
            if mgr is not None:
                try:
                    mgr.set(REMEMBER_COOKIE, _remember_token(),
                            expires_at=datetime.now() + timedelta(days=REMEMBER_DAYS))
                except Exception:
                    pass
            st.rerun()
        else:
            st.error("密码错误")
    hint = st.secrets.get("PASSWORD_HINT", "")
    if hint:
        with st.expander("💡 忘记密码？查看提示"):
            st.caption(hint)
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


@st.cache_data(ttl=60)
def btc_live():
    """BTC/USDT 实时参考价（Binance 公开行情，仅展示，不进策略）。"""
    try:
        r = requests.get("https://data-api.binance.vision/api/v3/ticker/price",
                         params={"symbol": "BTCUSDT"}, timeout=5)
        r.raise_for_status()
        return float(r.json()["price"])
    except Exception:
        return None


def _day_word(dt, now):
    dd = (dt.date() - now.date()).days
    if dd <= 0:
        return "今日"
    if dd == 1:
        return "明日"
    return dt.strftime("%m-%d")


def tape_html():
    """顶部滚动行情条：只保留标的价格（全跟踪标的最新收盘 + 涨跌幅 + BTC 实时）。"""
    items = []
    live = btc_live()
    if live:
        items.append(f'BTC/USDT <span class="num">{live:,.1f}</span> '
                     f'<span class="livedot" style="margin:0 0 1px 4px"></span>')
    for t in snap.get("tape", []) or []:
        if t.get("symbol") == "BTCUSDT":
            continue  # 已有实时，跳过收盘价避免重复
        px = t.get("price")
        if px:
            fmt = ",.3f" if px < 1000 else ",.1f"
            chg = t.get("change_pct")
            if chg is None:
                tag = ""
            else:
                cls = "up" if chg > 0 else ("down" if chg < 0 else "flat")
                arw = "▲" if chg > 0 else ("▼" if chg < 0 else "")
                tag = f' <span class="{cls}">{arw}{chg:+.2f}%</span>'
            items.append(f'{t["symbol"]} <span class="num">{px:{fmt}}</span>{tag}')
    if not items:
        return
    # 每个标的只出现一次：内容超宽时左右摆动，不够宽时静止
    half = "".join(f'<span class="tape-item">{it}</span>' for it in items)
    st.markdown(f'<div class="tape"><div class="tape-inner">{half}</div></div>',
                unsafe_allow_html=True)


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
    for aid, label, color in (("sim_hk", "港股", "#e8e8e8"),
                             ("sim_crypto", "加密", "#f0b90b")):
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
                     'stroke="#2a2e39" stroke-dasharray="4 3"/>')
    for label, color, vals, start in aligned:
        pts_str = " ".join(f"{X(start + i):.1f},{Y(v):.1f}"
                           for i, v in enumerate(vals))
        poly = (pts_str + f" {X(start + len(vals) - 1):.1f},{Y(lo):.1f}"
                f" {X(start):.1f},{Y(lo):.1f}")
        parts.append(f'<polygon points="{poly}" fill="{color}" opacity="0.08"/>')
        parts.append(f'<polyline points="{pts_str}" fill="none" '
                     f'stroke="{color}" stroke-width="2"/>')
        ex, ey = X(start + len(vals) - 1), Y(vals[-1])
        parts.append(f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="3" fill="{color}"/>')
        parts.append(f'<text x="{ex - 5:.1f}" y="{ey - 8:.1f}" font-size="11" '
                     f'fill="{color}" text-anchor="end">{vals[-1]:.1f}</text>')
    parts.append(f'<text x="2" y="{Y(hi) + 11:.1f}" font-size="10" '
                 f'fill="#5f6572">{hi:.1f}</text>')
    parts.append(f'<text x="2" y="{Y(lo) - 3:.1f}" font-size="10" '
                 f'fill="#5f6572">{lo:.1f}</text>')
    parts.append(f'<text x="2" y="{H - 6:.1f}" font-size="10" '
                 f'fill="#5f6572">{dates[0]}</text>')
    parts.append(f'<text x="{W - 2:.1f}" y="{H - 6:.1f}" font-size="10" '
                 f'fill="#5f6572" text-anchor="end">{dates[-1]}</text>')
    svg = (f'<svg viewBox="0 0 {W} {H}" style="width:100%;height:auto">'
           f'{"".join(parts)}</svg>')
    legend = " &nbsp; ".join(
        f'<span class="dot" style="background:{c}"></span>{l}'
        for l, c, _ in series)
    st.markdown('<div class="chart-label">净值走势（起点=100）</div>',
                unsafe_allow_html=True)
    st.markdown(svg, unsafe_allow_html=True)
    st.markdown(f'<div class="chart-legend">{legend}</div>', unsafe_allow_html=True)


def kline_svg(kl, ma=20, w=340, h=132):
    """迷你K线 + MA20：kl=[[mm-dd,o,h,l,c]...]；阳线红阴线绿（中国习惯）。"""
    if not kl or len(kl) < 2:
        return ""
    closes = [r[4] for r in kl]
    ma_vals = [sum(closes[i + 1 - ma:i + 1]) / ma if i + 1 >= ma else None
               for i in range(len(kl))]
    lo = min(r[3] for r in kl)
    hi = max(r[2] for r in kl)
    span = (hi - lo) or 1
    n = len(kl)
    cw = w / n
    bw = max(1.5, cw * 0.62)

    def Y(px):
        return 8 + (1 - (px - lo) / span) * (h - 18)

    parts = []
    for i, r in enumerate(kl):
        _, o, hh, ll, c = r
        x = i * cw + cw / 2
        col = "#f6465d" if c >= o else "#2ebd85"
        parts.append(
            f'<line x1="{x:.1f}" y1="{Y(hh):.1f}" x2="{x:.1f}" y2="{Y(ll):.1f}" '
            f'stroke="{col}" stroke-width="1"/>')
        top, bot = min(Y(o), Y(c)), max(Y(o), Y(c))
        if bot - top < 1:
            bot = top + 1
        parts.append(
            f'<rect x="{x - bw / 2:.1f}" y="{top:.1f}" width="{bw:.1f}" '
            f'height="{bot - top:.1f}" fill="{col}"/>')
    pts = " ".join(f"{i * cw + cw / 2:.1f},{Y(v):.1f}"
                   for i, v in enumerate(ma_vals) if v is not None)
    if pts:
        parts.append(f'<polyline points="{pts}" fill="none" '
                     'stroke="#f0b90b" stroke-width="1.2"/>')
    yl = Y(closes[-1])
    parts.append(f'<line x1="0" y1="{yl:.1f}" x2="{w}" y2="{yl:.1f}" '
                 'stroke="#8a94a6" stroke-width="0.8" stroke-dasharray="3,3"/>')
    parts.append(f'<text x="{w - 2:.1f}" y="{yl - 4:.1f}" font-size="10" '
                 f'fill="#8a94a6" text-anchor="end">{closes[-1]:,.4g}</text>')
    return (f'<svg viewBox="0 0 {w} {h}" style="width:100%;height:auto;display:block">'
            f'{"".join(parts)}</svg>')


# ---------- 通用组件 ----------
ACCT_CN = {"sim_a": "A股", "sim_hk": "港股", "sim_crypto": "加密"}


def pending_panel(items):
    """待审批面板（订单区）：全账户合并，按日期倒序；行内批准/跳过。"""
    items = sorted(items, key=lambda p: p.get("date", ""), reverse=True)
    if not items:
        st.markdown('<div class="sec">待审批</div>', unsafe_allow_html=True)
        st.markdown('<div class="empty"><b>队列为空</b>'
                    '<span>有信号会在这里出现，等你批准</span></div>',
                    unsafe_allow_html=True)
        return
    st.markdown(f'<div class="sec">待审批 <span class="badge">{len(items)}</span></div>',
                unsafe_allow_html=True)
    for p in items:
        st.markdown(
            f'<div class="sig-row"><span class="num">{p["date"]} {p["symbol"]} '
            f'{side_cn(p["side"])} @{f2(p.get("price"))}</span>'
            f'<span class="flat" style="font-size:12px">'
            f'{ACCT_CN.get(p.get("account"), "")}</span></div>',
            unsafe_allow_html=True)
        b1, b2 = st.columns(2)
        key = f'{p["account"]}_{p["date"]}_{p["symbol"]}_{p["side"]}'
        if b1.button("批准", key="ap_" + key, width="stretch"):
            if queue_command("approve", {"date": p["date"], "account": p["account"],
                                         "symbol": p["symbol"], "side": p["side"]}):
                st.rerun()
        if b2.button("跳过", key="sk_" + key, width="stretch"):
            if queue_command("skip", {"date": p["date"], "account": p["account"],
                                      "symbol": p["symbol"], "side": p["side"]}):
                st.rerun()


def event_stream():
    """统一事件流：信号 + 成交，按日期倒序。"""
    ev = []
    for s in snap.get("signals", []) or []:
        ev.append((s.get("date", ""), "sig", "信号",
                   f'{s.get("symbol")} {side_cn(s.get("side"))} @{f2(s.get("price"))}'))
    for f in snap.get("fills", []) or []:
        ev.append((f.get("date", ""), "fill", "成交",
                   f'{f.get("symbol")} {side_cn(f.get("side"))} '
                   f'{(f.get("qty") or 0):g} @{f2(f.get("price"))}'))
    ev.sort(key=lambda e: e[0], reverse=True)
    st.markdown('<div class="sec">事件流</div>', unsafe_allow_html=True)
    if not ev:
        st.markdown('<div class="empty"><b>暂无事件</b>'
                    '<span>信号与成交会出现在这里</span></div>', unsafe_allow_html=True)
        return
    for d, cls, tag, txt in ev[:25]:
        st.markdown(
            f'<div class="ev-row"><span class="ev-date num">{d}</span>'
            f'<span class="etag etag-{cls}">{tag}</span>'
            f'<span class="num">{txt}</span></div>', unsafe_allow_html=True)


CMD_CN = {"set_status": "运行", "set_mode": "模式",
          "approve": "批准", "skip": "跳过"}


def command_log():
    """指令历史：已执行的网页指令归档（commands/done/）。"""
    st.markdown('<div class="sec">指令历史</div>', unsafe_allow_html=True)
    files = sorted(glob.glob(os.path.join(BASE, "commands", "done", "*.json")),
                   reverse=True)[:10]
    recs = []
    for fp in files:
        try:
            recs.append(json.load(open(fp, encoding="utf-8")))
        except Exception:
            continue
    if not recs:
        st.markdown('<div class="empty"><b>暂无记录</b>'
                    '<span>你在页面点的操作会记在这里</span></div>', unsafe_allow_html=True)
        return
    for c in recs:
        kind, ts = c.get("kind", ""), c.get("ts", "")
        try:
            pl = json.loads(c.get("payload_json", "{}") or "{}")
        except Exception:
            pl = {}
        if kind == "set_mode":
            txt = "切自动" if pl.get("mode") == "auto" else "切手动"
        elif kind == "set_status":
            txt = "暂停" if pl.get("status") == "paused" else "开始"
        elif kind in ("approve", "skip"):
            txt = (f'{"批准" if kind == "approve" else "跳过"} '
                   f'{pl.get("symbol")} {side_cn(pl.get("side"))}')
        else:
            txt = kind
        st.markdown(
            f'<div class="ev-row"><span class="ev-date num">{ts[5:16]}</span>'
            f'<span class="etag etag-cmd">{CMD_CN.get(kind, kind)}</span>'
            f'<span>{txt}</span></div>', unsafe_allow_html=True)


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
    # 持仓（终端式表格：成本 / 现价 / 浮盈亏 / 盈亏比）
    poss = [p for p in snap.get("positions", []) if p.get("account") == aid]
    st.markdown('<div class="sec" style="font-size:14px">持仓</div>', unsafe_allow_html=True)
    if not poss:
        st.markdown('<div class="empty"><b>运行中 · 全现金</b>'
                    '<span>暂无持仓，有信号会在顶部出现</span></div>',
                    unsafe_allow_html=True)
    else:
        rows = []
        for p in poss:
            qty = p.get("qty") or 0
            cost = p.get("avg_cost") or 0
            last = p.get("last_price") or 0
            if not last and qty:
                last = (p.get("market_value") or 0) / qty
            pnl = (last - cost) * qty if cost else 0
            ret = (last / cost - 1) * 100 if cost else None
            cls = "up" if pnl > 0 else ("down" if pnl < 0 else "flat")
            rows.append(
                f'<tr><td>{p["symbol"]}</td>'
                f'<td class="num">{qty:g}</td>'
                f'<td class="num">{cost:,.4g}</td>'
                f'<td class="num">{last:,.4g}</td>'
                f'<td class="num {cls}">{pnl:+,.2f}</td>'
                f'<td class="num {cls}">'
                f'{f"{ret:+.2f}%" if ret is not None else "—"}</td></tr>')
        st.markdown(
            '<table class="pos"><thead><tr><th>标的</th><th>数量</th><th>成本</th>'
            '<th>现价</th><th>浮盈亏</th><th>盈亏比</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>', unsafe_allow_html=True)
        # 迷你K线 + MA20（近60日收盘K，仅展示不进策略）
        klines = snap.get("klines", {}) or {}
        for p in poss:
            kl = klines.get(p["symbol"])
            if kl:
                st.markdown(
                    f'<div class="chart-label" style="margin:10px 0 4px">'
                    f'{p["symbol"]} · 近{len(kl)}日K + MA20</div>',
                    unsafe_allow_html=True)
                st.markdown(kline_svg(kl), unsafe_allow_html=True)
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



# ---------- 页眉 ----------
tape_html()
st.markdown('### 验证终端 <span class="en-tag">PAPER TRADING TERMINAL</span>',
            unsafe_allow_html=True)
now = datetime.now()
age = now - datetime.fromtimestamp(os.path.getmtime(SNAP))
if age < timedelta(hours=1):
    age_txt = f"{max(int(age.total_seconds() // 60), 1)}分钟前"
elif age < timedelta(days=1):
    age_txt = f"{int(age.total_seconds() // 3600)}小时前"
else:
    age_txt = f"{age.days}天前"
stt, mod = control.get("status"), control.get("mode")
dot = '<span class="livedot"></span>' if stt == "running" else ""

# ---------- 控制条：一排并列（状态 / 模式 / 操作） ----------
p1, p2, _, b1, b2 = st.columns([0.9, 0.9, 3.4, 1, 1])
with p1:
    st.markdown(
        f'<span class="pill {"run" if stt == "running" else "pause"}">{dot}'
        f'{"运行中" if stt == "running" else "已暂停"}</span>',
        unsafe_allow_html=True)
with p2:
    st.markdown(f'<span class="pill">{"自动" if mod == "auto" else "手动"}</span>',
                unsafe_allow_html=True)
if b1.button("⏸ 暂停" if stt == "running" else "▶ 开始", width="stretch"):
    if queue_command("set_status", {"status": "paused" if stt == "running" else "running"}):
        st.rerun()
if b2.button("切手动" if mod == "auto" else "切自动", width="stretch"):
    if queue_command("set_mode", {"mode": "manual" if mod == "auto" else "auto"}):
        st.rerun()

# ---------- 元信息 + 下一步：并入同一排 ----------
_ups = []
_n8 = now.replace(hour=8, minute=0, second=0, microsecond=0)
if _n8 <= now:
    _n8 += timedelta(days=1)
_ups.append(f"BTC日K{_day_word(_n8, now)}08:00收盘后更新")
_d = now.date()
while True:
    _d += timedelta(days=1)
    if _d.weekday() < 5:
        break
_ups.append(f"港股下个交易日{_d.strftime('%m-%d')}")
if now.date() < date(2026, 10, 8):
    _ups.append("A股10-08接入验证")
st.markdown(
    f'<div class="hero-note">数据截至 {asof} · 页面{age_txt}更新 · 每日17:12更新数据 · '
    f'规则 {snap.get("rule_version", "—")} · '
    f'<span style="color:#8b93a5">下一步</span> · {" · ".join(_ups)}</div>',
    unsafe_allow_html=True)

# ---------- 终端区：净值 + 待审批 ----------
col_chart, col_panel = st.columns([2, 1])
with col_chart:
    nav_chart_svg(snap.get("equity", {}) or {})
with col_panel:
    pending_panel(pend)

# 股票汇总（一行）：港股按当日 HKDCNY 折算，明细按原生币种独立记账
pool = snap.get("stock_pool", {}) or {}
st.markdown(
    f'<div class="hero-note">股票总资产（CNY）'
    f'<span class="num">{f2(pool.get("total_cny"))}</span>'
    f' · 港股按当日 HKDCNY {pool.get("hkdcny") or "—"} 折算</div>',
    unsafe_allow_html=True)

col_a, col_hk, col_c = st.columns(3)


# ---------- A股 ----------
with col_a:
    a_not_started = (asof < VAL_START_A and
                     not [f for f in snap.get("fills", []) if f.get("account") == "sim_a"])
    account_card("sim_a", "A股",
                 not_started_text="验证期 10-08 开始，届时信号会出现在这里"
                 if a_not_started else None)

# ---------- 港股 ----------
with col_hk:
    account_card("sim_hk", "港股")

# ---------- 加密货币 ----------
with col_c:
    a = accts.get("sim_crypto", {})
    st.markdown('<div class="hero-label">总资产 · USDT</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="hero-num num">{f2(a.get("nav"))}</div>', unsafe_allow_html=True)
    st.markdown('<div class="hero-note">每日更新一次（UTC 日K收盘后）</div>',
                unsafe_allow_html=True)
    _live = btc_live()
    _bp = next((p for p in snap.get("positions", [])
                if p.get("account") == "sim_crypto"
                and p.get("symbol") == "BTCUSDT"), None)
    if _live and _bp and _bp.get("qty"):
        _close = (_bp.get("market_value") or 0) / _bp["qty"]
        _chg = (_live - _close) / _close * 100 if _close else 0
        _cls = "up" if _chg > 0 else ("down" if _chg < 0 else "flat")
        _arw = "▲" if _chg > 0 else ("▼" if _chg < 0 else "")
        st.markdown(
            f'<div class="hero-note">BTC 实时参考 '
            f'<span class="num">{_live:,.1f}</span> · 持仓参考 '
            f'<span class="num">{_bp["qty"] * _live:,.2f}</span> '
            f'<span class="num {_cls}">{_arw} {_chg:+.2f} %</span>'
            f'（vs 日K收盘，仅参考，不进策略）</div>',
            unsafe_allow_html=True)
    st.markdown('<hr class="hairline"/>', unsafe_allow_html=True)

    account_card("sim_crypto", "加密账户")

# ---------- 事件流 / 指令历史 ----------
col_ev, col_cmd = st.columns(2)
with col_ev:
    event_stream()
with col_cmd:
    command_log()

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
