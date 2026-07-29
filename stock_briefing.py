#!/usr/bin/env python3
"""
觉爱家纺 · A 股每日行情简报
==================================================
数据来源：腾讯财经 qt.gtimg.cn（本环境东方财富 push2 接口被网络策略阻断，改用腾讯源）
输出：HTML 邮件（发送至老板 QQ 邮箱）+ 纯文本（兜底）
定时：收盘后（北京 16:30）触发，周一至周五

报告七大板块：
  1、大盘涨跌（主要指数）
  2、今日最强 3 个板块
  3、今日最弱 3 个板块
  4、主力资金流向（基于内外盘主动买卖净额近似，非东方财富官方主力净流入）
  5、明日观察股票池
  6、赛轮轮胎 / 博实股份 分析
  7、推荐 2 支 10 元左右股票（含原因）

免责声明：本简报由 AI 基于公开市场行情数据自动生成，所列分析与个股提及
仅为信息整理与参考，不构成任何投资建议。股市有风险，投资需谨慎。

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

# 复用老板报表的邮件配置（sender/receiver/password 已在 pospal_report_standalone.CONFIG 中）
import pospal_report_standalone as pp

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOCAL_REPORT = os.path.join(SCRIPT_DIR, "stock_briefing_{date}.html")
RECEIVER = pp.CONFIG["email"]["receiver_email"]

REPORT_ACCENT = "#b71c1c"   # 与老板报表一致的红

# ============================================================
# 标的池
# ============================================================
# 主要指数（用于"大盘涨跌"）
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

# 主流行业/主题指数（用于"板块强弱"排行）。以下代码均已实测返回有效行业指数。
SECTOR_CODES = [
    "sz399965",  # 800地产
    "sz399417",  # 新能源车
    "sz399437",  # 证券龙头
    "sz399440",  # 国证钢铁
    "sz399441",  # 生物医药
    "sh000036",  # 上证消费
    "sh000040",  # 上证电信
    "sz399324",  # 深证红利
    "sz399550",  # 央视50
    "sz399673",  # 创业板50
    "sz399101",  # 中小综指
    "sz399005",  # 中小100
    "sh000044",  # 上证中盘
    "sz399394",  # 国证医药
    "sz399395",  # 国证有色
    "sz399808",  # 中证新能
    "sz399998",  # 中证煤炭
    "sz399973",  # 中证国防
    "sz399975",  # 证券公司
    "sz399986",  # 中证银行
    "sz399971",  # 中证传媒
    "sz399932",  # 中证消费
    "sz399933",  # 中证医药
    "sz399814",  # 大农业
    "sz399995",  # 基建工程
    "sz399807",  # 高铁产业
    "sz980017",  # 国证芯片
    "sh000037",  # 上证医药
    "sh000922",  # 中证红利
    "sz399976",  # CS新能车
    "sz399989",  # 中证医疗
    "sz399997",  # 中证白酒
    "sz399967",  # 中证军工
]

# 重点分析个股
FOCUS = {
    "sh601058": "赛轮轮胎",
    "sz002698": "博实股份",
}

# 推荐/观察 候选池（覆盖多行业、多价位，便于筛选 ~10 元且具动量的标的）
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
    """数值 -> 亿元（带正负号，2 位）"""
    try:
        x = float(v)
        sign = "+" if x >= 0 else "-"
        return f"{sign}{abs(x):,.2f}亿"
    except Exception:
        return "—"


def api_sleep():
    time.sleep(0.25)


def tx_batch(codes):
    """批量抓取腾讯行情，返回 {code: fields(list)}。codes 为腾讯代码（sh/sz 前缀）。"""
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
    """从腾讯字段列表解析为结构化字典（字段为空/异常时给 None）。"""
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
        amt_wan = float(g(37) or 0)   # 成交额(万元)
        # 主动净买入金额(亿元) = (外盘-内盘)/(外盘+内盘) × 成交额(亿)
        # 用比例法，与成交量单位(手/股)无关，且天然不超过全天成交额。
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
        "amount_wan": g(37),     # 成交额(万元)
        "turnover": g(38),       # 换手率%
        "pe": g(39),             # 市盈率TTM
        "pb": g(40),             # 市净率
        "amplitude": (f"{amp:.2f}" if amp is not None else None),
        "mktcap_yi": g(44),      # 总市值(亿)
        "limit_up": g(47),
        "limit_down": g(48),
        "time": g(30),           # YYYYMMDDHHMMSS
        "wai": g(7),
        "nei": g(8),
        "active_net_yi": active_net_yi,
    }


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
        # 用返回的名称（更准），空则用 code
        res.append(q)
    # 按涨跌幅排序
    def cp(q):
        try:
            return float(q["change_pct"] or 0)
        except Exception:
            return -999
    res.sort(key=cp, reverse=True)
    up = [q for q in res if (float(q["change_pct"] or 0)) > 0]
    down = [q for q in res if (float(q["change_pct"] or 0)) < 0]
    flat = [q for q in res if (float(q["change_pct"] or 0)) == 0]
    return res, up, down, flat


def get_active_capital():
    """基于内外盘主动买卖净额，估算市场主力资金净流向（近似）。"""
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
    data = tx_batch(list(FOCUS.keys()))
    res = {}
    for code, name in FOCUS.items():
        f = data.get(code)
        if not f:
            continue
        q = parse_quote(f)
        q["label"] = name
        res[code] = q
    return res


def recommend_10yuan(sectors_top_names):
    """从候选池筛选 ~8-13 元、当日上涨、具备流动性的标的，按动量+估值打分取前 2。"""
    data = tx_batch(SCREEN_UNIVERSE)
    cands = []
    for code in SCREEN_UNIVERSE:
        f = data.get(code)
        if not f:
            continue
        q = parse_quote(f)
        try:
            price = float(q["price"])
            chg = float(q["change_pct"] or 0)
            amount_wan = float(q["amount_wan"] or 0)
            pe = float(q["pe"] or 0)
        except Exception:
            continue
        # 筛选条件
        if not (8.0 <= price <= 13.0):
            continue
        if chg <= 0:
            continue
        if amount_wan < 20000:      # 成交额 < 2 亿，流动性偏弱，剔除
            continue
        # 打分：动量 + 估值合理（PE 0~40）+ 流动性
        score = chg
        if 0 < pe <= 30:
            score += 1.5
        elif 30 < pe <= 50:
            score += 0.5
        if amount_wan >= 80000:
            score += 1.0
        # 若所属板块处于强势榜，加分
        if q["name"] and any(k in (q["name"] or "") for k in sectors_top_names):
            score += 1.0
        q["score"] = score
        cands.append(q)
    cands.sort(key=lambda x: x["score"], reverse=True)
    return cands[:2], cands


# ============================================================
# 报告生成
# ============================================================
def build_report(date_str, indices, sectors, up, down, flat,
                 total_net, capital_items, focus, recs, recs_all, is_trading_day):
    W = []

    def sec(title, body):
        W.append(f'<div class="section"><h2>{title}</h2>{body}</div>')

    disclaimer = ('<p class="disc">⚠️ 免责声明：本简报由 AI 基于公开市场行情数据自动生成，'
                  '所列分析、个股提及与推荐仅为信息整理与参考，<b>不构成任何投资建议</b>。'
                  '股市有风险，投资需谨慎，请结合自身判断独立决策。</p>')

    # ---------- 头部提示 ----------
    if not is_trading_day:
        note = (f'<div class="notice">📌 今日（{date_str}）为非交易日或休市，'
                f'以下数据为最近一个交易日行情，仅供参考。</div>')
    else:
        note = ""

    # ---------- 1、大盘涨跌 ----------
    s1 = '<table><tr><th>指数</th><th>收盘</th><th>涨跌</th><th>涨跌幅</th><th>成交额</th></tr>'
    for q in indices:
        cp = float(q["change_pct"] or 0)
        cls = "up" if cp > 0 else ("down" if cp < 0 else "")
        arrow = "▲" if cp > 0 else ("▼" if cp < 0 else "—")
        s1 += (f"<tr><td>{q['label']}</td><td>{fmt(q['price'])}</td>"
               f"<td class='{cls}'>{fmt(q['change'])}</td>"
               f"<td class='{cls}'>{arrow} {fmt(cp)}%</td>"
               f"<td>{fmt(float(q['amount_wan'] or 0)/10000, 2, '亿') if q['amount_wan'] else '—'}</td></tr>")
    s1 += "</table>"
    sec("一、大盘涨跌", s1)

    # ---------- 2/3、板块强弱 ----------
    def sector_table(rows):
        if not rows:
            return "<p>暂无数据</p>"
        t = '<table><tr><th>板块</th><th>涨跌幅</th><th>领涨/点位</th></tr>'
        for q in rows:
            cp = float(q["change_pct"] or 0)
            cls = "up" if cp > 0 else "down"
            t += (f"<tr><td>{q['name']}</td><td class='{cls}'>{fmt(cp)}%</td>"
                  f"<td>{fmt(q['price'])}</td></tr>")
        t += "</table>"
        return t

    s2 = ""
    s2 += "<h3>🔥 今日最强 3 个板块</h3>"
    s2 += sector_table(sectors[:3])
    s2 += "<h3>❄️ 今日最弱 3 个板块</h3>"
    s2 += sector_table(sectors[-3:][::-1]) if len(sectors) >= 3 else sector_table([])
    s2 += (f"<p class='breadth'>行业广度：监测 {len(sectors)} 个主流行业中，"
           f"<span class='up'>上涨 {len(up)}</span> 个、"
           f"<span class='down'>下跌 {len(down)}</span> 个、平盘 {len(flat)} 个。</p>")
    sec("二、板块强弱（最强 / 最弱）", s2)

    # ---------- 4、主力资金流向（近似） ----------
    s4 = ""
    s4 += (f"<p>全市场主动资金净流向（基于内外盘近似）："
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
    # 赛轮 / 博实 必入
    for code, q in focus.items():
        cp = float(q["change_pct"] or 0)
        cls = "up" if cp > 0 else "down"
        logic = "重点跟踪标的（用户指定）"
        s5 += (f"<tr><td>{q['label']}</td><td>{fmt(q['price'])}</td>"
               f"<td class='{cls}'>{fmt(cp)}%</td><td>{logic}</td></tr>")
    # 推荐股入池
    for q in recs:
        cp = float(q["change_pct"] or 0)
        cls = "up" if cp > 0 else "down"
        s5 += (f"<tr><td>{q['name']}</td><td>{fmt(q['price'])}</td>"
               f"<td class='{cls}'>{fmt(cp)}%</td><td>10元附近+动量候选</td></tr>")
    s5 += "</table>"
    sec("四、明日观察股票池", s5)

    # ---------- 6、赛轮轮胎 / 博实股份 分析 ----------
    s6 = ""
    for code, q in focus.items():
        cp = float(q["change_pct"] or 0)
        cls = "up" if cp > 0 else "down"
        pe = fmt(q["pe"]) if q["pe"] else "—"
        pb = fmt(q["pb"]) if q["pb"] else "—"
        mc = fmt(q["mktcap_yi"], 2, "亿") if q["mktcap_yi"] else "—"
        amp = fmt(q["amplitude"]) if q["amplitude"] else "—"
        turn = fmt(q["turnover"]) if q["turnover"] else "—"
        s6 += f"<h3>{q['label']}（{q['code'].upper()}）</h3>"
        s6 += ('<table><tr><th>现价</th><th>涨跌幅</th><th>振幅</th><th>换手</th>'
               '<th>市盈率(TTM)</th><th>市净率</th><th>总市值</th></tr>')
        s6 += (f"<tr><td>{fmt(q['price'])}</td><td class='{cls}'>{fmt(cp)}%</td>"
               f"<td>{amp}%</td><td>{turn}%</td><td>{pe}</td><td>{pb}</td><td>{mc}</td></tr>")
        s6 += "</table>"
        # 数据驱动点评（非预测）
        trend = ("当日收涨" if cp > 0 else ("收跌" if cp < 0 else "平盘"))
        s6 += (f"<p class='ana'>· 数据快照：{q['label']} 今日{trend} {fmt(cp)}%，"
               f"振幅 {amp}%，换手 {turn}%，换手反映交投活跃度；"
               f"当前市盈率(TTM) {pe}、市净率 {pb}，总市值 {mc}。"
               f"主动买卖净额 {fmt_yi(q['active_net_yi']) if q['active_net_yi'] is not None else '—'}，"
               f"可观察资金态度。</p>")
        s6 += ("<p class='ana'>· 提示：以上为客观行情指标，不构成买卖判断；"
               "具体操作需结合公司基本面、行业周期与大盘环境综合考量。</p>")
    sec("五、赛轮轮胎 / 博实股份 分析", s6)

    # ---------- 7、推荐 2 支 10 元左右股票 ----------
    s7 = ""
    if recs:
        s7 += "<h3>候选筛选结果（8–13 元、当日上涨、成交额≥2 亿）</h3>"
        s7 += '<table><tr><th>股票</th><th>现价</th><th>涨跌幅</th><th>市盈率</th><th>总市值</th><th>推荐理由</th></tr>'
        for rank, q in enumerate(recs, 1):
            cp = float(q["change_pct"] or 0)
            cls = "up" if cp > 0 else "down"
            pe = fmt(q["pe"]) if q["pe"] else "—"
            mc = fmt(q["mktcap_yi"], 2, "亿") if q["mktcap_yi"] else "—"
            reason = build_reason(q, sectors[:3])
            s7 += (f"<tr><td><b>{q['name']}</b><br><span class='code'>{q['code'].upper()}</span></td>"
                   f"<td>{fmt(q['price'])}</td><td class='{cls}'>{fmt(cp)}%</td>"
                   f"<td>{pe}</td><td>{mc}</td><td>{reason}</td></tr>")
        s7 += "</table>"
    else:
        s7 += "<p>今日候选池中无同时满足「8–13 元 + 上涨 + 流动性达标」的标的，"
        s7 += "建议结合明日盘面再从观察池中择优。</p>"
    s7 += ("<p class='disc'>⚠️ 上述个股仅为量化初筛（价格区间 + 动量 + 估值 + 流动性），"
           "并非买入建议。请务必自行研究基本面与风险后决策。</p>")
    sec("六、推荐 2 支 10 元左右股票", s7)

    # 纯文本版（兜底）
    text = build_text(date_str, indices, sectors, up, down, total_net, capital_items,
                      focus, recs, is_trading_day)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>A股每日行情简报 - {date_str}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{font-family:-apple-system,"Microsoft YaHei",sans-serif;background:#f0f2f5;color:#222;padding:16px;}}
.container{{max-width:800px;margin:0 auto;}}
.header{{background:linear-gradient(135deg,#0d47a1,#1976d2);color:#fff;padding:22px 26px;border-radius:10px 10px 0 0;}}
.header h1{{font-size:21px;margin-bottom:6px;}}
.header .meta{{font-size:13px;opacity:.9;}}
.section{{background:#fff;padding:18px 22px;margin-bottom:14px;border-radius:8px;}}
.section h2{{font-size:17px;color:{REPORT_ACCENT};border-left:4px solid {REPORT_ACCENT};padding-left:10px;margin-bottom:12px;}}
h3{{font-size:14.5px;color:#333;margin:14px 0 8px;}}
table{{width:100%;border-collapse:collapse;font-size:13px;margin-bottom:6px;}}
th{{background:#e8f0fe;padding:8px 9px;text-align:left;font-weight:600;color:#0d47a1;}}
td{{padding:7px 9px;border-bottom:1px solid #f0f0f0;}}
tr:hover td{{background:#f7fbff;}}
.up{{color:#c62828;font-weight:700;}}
.down{{color:#1565c0;font-weight:700;}}
.code{{font-size:11px;color:#888;}}
.ana{{font-size:13px;line-height:1.8;margin:4px 0;color:#444;}}
.note{{font-size:12.5px;color:#777;line-height:1.7;margin:4px 0;}}
.breadth{{font-size:13px;margin-top:8px;}}
.disc{{font-size:12px;color:#b71c1c;background:#fdecea;padding:10px 12px;border-radius:6px;margin-top:8px;line-height:1.7;}}
.notice{{background:#fff8e1;color:#8a6d00;padding:10px 14px;border-radius:8px;margin-bottom:14px;font-size:13.5px;}}
.footer{{text-align:center;color:#999;font-size:12px;padding:14px;}}
</style></head><body><div class="container">
<div class="header"><h1>📈 A 股每日行情简报</h1>
<div class="meta">报告日期：{date_str}　|　数据来源：腾讯财经　|　生成：{now_str}</div></div>
{note}
{''.join(W)}
{disclaimer}
<div class="footer">本简报由 AI 事务管家自动生成 · 仅供信息参考，不构成投资建议</div>
</div></body></html>"""
    return html, text


def build_reason(q, top_sectors):
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
    if q["name"] and any(k in (q["name"] or "") for k in [s["name"] for s in top_sectors]):
        parts.append("所属板块位居今日强势前列")
    return "；".join(parts) + "。"


def build_text(date_str, indices, sectors, up, down, total_net, capital_items,
               focus, recs, is_trading_day):
    L = []
    L.append(f"【A股每日行情简报 {date_str}】")
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
    L.append("—— 五、赛轮/博实 ——")
    for code, q in focus.items():
        L.append(f"{q['label']} 价{fmt(q['price'])} 涨{fmt(float(q['change_pct'] or 0))}% PE{fmt(q['pe']) if q['pe'] else '—'} 市值{fmt(q['mktcap_yi'],2,'亿') if q['mktcap_yi'] else '—'}")
    L.append("—— 六、10元附近推荐 ——")
    for q in recs:
        L.append(f"{q['name']}({q['code'].upper()}) {fmt(q['price'])} 涨{fmt(float(q['change_pct'] or 0))}% PE{fmt(q['pe']) if q['pe'] else '—'}")
    L.append("⚠️ 仅供信息参考，不构成投资建议。")
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
    focus = analyze_focus()
    top_names = [s["name"] for s in sectors[:3]]
    recs, recs_all = recommend_10yuan(top_names)

    # 是否交易日：以主要指数行情时间判断（非交易日时间为旧日期或非交易时段）
    is_trading_day = True
    if indices:
        t = indices[0].get("time") or ""
        if len(t) >= 8:
            idx_date = t[:8]
            # 若指数数据日期不是今天，且今天不是周五后(周末)场景，简单判定非交易
            if idx_date != report_date.replace("-", ""):
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
