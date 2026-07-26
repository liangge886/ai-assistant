#!/usr/bin/env python3
"""
觉爱家纺 · 每日经营分析报表（V2：含成本/净利润/会员/补货）
==================================================
按最新规格实现，报表结构：
    一、今日经营汇总（营业额/毛利/毛利率/订单/客单价/总成本/净利润/净利率 + 昨日&上周对比 + 新增会员）
    二、门店对比（排名 + 每店 营业额/毛利/订单/客单价/日成本/净利润/净利率 + 成本明细）
    三、销售 TOP5 商品（按金额，含所属门店）
    四、成本明细（各店 工资+提成+房租=日成本→净利润；昨日对比）
    五、补货提醒（当月有销量且库存≤2，按门店分开）

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
# 报表生成（5 段）
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

    # ---------- 三、销售 TOP5 ----------
    top5 = stores_data["top5"]
    if top5:
        trows = ""
        for i, p in enumerate(top5, 1):
            stores_txt = "、".join(p["stores"]) if p["stores"] else "—"
            trows += f"<tr><td>{i}</td><td>{p['name']}</td><td>{fmt_money(p['amount'])}</td><td>{stores_txt}</td></tr>"
        s3 = f"<table><tr><th>排名</th><th>商品</th><th>销售金额</th><th>所属门店</th></tr>{trows}</table>"
    else:
        s3 = "<p>今日无销售数据。</p>"
    sec("三、销售 TOP5 商品", s3)

    # ---------- 四、成本明细（含昨日对比） ----------
    s4 = "<table><tr><th>门店</th><th>今日日成本</th><th>今日净利润</th><th>昨日日成本</th><th>昨日净利润</th></tr>"
    for s in ranked:
        s4 += (f"<tr><td>{s['name']}</td><td>{fmt_money(s['day_cost'])}</td><td>{fmt_money(s['net'])}</td>"
               f"<td>{fmt_money(s['yest_cost'])}</td><td>{fmt_money(s['yest_net'])}</td></tr>")
    s4 += f"<tr style='font-weight:700'><td>合计</td><td>{fmt_money(tc)}</td><td>{fmt_money(tn)}</td><td>{fmt_money(yc)}</td><td>{fmt_money(yn)}</td></tr>"
    s4 += "</table>"
    sec("四、成本明细", s4)

    # ---------- 五、补货提醒（按门店分开） ----------
    any_repl = False
    s5 = ""
    for s in stores_data["stores"]:
        items = s.get("replen", [])
        if not items:
            continue
        any_repl = True
        s5 += f"<h3>{s['name']}</h3><table><tr><th>商品</th><th>当前库存</th><th>当月销量</th><th>售价</th></tr>"
        for it in items:
            s5 += f"<tr><td>{it['name']}</td><td class='bad'>{it['stock']}</td><td>{it['month_qty']:.0f}</td><td>{fmt_money(it['price'])}</td></tr>"
        s5 += "</table>"
    if not any_repl:
        s5 = "<p>当前无「当月有销量且库存≤2」的商品，库存健康。✅</p>"
    else:
        s5 += "<ul class='ana'><li>· 以上商品当月有动销但库存≤2，建议尽快补货/调货，避免断货流失。</li></ul>"
    sec("五、补货提醒", s5)

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
    L.append("—— TOP5 商品 ——")
    for i, p in enumerate(top5, 1):
        L.append(f"{i}. {p['name']} {fmt_money(p['amount'])}（{'、'.join(p['stores']) or '—'}）")
    L.append("—— 补货提醒 ——")
    found = False
    for s in stores_data["stores"]:
        for it in s.get("replen", []):
            found = True
            L.append(f"{s['name']}：{it['name']} 库存{it['stock']}/当月售{it['month_qty']:.0f}")
    if not found:
        L.append("当前无紧急补货商品 ✅")
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
    all_today_tk = []
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
        month_tk = fetch_monthly(p, report_date)
        inv = fetch_inventory(p)
        members = fetch_members(p, report_date)
        global_members += len(members)
        raw[name] = {
            "today": len(today_tk), "yesterday": len(yest_tk),
            "lastweek": len(lw_tk), "month": len(month_tk),
            "inventory": len(inv), "members": len(members),
        }

        today_a = pp.analyze_sales(today_tk)
        yest_a = pp.analyze_sales(yest_tk)
        lw_a = pp.analyze_sales(lw_tk)
        all_today_tk.extend(today_tk)

        wage, comm, rent, day_cost = cost_breakdown(today_a["total_sales"], cfg)
        ywage, ycomm, yrent, yday_cost = cost_breakdown(yest_a["total_sales"], cfg)
        net = today_a["total_profit"] - day_cost
        ynet = yest_a["total_profit"] - yday_cost
        net_margin = (net / today_a["total_sales"] * 100) if today_a["total_sales"] else 0

        # 补货：当月有销量 且 库存≤2
        month_prod = agg_products(month_tk)
        stock_map = {it["name"]: it for it in inv.get("stock_summary", [])} if isinstance(inv, dict) else {}
        # analyze_inventory 返回的 stock_summary 在 inv["stock_summary"]
        replen = []
        inv_sum = inv.get("stock_summary", []) if isinstance(inv, dict) else []
        for it in inv_sum:
            nm = it.get("name", "")
            mp = month_prod.get(nm)
            if mp and mp["quantity"] > 0 and float(it.get("stock", 0) or 0) <= 2:
                replen.append({"name": nm, "stock": float(it.get("stock", 0) or 0),
                                "month_qty": mp["quantity"], "price": float(it.get("sell_price", 0) or 0)})

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

    # TOP5（全局，按金额，带门店）
    gp = agg_products(all_today_tk)
    top5 = sorted(gp.values(), key=lambda x: x["amount"], reverse=True)[:5]
    for p in top5:
        p["stores"] = sorted(p["stores"])
    stores_data["top5"] = top5

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
