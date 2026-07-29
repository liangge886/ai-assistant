#!/usr/bin/env python3
"""
觉爱家纺 · A 股每日行情简报（含基本面升级版）
==================================================
数据来源：
  - 腾讯财经 qt.gtimg.cn（指数 / 行业指数 / 个股 / 内外盘 / K线）
  - 东方财富 datacenter-web.eastmoney.com（机构评级 / 财务主要指标 / 业绩预告）
    （注：东方财富 push2 行情接口在本环境被网络策略阻断，改用腾讯源取行情；
       datacenter-web 子域可达，用于取基本面数据）
输出：HTML 邮件（发送至老板 QQ 邮箱）+ 纯文本（兜底）
定时：收盘后（北京 16:30）触发，周一至周五

报告七大板块：
  1、大盘涨跌
  2、今日最强 3 个板块
  3、今日最弱 3 个板块
  4、主力资金流向（内外盘近似，非东方财富官方主力净流入）
  5、明日观察股票池
  6、赛轮轮胎 / 博实股份 半研究（技术面 + 基本面 + 机构评级 + 业绩预告）
  7、推荐 2 支 10 元左右股票（量价 + 估值 + 机构评级 三维筛选）

免责声明：本简报由 AI 基于公开市场行情与基本面数据自动聚合生成，
所列分析、个股提及与推荐仅为信息整理与参考，不构成任何投资建议。
股市有风险，投资需谨慎，请结合专业研究独立决策。

用法：
    python3 stock_briefing.py                 # 生成并发送
    python3 stock_briefing.py --date 2026-07-29
    python3 stock_briefing.py --no-send        # 只生成本地，不发送
环境变量：REPORT_NO_SEND=1 等价于 --no-send
"""

import os
import re
import sys
import json
import time
import argparse
from datetime import datetime, timedelta

try:
    import requests
except ImportError:
    requests = None

import pospal_report_standalone as pp

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOCAL_REPORT = os.path.join(SCRIPT_DIR, "stock_briefing_{date}.html")
RECEIVER = pp.CONFIG["email"]["receiver_email"]

REPORT_ACCENT = "#b71c1c"
EM_DC = "https://datacenter-web.eastmoney.com/api/data/v1/get"

# ============================================================
# 标的池
# ============================================================
INDICES = [
    ("sh000001", "上证指数"),
    ("sz399001", "深证成指"),
    ("sz399006", "创业板指"),
    ("sh000300", "沪深300"),
    ("sh000016", "上证50"),
    ("sh000688", "科创50"),
    ("sz399905", "中证500"),
    ("sz399303", "国证2000"),
]

# 主流行业/主题指数（均已实测返回有效行业指数）
SECTOR_CODES = [
    "sz399965", "sz399417", "sz399437", "sz399440", "sz399441", "sh000036",
    "sh000040", "sz399324", "sz399550", "sz399673", "sz399101", "sz399005",
    "sh000044", "sz399394", "sz399395", "sz399808", "sz399998", "sz399973",
    "sz399975", "sz399986", "sz399971", "sz399932", "sz399933", "sz399814",
    "sz399995", "sz399807", "sz980017", "sh000037", "sh000922", "sz399976",
    "sz399989", "sz399997", "sz399967",
]

FOCUS = {
    "sh601058": "赛轮轮胎",
    "sz002698": "博实股份",
}

SCREEN_UNIVERSE = [
    "sh600010","sh600019","sh600028","sh600036","sh600048","sh600085","sh600104",
    "sh600111","sh600150","sh600160","sh600176","sh600196","sh600276","sh600309",
    "sh600315","sh600346","sh600362","sh600372","sh600415","sh600436","sh600438",
    "sh600460","sh600482","sh600519","sh600547","sh600585","sh600588","sh600606",
    "sh600660","sh600690","sh600703","sh600741","sh600809","sh600837","sh600872",
    "sh600900","sh600919","sh600936","sh600998","sh601006","sh601012","sh601038",
    "sh601058","sh601066","sh601088","sh601117","sh601138","sh601166","sh601186",
    "sh601225","sh601288","sh601318","sh601333","sh601390","sh601398","sh601600",
    "sh601618","sh601628","sh601668","sh601669","sh601688","sh601698","sh601728",
    "sh601766","sh601800","sh601818","sh601857","sh601866","sh601888","sh601898",
    "sh601899","sh601916","sh601919","sh601933","sh601939","sh601988","sh601989",
    "sh601990","sh603000","sh603019","sh603260","sh603288","sh603345","sh603501",
    "sh603659","sh603899","sh603986","sh688111","sh688599","sh688981",
    "sz000063","sz000100","sz000157","sz000425","sz000538","sz000568","sz000629",
    "sz000651","sz000709","sz000725","sz000761","sz000768","sz000807","sz000825",
    "sz000858","sz000895","sz000937","sz000938","sz000977","sz001965","sz002027",
    "sz002065","sz002152","sz002179","sz002241","sz002252","sz002304","sz002371",
    "sz002415","sz002456","sz002475","sz002555","sz002594","sz002601","sz002698",
    "sz002714","sz002736","sz002798","sz002841","sz300003","sz300014","sz300015",
    "sz300033","sz300059","sz300073","sz300122","sz300136","sz300251","sz300274",
    "sz300316","sz300360","sz300433","sz300498","sz300502","sz300617","sz300661",
    "sz300750","sz300773",
]


# ============================================================
# 工具
# ============================================================
def fmt(x, d=2, suffix=""):
    try:
        return f"{float(x):,.{d}f}{suffix}"
    except Exception:
        return "—"


def fmt_yi(v):
    try:
        x = float(v)
        sign = "+" if x >= 0 else "-"
        return f"{sign}{abs(x):,.2f}亿"
    except Exception:
        return "—"


def tx_prefix(code6):
    """6 位代码 -> 腾讯前缀代码"""
    return ("sh" if code6[0] in ("6", "9") else "sz") + code6


def api_sleep():
    time.sleep(0.25)


def tx_batch(codes):
    """批量抓取腾讯行情，返回 {code: fields(list)}。"""
    if requests is None:
        raise RuntimeError("requests 未安装")
    out = {}
    for i in range(0, len(codes), 80):
        chunk = codes[i:i + 80]
        url = "https://qt.gtimg.cn/q=" + ",".join(chunk)
        try:
            r = requests.get(url, timeout=15)
            r.encoding = "gbk"
            text = r.text
        except Exception as e:
            print(f"[WARN] 腾讯行情请求失败: {e}")
            api_sleep()
            continue
        for m in re.finditer(r'v_(\w+)="([^"]*)"', text):
            code = m.group(1)
            f = m.group(2).split("~")
            if len(f) < 10 or not f[1]:
                continue
            out[code] = f
        api_sleep()
    return out


def parse_quote(f):
    def g(i):
        try:
            v = f[i]
            return v if v not in ("", "-", "--") else None
        except Exception:
            return None

    price = g(3)
    prev = g(4)
    high = g(33)
    low = g(34)
    try:
        amp = (float(high) - float(low)) / float(prev) * 100 if (high and low and prev) else None
    except Exception:
        amp = None
    try:
        wai = float(g(7) or 0)
        nei = float(g(8) or 0)
        amt_wan = float(g(37) or 0)
        if (wai + nei) > 0 and amt_wan > 0:
            active_net_yi = (wai - nei) / (wai + nei) * (amt_wan / 10000)
        else:
            active_net_yi = None
    except Exception:
        active_net_yi = None
    return {
        "name": g(1),
        "code": g(2),
        "price": price,
        "prev_close": prev,
        "open": g(5),
        "high": high,
        "low": low,
        "change": g(31),
        "change_pct": g(32),
        "amount_wan": g(37),
        "turnover": g(38),
        "pe": g(39),
        "pb": g(40),
        "amplitude": (f"{amp:.2f}" if amp is not None else None),
        "mktcap_yi": g(44),
        "limit_up": g(47),
        "limit_down": g(48),
        "time": g(30),
        "wai": g(7),
        "nei": g(8),
        "active_net_yi": active_net_yi,
    }


# ============================================================
# 东方财富 datacenter（基本面）
# ============================================================
def em_datacenter(report_name, code6, page_size=20):
    """东方财富 datacenter-web 取单只股票的基本面数据。返回 list[dict]。"""
    url = (f"{EM_DC}?reportName={report_name}&columns=ALL"
           f"&filter=(SECURITY_CODE%3D%22{code6}%22)&pageSize={page_size}&source=WEB&client=WEB")
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        result = r.json().get("result") or {}
        return result.get("data", []) or []
    except Exception as e:
        print(f"[WARN] 东方财富 {report_name} 取数失败({code6}): {e}")
        return []


def get_rating(code6):
    """机构评级 + 一致预期 EPS + 目标价区间。"""
    try:
        data = em_datacenter("RPT_WEB_RESPREDICT", code6, 5)
        if not data:
            return None
        r = data[0]
        org = int(r.get("RATING_ORG_NUM") or 0)
        buy = int(r.get("RATING_BUY_NUM") or 0)
        add = int(r.get("RATING_ADD_NUM") or 0)
        neu = int(r.get("RATING_NEUTRAL_NUM") or 0)
        red = int(r.get("RATING_REDUCE_NUM") or 0)
        sale = int(r.get("RATING_SALE_NUM") or 0)
        bull = buy + add
        ratio = (bull / org) if org else None
        return {
            "org": org, "buy": buy, "add": add, "neutral": neu,
            "reduce": red, "sale": sale, "bull": bull, "bull_ratio": ratio,
            "eps_next": r.get("EPS2"), "year_next": r.get("YEAR2"),
            "eps_next2": r.get("EPS3"), "year_next2": r.get("YEAR3"),
            "target_min": r.get("DEC_AIMPRICEMIN"), "target_max": r.get("DEC_AIMPRICEMAX"),
            "industry": r.get("INDUSTRY_BOARD"),
        }
    except Exception as e:
        print(f"[WARN] 评级解析失败({code6}): {e}")
        return None


def get_financials(code6):
    """财务主要指标：最新报告期 + 最新年报。返回结构化 dict。"""
    try:
        data = em_datacenter("RPT_F10_FINANCE_MAINFINADATA", code6, 20)
        if not data:
            return None
        rows = sorted(data, key=lambda x: (x.get("REPORT_DATE") or ""), reverse=True)
        latest = rows[0]
        annual = next((x for x in rows if x.get("REPORT_TYPE") == "年报"), latest)

        def yi(v):
            try:
                return float(v) / 1e8
            except Exception:
                return None

        def pct(v):
            try:
                return float(v)
            except Exception:
                return None

        def roe(x):
            rv = x.get("WEIGHTAVG_ROE")
            if rv in (None, "", "-"):
                rv = x.get("ROEJQ")
            return pct(rv)

        return {
            "rep_name": latest.get("REPORT_DATE_NAME"),
            "revenue_yi": yi(latest.get("TOTALOPERATEREVE")),
            "np_yi": yi(latest.get("PARENTNETPROFIT")),
            "rev_yoy": pct(latest.get("TOTALOPERATEREVETZ")),
            "np_yoy": pct(latest.get("PARENTNETPROFITTZ")),
            "gm": pct(latest.get("XSMLL")),
            "debt": pct(latest.get("ZCFZL")),
            "roe": roe(latest),
            "eps": pct(latest.get("EPSJB")),
            "annual_name": annual.get("REPORT_DATE_NAME"),
            "annual_revenue_yi": yi(annual.get("TOTALOPERATEREVE")),
            "annual_np_yi": yi(annual.get("PARENTNETPROFIT")),
            "annual_eps": pct(annual.get("EPSJB")),
            "annual_roe": roe(annual),
        }
    except Exception as e:
        print(f"[WARN] 财务解析失败({code6}): {e}")
        return None


def get_forecast(code6):
    """最新业绩预告（取全量再按报告期取最新；接口默认升序，需 pageSize 足够大）。"""
    try:
        data = em_datacenter("RPT_PUBLIC_OP_NEWPREDICT", code6, 100)
        if not data:
            return None
        latest_list = [x for x in data if x.get("IS_LATEST") == "T"] or data
        r = max(latest_list, key=lambda x: (x.get("REPORT_DATE") or ""))
        return {
            "type": r.get("PREDICT_TYPE"),
            "amp_low": r.get("ADD_AMP_LOWER"),
            "amp_up": r.get("ADD_AMP_UPPER"),
            "content": r.get("PREDICT_CONTENT"),
            "report_date": (r.get("REPORT_DATE") or "")[:10],
        }
    except Exception as e:
        print(f"[WARN] 业绩预告解析失败({code6}): {e}")
        return None


def get_kline(code):
    """腾讯 K 线（前复权日线，120 根），返回技术面派生指标。"""
    try:
        url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={code},day,,,120,qfq"
        r = requests.get(url, timeout=15)
        r.encoding = "gbk"
        d = r.json().get("data", {}).get(code, {})
        bars = d.get("qfqday") or d.get("day") or []
        closes = [float(b[2]) for b in bars if len(b) >= 3]
        if len(closes) < 2:
            return None
        last = closes[-1]
        n = len(closes)
        ma20 = sum(closes[-20:]) / min(20, n)
        ma60 = sum(closes[-60:]) / min(60, n)
        ret20 = (last / closes[-20] - 1) * 100 if n >= 20 else None
        ret60 = (last / closes[-60] - 1) * 100 if n >= 60 else None
        hi = max(closes)
        lo = min(closes)
        pos = (last - lo) / (hi - lo) * 100 if hi > lo else 50.0
        # 量能：近5日均量 vs 前20日均量
        vol = [float(b[5]) for b in bars if len(b) >= 6]
        vol_ratio = (sum(vol[-5:]) / 5 / (sum(vol[-20:]) / 20)) if len(vol) >= 20 else None
        return {
            "last": last, "ma20": ma20, "ma60": ma60,
            "ret20": ret20, "ret60": ret60, "pos": pos,
            "hi": hi, "lo": lo, "vol_ratio": vol_ratio, "n": n,
        }
    except Exception as e:
        print(f"[WARN] K线解析失败({code}): {e}")
        return None


# ============================================================
# 各板块取数
# ============================================================
def get_indices():
    data = tx_batch([c for c, _ in INDICES])
    res = []
    for code, label in INDICES:
        f = data.get(code)
        if not f:
            continue
        q = parse_quote(f)
        q["label"] = label
        res.append(q)
    return res


def get_sectors():
    data = tx_batch(SECTOR_CODES)
    res = []
    for code in SECTOR_CODES:
        f = data.get(code)
        if not f:
            continue
        q = parse_quote(f)
        q["code"] = code
        res.append(q)
    res.sort(key=lambda q: float(q["change_pct"] or 0), reverse=True)
    up = [q for q in res if float(q["change_pct"] or 0) > 0]
    down = [q for q in res if float(q["change_pct"] or 0) < 0]
    flat = [q for q in res if float(q["change_pct"] or 0) == 0]
    return res, up, down, flat


def get_active_capital():
    """返回 (全市场主动净流向亿元, 候选池解析行情列表)。"""
    data = tx_batch(SCREEN_UNIVERSE)
    items = []
    total_net = 0.0
    for code in SCREEN_UNIVERSE:
        f = data.get(code)
        if not f:
            continue
        q = parse_quote(f)
        if q["active_net_yi"] is None:
            continue
        total_net += q["active_net_yi"]
        items.append(q)
    items.sort(key=lambda x: x["active_net_yi"], reverse=True)
    return total_net, items


def analyze_focus():
    """赛轮/博实：行情 + 技术面 + 基本面 + 评级 + 业绩预告。"""
    data = tx_batch(list(FOCUS.keys()))
    res = {}
    for code, name in FOCUS.items():
        f = data.get(code)
        if not f:
            continue
        q = parse_quote(f)
        q["label"] = name
        q["kline"] = get_kline(code)
        q["fin"] = get_financials(code[2:])
        q["rating"] = get_rating(code[2:])
        q["forecast"] = get_forecast(code[2:])
        res[code] = q
    return res


def recommend_10yuan(universe, top_sector_names):
    """量价 + 估值 + 机构评级 三维筛选 ~10 元候选，取前 2 并补全基本面。"""
    shortlist = []
    for code6, q in universe.items():
        try:
            price = float(q["price"])
            chg = float(q["change_pct"] or 0)
            amt = float(q["amount_wan"] or 0)
            pe = float(q["pe"] or 0)
        except Exception:
            continue
        if not (8.0 <= price <= 13.0):
            continue
        if chg <= 0:
            continue
        if amt < 20000:
            continue
        q["_code6"] = code6
        shortlist.append(q)

    # 取短名单机构评级
    for q in shortlist:
        q["rating"] = get_rating(q["_code6"])

    # 打分
    for q in shortlist:
        pe = float(q["pe"] or 0)
        amt = float(q["amount_wan"] or 0)
        chg = float(q["change_pct"] or 0)
        score = chg
        if 0 < pe <= 30:
            score += 1.5
        elif 30 < pe <= 50:
            score += 0.5
        if amt >= 80000:
            score += 1.0
        if q["name"] and any(k in (q["name"] or "") for k in top_sector_names):
            score += 1.0
        rt = q.get("rating")
        if rt and rt.get("bull_ratio") is not None:
            score += (rt["bull_ratio"] - 0.5) * 2
        q["score"] = score

    shortlist.sort(key=lambda x: x["score"], reverse=True)
    top = shortlist[:8]
    # 补全前 2 名的基本面 + 技术面
    for q in top[:2]:
        q["fin"] = get_financials(q["_code6"])
        q["forecast"] = get_forecast(q["_code6"])
        q["kline"] = get_kline(tx_prefix(q["_code6"]))
    return top[:2], shortlist


# ============================================================
# 报告生成
# ============================================================
def build_report(date_str, indices, sectors, up, down, flat,
                 total_net, capital_items, focus, recs, recs_all, is_trading_day):
    W = []

    def sec(title, body):
        W.append(f'<div class="section"><h2>{title}</h2>{body}</div>')

    disclaimer = ('<p class="disc">⚠️ 免责声明：本简报由 AI 基于公开市场行情与基本面数据自动聚合生成，'
                  '所列分析、个股提及与推荐仅为信息整理与参考，<b>不构成任何投资建议</b>。'
                  '股市有风险，投资需谨慎，请结合专业研究独立决策。</p>')

    note = ""
    if not is_trading_day:
        note = (f'<div class="notice">📌 今日（{date_str}）为非交易日或休市，'
                f'以下数据为最近一个交易日行情，仅供参考。</div>')

    # ---------- 1、大盘涨跌 ----------
    s1 = '<table><tr><th>指数</th><th>收盘</th><th>涨跌</th><th>涨跌幅</th><th>成交额</th></tr>'
    for q in indices:
        cp = float(q["change_pct"] or 0)
        cls = "up" if cp > 0 else ("down" if cp < 0 else "")
        arrow = "▲" if cp > 0 else ("▼" if cp < 0 else "—")
        amt = (f"{fmt(float(q['amount_wan'] or 0)/10000, 2, '亿')}" if q["amount_wan"] else "—")
        s1 += (f"<tr><td>{q['label']}</td><td>{fmt(q['price'])}</td>"
               f"<td class='{cls}'>{fmt(q['change'])}</td>"
               f"<td class='{cls}'>{arrow} {fmt(cp)}%</td><td>{amt}</td></tr>")
    s1 += "</table>"
    sec("一、大盘涨跌", s1)

    # ---------- 2/3、板块强弱 ----------
    def sector_table(rows):
        if not rows:
            return "<p>暂无数据</p>"
        t = '<table><tr><th>板块</th><th>涨跌幅</th><th>点位</th></tr>'
        for q in rows:
            cp = float(q["change_pct"] or 0)
            cls = "up" if cp > 0 else "down"
            t += (f"<tr><td>{q['name']}</td><td class='{cls}'>{fmt(cp)}%</td>"
                  f"<td>{fmt(q['price'])}</td></tr>")
        t += "</table>"
        return t

    s2 = "<h3>🔥 今日最强 3 个板块</h3>" + sector_table(sectors[:3])
    s2 += "<h3>❄️ 今日最弱 3 个板块</h3>"
    s2 += sector_table(sectors[-3:][::-1]) if len(sectors) >= 3 else sector_table([])
    s2 += (f"<p class='breadth'>行业广度：监测 {len(sectors)} 个主流行业中，"
           f"<span class='up'>上涨 {len(up)}</span> 个、"
           f"<span class='down'>下跌 {len(down)}</span> 个、平盘 {len(flat)} 个。</p>")
    sec("二、板块强弱（最强 / 最弱）", s2)

    # ---------- 4、主力资金流向（近似） ----------
    s4 = (f"<p>全市场主动资金净流向（基于内外盘近似）："
          f"<b class='{'up' if total_net>=0 else 'down'}'>{fmt_yi(total_net)}</b>"
          f"（正值代表主动买入占优，负值代表主动卖出占优）。</p>")
    s4 += "<p class='note'>说明：东方财富官方主力净流入接口在当前环境不可达，"
    s4 += "本处采用腾讯内外盘（主动买卖盘）净额估算，方向与量级仅供参考。</p>"
    s4 += "<h3>主动资金净流入前 5</h3>"
    s4 += '<table><tr><th>个股</th><th>现价</th><th>涨跌幅</th><th>主动净流入</th></tr>'
    for q in capital_items[:5]:
        cp = float(q["change_pct"] or 0)
        cls = "up" if cp > 0 else "down"
        s4 += (f"<tr><td>{q['name']}</td><td>{fmt(q['price'])}</td>"
               f"<td class='{cls}'>{fmt(cp)}%</td>"
               f"<td class='up'>{fmt_yi(q['active_net_yi'])}</td></tr>")
    s4 += "</table>"
    s4 += "<h3>主动资金净流出前 5</h3>"
    s4 += '<table><tr><th>个股</th><th>现价</th><th>涨跌幅</th><th>主动净流出</th></tr>'
    for q in capital_items[-5:][::-1]:
        cp = float(q["change_pct"] or 0)
        cls = "up" if cp > 0 else "down"
        s4 += (f"<tr><td>{q['name']}</td><td>{fmt(q['price'])}</td>"
               f"<td class='{cls}'>{fmt(cp)}%</td>"
               f"<td class='down'>{fmt_yi(q['active_net_yi'])}</td></tr>")
    s4 += "</table>"
    sec("三、主力资金流向（近似）", s4)

    # ---------- 5、明日观察股票池 ----------
    s5 = "<p class='note'>以下为结合今日强势板块与重点标的生成的观察池，非买卖建议：</p>"
    s5 += '<table><tr><th>标的</th><th>现价</th><th>涨跌幅</th><th>关注逻辑</th></tr>'
    for code, q in focus.items():
        cp = float(q["change_pct"] or 0)
        cls = "up" if cp > 0 else "down"
        s5 += (f"<tr><td>{q['label']}</td><td>{fmt(q['price'])}</td>"
               f"<td class='{cls}'>{fmt(cp)}%</td><td>重点跟踪标的（用户指定）</td></tr>")
    for q in recs:
        cp = float(q["change_pct"] or 0)
        cls = "up" if cp > 0 else "down"
        s5 += (f"<tr><td>{q['name']}</td><td>{fmt(q['price'])}</td>"
               f"<td class='{cls}'>{fmt(cp)}%</td><td>10元附近+动量+评级候选</td></tr>")
    s5 += "</table>"
    sec("四、明日观察股票池", s5)

    # ---------- 6、赛轮 / 博实 半研究 ----------
    s6 = ""
    for code, q in focus.items():
        cp = float(q["change_pct"] or 0)
        cls = "up" if cp > 0 else "down"
        pe = fmt(q["pe"]) if q["pe"] else "—"
        pb = fmt(q["pb"]) if q["pb"] else "—"
        mc = fmt(q["mktcap_yi"], 2, "亿") if q["mktcap_yi"] else "—"
        amp = fmt(q["amplitude"]) if q["amplitude"] else "—"
        turn = fmt(q["turnover"]) if q["turnover"] else "—"
        s6 += f"<h3>{q['label']}（{code.upper()}）</h3>"
        # 行情快照
        s6 += ('<table><tr><th>现价</th><th>涨跌幅</th><th>振幅</th><th>换手</th>'
               '<th>市盈率(TTM)</th><th>市净率</th><th>总市值</th></tr>')
        s6 += (f"<tr><td>{fmt(q['price'])}</td><td class='{cls}'>{fmt(cp)}%</td>"
               f"<td>{amp}%</td><td>{turn}%</td><td>{pe}</td><td>{pb}</td><td>{mc}</td></tr></table>")

        # 技术面
        k = q.get("kline")
        if k:
            ma_cls = "up" if k["last"] >= k["ma20"] else "down"
            pos = k["pos"]
            pos_tag = ("高位区" if pos >= 70 else "中位区" if pos >= 40 else "低位区")
            s6 += "<h4>技术面（120 日）</h4><ul class='ana'>"
            s6 += f"<li>· 现价 {fmt(k['last'])}，MA20 {fmt(k['ma20'])}（<span class='{ma_cls}'>{'站上' if k['last']>=k['ma20'] else '跌破'}</span>）、MA60 {fmt(k['ma60'])}</li>"
            if k["ret20"] is not None:
                s6 += f"<li>· 近20日 {'上涨' if k['ret20']>=0 else '下跌'} {fmt(abs(k['ret20']))}%，近60日 {fmt(abs(k['ret60'])) if k['ret60'] is not None else '—'}{'%' if k['ret60'] is not None else ''}</li>"
            s6 += f"<li>· 当前价处于近120日区间 <b>{fmt(pos)}%</b> 位置（{pos_tag}）；区间 {fmt(k['lo'])}–{fmt(k['hi'])}</li>"
            if k["vol_ratio"] is not None:
                s6 += f"<li>· 近5日均量 / 前20日均量 = {fmt(k['vol_ratio'])}（{'放量' if k['vol_ratio']>=1.2 else '缩量' if k['vol_ratio']<=0.8 else '平稳'}）</li>"
            s6 += "</ul>"

        # 基本面
        fin = q.get("fin")
        if fin:
            s6 += f"<h4>基本面（{fin.get('rep_name') or '最新'}）</h4><ul class='ana'>"
            if fin.get("revenue_yi") is not None:
                s6 += f"<li>· 营收 {fmt(fin['revenue_yi'])} 亿（同比 {fmt(fin['rev_yoy'])}%）</li>"
            if fin.get("np_yi") is not None:
                s6 += f"<li>· 归母净利润 {fmt(fin['np_yi'])} 亿（同比 {fmt(fin['np_yoy'])}%）</li>"
            if fin.get("gm") is not None:
                s6 += f"<li>· 毛利率 {fmt(fin['gm'])}%，资产负债率 {fmt(fin['debt'])}%</li>"
            if fin.get("roe") is not None:
                s6 += f"<li>· 加权ROE {fmt(fin['roe'])}%，EPS {fmt(fin['eps'])}</li>"
            if fin.get("annual_name"):
                s6 += (f"<li>· {fin['annual_name']}：营收 {fmt(fin['annual_revenue_yi']) if fin['annual_revenue_yi'] is not None else '—'} 亿，"
                       f"净利 {fmt(fin['annual_np_yi']) if fin['annual_np_yi'] is not None else '—'} 亿，EPS {fmt(fin['annual_eps']) if fin['annual_eps'] is not None else '—'}</li>")
            s6 += "</ul>"

        # 机构评级
        rt = q.get("rating")
        if rt:
            bull_txt = (f"{rt['bull']}/{rt['org']} 家看多（买入+增持）" if rt["org"] else "—")
            s6 += "<h4>机构评级与一致预期</h4><ul class='ana'>"
            s6 += f"<li>· 评级分布：买入 {rt['buy']} / 增持 {rt['add']} / 中性 {rt['neutral']} / 减持 {rt['reduce']} / 卖出 {rt['sale']}（共 {rt['org']} 家）</li>"
            s6 += f"<li>· 看多比例 {fmt(rt['bull_ratio']*100) if rt['bull_ratio'] is not None else '—'}%（{bull_txt}）</li>"
            if rt.get("eps_next"):
                s6 += f"<li>· 一致预期 EPS：{rt['year_next']} 年 {fmt(rt['eps_next'])} 元、{rt['year_next2']} 年 {fmt(rt['eps_next2']) if rt.get('eps_next2') else '—'} 元</li>"
            if rt.get("target_min") and rt.get("target_max"):
                s6 += f"<li>· 机构目标价区间 {fmt(rt['target_min'])}–{fmt(rt['target_max'])} 元</li>"
            if rt.get("industry"):
                s6 += f"<li>· 所属行业：{rt['industry']}</li>"
            s6 += "</ul>"

        # 业绩预告
        fc = q.get("forecast")
        if fc:
            s6 += "<h4>最新业绩预告</h4><ul class='ana'>"
            s6 += f"<li>· 预告类型：<b>{fc.get('type') or '—'}</b>（报告期 {fc.get('report_date') or '—'}）</li>"
            if fc.get("amp_low") is not None and fc.get("amp_up") is not None:
                s6 += f"<li>· 预计变动幅度：{fmt(fc['amp_low'])}% ～ {fmt(fc['amp_up'])}%</li>"
            if fc.get("content"):
                s6 += f"<li>· 摘要：{fc['content']}</li>"
            s6 += "</ul>"

        s6 += ("<p class='disc'>上述为客观行情/财务/评级数据聚合，非买卖建议；"
               "具体操作需结合公司基本面深度研究、行业周期与大盘环境综合考量。</p>")
    sec("五、赛轮轮胎 / 博实股份 半研究", s6)

    # ---------- 7、推荐 2 支 10 元左右 ----------
    s7 = ""
    if recs:
        s7 += "<h3>候选筛选结果（8–13 元、当日上涨、成交额≥2 亿，叠加机构评级）</h3>"
        s7 += ('<table><tr><th>股票</th><th>现价</th><th>涨跌幅</th><th>市盈率</th>'
               '<th>机构评级</th><th>明年EPS预期</th><th>目标价区间</th><th>推荐理由</th></tr>')
        for q in recs:
            cp = float(q["change_pct"] or 0)
            cls = "up" if cp > 0 else "down"
            pe = fmt(q["pe"]) if q["pe"] else "—"
            rt = q.get("rating")
            if rt and rt.get("org"):
                rating_txt = f"{rt['bull']}/{rt['org']}看多"
            else:
                rating_txt = "—"
            eps_txt = fmt(rt["eps_next"]) if (rt and rt.get("eps_next")) else "—"
            tgt = (f"{fmt(rt['target_min'])}-{fmt(rt['target_max'])}" if (rt and rt.get("target_min")) else "—")
            reason = build_reason(q, sectors[:3], rt)
            s7 += (f"<tr><td><b>{q['name']}</b><br><span class='code'>{q['code'].upper()}</span></td>"
                   f"<td>{fmt(q['price'])}</td><td class='{cls}'>{fmt(cp)}%</td><td>{pe}</td>"
                   f"<td>{rating_txt}</td><td>{eps_txt}</td><td>{tgt}</td><td>{reason}</td></tr>")
        s7 += "</table>"
        # 基本面补充（前2名）
        for q in recs:
            fin = q.get("fin")
            if fin and fin.get("rep_name"):
                s7 += (f"<p class='ana'>· <b>{q['name']}</b>（{fin['rep_name']}）：营收 "
                       f"{fmt(fin['revenue_yi']) if fin['revenue_yi'] is not None else '—'} 亿"
                       f"(同比{fmt(fin['rev_yoy'])}%)、净利 "
                       f"{fmt(fin['np_yi']) if fin['np_yi'] is not None else '—'} 亿"
                       f"(同比{fmt(fin['np_yoy'])}%)、毛利率 {fmt(fin['gm'])}%。</p>")
    else:
        s7 += "<p>今日候选池中无同时满足「8–13 元 + 上涨 + 流动性达标」的标的，"
        s7 += "建议结合明日盘面再从观察池中择优。</p>"
    s7 += ("<p class='disc'>⚠️ 上述个股为量化初筛（价格区间 + 动量 + 估值 + 机构评级），"
           "并非买入建议。请务必自行研究基本面与风险后决策。</p>")
    sec("六、推荐 2 支 10 元左右股票", s7)

    text = build_text(date_str, indices, sectors, up, down, total_net, capital_items,
                      focus, recs, is_trading_day)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>A股每日行情简报 - {date_str}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{font-family:-apple-system,"Microsoft YaHei",sans-serif;background:#f0f2f5;color:#222;padding:16px;}}
.container{{max-width:820px;margin:0 auto;}}
.header{{background:linear-gradient(135deg,#0d47a1,#1976d2);color:#fff;padding:22px 26px;border-radius:10px 10px 0 0;}}
.header h1{{font-size:21px;margin-bottom:6px;}}
.header .meta{{font-size:13px;opacity:.9;}}
.section{{background:#fff;padding:18px 22px;margin-bottom:14px;border-radius:8px;}}
.section h2{{font-size:17px;color:{REPORT_ACCENT};border-left:4px solid {REPORT_ACCENT};padding-left:10px;margin-bottom:12px;}}
h3{{font-size:14.5px;color:#333;margin:14px 0 8px;}}
h4{{font-size:13px;color:{REPORT_ACCENT};margin:10px 0 4px;font-weight:600;}}
table{{width:100%;border-collapse:collapse;font-size:12.5px;margin-bottom:6px;}}
th{{background:#e8f0fe;padding:7px 8px;text-align:left;font-weight:600;color:#0d47a1;}}
td{{padding:6px 8px;border-bottom:1px solid #f0f0f0;}}
tr:hover td{{background:#f7fbff;}}
.up{{color:#c62828;font-weight:700;}}
.down{{color:#1565c0;font-weight:700;}}
.code{{font-size:11px;color:#888;}}
.ana{{font-size:12.5px;line-height:1.7;margin:3px 0;color:#444;}}
.note{{font-size:12px;color:#777;line-height:1.6;margin:4px 0;}}
.breadth{{font-size:13px;margin-top:8px;}}
.disc{{font-size:11.5px;color:#b71c1c;background:#fdecea;padding:9px 11px;border-radius:6px;margin-top:8px;line-height:1.6;}}
.notice{{background:#fff8e1;color:#8a6d00;padding:10px 14px;border-radius:8px;margin-bottom:14px;font-size:13.5px;}}
.footer{{text-align:center;color:#999;font-size:12px;padding:14px;}}
</style></head><body><div class="container">
<div class="header"><h1>📈 A 股每日行情简报（行情 + 基本面）</h1>
<div class="meta">报告日期：{date_str}　|　行情：腾讯财经　基本面：东方财富　|　生成：{now_str}</div></div>
{note}
{''.join(W)}
{disclaimer}
<div class="footer">本简报由 AI 事务管家自动生成 · 数据聚合，仅供信息参考，不构成投资建议</div>
</div></body></html>"""
    return html, text


def build_reason(q, top_sectors, rt):
    parts = []
    cp = float(q["change_pct"] or 0)
    pe = float(q["pe"] or 0)
    price = float(q["price"] or 0)
    amount = float(q["amount_wan"] or 0)
    parts.append(f"价格 {fmt(price)} 元落入 10 元附近区间")
    parts.append(f"当日上涨 {fmt(cp)}%、具备短期动量")
    if 0 < pe <= 30:
        parts.append(f"市盈率 {fmt(pe)} 估值相对合理")
    elif pe > 30:
        parts.append(f"市盈率 {fmt(pe)} 偏高，注意估值")
    if amount >= 80000:
        parts.append("成交额放大、流动性好")
    if rt and rt.get("bull_ratio") is not None and rt["bull_ratio"] >= 0.6:
        parts.append(f"机构看多比例 {fmt(rt['bull_ratio']*100)}%")
    if q["name"] and any(k in (q["name"] or "") for k in [s["name"] for s in top_sectors]):
        parts.append("所属板块位居今日强势前列")
    return "；".join(parts) + "。"


def build_text(date_str, indices, sectors, up, down, total_net, capital_items,
               focus, recs, is_trading_day):
    L = []
    L.append(f"【A股每日行情简报(行情+基本面) {date_str}】")
    if not is_trading_day:
        L.append("（非交易日，以下为最近交易日数据）")
    L.append("—— 一、大盘 ——")
    for q in indices:
        cp = float(q["change_pct"] or 0)
        L.append(f"{q['label']} {fmt(q['price'])} 涨跌{fmt(q['change'])} ({fmt(cp)}%)")
    L.append("—— 二、板块强弱 ——")
    L.append("最强3：" + "、".join(f"{s['name']}({fmt(float(s['change_pct'] or 0))}%)" for s in sectors[:3]))
    L.append("最弱3：" + "、".join(f"{s['name']}({fmt(float(s['change_pct'] or 0))}%)" for s in sectors[-3:][::-1]))
    L.append(f"广度：上涨{len(up)}/下跌{len(down)}/平{len([s for s in sectors if float(s['change_pct'] or 0)==0])}")
    L.append("—— 三、主力资金(近似) ——")
    L.append(f"主动资金净流向：{fmt_yi(total_net)}（内外盘近似）")
    if capital_items:
        L.append("净流入前3：" + "、".join(f"{q['name']}({fmt_yi(q['active_net_yi'])})" for q in capital_items[:3]))
        L.append("净流出前3：" + "、".join(f"{q['name']}({fmt_yi(q['active_net_yi'])})" for q in capital_items[-3:][::-1]))
    L.append("—— 四、明日观察池 ——")
    for code, q in focus.items():
        L.append(f"{q['label']} {fmt(q['price'])} ({fmt(float(q['change_pct'] or 0))}%)")
    for q in recs:
        L.append(f"{q['name']} {fmt(q['price'])} ({fmt(float(q['change_pct'] or 0))}%)")
    L.append("—— 五、赛轮/博实 半研究 ——")
    for code, q in focus.items():
        fin = q.get("fin")
        rt = q.get("rating")
        fstr = ""
        if fin and fin.get("np_yi") is not None:
            fstr = f" 最新季净利{fmt(fin['np_yi'])}亿(同比{fmt(fin['np_yoy'])}%)"
        rstr = ""
        if rt and rt.get("org"):
            rstr = f" 评级{rt['bull']}/{rt['org']}看多"
        L.append(f"{q['label']} 价{fmt(q['price'])} 涨{fmt(float(q['change_pct'] or 0))}% PE{fmt(q['pe']) if q['pe'] else '—'} 市值{fmt(q['mktcap_yi'],2,'亿') if q['mktcap_yi'] else '—'}{fstr}{rstr}")
    L.append("—— 六、10元附近推荐 ——")
    for q in recs:
        rt = q.get("rating")
        rstr = f" 评级{rt['bull']}/{rt['org']}看多" if (rt and rt.get("org")) else ""
        L.append(f"{q['name']}({q['code'].upper()}) {fmt(q['price'])} 涨{fmt(float(q['change_pct'] or 0))}% PE{fmt(q['pe']) if q['pe'] else '—'}{rstr}")
    L.append("⚠️ 数据聚合，仅供信息参考，不构成投资建议。")
    return "\n".join(L)


# ============================================================
# 邮件发送
# ============================================================
def send_email(html, text, date_str):
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    cfg = pp.CONFIG["email"]
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"【A股每日行情简报】大盘/板块/资金/个股推荐 - {date_str}"
    msg["From"] = cfg["sender_email"]
    msg["To"] = cfg["receiver_email"]
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    with smtplib.SMTP_SSL(cfg["smtp_host"], cfg["smtp_port"]) as server:
        server.login(cfg["sender_email"], cfg["sender_password"])
        server.sendmail(cfg["sender_email"], [cfg["receiver_email"]], msg.as_string())
    print(f"[OK] 邮件已发送至 {cfg['receiver_email']}")


# ============================================================
# 主流程
# ============================================================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    ap.add_argument("--no-send", action="store_true")
    args = ap.parse_args()

    if args.date:
        report_date = args.date
    else:
        report_date = datetime.now().strftime("%Y-%m-%d")

    print(f"[INFO] 行情简报日期 {report_date}")

    indices = get_indices()
    sectors, up, down, flat = get_sectors()
    total_net, capital_items = get_active_capital()
    universe = {q["code"]: q for q in capital_items if q.get("code")}
    focus = analyze_focus()
    top_names = [s["name"] for s in sectors[:3]]
    recs, recs_all = recommend_10yuan(universe, top_names)

    is_trading_day = True
    if indices:
        t = indices[0].get("time") or ""
        if len(t) >= 8 and t[:8] != report_date.replace("-", ""):
            is_trading_day = False

    html, text = build_report(report_date, indices, sectors, up, down, flat,
                              total_net, capital_items, focus, recs, recs_all, is_trading_day)

    path = LOCAL_REPORT.format(date=report_date)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[OK] 本地报表: {path}")
    print("---- 文本版 ----")
    print(text)

    no_send = args.no_send or os.environ.get("REPORT_NO_SEND") == "1"
    if no_send:
        print("[INFO] --no-send，跳过推送")
        return

    try:
        send_email(html, text, report_date)
    except Exception as e:
        print(f"[ERROR] 邮件发送失败: {e}")


if __name__ == "__main__":
    main()
