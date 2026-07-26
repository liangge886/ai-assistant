#!/usr/bin/env python3
"""
觉爱家纺 · 每日经营分析报表（V2：含成本/净利润/会员/补货）
==================================================
按最新规格实现，报表结构：
    一、今日经营汇总（营业额/毛利/毛利率/订单/客单价/总成本/净利润/净利率 + 昨日&上周对比 + 新增会员）
    二、门店对比（排名 + 每店 营业额/毛利/订单/客单价/日成本/净利润/净利率 + 成本明细）
    三、商品销售排名（按门店单独列出：当日销量排名全部有销量商品 + 近30天销量>1排名）
    四、补货提醒（近30天动销且库存≤2，按门店分开；含换季提前备货提醒）

数据：银豹(PosPal) API（复用 pospal_report_standalone 取数）
推送：① QQ 邮箱（保留）；② 飞书 `lark-cli` 私聊老板（open_id）
数据存档：/workspace/scripts/data/pospal_data.json

用法：
    python3 boss_daily_report.py                 # 自动判定日期并推送
    python3 boss_daily_report.py --date 2026-07-26
    python3 boss_daily_report.py --no-send        # 只生成本地，不推送
环境变量：REPORT_NO_SEND=1 等价于 --no-send
"""

import os
import sys
import os as _os
import json
import time
import argparse
import shutil
import subprocess
from datetime import datetime, timedelta

import pospal_report_standalone as pp  # 复用：PosPal 取数 + CONFIG（门店/邮件）

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOCAL_REPORT = os.path.join(SCRIPT_DIR, "boss_report_{date}.html")
DATA_DIR = os.path.join(SCRIPT_DIR, "scripts", "data")
DATA_FILE = os.path.join(DATA_DIR, "pospal_data.json")
FEISHU_UID = "ou_1c19080603d7c0ec43d4bfa1ce378a62"   # 老板飞书 open_id

# ============================================================
# 门店成本配置（来自经营规格）
# ============================================================
COST = {
    "觉爱家纺泰安店（新时代徐家楼店）": {"staff": 2, "monthly_salary": 2400, "commission": 0.015, "rent_type": "fixed", "rent_value": 340},
    "觉爱家纺禹城店":                   {"staff": 1, "monthly_salary": 2200, "commission": 0.03,  "rent_type": "pct",   "rent_value": 0.14},
    "觉爱家纺肥城店":                   {"staff": 2, "monthly_salary": 2500, "commission": 0.01,  "rent_type": "pct",   "rent_value": 0.12},
}


# ============================================================
# 工具
# ============================================================
def fmt_money(v) -> str:
    try:
        return f"¥{float(v):,.2f}"
    except Exception:
        return "—"


def fmt_pct(v) -> str:
    try:
        return f"{float(v):.1f}%"
    except Exception:
        return "—"


def delta_pct(cur, prev):
    try:
        cur, prev = float(cur), float(prev)
    except Exception:
        return None
    if prev == 0:
        return None
    return (cur - prev) / abs(prev) * 100


def trend(cur, prev, better_up=True):
    d = delta_pct(cur, prev)
    if d is None:
        return "（无对比）"
    if d == 0:
        return "持平"
    arrow = "▲" if d > 0 else "▼"
    good = (d > 0) if better_up else (d < 0)
    return f'<span class="trend {("good" if good else "bad")}">{arrow} {abs(d):.1f}%</span>'


def api_sleep():
    time.sleep(0.3)  # 规格要求：API 调用间隔 0.3s，避免频率限制


# ============================================================
# 取数（带 0.3s 间隔 + 配额容错 + 门店标记）
# ============================================================
def fetch_tickets(store_pospal, date_str, label):
    api_sleep()
    try:
        tk = pp.fetch_sales_data(store_pospal, date_str)
        for t in tk:
            t["_store"] = store_pospal.get("_name", "")
        return tk
    except Exception as e:
        print(f"[WARN] {store_pospal.get('_name')} {label} 取数失败: {e}")
        return []


def fetch_monthly(store_pospal, date_str):
    api_sleep()
    try:
        tk = pp.fetch_monthly_sales_data(store_pospal, date_str)
        for t in tk:
            t["_store"] = store_pospal.get("_name", "")
        return tk
    except Exception as e:
        print(f"[WARN] {store_pospal.get('_name')} 当月取数失败: {e}")
        return []


def fetch_30d(store_pospal, date_str):
    """拉取指定日期往前 30 天（含当日，共 30 天）的销售单据，按门店标记"""
    api_sleep()
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        start = (dt - timedelta(days=29)).strftime("%Y-%m-%d")
        payload = {
            "startTime": f"{start} 00:00:00",
            "endTime": f"{date_str} 23:59:59",
            "noLimitTimeRange": 1,
        }
        tk = pp.fetch_all_pages(
            store_pospal["url_prefix"], store_pospal["app_id"], store_pospal["app_key"],
            "/pospal-api2/openapi/v1/ticketOpenApi/queryTicketPages",
            payload,
        )
        for t in tk:
            t["_store"] = store_pospal.get("_name", "")
        return tk
    except Exception as e:
        print(f"[WARN] {store_pospal.get('_name')} 近30天取数失败: {e}")
        return []


def fetch_inventory(store_pospal):
    api_sleep()
    try:
        return pp.fetch_inventory_data(store_pospal)
    except Exception as e:
        print(f"[WARN] {store_pospal.get('_name')} 库存取数失败: {e}")
        return []


def fetch_members(store_pospal, date_str):
    api_sleep()
    try:
        return pp.fetch_all_pages(
            store_pospal["url_prefix"], store_pospal["app_id"], store_pospal["app_key"],
            "/pospal-api2/openapi/v1/customerOpenApi/queryCustomerPages",
            {"startCreateDateTime": f"{date_str} 00:00:00"},
        )
    except Exception as e:
        print(f"[WARN] {store_pospal.get('_name')} 会员取数失败: {e}")
        return []


# ============================================================
# 商品聚合（带门店归属）
# ============================================================
def agg_products(tickets):
    d = {}
    for t in tickets:
        if t.get("ticketType") != "SELL" or t.get("invalid", 0) != 0:
            continue
        store = t.get("_store", "")
        for it in t.get("items", []):
            name = it.get("name", "")
            rec = d.setdefault(name, {"name": name, "quantity": 0.0, "amount": 0.0, "profit": 0.0, "stores": set()})
            rec["quantity"] += float(it.get("quantity", 0) or 0)
            rec["amount"] += float(it.get("totalAmount", 0) or 0)
            rec["profit"] += float(it.get("totalProfit", 0) or 0)
            if store:
                rec["stores"].add(store)
    return d


def agg_store_products(tickets):
    """单店商品聚合（不含门店集合，按销量/金额/毛利汇总）"""
    d = {}
    for t in tickets:
        if t.get("ticketType") != "SELL" or t.get("invalid", 0) != 0:
            continue
        for it in t.get("items", []):
            name = it.get("name", "")
            rec = d.setdefault(name, {"name": name, "quantity": 0.0, "amount": 0.0, "profit": 0.0})
            rec["quantity"] += float(it.get("quantity", 0) or 0)
            rec["amount"] += float(it.get("totalAmount", 0) or 0)
            rec["profit"] += float(it.get("totalProfit", 0) or 0)
    return d


# ============================================================
# 成本与净利润
# ============================================================
def cost_breakdown(sales, cfg):
    daily_wage = cfg["monthly_salary"] / 30 * cfg["staff"]
    commission = sales * cfg["commission"]
    rent = cfg["rent_value"] if cfg["rent_type"] == "fixed" else sales * cfg["rent_value"]
    day_cost = daily_wage + commission + rent
    return daily_wage, commission, rent, day_cost


# ============================================================
# 换季提醒：当前月份应提前备货的品类关键词
# ============================================================
def seasonal_keywords(month):
    """按月份返回应提前备货的换季品类关键词（用于换季提醒）。

    逻辑：在季节切换前，提前关注下一季主力品类的库存，避免换季断货。
    例如 7 月（夏末）应关注「春秋被/冬被」的铺货。
    """
    table = {
        1: ["冬被", "加厚", "绒", "毛毯"],
        2: ["春秋被", "春"],
        3: ["春秋被", "春", "薄被"],
        4: ["夏被", "凉席", "夏凉", "冰丝"],
        5: ["夏被", "凉席", "夏凉", "冰丝"],
        6: ["夏被", "凉席", "夏凉", "冰丝"],
        7: ["春秋被", "冬被"],
        8: ["春秋被", "冬被", "加厚", "绒"],
        9: ["冬被", "加厚", "绒", "毛毯"],
        10: ["冬被", "加厚", "绒", "毛毯"],
        11: ["冬被", "加厚", "绒", "毛毯"],
        12: ["春秋被", "春"],
    }
    return table.get(month, [])


# ============================================================
# 报表生成（4 段）
# ============================================================
def build_report(date_str, yest_str, lw_str, stores_data):
    g = stores_data["global"]
    ts, tp, to = g["today_sales"], g["today_profit"], g["today_orders"]
    tc, tn, tnm = g["today_cost"], g["today_net"], g["today_net_margin"]
    ys, yp = g["yest_sales"], g["yest_profit"]
    yc, yn = g["yest_cost"], g["yest_net"]
    ls = g["lw_sales"]

    gm = (tp / ts * 100) if ts else 0
    avg = (ts / to) if to else 0
    members = g["members"]

    W = []

    def sec(title, body):
        W.append(f'<div class="section"><h2>{title}</h2>{body}</div>')

    # ---------- 一、今日经营汇总 ----------
    s1 = '<div class="kpi-grid">'
    s1 += f'<div class="kpi-card"><div class="label">总营业额</div><div class="value">{fmt_money(ts)}</div>{trend(ts, ys)}</div>'
    s1 += f'<div class="kpi-card"><div class="label">总毛利额</div><div class="value">{fmt_money(tp)}</div>{trend(tp, yp)}</div>'
    s1 += f'<div class="kpi-card"><div class="label">毛利率</div><div class="value">{fmt_pct(gm)}</div></div>'
    s1 += f'<div class="kpi-card"><div class="label">成交订单</div><div class="value">{to} 单</div></div>'
    s1 += f'<div class="kpi-card"><div class="label">平均客单价</div><div class="value">{fmt_money(avg)}</div></div>'
    s1 += f'<div class="kpi-card"><div class="label">今日总成本</div><div class="value">{fmt_money(tc)}</div></div>'
    s1 += f'<div class="kpi-card"><div class="label">今日净利润</div><div class="value green">{fmt_money(tn)}</div>{trend(tn, yn)}</div>'
    s1 += f'<div class="kpi-card"><div class="label">净利润率</div><div class="value green">{fmt_pct(tnm)}</div></div>'
    s1 += "</div>"
    s1 += "<ul class='ana'>"
    s1 += f"<li>· 昨日营业额 {fmt_money(ys)}、昨日净利润 {fmt_money(yn)}（净利率 {fmt_pct(yn/ys*100 if ys else 0)}）</li>"
    if ls:
        s1 += f"<li>· 上周同期营业额 {fmt_money(ls)}（周同比 {trend(ts, ls, True)}）</li>"
    s1 += f"<li>· 今日新增会员 <b>{members}</b> 人</li>"
    if tn < 0:
        s1 += f"<li class='bad'>· ⚠️ 今日净利润为负，成本已超过毛利，需立即核查房租/提成占比或提升高毛利品销售。</li>"
    s1 += "</ul>"
    sec("一、今日经营汇总", s1)

    # ---------- 二、门店对比 ----------
    ranked = sorted(stores_data["stores"], key=lambda s: s["today_sales"], reverse=True)
    rows = ""
    for s in ranked:
        rows += (f"<tr><td>{s['name']}</td><td>{fmt_money(s['today_sales'])}</td>"
                 f"<td>{fmt_money(s['today_profit'])}</td><td>{s['today_orders']}</td>"
                 f"<td>{fmt_money(s['avg_price'])}</td><td>{fmt_money(s['day_cost'])}</td>"
                 f"<td>{fmt_money(s['net'])}</td><td>{fmt_pct(s['net_margin'])}</td></tr>")
    s2 = (f"<p class='rank'>门店排名（按营业额）：" + " ＞ ".join(
        f"{i+1}.{s['name']}（{fmt_money(s['today_sales'])}）" for i, s in enumerate(ranked)) + "</p>")
    s2 += (f"<table><tr><th>门店</th><th>营业额</th><th>毛利额</th><th>订单</th><th>客单价</th>"
           f"<th>日成本</th><th>净利润</th><th>净利率</th></tr>{rows}</table>")
    # 成本明细（每店）
    s2 += "<h3>各门店成本明细（工资+提成+房租）</h3><table><tr><th>门店</th><th>工资</th><th>提成</th><th>房租</th><th>日成本</th><th>净利润</th></tr>"
    for s in ranked:
        s2 += (f"<tr><td>{s['name']}</td><td>{fmt_money(s['wage'])}</td><td>{fmt_money(s['commission'])}</td>"
               f"<td>{fmt_money(s['rent'])}</td><td>{fmt_money(s['day_cost'])}</td><td>{fmt_money(s['net'])}</td></tr>")
    s2 += "</table>"
    sec("二、门店对比", s2)

    # ---------- 三、商品销售排名（按门店单独列出） ----------
    s3 = ""
    for s in stores_data["stores"]:
        s3 += f"<h3>{s['name']}</h3>"
        # 当日销量排名：所有有销量的商品
        tp = s.get("today_products", [])
        if tp:
            s3 += "<h4>▌当日销量排名（全部有销量商品）</h4>"
            s3 += "<table><tr><th>排名</th><th>商品</th><th>销量</th><th>销售额</th><th>毛利</th></tr>"
            for i, p in enumerate(tp, 1):
                s3 += (f"<tr><td>{i}</td><td>{p['name']}</td><td>{p['quantity']:.0f}</td>"
                       f"<td>{fmt_money(p['amount'])}</td><td>{fmt_money(p['profit'])}</td></tr>")
            s3 += "</table>"
        else:
            s3 += "<p>· 当日无销售</p>"
        # 近30天销量排名：销量>1 的商品
        r30 = s.get("rank30_products", [])
        if r30:
            s3 += "<h4>▌近30天销量排名（销量＞1）</h4>"
            s3 += "<table><tr><th>排名</th><th>商品</th><th>销量</th><th>销售额</th><th>毛利</th></tr>"
            for i, p in enumerate(r30, 1):
                s3 += (f"<tr><td>{i}</td><td>{p['name']}</td><td>{p['quantity']:.0f}</td>"
                       f"<td>{fmt_money(p['amount'])}</td><td>{fmt_money(p['profit'])}</td></tr>")
            s3 += "</table>"
        else:
            s3 += "<p>· 近30天无销量＞1的商品</p>"
    sec("三、商品销售排名（按门店）", s3)

    # ---------- 四、补货提醒（近30天动销+库存≤2，按门店；含换季提醒） ----------
    any_repl = False
    any_season = False
    s5 = ""
    for s in stores_data["stores"]:
        items = s.get("replen", [])
        season_items = s.get("seasonal", [])
        if not items and not season_items:
            continue
        s5 += f"<h3>{s['name']}</h3>"
        # 近30天有销量且库存≤2
        if items:
            any_repl = True
            s5 += "<h4>▌近30天动销且库存≤2（建议补货）</h4>"
            s5 += "<table><tr><th>商品</th><th>当前库存</th><th>近30天销量</th><th>售价</th></tr>"
            for it in items:
                s5 += (f"<tr><td>{it['name']}</td><td class='bad'>{it['stock']:.0f}</td>"
                       f"<td>{it['sold_qty']:.0f}</td><td>{fmt_money(it['price'])}</td></tr>")
            s5 += "</table>"
        # 换季提醒：当前应提前备货的品类，库存≤2
        if season_items:
            any_season = True
            kw = "、".join(s.get("season_kw", []))
            s5 += f"<h4>▌换季提醒 · 关注品类：{kw}（库存≤2，建议提前备货）</h4>"
            s5 += "<table><tr><th>商品</th><th>当前库存</th><th>售价</th></tr>"
            for it in season_items:
                s5 += f"<tr><td>{it['name']}</td><td class='bad'>{it['stock']:.0f}</td><td>{fmt_money(it['price'])}</td></tr>"
            s5 += "</table>"
    if not any_repl and not any_season:
        s5 = "<p>当前无紧急补货商品，库存健康。✅</p>"
    else:
        notes = []
        if any_repl:
            notes.append("· 以上商品近30天有动销但库存≤2，建议尽快补货/调货，避免断货流失。")
        if any_season:
            notes.append("· 以上为换季需提前备货的品类（当前库存≤2），请结合季节需求提前铺货，避免换季断货。")
        s5 += "<ul class='ana'>" + "".join(f"<li>{n}</li>" for n in notes) + "</ul>"
    sec("四、补货提醒", s5)

    # ---------- 组装 ----------
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>觉爱家纺·每日经营分析报表 - {date_str}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{font-family:-apple-system,"Microsoft YaHei",sans-serif;background:#f0f2f5;color:#222;padding:16px;}}
.container{{max-width:780px;margin:0 auto;}}
.header{{background:linear-gradient(135deg,#b71c1c,#e53935);color:#fff;padding:22px 26px;border-radius:10px 10px 0 0;}}
.header h1{{font-size:21px;margin-bottom:6px;}}
.header .meta{{font-size:13px;opacity:.9;}}
.section{{background:#fff;padding:20px 24px;margin-bottom:14px;border-radius:8px;}}
.section h2{{font-size:17px;color:#b71c1c;border-left:4px solid #e53935;padding-left:10px;margin-bottom:14px;}}
h3{{font-size:15px;color:#444;margin:14px 0 8px;}}
h4{{font-size:13.5px;color:#b71c1c;margin:14px 0 6px;font-weight:600;}}
.kpi-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:12px;}}
.kpi-card{{background:#fafafa;border:1px solid #eee;border-radius:6px;padding:12px;text-align:center;}}
.kpi-card .label{{font-size:12px;color:#777;}}
.kpi-card .value{{font-size:19px;font-weight:700;color:#b71c1c;margin-top:4px;}}
.kpi-card .value.green{{color:#2e7d32;}}
table{{width:100%;border-collapse:collapse;font-size:13px;}}
th{{background:#fdecea;padding:9px 10px;text-align:left;font-weight:600;color:#b71c1c;}}
td{{padding:8px 10px;border-bottom:1px solid #f0f0f0;}}
tr:hover td{{background:#fff8f8;}}
.rank{{margin:0 0 10px;font-size:13px;color:#555;}}
.ana{{margin:6px 0;padding-left:2px;}}
.ana li{{font-size:13.5px;line-height:1.7;margin:4px 0;list-style:none;}}
.ana li::before{{content:"•";color:#e53935;margin-right:6px;}}
.trend{{font-size:12px;font-weight:700;}}
.trend.good{{color:#2e7d32;}}
.trend.bad{{color:#c62828;}}
.bad{{color:#c62828;}}
.footer{{text-align:center;color:#999;font-size:12px;padding:14px;}}
</style></head><body><div class="container">
<div class="header"><h1>📊 觉爱家纺 · 每日经营分析报表</h1>
<div class="meta">报表日期：{date_str}　|　昨日 {yest_str} / 上周同期 {lw_str}　|　生成：{now_str}</div></div>
{''.join(W)}
<div class="footer">数据来源：银豹(PosPal)开放平台 API　|　本报表由 AI 事务管家自动生成</div>
</div></body></html>"""

    # ---------- 纯文本版（飞书）----------
    L = []
    L.append(f"【觉爱家纺 每日经营分析 {date_str}】")
    L.append(f"总营业额 {fmt_money(ts)}（昨日 {fmt_money(ys)}）｜毛利 {fmt_money(tp)}（毛利率 {fmt_pct(gm)}）")
    L.append(f"成交 {to} 单｜客单价 {fmt_money(avg)}｜总成本 {fmt_money(tc)}")
    L.append(f"今日净利润 {fmt_money(tn)}（净利率 {fmt_pct(tnm)}）｜昨日净利润 {fmt_money(yn)}")
    L.append(f"今日新增会员 {members} 人")
    L.append("—— 门店对比（营业额/净利润） ——")
    for s in ranked:
        L.append(f"{s['name']}：营业额 {fmt_money(s['today_sales'])}，净利润 {fmt_money(s['net'])}（净利率 {fmt_pct(s['net_margin'])}），成本 {fmt_money(s['day_cost'])}")
    L.append("—— 商品销售排名（按门店） ——")
    for s in stores_data["stores"]:
        L.append(f"【{s['name']}】")
        tp = s.get("today_products", [])
        if tp:
            L.append("· 当日销量：" + "；".join(f"{p['name']} {p['quantity']:.0f}件" for p in tp))
        else:
            L.append("· 当日无销售")
        r30 = s.get("rank30_products", [])
        if r30:
            # 文本版限前 15 条，避免超长；邮件/网页版为完整全部
            shown = "；".join(f"{p['name']} {p['quantity']:.0f}件" for p in r30[:15])
            more = f"（共 {len(r30)} 项，更多见邮件）" if len(r30) > 15 else ""
            L.append(f"· 近30天(＞1)：{shown}{more}")
        else:
            L.append("· 近30天无销量＞1的商品")
    L.append("—— 补货提醒（近30天动销+库存≤2，按门店） ——")
    found = False
    for s in stores_data["stores"]:
        items = s.get("replen", [])
        if items:
            found = True
            top = sorted(items, key=lambda x: x["sold_qty"], reverse=True)[:5]
            ex = "；".join(f"{it['name']}(库{it['stock']:.0f}/30天{it['sold_qty']:.0f})" for it in top)
            L.append(f"{s['name']}：共 {len(items)} 项，示例 {ex}（完整见邮件）")
        else:
            L.append(f"{s['name']}：近30天动销且库存≤2 无")
    L.append("—— 换季提醒（按门店） ——")
    for s in stores_data["stores"]:
        items = s.get("seasonal", [])
        kw = "、".join(s.get("season_kw", []))
        if items:
            found = True
            L.append(f"{s['name']}【{kw}】共 {len(items)} 款需提前备货（完整见邮件）")
        else:
            L.append(f"{s['name']}【{kw}】库存充足")
    if not found:
        L.append("当前无紧急补货/换季商品 ✅")
    text = "\n".join(L)
    return html, text


# ============================================================
# 飞书推送（lark-cli 私聊老板，open_id）
# ============================================================
def send_feishu(text):
    # 优先 lark-cli（按规格），不可用则回退到 webhook 机器人
    if shutil.which("lark-cli"):
        # 文本过长则分段发送
        chunks = _chunk(text, 1500)
        for i, ch in enumerate(chunks, 1):
            cmd = ["lark-cli", "im", "+messages-send", "--user-id", FEISHU_UID,
                   "--as", "user", "--text", ch]
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                print(f"[OK] 飞书推送({i}/{len(chunks)}) exit={r.returncode} {r.stdout.strip()[:120]}")
            except Exception as e:
                print(f"[ERROR] 飞书推送失败: {e}")
        return
    # 回退：webhook 机器人
    try:
        import feishu_notify
        feishu_notify.send_report(text, _os.environ.get("REPORT_DATE", ""))
    except Exception as e:
        print(f"[WARN] 飞书推送跳过（lark-cli 未安装且无 FEISHU_WEBHOOK）：{e}")


def _chunk(text, size):
    lines = text.split("\n")
    out, cur = [], ""
    for ln in lines:
        if len(cur) + len(ln) + 1 > size and cur:
            out.append(cur)
            cur = ln
        else:
            cur = (cur + "\n" + ln) if cur else ln
    if cur:
        out.append(cur)
    return out or [text]


# ============================================================
# 邮件发送（复用 CONFIG，HTML + 纯文本）
# ============================================================
def send_email(html, text, date_str):
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    cfg = pp.CONFIG["email"]
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"【觉爱家纺】每日经营分析报表（含净利润） - {date_str}"
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
        now = datetime.now()
        report_date = (now - timedelta(days=1)).strftime("%Y-%m-%d") if now.hour < 6 else now.strftime("%Y-%m-%d")
    _os.environ["REPORT_DATE"] = report_date
    dt = datetime.strptime(report_date, "%Y-%m-%d")
    yest_str = (dt - timedelta(days=1)).strftime("%Y-%m-%d")
    lw_str = (dt - timedelta(days=7)).strftime("%Y-%m-%d")
    print(f"[INFO] 报表日期 {report_date}（昨日 {yest_str} / 上周同期 {lw_str}）")

    stores_data = {"stores": [], "global": {}}
    global_members = 0
    raw = {}

    for sc in pp.CONFIG["stores"]:
        name = sc["name"]
        p = dict(sc["pospal"])
        p["_name"] = name
        cfg = COST.get(name)
        if not cfg:
            print(f"[WARN] {name} 无成本配置，跳过")
            continue

        today_tk = fetch_tickets(p, report_date, "今日")
        yest_tk = fetch_tickets(p, yest_str, "昨日")
        lw_tk = fetch_tickets(p, lw_str, "上周同期")
        rank30_tk = fetch_30d(p, report_date)
        inv = fetch_inventory(p)
        # fetch_inventory 返回原始商品列表；analyze_inventory 的 stock_summary 仅取库存前50（高库存），
        # 会漏掉低库存商品，故这里直接遍历原始列表提取在售商品的 名称/库存/售价（不过滤库存量）
        inv_sum = []
        if isinstance(inv, list):
            for pr in inv:
                if pr.get("enable") != 1 or pr.get("noStock") == 1:
                    continue
                inv_sum.append({
                    "name": pr.get("name", ""),
                    "stock": float(pr.get("stock", 0) or 0),
                    "sell_price": float(pr.get("sellPrice", 0) or 0),
                })
        members = fetch_members(p, report_date)
        global_members += len(members)
        raw[name] = {
            "today": len(today_tk), "yesterday": len(yest_tk),
            "lastweek": len(lw_tk), "rank30": len(rank30_tk),
            "inventory": len(inv), "members": len(members),
        }

        today_a = pp.analyze_sales(today_tk)
        yest_a = pp.analyze_sales(yest_tk)
        lw_a = pp.analyze_sales(lw_tk)

        # 单店商品销量排名
        today_prod = agg_store_products(today_tk)
        today_products = sorted(today_prod.values(), key=lambda x: x["quantity"], reverse=True)
        rank30_prod = agg_store_products(rank30_tk)
        rank30_products = sorted(
            [v for v in rank30_prod.values() if v["quantity"] > 1],
            key=lambda x: x["quantity"], reverse=True,
        )

        wage, comm, rent, day_cost = cost_breakdown(today_a["total_sales"], cfg)
        ywage, ycomm, yrent, yday_cost = cost_breakdown(yest_a["total_sales"], cfg)
        net = today_a["total_profit"] - day_cost
        ynet = yest_a["total_profit"] - yday_cost
        net_margin = (net / today_a["total_sales"] * 100) if today_a["total_sales"] else 0

        # 补货：近30天有销量 且 库存≤2（按门店，不混）
        replen = []
        for it in inv_sum:
            nm = it.get("name", "")
            rp = rank30_prod.get(nm)
            if rp and rp["quantity"] > 0 and float(it.get("stock", 0) or 0) <= 2:
                replen.append({"name": nm, "stock": float(it.get("stock", 0) or 0),
                                "sold_qty": rp["quantity"], "price": float(it.get("sell_price", 0) or 0)})
        # 换季提醒：当前应提前备货的品类（库存≤2 即提示，不看近期销量）
        season_kw = seasonal_keywords(dt.month)
        seasonal = []
        if season_kw:
            for it in inv_sum:
                nm = it.get("name", "")
                if any(k in nm for k in season_kw) and float(it.get("stock", 0) or 0) <= 2:
                    seasonal.append({"name": nm, "stock": float(it.get("stock", 0) or 0),
                                     "price": float(it.get("sell_price", 0) or 0)})

        stores_data["stores"].append({
            "name": name,
            "today_sales": today_a["total_sales"], "today_profit": today_a["total_profit"],
            "today_orders": today_a["valid_sell_count"], "avg_price": today_a["avg_price"],
            "wage": wage, "commission": comm, "rent": rent, "day_cost": day_cost,
            "net": net, "net_margin": net_margin,
            "yest_sales": yest_a["total_sales"], "yest_profit": yest_a["total_profit"],
            "yest_cost": yday_cost, "yest_net": ynet,
            "lw_sales": lw_a["total_sales"],
            "replen": replen,
            "seasonal": seasonal,
            "season_kw": season_kw,
            "today_products": today_products,
            "rank30_products": rank30_products,
        })

    # 全局汇总
    ts = sum(s["today_sales"] for s in stores_data["stores"])
    tp = sum(s["today_profit"] for s in stores_data["stores"])
    to = sum(s["today_orders"] for s in stores_data["stores"])
    tc = sum(s["day_cost"] for s in stores_data["stores"])
    tn = sum(s["net"] for s in stores_data["stores"])
    ys = sum(s["yest_sales"] for s in stores_data["stores"])
    yp = sum(s["yest_profit"] for s in stores_data["stores"])
    yc = sum(s["yest_cost"] for s in stores_data["stores"])
    yn = sum(s["yest_net"] for s in stores_data["stores"])
    lw_sales = sum(s.get("lw_sales", 0) for s in stores_data["stores"])

    stores_data["global"] = {
        "today_sales": ts, "today_profit": tp, "today_orders": to,
        "today_cost": tc, "today_net": tn,
        "today_net_margin": (tn / ts * 100) if ts else 0,
        "yest_sales": ys, "yest_profit": yp, "yest_cost": yc, "yest_net": yn,
        "lw_sales": lw_sales, "members": global_members,
    }

    # 存档原始计数
    _os.makedirs(DATA_DIR, exist_ok=True)
    json.dump(raw, open(DATA_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"[OK] 原始数据存档: {DATA_FILE}")

    html, text = build_report(report_date, yest_str, lw_str, stores_data)

    path = LOCAL_REPORT.format(date=report_date)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[OK] 本地报表: {path}")
    print("---- 报表文本（飞书/摘要）----")
    print(text)

    no_send = args.no_send or _os.environ.get("REPORT_NO_SEND") == "1"
    if no_send:
        print("[INFO] --no-send，跳过推送")
    else:
        try:
            send_email(html, text, report_date)
        except Exception as e:
            print(f"[ERROR] 邮件发送失败: {e}")
        try:
            send_feishu(text)
        except Exception as e:
            print(f"[WARN] 飞书推送失败: {e}")


if __name__ == "__main__":
    main()
