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

import sys as _sys
_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.freshness import data_freshness as _data_freshness_fn

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
.mkt-card { background: #10141b; border: 1px solid #1a1f2a; border-radius: 8px;
            padding: 14px 16px 12px; margin-bottom: 12px; min-height: 112px;
            display: flex; flex-direction: column; justify-content: center; }
.mkt-name { font-size: 13px; color: #aab; margin-bottom: 6px; }
.mkt-px { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
          font-size: 26px; font-weight: 800; letter-spacing: -0.5px; line-height: 1.2; }
.mkt-chg { font-size: 13px; margin-top: 6px; font-variant-numeric: tabular-nums; }
.mkt-sec { font-size: 13px; color: #5f6572; margin: 14px 0 8px; letter-spacing: 1px; }
/* 市场三 tab：深色胶囊条，选中高亮 */
div[data-testid="column"] > div > div > button[kind="secondary"] {
    background: #14181f; border: 1px solid #1a1f2a; color: #8b93a5; border-radius: 8px; }
div[data-testid="column"] > div > div > button[kind="primary"] {
    background: #232a36; border: 1px solid #2c3542; color: #e8ecf1; border-radius: 8px; }
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
/* ---- 5 分区改版：状态横幅 / 指标卡 / 留白 ---- */
.sysbanner { display: flex; align-items: center; gap: 10px; padding: 12px 16px;
  border-radius: 10px; margin: 12px 0 4px; font-size: 15px; }
.sysbanner b { font-size: 16px; }
.sysbanner span { color: #8b93a5; font-size: 13px; margin-left: auto; }
.sysbanner.ok { background: rgba(46,189,133,.08); border: 1px solid rgba(46,189,133,.25); }
.sysbanner.ok b { color: #2ebd85; }
.sysbanner.warn { background: rgba(240,185,11,.08); border: 1px solid rgba(240,185,11,.3); }
.sysbanner.warn b { color: #f0b90b; }
.sysbanner.bad { background: rgba(246,70,93,.08); border: 1px solid rgba(246,70,93,.3); }
.sysbanner.bad b { color: #f6465d; }
.metric { background: #10141b; border: 1px solid #1a1f2a; border-radius: 10px;
  padding: 16px 18px; margin-bottom: 12px; }
.mlabel { font-size: 13px; color: #8b93a5; margin-bottom: 8px; }
.mnum { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 22px; font-weight: 700; color: #e8ecf1; }
.mnum.sub { font-size: 15px; color: #8b93a5; margin-top: 4px; font-weight: 400; }
.warnline { padding: 10px 14px; background: rgba(240,185,11,.06);
  border-left: 3px solid #f0b90b; border-radius: 0 8px 8px 0;
  margin-bottom: 8px; font-size: 14px; color: #d8dce3; }
.sec { margin-top: 26px !important; }
/* ---- 验证 KPI 卡片（参考 tradesgnl） ---- */
.kpi { background: #10141b; border: 1px solid #1a1f2a; border-radius: 10px;
  padding: 16px 18px; margin-bottom: 12px; }
.kpi-head { display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 10px; }
.kpi-label { font-size: 13px; color: #8b93a5; }
.kpi-value { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 26px; font-weight: 800; color: #e8ecf1; line-height: 1.25; }
.kpi-unit { font-size: 14px; color: #8b93a5; font-weight: 400; }
.kpi-sub { font-size: 12px; color: #5f6572; margin-top: 6px; }
.sdot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; }
.sdot.ok { background: #2ebd85; box-shadow: 0 0 6px rgba(46,189,133,.6); }
.sdot.bad { background: #f6465d; box-shadow: 0 0 6px rgba(246,70,93,.6); }
.sdot.wait { background: #5f6572; }
/* ---- 风控/系统状态卡片（参考 CYG） ---- */
.stcard { background: #10141b; border: 1px solid #1a1f2a; border-radius: 10px;
  padding: 14px 16px; margin-bottom: 12px; }
.stcard .kpi-value { font-size: 20px; }
.stpill { display: inline-block; padding: 2px 10px; border-radius: 20px; font-size: 12px; }
.stpill.ok { background: rgba(46,189,133,.12); color: #2ebd85; }
.stpill.warn { background: rgba(240,185,11,.12); color: #f0b90b; }
.stpill.bad { background: rgba(246,70,93,.12); color: #f6465d; }
/* ---- segmented_control 深色化 ---- */
div[data-testid="stSegmentedControl"] button { border-radius: 8px; }
/* ---- 卡片网格：桌面3列，手机2列小方块（对标万得） ---- */
.cardgrid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
.cardgrid .kpi, .cardgrid .metric, .cardgrid .stcard { margin-bottom: 0; }
@media (max-width: 768px) {
  .cardgrid { grid-template-columns: repeat(2, 1fr); gap: 8px; }
  .cardgrid .mkt-card { min-height: 96px; padding: 10px 12px; }
  .cardgrid .mkt-px { font-size: 21px; }
  .cardgrid .kpi { padding: 12px 14px; }
  .cardgrid .kpi-value { font-size: 20px; }
  .cardgrid .kpi-label { font-size: 12px; }
  .cardgrid .kpi-sub { font-size: 11px; }
  .cardgrid .metric { padding: 12px 14px; }
  .cardgrid .mnum { font-size: 18px; }
  .cardgrid .mnum.sub { font-size: 13px; }
  .cardgrid .mlabel { font-size: 12px; margin-bottom: 6px; }
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


def _read_remember_cookie():
    # 只走原生：服务端直接读 HTTP Cookie 头，首刷即正确，无 JS round-trip。
    # 不用组件读（同一 run 内多次 get_all 会触发 key 重复，且组件读在云上不可靠）。
    try:
        cc = st.context.cookies
        if cc:
            v = cc.get(REMEMBER_COOKIE)
            if v:
                return v
    except Exception:
        pass
    return None


def _write_remember_cookie():
    # 写 cookie 必须在"不紧跟 st.rerun()" 的 run 里执行：
    # set() 后立即 rerun 会提前销毁组件 iframe，cookie 写不进去（已本地实测）。
    # 因此登录成功时只置 flag，本函数在紧接着的终端 run 里执行写操作。
    try:
        from extra_streamlit_components import CookieManager
        mgr = CookieManager()
        mgr.get_all()
        # 用 max_age（秒）而不用 expires_at 字符串：
        # 旧代码传裸 ISO 日期，Safari 解析失败会把 cookie 降级成会话 cookie，关掉即删。
        mgr.set(REMEMBER_COOKIE, _remember_token(),
                max_age=REMEMBER_DAYS * 24 * 3600)
    except Exception as e:
        print(f"[auth] 写记住我 cookie 失败: {e}", flush=True)


def check_auth():
    pw_cfg = st.secrets.get("APP_PASSWORD", "")
    if not pw_cfg:
        st.error("本站尚未配置访问密码（Streamlit Secrets 缺少 APP_PASSWORD）。")
        st.stop()
    if st.session_state.get("authed"):
        return
    # 记住我：本机 cookie 命中则免登（换密码后旧 cookie 自动失效）
    tok = _remember_token()
    saved = _read_remember_cookie()
    if tok and saved and hmac.compare_digest(saved, tok):
        st.session_state["authed"] = True
        return
    st.markdown("### 验证终端")
    pw = st.text_input("访问密码", type="password")
    if st.button("进入", type="primary"):
        if pw == pw_cfg:
            st.session_state["authed"] = True
            # cookie 写操作放到下一个 run 做（见 _write_remember_cookie 注释）
            st.session_state["_write_remember_cookie"] = True
            st.rerun()
        else:
            st.error("密码错误")
    hint = st.secrets.get("PASSWORD_HINT", "")
    if hint:
        with st.expander("💡 忘记密码？查看提示"):
            st.caption(hint)
    st.stop()


check_auth()

# 登录成功后的第一个终端 run：在此写 30 天记住我 cookie（本 run 正常结束，不 rerun）
if st.session_state.pop("_write_remember_cookie", False):
    _write_remember_cookie()

# 页面自动刷新：快照由服务端每 ~2 分钟推送，无需手动刷新页面
try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=120_000, key="vterm_autorefresh")
except Exception:
    pass


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


@st.cache_data(ttl=60)
def indices_live():
    """A股三大指数实时（新浪公开行情，仅展示）。返回 [(名称, 现价, 涨跌额, 涨跌幅%), ...]。"""
    try:
        r = requests.get("https://hq.sinajs.cn/list=s_sh000001,s_sz399001,s_sz399006",
                         headers={"Referer": "https://finance.sina.com.cn"},
                         timeout=8)
        r.raise_for_status()
        out = []
        for line in r.text.strip().splitlines():
            # 指数格式 var hq_str_s_sh000001="上证指数,3813.79,1.89,0.05,..."
            # 字段：名称,现价,涨跌额,涨跌幅%,...（注意不是昨收）
            m = line.split('"')
            if len(m) < 2:
                continue
            f = m[1].split(",")
            if len(f) < 4:
                continue
            name, px, chg, pct = f[0], float(f[1]), float(f[2]), float(f[3])
            out.append((name, px, chg, pct))
        return out
    except Exception:
        return []


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


def _mkt_card(name, px, chg=None, pct=None):
    """万得式指数/标的卡片：大数字 + 红涨绿跌。chg 为 None 时只显示涨跌幅。"""
    if pct is None:
        chg_html = ""
    else:
        cls = "up" if pct > 0 else ("down" if pct < 0 else "flat")
        arw = "▲" if pct > 0 else ("▼" if pct < 0 else "")
        pts = f'{arw} {chg:+,.2f}　' if chg is not None else f'{arw} '
        chg_html = (f'<div class="mkt-chg"><span class="{cls}">'
                    f'{pts}{pct:+.2f}%</span></div>')
    px_cls = "up" if (pct or 0) > 0 else ("down" if (pct or 0) < 0 else "")
    return (f'<div class="mkt-card"><div class="mkt-name">{name}</div>'
            f'<div class="mkt-px num {px_cls}">{px:,.2f}</div>{chg_html}</div>')


@st.cache_data(ttl=300)
def fund_flow_live():
    """主力资金净额（东方财富公开行情，仅展示）。返回 {标的: 主力净额(元)}。"""
    sec_map = {"002446": "0.002446", "688305": "1.688305",
               "HK9660": "116.09660", "HK0354": "116.00354"}
    inv = {"002446": "002446", "688305": "688305",
           "09660": "HK9660", "00354": "HK0354"}
    try:
        r = requests.get("https://push2delay.eastmoney.com/api/qt/ulist.np/get",
                         params={"secids": ",".join(sec_map.values()),
                                 "fields": "f12,f14,f2,f3,f62"},
                         timeout=10)
        r.raise_for_status()
        out = {}
        for it in r.json()["data"]["diff"]:
            sym = inv.get(it.get("f12"))
            if sym:
                out[sym] = it.get("f62") or 0
        return out
    except Exception:
        return {}


def _flow_card(sym, net_yuan):
    """资金卡片：主力净流入/出（万元），红入绿出。"""
    w = (net_yuan or 0) / 1e4
    cls = "up" if w > 0 else ("down" if w < 0 else "flat")
    arw = "▲" if w > 0 else ("▼" if w < 0 else "")
    return (f'<div class="mkt-card"><div class="mkt-name">{sym} · 主力净'
            f'{"流入" if w > 0 else ("流出" if w < 0 else "")}</div>'
            f'<div class="mkt-px num {cls}">{arw} {abs(w):,.1f}</div>'
            f'<div class="mkt-chg"><span class="flat">万元</span></div></div>')


def mkt_flow():
    """资金净流入：跟踪标的的主力资金（仅展示）。"""
    ff = fund_flow_live()
    if not ff:
        st.markdown('<div class="empty"><b>暂无资金数据</b>'
                    '<span>数据源暂时不可用，稍后再看</span></div>',
                    unsafe_allow_html=True)
        return
    st.markdown('<div class="mkt-sec">主力资金净流入 · 当日累计</div>',
                unsafe_allow_html=True)
    syms = [s for s in ["002446", "688305", "HK9660", "HK0354"] if s in ff]
    st.markdown(f'<div class="cardgrid">'
                f'{"".join(_flow_card(s, ff[s]) for s in syms)}</div>',
                unsafe_allow_html=True)
    st.caption("加密市场无主力资金统计口径 · 数据来自东方财富公开行情")


def mkt_breadth():
    """涨跌分布：跟踪标的的上涨/下跌家数。"""
    tape = snap.get("tape", []) or []
    if not tape:
        return
    up = [t for t in tape if (t.get("change_pct") or 0) > 0]
    dn = [t for t in tape if (t.get("change_pct") or 0) < 0]
    fl = [t for t in tape if (t.get("change_pct") or 0) == 0]
    n = len(tape)
    up_w = len(up) / n * 100 if n else 0
    st.markdown('<div class="mkt-sec">跟踪标的涨跌分布</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div style="display:flex;gap:12px;align-items:center;margin:6px 0 10px">'
        f'<span class="up">涨 {len(up)}</span>'
        f'<span class="flat">平 {len(fl)}</span>'
        f'<span class="down">跌 {len(dn)}</span></div>'
        f'<div style="display:flex;height:10px;border-radius:5px;overflow:hidden">'
        f'<div style="width:{up_w:.1f}%;background:#f6465d"></div>'
        f'<div style="width:{100-up_w:.1f}%;background:#2ebd85"></div></div>',
        unsafe_allow_html=True)
    st.markdown(
        f'<div class="cardgrid">'
        f'{"".join(_mkt_card(t["symbol"], t.get("price") or 0, None, t.get("change_pct") or 0) for t in tape)}</div>',
        unsafe_allow_html=True)


@st.cache_data(ttl=300)
def northbound_live():
    """北向资金（东方财富公开行情，仅展示）。
    返回 (今日净流入亿元, [(MM-DD, 净流入亿元)], 沪股通今日, 深股通今日)。"""
    try:
        r = requests.get("https://push2delay.eastmoney.com/api/qt/kamt.kline/get",
                         params={"fields1": "f1,f3,f5", "fields2": "f51,f52",
                                 "klt": "101", "lmt": "6"},
                         timeout=10)
        r.raise_for_status()
        d = r.json()["data"]

        def _parse(key):
            out = []
            for item in d.get(key, []) or []:
                p = item.split(",")
                if len(p) == 2:
                    try:
                        out.append((p[0][5:], float(p[1])))
                    except ValueError:
                        pass
            return out
        s2n = _parse("s2n")      # 北向合计
        hsh = _parse("hk2sh")    # 沪股通
        hsz = _parse("hk2sz")    # 深股通
        if not s2n or all(v == 0 for _, v in s2n):
            # 历史序列为空或全零：接口已停更，按数据诚信规则报未知，不显示误导性 0.0
            return None
        today = s2n[-1][1] if s2n else 0
        return today, s2n, (hsh[-1][1] if hsh else 0), (hsz[-1][1] if hsz else 0)
    except Exception:
        return None


def mkt_northbound():
    """北向资金：今日净流入 + 沪/深拆分 + 近5日趋势（仅展示）。"""
    nb = northbound_live()
    if nb is None:
        st.markdown('<div class="empty"><b>暂无北向数据</b>'
                    '<span>数据源暂时不可用，稍后再看</span></div>',
                    unsafe_allow_html=True)
        return
    today, hist, hsh_t, hsz_t = nb
    cls = "up" if today > 0 else ("down" if today < 0 else "flat")
    arw = "▲" if today > 0 else ("▼" if today < 0 else "")
    st.markdown('<div class="mkt-sec">北向资金 · 当日净流入</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="mkt-card"><div class="mkt-name">北向合计（亿元）</div>'
        f'<div class="mkt-px num {cls}">{arw} {today:+,.1f}</div>'
        f'<div class="mkt-chg"><span class="flat">沪股通 {hsh_t:+,.1f} 亿　'
        f'深股通 {hsz_t:+,.1f} 亿</span></div></div>',
        unsafe_allow_html=True)
    if len(hist) >= 2:
        st.markdown('<div class="mkt-sec">近5个交易日</div>', unsafe_allow_html=True)
        _max = max(abs(v) for _, v in hist) or 1
        bars = []
        for dt, v in hist[-5:]:
            _c = "up" if v > 0 else ("down" if v < 0 else "flat")
            _h = max(abs(v) / _max * 64, 3)
            bars.append(
                f'<div style="flex:1;text-align:center">'
                f'<div style="height:64px;display:flex;align-items:flex-end;justify-content:center">'
                f'<div style="width:70%;height:{_h:.0f}px;border-radius:3px;'
                f'background:{"#f6465d" if v > 0 else ("#2ebd85" if v < 0 else "#5f6572")}"></div></div>'
                f'<div class="num {_c}" style="font-size:11px;margin-top:4px">{v:+.0f}</div>'
                f'<div class="flat" style="font-size:11px">{dt}</div></div>')
        st.markdown(f'<div style="display:flex;gap:6px">{"".join(bars)}</div>'
                    f'<div class="flat" style="font-size:11px;margin-top:6px">单位：亿元，红为净流入</div>',
                    unsafe_allow_html=True)
    st.caption("休市日显示上一交易日数据 · 数据来自东方财富公开行情")


def market_tabs():
    """市场盘面四 tab：行情 / 资金净流入 / 北向资金 / 涨跌分布。"""
    tab = pill_nav(("行情", "资金净流入", "北向资金", "涨跌分布"), "mtab", "行情")
    if tab == "资金净流入":
        mkt_flow()
    elif tab == "北向资金":
        mkt_northbound()
    elif tab == "涨跌分布":
        mkt_breadth()
    else:
        market_overview()


def market_overview():
    """市场盘面：指数卡片 + 跟踪标的卡片（CSS 网格：桌面3列/手机2列）。"""
    idx = indices_live()
    cards = []
    if idx:
        for name, px, chg, pct in idx[:3]:
            cards.append(_mkt_card(name, px, chg, pct))
    tape = snap.get("tape", []) or []
    for t in tape:
        px, pct = t.get("price"), t.get("change_pct") or 0
        cards.append(_mkt_card(t["symbol"], px or 0, None, pct))
    if not cards:
        return
    st.markdown('<div class="mkt-sec">指数 · 跟踪标的</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="cardgrid">{"".join(cards)}</div>', unsafe_allow_html=True)


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


def fpx_sym(sym, x):
    """交易所式价格：港股3位、加密1位无千分位、A股2位。"""
    if x is None:
        return "—"
    s = str(sym or "").upper()
    if s.endswith("USDT"):
        return f"{x:,.1f}".replace(",", "")
    if s.startswith("HK"):
        return f"{x:,.3f}"
    return f"{x:,.2f}"


def fpx(x):
    """价格显示：大数用千分位，小数保留4位去尾零，永不科学计数法。"""
    if x is None:
        return "—"
    if abs(x) >= 1000:
        return f"{x:,.2f}"
    s = f"{x:,.4f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-") else "0"


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
        return True
    if r.status_code == 401:
        st.error("提交失败：GitHub token 无效或已过期 → 去 Streamlit Secrets 更换 GITHUB_TOKEN")
    elif r.status_code == 403:
        st.error("提交失败：token 权限不足（需要给 paper-sim-web 仓库 Contents 读写权限）")
    elif r.status_code == 404:
        st.error("提交失败：仓库不存在 → 检查 Secrets 里的 GITHUB_REPO 是否写对")
    else:
        st.error(f"提交失败（{r.status_code}），稍后重试")
    return False


def github_link_ok():
    """指令链路自检：token 能否读到仓库。结果缓存 5 分钟，避免每次刷新都打 API。"""
    now = datetime.now().timestamp()
    cached = st.session_state.get("_link_check")
    if cached and now - cached[0] < 300:
        return cached[1]
    token = st.secrets.get("GITHUB_TOKEN", "")
    repo = st.secrets.get("GITHUB_REPO", "")
    ok = False
    if token and repo:
        try:
            r = requests.get(
                f"https://api.github.com/repos/{repo}",
                headers={"Authorization": f"Bearer {token}",
                         "Accept": "application/vnd.github+json"},
                timeout=10)
            ok = r.status_code == 200
        except Exception:
            ok = False
    st.session_state["_link_check"] = (now, ok)
    return ok


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
                 f'fill="#8a94a6" text-anchor="end">{fpx(closes[-1])}</text>')
    return (f'<svg viewBox="0 0 {w} {h}" style="width:100%;height:auto;display:block">'
            f'{"".join(parts)}</svg>')


def _win_rate(aid, val_start):
    """验证期内卖出即算一笔完整 round-trip（与管线口径一致）。返回 (win_rate, wins, total)。"""
    fills = [f for f in snap.get("fills", [])
             if f.get("account") == aid and f.get("side") == "SELL"
             and (f.get("date") or "") >= (val_start or "")]
    total = len(fills)
    wins = sum(1 for f in fills if (f.get("pnl") or 0) > 0)
    return (wins / total if total else None), wins, total


def _kpi_card(label, value_html, sub_html="", status=None):
    """验证 KPI 卡片（参考 tradesgnl）：大数字 + 小字说明 + 达标状态点。"""
    dot = ""
    if status == "ok":
        dot = '<span class="sdot ok"></span>'
    elif status == "bad":
        dot = '<span class="sdot bad"></span>'
    elif status == "wait":
        dot = '<span class="sdot wait"></span>'
    return (f'<div class="kpi"><div class="kpi-head"><span class="kpi-label">{label}</span>{dot}</div>'
            f'<div class="kpi-value">{value_html}</div>'
            f'<div class="kpi-sub">{sub_html}</div></div>')


def validation_dashboard():
    """验证中心：KPI 卡片 + 账户切换，一眼判断是否达到验收标准。"""
    g = snap.get("graduation", {}) or {}
    tg = g.get("targets", {}) or {}
    accts_g = g.get("accounts", {}) or {}
    wlr_t = tg.get("win_loss_ratio") or 3.0
    mdd_t = tg.get("max_drawdown") or 0.10
    smin, smax = tg.get("sample_min", 20), tg.get("sample_max", 30)

    st.markdown('<div class="sec">验证中心</div>', unsafe_allow_html=True)
    _vlabel = pill_nav(("A股", "港股", "加密"), "vacct", "港股")
    aid = {"A股": "sim_a", "港股": "sim_hk", "加密": "sim_crypto"}[_vlabel]
    a = accts_g.get(aid) or {}
    n = a.get("round_trips") or 0
    exp = a.get("expectancy")
    wlr = a.get("win_loss_ratio")
    pf = a.get("profit_factor")
    mdd = a.get("max_drawdown")
    vret = a.get("val_return")
    wr, wins, total = _win_rate(aid, a.get("val_start"))

    # 样本是否足够决定状态：样本不足 → wait；达标 → ok；不达标 → bad
    def _st(ok):
        if n < smin:
            return "wait"
        return "ok" if ok else "bad"

    _kpis = [
        ("验证期收益",
         '<span class="num flat">—</span>' if vret is None
         else f'<span class="num {"up" if vret > 0 else ("down" if vret < 0 else "flat")}">'
              f'{vret * 100:+.2f}%</span>',
         f"验证期 {a.get('val_start', '—')} 至今",
         _st(vret is not None and vret > 0)),
        ("样本进度",
         f'<span class="num">{n}</span>'
         f'<span class="kpi-unit"> / {smin}–{smax}笔</span>',
         f"验证期自 {a.get('val_start', '—')} 起",
         _st(True)),
        ("期望值 / 笔",
         '<span class="num flat">—</span>' if exp is None
         else f'<span class="num {"up" if exp > 0 else "down"}">{exp:+,.2f}</span>',
         "目标 &gt; 0",
         _st(exp is not None and exp > 0)),
        ("胜率",
         '<span class="num flat">—</span>' if wr is None
         else f'<span class="num">{wr * 100:.1f}%</span>',
         f"{wins} / {total} 笔" if total else "仅记录",
         "wait" if wr is None else None),
        ("盈亏比",
         '<span class="num flat">—</span>' if wlr is None
         else f'<span class="num {"up" if wlr >= wlr_t else "down"}">{wlr:,.2f}</span>',
         f"目标 ≥ {wlr_t:g}（硬线）",
         _st(wlr is not None and wlr >= wlr_t)),
        ("盈利因子",
         '<span class="num flat">—</span>' if pf is None
         else f'<span class="num">{pf:,.2f}</span>',
         "仅参考",
         "wait" if pf is None else None),
        ("最大回撤",
         '<span class="num flat">—</span>' if mdd is None
         else f'<span class="num {"up" if mdd <= mdd_t else "down"}">{mdd * 100:.2f}%</span>',
         f"目标 ≤ {mdd_t * 100:.0f}%",
         _st(mdd is not None and mdd <= mdd_t)),
    ]
    st.markdown(f'<div class="cardgrid">'
                f'{"".join(_kpi_card(lbl, val, sub, st_) for lbl, val, sub, st_ in _kpis)}</div>',
                unsafe_allow_html=True)
    st.caption("● 达标　● 未达标　● 样本不足　" + (g.get("execution_note") or ""))


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
    link_txt = ('<span class="livedot"></span>指令链路正常' if github_link_ok()
                else '<span style="color:#f6465d">●</span> 指令链路异常，提交会失败')
    st.markdown(f'<div class="sec">待审批 <span class="badge">{len(items)}</span>'
                f'<span style="font-weight:400;font-size:12px;color:#5f6572;margin-left:10px">'
                f'{link_txt}</span></div>',
                unsafe_allow_html=True)
    # 已提交追踪：点过批准/跳过后，即使快照还没更新，也明确显示"已提交"，
    # 不再让用户对着一条已提交的信号反复点。快照更新（信号消失）后自动清理。
    submitted = st.session_state.setdefault("submitted_cmds", set())
    cur_keys = {f'{p["account"]}_{p["date"]}_{p["symbol"]}_{p["side"]}' for p in items}
    submitted.intersection_update(cur_keys)
    for p in items:
        st.markdown(
            f'<div class="sig-row"><span class="num">{p["date"]} {p["symbol"]} '
            f'{side_cn(p["side"])} @{f2(p.get("price"))}</span>'
            f'<span class="flat" style="font-size:12px">'
            f'{ACCT_CN.get(p.get("account"), "")}</span></div>',
            unsafe_allow_html=True)
        key = f'{p["account"]}_{p["date"]}_{p["symbol"]}_{p["side"]}'
        if key in submitted:
            st.markdown('<div style="font-size:12px;color:#2ebd85;padding:4px 2px">'
                        '✓ 已提交，约2分钟内生效（页面会自动刷新）</div>',
                        unsafe_allow_html=True)
            continue
        b1, b2 = st.columns(2)
        if b1.button("批准", key="ap_" + key, width="stretch"):
            if queue_command("approve", {"date": p["date"], "account": p["account"],
                                         "symbol": p["symbol"], "side": p["side"]}):
                submitted.add(key)
                st.rerun()
        if b2.button("跳过", key="sk_" + key, width="stretch"):
            if queue_command("skip", {"date": p["date"], "account": p["account"],
                                      "symbol": p["symbol"], "side": p["side"]}):
                submitted.add(key)
                st.rerun()


def event_stream():
    """交易动态：交易所式流水表，一信号一行。列：日期|标的|方向|数量|价格|盈亏。"""
    signals = snap.get("signals", []) or []
    fills = snap.get("fills", []) or []
    apprs = snap.get("approvals", []) or []
    klines = snap.get("klines", {}) or {}
    last_px = {s: kl[-1][4] for s, kl in klines.items() if kl}

    def _k(x):
        return (x.get("date"), x.get("account"), x.get("symbol"), x.get("side"))
    fill_map = {_k(f): f for f in fills}
    appr_map = {_k(a): a.get("decision") for a in apprs}

    st.markdown('<div class="sec">交易动态</div>', unsafe_allow_html=True)
    if not signals:
        st.markdown('<div class="empty"><b>暂无动态</b>'
                    '<span>信号出现后会在这里跟踪全生命周期</span></div>',
                    unsafe_allow_html=True)
        return
    # 今日盈亏归因（按快照 asof 口径）：卖出看已实现，买入看浮动
    t_real, t_float = 0.0, 0.0
    for f in fills:
        if f.get("date") != asof:
            continue
        if f.get("side") == "SELL":
            t_real += f.get("pnl") or 0
        else:
            lp = last_px.get(f.get("symbol"))
            if lp:
                t_float += (lp - (f.get("price") or 0)) * (f.get("qty") or 0)
    st.markdown(
        f'<div class="strip"><span class="strip-title">今日盈亏</span>　'
        f'已实现 {pnl_html(t_real)}　浮动 {pnl_html(t_float)}</div>',
        unsafe_allow_html=True)

    rows = []
    # 按日期倒序：最新的信号在最上面，避免旧记录看起来像"落后"
    for s in sorted(signals, key=lambda x: x.get("date") or "", reverse=True)[:20]:
        k = _k(s)
        f = fill_map.get(k)
        dec = appr_map.get(k)
        sym, side = s.get("symbol"), s.get("side")
        acct = ACCT_CN.get(s.get("account"), "")
        d = (s.get("date") or "")[5:].replace("-", "/")
        side_cls = "up" if side == "BUY" else "down"
        if f:
            qty, px = f.get("qty") or 0, f.get("price") or 0
            if side == "SELL":
                pnl_txt = f'已实现 {pnl_html(f.get("pnl") or 0)}'
            else:
                lp = last_px.get(sym)
                upnl = (lp - px) * qty if lp else None
                pnl_txt = f'浮动 {pnl_html(upnl)}'
            status = '<span class="etag etag-fill">成交</span>'
            price_txt, qty_txt = fpx_sym(sym, px), f"{qty:g}"
        elif dec == "skipped":
            status, price_txt, qty_txt, pnl_txt = (
                '<span class="etag" style="background:rgba(122,127,140,.16);'
                'color:#8b93a5">跳过</span>', fpx_sym(sym, s.get("price")), "—", "—")
        elif dec == "approved":
            status, price_txt, qty_txt, pnl_txt = (
                '<span class="etag" style="background:rgba(80,140,255,.14);'
                'color:#6ea8ff">待成交</span>', fpx_sym(sym, s.get("price")), "—", "—")
        else:
            status, price_txt, qty_txt, pnl_txt = (
                '<span class="etag etag-sig">待审批</span>', fpx_sym(sym, s.get("price")),
                "—", "—")
        rows.append(
            f'<tr><td class="num">{d}</td>'
            f'<td><b>{sym}</b> <span class="flat" style="font-size:11px">{acct}</span></td>'
            f'<td class="{side_cls}">{side_cn(side)}</td>'
            f'<td class="num">{qty_txt}</td>'
            f'<td class="num">{price_txt}</td>'
            f'<td>{status}</td>'
            f'<td class="num">{pnl_txt}</td></tr>')
    st.markdown(
        '<table class="pos"><thead><tr><th>日期</th><th>标的</th><th>方向</th>'
        '<th>数量</th><th>价格</th><th>状态</th><th>盈亏</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table>', unsafe_allow_html=True)


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
                f'<td class="num">{fpx(cost)}</td>'
                f'<td class="num">{fpx(last)}</td>'
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



def pill_nav(options, key, default):
    """Pill 导航：优先 segmented_control（无整页刷新、移动端原生横滑，
    不丢会话）；旧版 Streamlit 降级为按钮列。返回当前选中。"""
    if hasattr(st, "segmented_control"):
        val = st.segmented_control("导航", list(options), key=key,
                                   default=default, label_visibility="collapsed")
        return val if val in options else default
    # 降级（Streamlit < 1.35）
    cur = st.session_state.get(key, default)
    cols = st.columns(len(options))
    for col, opt in zip(cols, options):
        with col:
            if st.button(opt, key=f"{key}_{opt}", use_container_width=True,
                         type="primary" if cur == opt else "secondary"):
                st.session_state[key] = opt
                st.rerun()
                return opt
    return cur


# ============================================================
# 页眉 + 顶层导航（5 个一级入口：总览 / 交易 / 验证 / 风控 / 系统）
# ============================================================
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

def data_freshness():
    """基于快照**内容**判定数据新鲜度（不依赖文件 mtime）。逻辑见 lib/freshness.py。"""
    return _data_freshness_fn(snap, now)


_fresh, _fresh_detail = data_freshness()

# 系统状态判定（优先级：数据异常 > 暂停中 > 等待人工确认 > 未知 > 正常运行）
# 注意：不可验证时显示"未知"而非"正常"
_n_pend = len(pend)
if _fresh == "stale":
    _sys_state, _sys_cls = "数据异常", "bad"
elif stt == "paused":
    _sys_state, _sys_cls = "暂停中", "warn"
elif _n_pend > 0 and mod == "manual":
    _sys_state, _sys_cls = f"等待人工确认（{_n_pend}）", "warn"
elif _fresh == "unknown":
    _sys_state, _sys_cls = "状态未知", "warn"
else:
    _sys_state, _sys_cls = "正常运行", "ok"
st.markdown(
    f'<div class="sysbanner {_sys_cls}">{dot if _sys_cls == "ok" else ""}'
    f'<b>{_sys_state}</b>'
    f'<span>{_fresh_detail} · {"自动" if mod == "auto" else "手动"}模式</span></div>',
    unsafe_allow_html=True)

# 顶层导航（pill，手机横滚）
nav = pill_nav(("总览", "交易", "验证", "风控", "系统"), "nav", "总览")

# 聚合指标（总览用）：股票 CNY / 加密 USDT 分开展示，不硬折算
_pool = snap.get("stock_pool", {}) or {}
_cnav = (accts.get("sim_crypto", {}) or {}).get("nav") or 0
_cpnl = (accts.get("sim_crypto", {}) or {}).get("pnl_day")
_ccash = (accts.get("sim_crypto", {}) or {}).get("cash")
_cpos = (accts.get("sim_crypto", {}) or {}).get("position_value")


def _metric_card(label, cny_val, usdt_val, cny_ccy="¥", usdt_ccy="$"):
    _cv = f'<div class="mnum">{cny_ccy}{f2(cny_val)}</div>' if cny_val is not None else ""
    _uv = f'<div class="mnum sub">{usdt_ccy}{f2(usdt_val)}</div>' if usdt_val is not None else ""
    return (f'<div class="metric"><div class="mlabel">{label}</div>'
            f'{_cv}{_uv}</div>')


# ============================================================
# 01 总览：打开即知当前状态
# ============================================================
def page_overview():
    st.markdown('<div class="sec">核心数据</div>', unsafe_allow_html=True)
    _spnl = sum(((accts.get(a, {}) or {}).get("pnl_day") or 0)
                for a in ("sim_a", "sim_hk"))
    _spos = sum(((accts.get(a, {}) or {}).get("position_value") or 0)
                for a in ("sim_a", "sim_hk"))
    _scash = sum(((accts.get(a, {}) or {}).get("cash") or 0)
                 for a in ("sim_a", "sim_hk"))
    _mcards = [
        _metric_card("账户总资产 · 股票/加密", _pool.get("total_cny"), _cnav),
        _metric_card("当日盈亏", _spnl, _cpnl),
        _metric_card("持仓市值", _spos, _cpos),
        _metric_card("可用资金", _scash, _ccash),
    ]
    st.markdown(f'<div class="cardgrid">{"".join(_mcards)}</div>',
                unsafe_allow_html=True)

    st.markdown('<div class="sec">市场环境</div>', unsafe_allow_html=True)
    market_tabs()

    # 今日信号
    _today_sigs = [s for s in snap.get("signals", []) if s.get("date") == asof]
    st.markdown('<div class="sec">今日交易信号</div>', unsafe_allow_html=True)
    if _today_sigs:
        for s in _today_sigs:
            _cls = "up" if s.get("side") == "BUY" else "down"
            st.markdown(
                f'<div class="kv"><span class="k"><b>{s.get("symbol")}</b> '
                f'<span class="flat">{ACCT_CN.get(s.get("account"), "")}</span></span>'
                f'<span class="v {_cls}">{side_cn(s.get("side"))} '
                f'<span class="num">@{fpx_sym(s.get("symbol"), s.get("price"))}</span></span></div>',
                unsafe_allow_html=True)
    else:
        st.markdown('<div class="empty"><b>今日暂无信号</b>'
                    '<span>新信号出现时会在此列出，并进入待确认</span></div>',
                    unsafe_allow_html=True)

    # 风险警告
    _warns = []
    if age > timedelta(minutes=30):
        _warns.append(f"快照已 {age_txt}未更新，同步可能中断")
    _a_note = None
    _a_sigs = [s for s in snap.get("signals", []) if s.get("account") == "sim_a"]
    if not _a_sigs and not [f for f in snap.get("fills", []) if f.get("account") == "sim_a"]:
        _warns.append("A股数据积累中：MA20 需 20 天历史，首个信号预计 11 月初")
    if _warns:
        st.markdown('<div class="sec">风险警告</div>', unsafe_allow_html=True)
        for w in _warns:
            st.markdown(f'<div class="warnline">⚠ {w}</div>', unsafe_allow_html=True)


# ============================================================
# 02 交易：只显示需要执行的事
# ============================================================
def page_trade():
    col_chart, col_panel = st.columns([2, 1])
    with col_chart:
        st.markdown('<div class="sec">净值走势</div>', unsafe_allow_html=True)
        nav_chart_svg(snap.get("equity", {}) or {})
    with col_panel:
        pending_panel(pend)

    st.markdown('<div class="sec">持仓</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="hero-note">股票总资产（CNY）'
        f'<span class="num">{f2(_pool.get("total_cny"))}</span>'
        f' · 港股按当日 HKDCNY {_pool.get("hkdcny") or "—"} 折算</div>',
        unsafe_allow_html=True)
    col_a, col_hk, col_c = st.columns(3)
    with col_a:
        _a_fills = [f for f in snap.get("fills", []) if f.get("account") == "sim_a"]
        _a_sigs = [s for s in snap.get("signals", []) if s.get("account") == "sim_a"]
        _a_note = ("数据积累中：MA20 需 20 天历史，首个信号预计 11 月初出现"
                   if not _a_sigs and not _a_fills else None)
        account_card("sim_a", "A股", not_started_text=_a_note)
    with col_hk:
        account_card("sim_hk", "港股")
    with col_c:
        account_card("sim_crypto", "加密")

    event_stream()


# ============================================================
# 03 验证：判断系统是否值得实盘
# ============================================================
def page_verify():
    validation_dashboard()
    rg = snap.get("rotation_gate", {}) or {}
    st.markdown(f'<div class="sec">轮动门槛（{rg.get("met", 0)}/{rg.get("total", 3)} 项满足）</div>',
                unsafe_allow_html=True)
    for it in rg.get("items", []):
        st.markdown(
            f'<div class="kv"><span class="k">{it["label"]} '
            f'<span class="num">{it["value"] if it["value"] is not None else "—"}{it.get("unit", "")}</span></span>'
            f'<span class="v">{it.get("status", "")}</span></div>',
            unsafe_allow_html=True)
    st.caption(rg.get("note", ""))


# ============================================================
# 04 风控：仓位限制、止损、回撤、暂停与异常记录
# ============================================================
def page_risk():
    st.markdown('<div class="sec">交易控制</div>', unsafe_allow_html=True)
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
            st.session_state["_ctrl_msg_ts"] = datetime.now().timestamp()
            st.rerun()
    if b2.button("切手动" if mod == "auto" else "切自动", width="stretch"):
        if queue_command("set_mode", {"mode": "manual" if mod == "auto" else "auto"}):
            st.session_state["_ctrl_msg_ts"] = datetime.now().timestamp()
            st.rerun()
    if datetime.now().timestamp() - st.session_state.get("_ctrl_msg_ts", 0) < 180:
        st.markdown('<div class="strip"><span style="color:#2ebd85">'
                    '✓ 指令已提交，约2分钟内生效（页面会自动刷新）</span></div>',
                    unsafe_allow_html=True)

    st.markdown('<div class="sec">系统状态</div>', unsafe_allow_html=True)
    _klines = snap.get("klines", {}) or {}
    _asof = snap.get("asof") or ""
    # 状态卡片：数据新鲜度（内容判定） / 行情源 / GitHub链路 / 交易引擎
    _cards = []
    if _fresh == "ok":
        _cards.append(("数据新鲜度", _asof, _fresh_detail, "ok"))
    elif _fresh == "stale":
        _cards.append(("数据新鲜度", "过期", _fresh_detail, "bad"))
    else:
        _cards.append(("数据新鲜度", "未知", _fresh_detail, "warn"))
    _ok_n = sum(1 for _s in ("002446", "688305", "HK9660", "HK0354", "BTCUSDT")
                if (_klines.get(_s) or []))
    _cards.append(("行情源", f"{_ok_n}/5", "标的有行情数据",
                   "ok" if _ok_n == 5 else ("warn" if _ok_n >= 3 else "bad")))
    _cards.append(("GitHub 链路", "正常" if github_link_ok() else "异常",
                   "指令下发通道", "ok" if github_link_ok() else "bad"))
    _cards.append(("交易引擎", "运行中" if stt == "running" else "已暂停",
                   f"{'自动' if mod == 'auto' else '手动'}模式",
                   "ok" if stt == "running" else "warn"))
    _stcards = []
    for _label, _val, _sub, _st in _cards:
        _pill_txt = "正常" if _st == "ok" else ("注意" if _st == "warn" else "异常")
        _stcards.append(
            '<div class="stcard"><div class="kpi-head">'
            f'<span class="kpi-label">{_label}</span>'
            f'<span class="stpill {_st}">{_pill_txt}</span></div>'
            f'<div class="kpi-value">{_val}</div>'
            f'<div class="kpi-sub">{_sub}</div></div>')
    st.markdown(f'<div class="cardgrid">{"".join(_stcards)}</div>',
                unsafe_allow_html=True)
    # 各标的行情形细：与 asof 对齐为正常，落后标红（BTC 日K按UTC收盘，允许晚一天）
    st.markdown('<div class="sec" style="font-size:14px">行情明细</div>',
                unsafe_allow_html=True)
    _asof_d = None
    try:
        _asof_d = datetime.strptime(_asof, "%Y-%m-%d").date() if _asof else None
    except ValueError:
        pass
    for _sym in ("002446", "688305", "HK9660", "HK0354", "BTCUSDT"):
        _kl = _klines.get(_sym) or []
        if not _kl:
            _tag = '<span class="v down">无数据</span>'
        else:
            _last = _kl[-1][0]
            _want = _asof[5:] if _asof else ""
            _prev = (_asof_d - timedelta(days=1)).strftime("%m-%d") if _asof_d else ""
            _is_btc = _sym.upper().endswith("USDT")
            _ok = (_last == _want) or (_is_btc and _last == _prev)
            _tag = (f'<span class="v {"up" if _ok else "down"}>截至 {_last}'
                    f'{"（落后）" if not _ok else ""}</span>')
        st.markdown(f'<div class="kv"><span class="k">{_sym}</span>{_tag}</div>',
                    unsafe_allow_html=True)


# ============================================================
# 05 系统：数据源、任务状态、日志、运行配置
# ============================================================
def page_system():
    st.markdown('<div class="sec">数据源</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="kv"><span class="k">快照</span>'
                f'<span class="v num">{age_txt}更新</span></div>',
                unsafe_allow_html=True)
    st.markdown(f'<div class="kv"><span class="k">数据截至</span>'
                f'<span class="v num">{asof}</span></div>',
                unsafe_allow_html=True)
    st.markdown(f'<div class="kv"><span class="k">规则版本</span>'
                f'<span class="v">{snap.get("rule_version", "—")}</span></div>',
                unsafe_allow_html=True)
    st.markdown(f'<div class="kv"><span class="k">GitHub 链路</span>'
                f'<span class="v">{"正常" if github_link_ok() else "异常"}</span></div>',
                unsafe_allow_html=True)

    st.markdown('<div class="sec">运行配置</div>', unsafe_allow_html=True)
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
    st.markdown(
        f'<div class="hero-note">每日17:12更新数据 · '
        f'<span style="color:#8b93a5">下一步</span> · {" · ".join(_ups)}</div>',
        unsafe_allow_html=True)

    command_log()
    st.markdown(
        f'<div class="foot">规则版本 {snap.get("rule_version", "—")} · '
        '信号按日收盘价成交 · 滑点 0.2% · 本站为模拟盘，不构成投资建议</div>',
        unsafe_allow_html=True)


# 路由
{"总览": page_overview, "交易": page_trade, "验证": page_verify,
 "风控": page_risk, "系统": page_system}[nav]()
