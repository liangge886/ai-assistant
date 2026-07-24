#!/usr/bin/env python3
"""
觉爱家纺 · 老板每日经营分析报表（6 段式）
==================================================
数据源：银豹(PosPal)开放平台 API（复用 pospal_report_standalone 的取数/邮件配置）
报表结构（按老板经营决策视角）：
    一、今日经营结果分析（对比昨日 / 上周同期）
    二、三家门店经营对比 + 排名 + 异常诊断
    三、销售过程数据分析（成交率，需门店补录进店客流）
    四、商品销售分析（TOP10 / 商品结构 / 库存提醒）
    五、客户资产分析（需门店补录微信/老客户数据）
    六、老板每日经营总结（亮点/问题/重点门店/重点商品/明日3动作）
输出：HTML 邮件（含正文） + 一份可直接作为「回复邮件」的每日营业总结草稿

用法：
    python3 boss_daily_report.py                 # 自动判定日期，发送邮件
    python3 boss_daily_report.py --date 2026-07-24   # 指定日期
    python3 boss_daily_report.py --no-send        # 只生成本地报表，不发邮件（调试用）

环境变量：REPORT_NO_SEND=1 等价于 --no-send
"""

import os
import sys
import json
import argparse
from datetime import datetime, timedelta

import pospal_report_standalone as pp  # 复用：PosPal 取数 + CONFIG（门店/邮件）

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DAILY_INPUT = os.path.join(SCRIPT_DIR, "daily_input.json")   # 门店每日补录（客流/微信/老客户）
LOCAL_REPORT = os.path.join(SCRIPT_DIR, "boss_report_{date}.html")


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
    """相对变化百分比；prev 为 0 时无法计算，返回 None。"""
    if prev is None:
        return None
    try:
        prev = float(prev)
        cur = float(cur)
    except Exception:
        return None
    if prev == 0:
        return None
    return (cur - prev) / abs(prev) * 100


def trend(cur, prev, better_up=True):
    d = delta_pct(cur, prev)
    if d is None:
        return "（无对比数据）"
    if d == 0:
        return "持平"
    arrow = "▲" if d > 0 else "▼"
    good = (d > 0) if better_up else (d < 0)
    tag = "good" if good else "bad"
    return f'<span class="trend {tag}">{arrow} {abs(d):.1f}%</span>'


def load_extra() -> dict:
    try:
        return json.load(open(DAILY_INPUT, encoding="utf-8"))
    except Exception:
        return {}


# ============================================================
# 取数
# ============================================================
def fetch_tickets(store_cfg, date_str):
    try:
        return pp.fetch_sales_data(store_cfg["pospal"], date_str)
    except Exception as e:
        print(f"[WARN] {store_cfg['name']} {date_str} 取数失败: {e}")
        return []


def fetch_inventory(store_cfg):
    try:
        return pp.fetch_inventory_data(store_cfg["pospal"])
    except Exception as e:
        print(f"[WARN] {store_cfg['name']} 库存取数失败: {e}")
        return []


def global_analysis(tickets_list):
    """合并多家门店单据做全局分析。"""
    merged = []
    for t in tickets_list:
        merged.extend(t)
    return pp.analyze_sales(merged)


# ============================================================
# 商品结构分类（引流 vs 利润，启发式）
# ============================================================
DRAIN_KEYWORDS = ["学生", "三件套", "夏凉被", "枕巾", "毛巾", "凉席", "空调被", "低价", "引流"]
PROFIT_KEYWORDS = ["婚庆", "四件套", "枕芯", "蚕丝", "乳胶", "羽绒", "高端", "套件", "被芯"]


def classify_product(p):
    name = (p.get("name") or "")
    amount = float(p.get("amount") or 0)
    profit = float(p.get("profit") or 0)
    margin = (profit / amount * 100) if amount > 0 else 0
    is_drain = any(k in name for k in DRAIN_KEYWORDS)
    is_profit = any(k in name for k in PROFIT_KEYWORDS) or margin >= 45
    if is_profit and not is_drain:
        return "利润产品"
    if is_drain and not is_profit:
        return "引流产品"
    if is_drain and is_profit:
        return "引流+利润"
    # 既无关键词：按利润率二分
    return "利润产品" if margin >= 35 else "引流产品"


# ============================================================
# 报表生成
# ============================================================
def build_report(date_str, yest_str, lw_str, per_store, global_today, global_yest,
                 global_lw, inventories, extra):
    y = int(date_str[:4])
    # ---- 全局汇总 ----
    g = global_today
    total_sales = g["total_sales"]
    total_profit = g["total_profit"]
    orders = g["valid_sell_count"]
    gm = (total_profit / total_sales * 100) if total_sales else 0
    avg = (total_sales / orders) if orders else 0

    y_sales = global_yest["total_sales"]
    y_profit = global_yest["total_profit"]
    y_orders = global_yest["valid_sell_count"]
    y_gm = (y_profit / y_sales * 100) if y_sales else 0
    y_avg = (y_sales / y_orders) if y_orders else 0

    lw_sales = global_lw["total_sales"]
    lw_profit = global_lw["total_profit"]
    lw_orders = global_lw["valid_sell_count"]
    lw_gm = (lw_profit / lw_sales * 100) if lw_sales else 0
    lw_avg = (lw_sales / lw_orders) if lw_orders else 0

    # ---- 门店排名 ----
    ranked = sorted(per_store.items(), key=lambda kv: kv[1]["total_sales"], reverse=True)
    best_store = ranked[0] if ranked else ("", {})
    worst_store = ranked[-1] if ranked else ("", {})

    # ---- TOP10 商品（全局合并）----
    combo = {}
    for name, s in per_store.items():
        for p in s["products_by_amount"]:
            key = p["name"]
            d = combo.setdefault(key, {"name": p["name"], "quantity": 0.0, "amount": 0.0, "profit": 0.0})
            d["quantity"] += p["quantity"]
            d["amount"] += p["amount"]
            d["profit"] += p["profit"]
    top10 = sorted(combo.values(), key=lambda x: x["amount"], reverse=True)[:10]
    champ = top10[0] if top10 else None                       # 销售冠军
    profit_king = max(combo.values(), key=lambda x: x["profit"]) if combo else None  # 利润贡献最高

    # ---- 库存（跨店合并预警）----
    low_all, zero_all = [], []
    for name, inv in inventories.items():
        for it in inv.get("low_stock_list", []):
            low_all.append({"store": name, **it})
        for it in inv.get("zero_stock_list", []):
            zero_all.append({"store": name, **it})

    # ============ 开始拼 HTML ============
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    W = []

    def sec(title, body):
        W.append(f'<div class="section"><h2>{title}</h2>{body}</div>')

    def kv(label, value, extra_html=""):
        return f'<div class="kpi-card"><div class="label">{label}</div><div class="value">{value}</div>{extra_html}</div>'

    # ---------- 一、今日经营结果分析 ----------
    s1 = '<div class="kpi-grid">'
    s1 += kv("今日总营业额", fmt_money(total_sales), trend(total_sales, y_sales))
    s1 += kv("今日毛利额", fmt_money(total_profit), trend(total_profit, y_profit))
    s1 += kv("今日毛利率", fmt_pct(gm), trend(gm, y_gm, better_up=True))
    s1 += kv("今日成交订单", f"{orders} 单", trend(orders, y_orders))
    s1 += kv("今日客单价", fmt_money(avg), trend(avg, y_avg))
    s1 += kv("对比上周同期", trend(total_sales, lw_sales), "")
    s1 += "</div>"

    ana = []
    d_sales = delta_pct(total_sales, y_sales)
    if d_sales is None:
        ana.append("· 昨日对比数据暂缺，无法计算环比；建议确认昨日门店是否正常营业/上传数据。")
    elif d_sales < -15:
        ana.append(f"· <b class='bad'>今日营业额较昨日下滑 {abs(d_sales):.1f}%，属明显异常</b>：优先排查是否为客流减少、主要品类缺货，或哪家门店出现成交率下滑。")
    elif d_sales < 0:
        ana.append(f"· 今日营业额较昨日小幅下降 {abs(d_sales):.1f}%，基本在正常波动范围。")
    else:
        ana.append(f"· 今日营业额较昨日增长 {d_sales:.1f}%，势头向好。")
    d_gm = delta_pct(gm, y_gm)
    if d_gm is not None and abs(d_gm) > 3:
        ana.append(f"· 毛利率较昨日{'提升' if d_gm>0 else '下降'} {abs(d_gm):.1f} 个百分点"
                   + ("，利润结构改善。" if d_gm > 0 else "，需关注是否低毛利引流品占比过高或折扣过大。"))
    d_avg = delta_pct(avg, y_avg)
    if d_avg is not None and abs(d_avg) > 10:
        ana.append(f"· 客单价较昨日{'上升' if d_avg>0 else '下降'} {abs(d_avg):.1f}%"
                   + ("，连带销售或高客单品类表现好。" if d_avg > 0 else "，可能存在大单流失或高客单商品动销不足。"))
    if not top10:
        ana.append("· 今日暂无成交数据，请确认门店是否正常营业及数据上传。")
    s1 += "<ul class='ana'>" + "".join(f"<li>{a}</li>" for a in ana) + "</ul>"
    sec("一、今日经营结果分析", s1)

    # ---------- 二、三家门店经营对比 ----------
    rows = ""
    for name, s in ranked:
        rows += (f"<tr><td>{name}</td><td>{fmt_money(s['total_sales'])}</td>"
                 f"<td>{fmt_money(s['total_profit'])}</td><td>{s['valid_sell_count']}</td>"
                 f"<td>{fmt_money(s['avg_price'])}</td><td>—</td></tr>")
    s2 = (f"<table><tr><th>门店</th><th>营业额</th><th>毛利额</th><th>订单数</th>"
          f"<th>客单价</th><th>成交率</th></tr>{rows}</table>")
    s2 += "<p class='rank'>门店排名（按营业额）：" + " ＞ ".join(f"{i+1}.{n}（{fmt_money(s['total_sales'])}）"
                                                              for i, (n, s) in enumerate(ranked)) + "</p>"

    best_ana = []
    best_ana.append(f"· 今日表现最好：<b>{best_store[0]}</b>（营业额 {fmt_money(best_store[1]['total_sales'])}）。")
    bp = sorted(best_store[1]["products_by_amount"], key=lambda x: x["amount"], reverse=True)[:3]
    if bp:
        best_ana.append("· 贡献最大商品：" + "、".join(f"{p['name']}（{fmt_money(p['amount'])}）" for p in bp) + "。")
        best_ana.append("· 可复制经验：将该店今日主推话术/陈列/连带组合，同步给另两家门店执行。")

    worst_ana = []
    wname, ws = worst_store
    worst_ana.append(f"· 今日表现异常/偏弱：<b>{wname}</b>（营业额 {fmt_money(ws['total_sales'])}，仅为榜首的"
                     f"{(ws['total_sales']/best_store[1]['total_sales']*100) if best_store[1]['total_sales'] else 0:.0f}%）。")
    if ws["valid_sell_count"] == 0:
        worst_ana.append("· 该店今日 0 成交，重点排查：是否营业/数据未传/店员排班。")
    else:
        worst_ana.append("· 可能原因：客流变化、成交率偏低、客单价下滑或商品结构偏差；建议明日到店蹲点半天，核对进店数与主推品动销。")
        worst_ana.append("· 改善建议：① 调整主推品为今日销冠同款；② 强化连带销售话术；③ 检查是否有热销品缺货。")
    s2 += "<div class='sub'>🏆 最佳门店</div><ul class='ana'>" + "".join(f"<li>{a}</li>" for a in best_ana) + "</ul>"
    s2 += "<div class='sub'>⚠️ 异常门店诊断</div><ul class='ana'>" + "".join(f"<li>{a}</li>" for a in worst_ana) + "</ul>"
    sec("二、三家门店经营对比", s2)

    # ---------- 三、销售过程数据分析 ----------
    foot = extra.get("进店客户")
    if foot in (None, ""):
        s3 = "<p class='warnbox'>📝 此项需门店每日补录：进店客户数 / 成交客户数（PosPal 不记录客流）。"
        s3 += "请在 <code>daily_input.json</code> 填入 <code>进店客户</code> 后自动计算成交率。</p>"
    else:
        foot = float(foot)
        deal = orders
        rate = (deal / foot * 100) if foot else 0
        s3 = '<div class="kpi-grid">'
        s3 += kv("进店客户", f"{int(foot)} 人")
        s3 += kv("成交客户", f"{deal} 人")
        s3 += kv("未成交客户", f"{int(foot)-deal} 人")
        s3 += kv("成交率", fmt_pct(rate))
        s3 += "</div>"
        if rate < 30:
            s3 += "<ul class='ana'><li>· <b class='bad'>成交率偏低（&lt;30%）</b>：重点排查产品推荐是否匹配需求、价格是否偏高、销售流程是否拖沓；建议优化商品组合与体验式销售。</li></ul>"
        else:
            s3 += "<ul class='ana'><li>· 成交率处于健康水平，保持当前产品组合与销售方式，总结今日高效成交的话术复制推广。</li></ul>"
    sec("三、销售过程数据分析", s3)

    # ---------- 四、商品销售分析 ----------
    trows = ""
    for i, p in enumerate(top10, 1):
        trows += (f"<tr><td>{i}</td><td>{p['name']}</td><td>{p['quantity']:.0f}</td>"
                  f"<td>{fmt_money(p['amount'])}</td><td>{fmt_money(p['profit'])}</td></tr>")
    s4 = (f"<h3>销售 TOP10 商品</h3><table><tr><th>排名</th><th>商品</th><th>销量</th>"
          f"<th>销售额</th><th>毛利贡献</th></tr>{trows}</table>")
    if champ:
        s4 += f"<ul class='ana'><li>· 今日销售冠军：<b>{champ['name']}</b>（{fmt_money(champ['amount'])}）。</li>"
    if profit_king:
        s4 += f"<li>· 利润贡献最高：<b>{profit_king['name']}</b>（毛利 {fmt_money(profit_king['profit'])}）。</li>"
    if champ and profit_king and champ["name"] != profit_king["name"]:
        s4 += "<li>· 值得重点推广：把高毛利的「利润贡献最高」商品做主推/组合，提升整体毛利结构。</li></ul>"
    else:
        s4 += "</ul>"

    # 商品结构
    struct = {"引流产品": 0.0, "利润产品": 0.0, "引流+利润": 0.0}
    for p in combo.values():
        struct[classify_product(p)] += p["amount"]
    s4 += "<h3>商品结构分析</h3><div class='kpi-grid'>"
    for k, v in struct.items():
        s4 += kv(k, fmt_money(v))
    s4 += "</div>"
    low_mix = struct["引流产品"]
    high_mix = struct["利润产品"] + struct["引流+利润"]
    if low_mix > high_mix * 1.5 and low_mix > 0:
        s4 += "<ul class='ana'><li>· <b class='bad'>今日出现「只卖低利润引流品」倾向</b>：引流品销售额明显高于利润品，需加强高毛利品类（婚庆/四件套/枕芯）的主动推荐与陈列。</li></ul>"
    else:
        s4 += "<ul class='ana'><li>· 商品结构相对均衡，引流与利润品类搭配正常。</li></ul>"

    # 库存提醒
    if low_all or zero_all:
        inv_rows = ""
        for it in (zero_all + low_all)[:15]:
            inv_rows += f"<tr><td>{it.get('store','')}</td><td>{it['name']}</td><td>{it.get('stock',0)}</td><td>{it.get('min_stock','')}</td></tr>"
        s4 += (f"<h3>⚠️ 库存提醒（低库存/零库存）</h3>"
               f"<table><tr><th>门店</th><th>商品</th><th>当前库存</th><th>下限</th></tr>{inv_rows}</table>")
        s4 += "<ul class='ana'><li>· 补货建议：零库存商品立即调货/补单；低库存商品按近 7 日销量预估补货量，避免断货流失。</li>"
        s4 += "<li>· 清库存建议：对长时间无动销的商品做特价/组合促销，释放资金和货架。</li></ul>"
    else:
        s4 += "<ul class='ana'><li>· 当前无低库存/零库存预警，库存健康。</li></ul>"
    sec("四、商品销售分析", s4)

    # ---------- 五、客户资产分析 ----------
    nx = extra.get("新增微信客户")
    old_n = extra.get("老客户成交数")
    old_amt = extra.get("老客户金额")
    src = extra.get("客户来源", "")
    if nx in (None, "") and old_n in (None, ""):
        s5 = "<p class='warnbox'>📝 此项需门店每日补录：新增微信客户 / 老客户成交数 / 老客户金额 / 客户来源（PosPal 不记录私域客户）。"
        s5 += "请在 <code>daily_input.json</code> 填入后自动统计。</p>"
    else:
        s5 = '<div class="kpi-grid">'
        s5 += kv("新增微信客户", f"{nx if nx not in (None,'') else '—'}")
        s5 += kv("老客户成交数", f"{old_n if old_n not in (None,'') else '—'}")
        s5 += kv("老客户贡献金额", fmt_money(old_amt) if old_amt not in (None, "") else "—")
        s5 += "</div>"
        if src:
            s5 += f"<p>客户来源：{src}</p>"
        s5 += "<ul class='ana'><li>· 家纺属长周期消费，持续积累家庭客户、婚庆客户、老客户复购是增长底盘。</li>"
        s5 += "<li>· 维护建议：今日新增微信客户当晚打标签分层；对 30/60/90 天未复购老客做定向关怀与唤醒。</li></ul>"
    sec("五、客户资产分析", s5)

    # ---------- 六、老板每日经营总结 ----------
    # 亮点
    if d_sales is not None and d_sales > 0:
        highlight = f"今日营业额较昨日增长 {d_sales:.1f}%，{best_store[0]} 领跑。"
    else:
        highlight = f"{best_store[0]} 今日营业额 {fmt_money(best_store[1]['total_sales'])}，为三店最高。"
    # 问题
    problem = (worst_ana[1] if len(worst_ana) > 1 else worst_ana[0]).lstrip("· ").strip()
    # 重点门店
    focus_store = wname
    # 重点商品
    focus_prod = (profit_king["name"] if profit_king else (champ["name"] if champ else "—"))
    # 明日3动作（规则化）
    actions = []
    if zero_all:
        actions.append(f"① 紧急补货：{zero_all[0]['store']} 的「{zero_all[0]['name']}」已零库存，今夜调货/明早补单。")
    else:
        actions.append("① 复盘今日销冠商品，三店统一主推并做组合连带，拉升客单价与毛利。")
    actions.append(f"② 重点盯 {focus_store}：到店蹲点核查客流与成交率，调整主推品与话术。")
    actions.append(f"③ 私域积累：今日新增微信客户当晚分层；定向唤醒 60 天以上未复购老客户。")

    s6 = "<ul class='summary'>"
    s6 += f"<li><b>今日最大亮点：</b>{highlight}</li>"
    s6 += f"<li><b>今日最大问题：</b>{problem}</li>"
    s6 += f"<li><b>需重点关注的门店：</b>{focus_store}</li>"
    s6 += f"<li><b>值得重点推广的商品：</b>{focus_prod}</li>"
    s6 += "<li><b>明天三个经营动作：</b><br>" + "<br>".join(actions) + "</li>"
    s6 += "</ul>"
    sec("六、老板每日经营总结", s6)

    # ---------- 组装 ----------
    html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>觉爱家纺·老板每日经营分析报表 - {date_str}</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{font-family:-apple-system,"Microsoft YaHei",sans-serif;background:#f0f2f5;color:#222;padding:16px;}}
.container{{max-width:780px;margin:0 auto;}}
.header{{background:linear-gradient(135deg,#b71c1c,#e53935);color:#fff;padding:22px 26px;border-radius:10px 10px 0 0;}}
.header h1{{font-size:21px;margin-bottom:6px;}}
.header .meta{{font-size:13px;opacity:.9;}}
.section{{background:#fff;padding:20px 24px;margin-bottom:14px;border-radius:8px;}}
.section h2{{font-size:17px;color:#b71c1c;border-left:4px solid #e53935;padding-left:10px;margin-bottom:14px;}}
.sub{{font-weight:700;color:#333;margin:14px 0 6px;}}
h3{{font-size:15px;color:#444;margin:14px 0 8px;}}
.kpi-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:12px;}}
.kpi-card{{background:#fafafa;border:1px solid #eee;border-radius:6px;padding:12px;text-align:center;}}
.kpi-card .label{{font-size:12px;color:#777;}}
.kpi-card .value{{font-size:20px;font-weight:700;color:#b71c1c;margin-top:4px;}}
table{{width:100%;border-collapse:collapse;font-size:13px;}}
th{{background:#fdecea;padding:9px 10px;text-align:left;font-weight:600;color:#b71c1c;}}
td{{padding:8px 10px;border-bottom:1px solid #f0f0f0;}}
tr:hover td{{background:#fff8f8;}}
.rank{{margin-top:10px;font-size:13px;color:#555;}}
.ana{{margin:6px 0 6px 2px;padding-left:2px;}}
.ana li{{font-size:13.5px;line-height:1.7;margin:4px 0;list-style:none;}}
.ana li::before{{content:"•";color:#e53935;margin-right:6px;}}
.summary li{{font-size:14px;line-height:1.9;margin:8px 0;}}
.trend{{font-size:12px;font-weight:700;}}
.trend.good{{color:#2e7d32;}}
.trend.bad{{color:#c62828;}}
.bad{{color:#c62828;}}
.warnbox{{background:#fff8e1;border:1px dashed #ffb300;color:#7a5b00;padding:12px;border-radius:6px;font-size:13px;}}
.footer{{text-align:center;color:#999;font-size:12px;padding:14px;}}
code{{background:#f0f0f0;padding:1px 5px;border-radius:3px;font-size:12px;}}
</style></head><body><div class="container">
<div class="header"><h1>📊 觉爱家纺 · 老板每日经营分析报表</h1>
<div class="meta">报表日期：{date_str}　|　对比：昨日 {yest_str} / 上周同期 {lw_str}　|　生成：{now_str}</div></div>
{''.join(W)}
<div class="footer">数据来源：银豹(PosPal)开放平台 API　|　本报表由 AI 事务管家自动生成</div>
</div></body></html>"""

    # ---------- 每日营业总结（回复邮件草稿，纯文本）----------
    reply = (
        f"【觉爱家纺 {date_str} 每日营业总结】\n"
        f"· 总营业额 {fmt_money(total_sales)}，毛利 {fmt_money(total_profit)}（毛利率 {fmt_pct(gm)}），成交 {orders} 单，客单价 {fmt_money(avg)}。\n"
        f"· 最大亮点：{highlight}\n"
        f"· 最大问题：{problem}\n"
        f"· 重点关注门店：{focus_store}\n"
        f"· 重点推广商品：{focus_prod}\n"
        f"· 明日三动作：\n" + "\n".join(f"   {a}" for a in actions) + "\n"
        f"（本总结可直接作为回复/转发邮件正文）"
    )
    return html, reply


# ============================================================
# 邮件发送（复用 CONFIG，HTML + 纯文本回执）
# ============================================================
def send_email(html, reply_text, date_str):
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    cfg = pp.CONFIG["email"]
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"【觉爱家纺】老板每日经营分析报表 - {date_str}"
    msg["From"] = cfg["sender_email"]
    msg["To"] = cfg["receiver_email"]
    msg.attach(MIMEText(reply_text, "plain", "utf-8"))
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
    ap.add_argument("--date", default=None, help="指定报表日期 YYYY-MM-DD")
    ap.add_argument("--no-send", action="store_true", help="只生成本地报表，不发邮件")
    args = ap.parse_args()

    if args.date:
        report_date = args.date
    else:
        now = datetime.now()
        report_date = (now - timedelta(days=1)).strftime("%Y-%m-%d") if now.hour < 6 else now.strftime("%Y-%m-%d")
    dt = datetime.strptime(report_date, "%Y-%m-%d")
    yest_str = (dt - timedelta(days=1)).strftime("%Y-%m-%d")
    lw_str = (dt - timedelta(days=7)).strftime("%Y-%m-%d")

    print(f"[INFO] 报表日期 {report_date}（昨日 {yest_str} / 上周同期 {lw_str}）")

    stores = pp.CONFIG["stores"]
    # 今日：逐店取数（用于门店对比）+ 全局合并（用于汇总/TOP10）
    per_store = {}
    today_tickets = []
    inventories = {}
    for sc in stores:
        tk = fetch_tickets(sc, report_date)
        per_store[sc["name"]] = pp.analyze_sales(tk)
        today_tickets.append(tk)
        inventories[sc["name"]] = pp.analyze_inventory(fetch_inventory(sc))
    global_today = pp.analyze_sales([t for sub in today_tickets for t in sub])

    # 昨日 / 上周同期全局
    yest_tk = [fetch_tickets(sc, yest_str) for sc in stores]
    lw_tk = [fetch_tickets(sc, lw_str) for sc in stores]
    global_yest = pp.analyze_sales([t for sub in yest_tk for t in sub])
    global_lw = pp.analyze_sales([t for sub in lw_tk for t in sub])

    extra = load_extra()
    html, reply = build_report(report_date, yest_str, lw_str, per_store,
                               global_today, global_yest, global_lw, inventories, extra)

    path = LOCAL_REPORT.format(date=report_date)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[OK] 本地报表: {path}")
    print("---- 每日营业总结（回复邮件草稿）----")
    print(reply)

    no_send = args.no_send or os.environ.get("REPORT_NO_SEND") == "1"
    if no_send:
        print("[INFO] --no-send 已设置，跳过邮件发送")
    else:
        try:
            send_email(html, reply, report_date)
        except Exception as e:
            print(f"[ERROR] 邮件发送失败: {e}")


if __name__ == "__main__":
    main()
