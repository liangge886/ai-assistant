#!/usr/bin/env python3
"""
A 股每日行情简报脚本
每天 15:00 收盘后运行，抓取行情数据，筛选重点股票，发送邮件报告。
数据来源：腾讯财经 API（免费无需注册）

重点跟踪：
  - 赛轮轮胎 (601058)：低估值出海成长股
  - 博实股份 (002698)：机器人热门赛道龙头
"""

import requests
import smtplib
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

# ============ 配置 ============
EMAIL_SENDER = "38797137@qq.com"
EMAIL_PASSWORD = "fpwguhihlqtnbggd"
EMAIL_RECEIVER = "38797137@qq.com"
SMTP_SERVER = "smtp.qq.com"
SMTP_PORT = 465

# 重点指数
INDEX_CODES = {
    "sh000001": "上证指数",
    "sz399001": "深证成指",
    "sz399006": "创业板指",
    "sh000688": "科创50",
    "sh000300": "沪深300",
}

# 市场观察池
WATCH_STOCKS = {
    "sh600519": "贵州茅台", "sh601318": "中国平安", "sh600036": "招商银行",
    "sh600900": "长江电力", "sz300750": "宁德时代", "sz002594": "比亚迪",
    "sh688981": "中芯国际", "sz000858": "五粮液", "sh601012": "隆基绿能",
    "sz300059": "东方财富", "sz000063": "中兴通讯", "sh600276": "恒瑞医药",
    "sz002475": "立讯精密", "sh601899": "紫金矿业", "sz300124": "汇川技术",
    "sz000333": "美的集团", "sz300274": "阳光电源", "sh603259": "药明康德",
}

# ★★★ 重点跟踪个股 ★★★
FOCUS_STOCKS = {
    "sh601058": {
        "name": "赛轮轮胎",
        "label": "🏭 低估值成长",
        "color": "#27ae60",
        "bg": "#f0fff4",
        "desc": "轮胎出海龙头，PE仅10倍，利润增速近30%，海外产能持续释放",
        "key_points": [
            ("PE估值", "10.6倍，行业中极低水平"),
            ("利润增速", "2026年机构预测+29%"),
            ("核心逻辑", "中国轮胎全球份额提升，越南/柬埔寨工厂规避关税"),
            ("关注点", "海外产能利用率、原材料橡胶价格、海运成本"),
        ],
    },
    "sz002698": {
        "name": "博实股份",
        "label": "🤖 机器人热门",
        "color": "#e74c3c",
        "bg": "#fff5f5",
        "desc": "工业机器人龙头+人形机器人概念，今日市场最热赛道核心标的",
        "key_points": [
            ("赛道热度", "机器人概念今日17家涨停，与芯片并列第一主线"),
            ("催化剂", "特斯拉Optimus量产临近，人形机器人产业链受益"),
            ("基本面", "2026年利润预增12%，PE 27倍合理区间"),
            ("关注点", "人形机器人样机进展、工业机器人订单、股东减持动态"),
        ],
    },
}


# ============ 数据获取 ============

def fetch_stock_data(codes):
    """通过腾讯财经 API 批量获取实时行情"""
    code_list = ",".join(codes)
    url = f"https://qt.gtimg.cn/q={code_list}"
    headers = {
        "Referer": "https://finance.qq.com",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    try:
        r = requests.get(url, headers=headers, timeout=15)
        r.encoding = "gbk"
        return r.text
    except Exception as e:
        print(f"[ERROR] 获取行情失败: {e}")
        return None


def parse_tencent_data(raw_text):
    """解析腾讯财经返回的股票数据"""
    results = {}
    if not raw_text:
        return results
    pattern = r'v_(\w+)="([^"]*)"'
    for code, data_str in re.findall(pattern, raw_text):
        if not data_str.strip():
            continue
        fields = data_str.split("~")
        if len(fields) < 40:
            continue
        try:
            results[code] = {
                "name": fields[1],
                "code": fields[2],
                "price": float(fields[3]) if fields[3] else 0,
                "prev_close": float(fields[4]) if fields[4] else 0,
                "open": float(fields[5]) if fields[5] else 0,
                "volume": int(fields[6]) if fields[6] else 0,
                "high": float(fields[33]) if fields[33] else 0,
                "low": float(fields[34]) if fields[34] else 0,
                "change": float(fields[31]) if fields[31] else 0,
                "change_pct": float(fields[32]) if fields[32] else 0,
                "turnover": float(fields[37]) if fields[37] else 0,
                "time": fields[30],
            }
        except (ValueError, IndexError):
            continue
    return results


def fetch_all_data():
    """获取所有数据"""
    all_codes = list(INDEX_CODES.keys()) + list(WATCH_STOCKS.keys()) + list(FOCUS_STOCKS.keys())
    raw = fetch_stock_data(all_codes)
    if not raw:
        return None, None, None
    all_data = parse_tencent_data(raw)
    index_data = {k: v for k, v in all_data.items() if k in INDEX_CODES}
    stock_data = {k: v for k, v in all_data.items() if k in WATCH_STOCKS}
    focus_data = {k: v for k, v in all_data.items() if k in FOCUS_STOCKS}
    return index_data, stock_data, focus_data


# ============ 分析 ============

def analyze_stocks(stock_data):
    if not stock_data:
        return [], [], []
    stocks = list(stock_data.values())
    sorted_by_change = sorted(stocks, key=lambda x: x["change_pct"], reverse=True)
    top_gainers = sorted_by_change[:5]
    top_losers = sorted_by_change[-5:]
    top_losers.reverse()
    sorted_by_turnover = sorted(stocks, key=lambda x: x["turnover"], reverse=True)
    top_active = sorted_by_turnover[:5]
    return top_gainers, top_losers, top_active


def get_market_sentiment(index_data):
    if not index_data:
        return "数据获取失败"
    sh = index_data.get("sh000001", {})
    sz = index_data.get("sz399001", {})
    cy = index_data.get("sz399006", {})
    vals = [d["change_pct"] for d in [sh, sz, cy] if d and d["change_pct"] != 0]
    if not vals:
        return "数据异常"
    avg = sum(vals) / len(vals)
    if avg > 2:
        return "🔥 市场强势上攻，情绪高涨"
    elif avg > 0.5:
        return "📈 市场温和上涨，情绪偏乐观"
    elif avg > -0.5:
        return "➡️ 市场窄幅震荡，情绪中性"
    elif avg > -2:
        return "📉 市场震荡走弱，情绪偏谨慎"
    else:
        return "❄️ 市场大幅下跌，情绪低迷"


def analyze_focus_stock(code, data, config):
    """对重点个股生成走势分析"""
    if not data:
        return ""
    d = data
    change_pct = d["change_pct"]
    price = d["price"]

    # 涨跌趋势判断
    if change_pct > 5:
        trend = "🚀 强势拉升"
        detail = "大幅上涨，资金追捧明显，关注后续能否持续放量。追高需谨慎。"
    elif change_pct > 2:
        trend = "📈 稳步走高"
        detail = "走势偏强，量价配合良好，短期趋势向好。"
    elif change_pct > 0:
        trend = "↗️ 小幅收涨"
        detail = "温和上涨，走势稳健。关注能否突破近期压力位。"
    elif change_pct > -2:
        trend = "↘️ 小幅回调"
        detail = "微幅调整，属正常波动。关注支撑位是否有效。"
    elif change_pct > -5:
        trend = "📉 明显下跌"
        detail = "跌幅较大，注意是否有利空消息。观察是否跌破关键均线。"
    else:
        trend = "⚠️ 大幅下挫"
        detail = "重挫需要警惕，建议复盘是否有基本面变化或黑天鹅事件。"

    # 量能分析
    turnover_yi = d["turnover"] / 10000
    if turnover_yi > 20:
        volume_note = "成交额较大，换手充分，多空博弈激烈。"
    elif turnover_yi > 5:
        volume_note = "成交额适中，交投活跃度正常。"
    else:
        volume_note = "成交额偏低，关注度一般。"

    # 振幅分析
    if d["prev_close"] > 0:
        amplitude = (d["high"] - d["low"]) / d["prev_close"] * 100
    else:
        amplitude = 0
    if amplitude > 8:
        amp_note = f"振幅 {amplitude:.1f}%，日内波动剧烈。"
    elif amplitude > 4:
        amp_note = f"振幅 {amplitude:.1f}%，有一定波动。"
    else:
        amp_note = f"振幅 {amplitude:.1f}%，走势平稳。"

    color = config["color"]
    bg = config["bg"]

    # 关键指标行
    point_rows = ""
    for title, content in config["key_points"]:
        point_rows += f"""
            <tr>
                <td style="padding:6px 12px; color:#888; width:80px; font-size:13px;">{title}</td>
                <td style="padding:6px 12px; font-size:13px;">{content}</td>
            </tr>"""

    return f"""
    <div style="background:{bg}; border-left:4px solid {color}; padding:16px 20px; border-radius:6px; margin-bottom:20px;">
        <h3 style="margin:0 0 4px 0; font-size:16px; color:{color};">
            {config['label']}：{config['name']}（{config.get('code', code)}）
        </h3>
        <p style="margin:4px 0 8px 0; font-size:12px; color:#888;">{config['desc']}</p>

        <!-- 今日行情 -->
        <table style="width:100%; border-collapse:collapse; margin-bottom:12px; font-size:14px;">
            <tr>
                <td style="padding:4px 0; width:50%;">
                    <span style="color:#888;">现价</span>
                    <span style="font-size:20px; font-weight:bold; margin-left:8px;">{price:.2f}</span>
                </td>
                <td style="padding:4px 0; width:50%;">
                    <span style="color:#888;">涨跌幅</span>
                    <span style="font-size:20px; font-weight:bold; color:{color}; margin-left:8px;">
                        {change_pct:+.2f}%
                    </span>
                </td>
            </tr>
            <tr>
                <td style="padding:4px 0;">开盘 {d['open']:.2f} · 最高 {d['high']:.2f}</td>
                <td style="padding:4px 0;">最低 {d['low']:.2f} · 昨收 {d['prev_close']:.2f}</td>
            </tr>
            <tr>
                <td style="padding:4px 0;">成交额 <b>{turnover_yi:.1f}亿</b></td>
                <td style="padding:4px 0;">成交量 <b>{d['volume']/10000:.0f}万手</b></td>
            </tr>
        </table>

        <!-- 走势判断 -->
        <div style="background:#fff; padding:10px 14px; border-radius:4px; margin-bottom:10px;">
            <span style="font-weight:bold; font-size:14px;">{trend}</span>
            <span style="font-size:13px; color:#555; margin-left:4px;">{detail}</span>
            <div style="font-size:12px; color:#888; margin-top:4px;">{volume_note} {amp_note}</div>
        </div>

        <!-- 关键指标 -->
        <table style="width:100%; border-collapse:collapse; font-size:13px;">
            {point_rows}
        </table>
    </div>"""


# ============ 报告生成 ============

def generate_report(index_data, stock_data, focus_data, date_str):
    if not index_data:
        return "<p>今日数据获取失败，请稍后查看。</p>"

    top_gainers, top_losers, top_active = analyze_stocks(stock_data)
    sentiment = get_market_sentiment(index_data)

    # 指数概览
    index_rows = ""
    for code, info in INDEX_CODES.items():
        d = index_data.get(code)
        if d:
            color = "#e74c3c" if d["change_pct"] >= 0 else "#27ae60"
            arrow = "↑" if d["change_pct"] >= 0 else "↓"
            index_rows += f"""
            <tr>
                <td style="font-weight:bold">{info}</td>
                <td style="font-size:16px;font-weight:bold">{d['price']:.2f}</td>
                <td style="color:{color}">{arrow} {d['change']:+.2f}</td>
                <td style="color:{color};font-weight:bold">{arrow} {d['change_pct']:+.2f}%</td>
                <td>{d['turnover']/10000:.0f}亿</td>
            </tr>"""

    # 涨幅榜
    gainer_rows = ""
    for s in top_gainers:
        gainer_rows += f"""
            <tr>
                <td>{s['name']}</td><td>{s['code']}</td><td>{s['price']:.2f}</td>
                <td style="color:#e74c3c;font-weight:bold">+{s['change_pct']:.2f}%</td>
                <td>{s['turnover']/10000:.0f}亿</td>
            </tr>"""

    # 跌幅榜
    loser_rows = ""
    for s in top_losers:
        loser_rows += f"""
            <tr>
                <td>{s['name']}</td><td>{s['code']}</td><td>{s['price']:.2f}</td>
                <td style="color:#27ae60;font-weight:bold">{s['change_pct']:.2f}%</td>
                <td>{s['turnover']/10000:.0f}亿</td>
            </tr>"""

    # 活跃榜
    active_rows = ""
    for s in top_active:
        active_rows += f"""
            <tr>
                <td>{s['name']}</td><td>{s['code']}</td><td>{s['price']:.2f}</td>
                <td style="color:{'#e74c3c' if s['change_pct'] >= 0 else '#27ae60'}">{s['change_pct']:+.2f}%</td>
                <td style="font-weight:bold">{s['turnover']/10000:.0f}亿</td>
            </tr>"""

    # ★★★ 重点个股深度分析 ★★★
    focus_sections = ""
    for code, config in FOCUS_STOCKS.items():
        d = focus_data.get(code) if focus_data else None
        focus_sections += analyze_focus_stock(code, d, config)

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family: 'Microsoft YaHei', Arial, sans-serif; background: #f5f6fa; padding: 20px;">

<div style="max-width:680px; margin:0 auto; background: #fff; border-radius: 12px; overflow: hidden; box-shadow: 0 2px 12px rgba(0,0,0,0.08);">

<!-- Header -->
<div style="background: linear-gradient(135deg, #1a1a2e, #16213e); color: #fff; padding: 28px 32px; text-align: center;">
    <h1 style="margin:0 0 4px 0; font-size: 22px;">📊 A股每日行情简报</h1>
    <p style="margin:0; opacity:0.7; font-size:13px;">{date_str} · 收盘后自动生成</p>
</div>

<div style="padding: 24px 32px;">

<!-- 市场情绪 -->
<div style="background: #f0f4ff; border-left: 4px solid #4a6cf7; padding: 14px 18px; border-radius: 6px; margin-bottom: 24px;">
    <span style="font-size: 15px;">{sentiment}</span>
</div>

<!-- ★★★ 重点个股深度分析 ★★★ -->
<h2 style="font-size:17px; color:#1a1a2e; border-bottom: 2px solid #6c5ce7; padding-bottom: 8px; margin-bottom: 16px;">
    🎯 重点个股深度分析
</h2>
{focus_sections}

<!-- 指数概览 -->
<h2 style="font-size:17px; color:#1a1a2e; border-bottom: 2px solid #4a6cf7; padding-bottom: 8px;">📈 主要指数</h2>
<table style="width:100%; border-collapse: collapse; margin-bottom: 24px; font-size:14px;">
    <tr style="background:#f8f9fc; color:#666;">
        <th style="padding:10px 12px; text-align:left;">指数</th>
        <th style="padding:10px 12px; text-align:right;">最新价</th>
        <th style="padding:10px 12px; text-align:right;">涨跌额</th>
        <th style="padding:10px 12px; text-align:right;">涨跌幅</th>
        <th style="padding:10px 12px; text-align:right;">成交额</th>
    </tr>
    {index_rows}
</table>

<!-- 涨幅榜 -->
<h2 style="font-size:17px; color:#e74c3c; border-bottom: 2px solid #e74c3c; padding-bottom: 8px;">🔥 市场涨幅 TOP5</h2>
<table style="width:100%; border-collapse: collapse; margin-bottom: 24px; font-size:14px;">
    <tr style="background:#fff5f5; color:#666;">
        <th style="padding:10px 12px; text-align:left;">股票</th><th style="padding:10px 12px; text-align:left;">代码</th>
        <th style="padding:10px 12px; text-align:right;">现价</th><th style="padding:10px 12px; text-align:right;">涨跌幅</th>
        <th style="padding:10px 12px; text-align:right;">成交额</th>
    </tr>
    {gainer_rows}
</table>

<!-- 跌幅榜 -->
<h2 style="font-size:17px; color:#27ae60; border-bottom: 2px solid #27ae60; padding-bottom: 8px;">📉 市场跌幅 TOP5</h2>
<table style="width:100%; border-collapse: collapse; margin-bottom: 24px; font-size:14px;">
    <tr style="background:#f5fff5; color:#666;">
        <th style="padding:10px 12px; text-align:left;">股票</th><th style="padding:10px 12px; text-align:left;">代码</th>
        <th style="padding:10px 12px; text-align:right;">现价</th><th style="padding:10px 12px; text-align:right;">涨跌幅</th>
        <th style="padding:10px 12px; text-align:right;">成交额</th>
    </tr>
    {loser_rows}
</table>

<!-- 活跃榜 -->
<h2 style="font-size:17px; color:#f39c12; border-bottom: 2px solid #f39c12; padding-bottom: 8px;">💹 成交最活跃 TOP5</h2>
<table style="width:100%; border-collapse: collapse; margin-bottom: 16px; font-size:14px;">
    <tr style="background:#fffdf5; color:#666;">
        <th style="padding:10px 12px; text-align:left;">股票</th><th style="padding:10px 12px; text-align:left;">代码</th>
        <th style="padding:10px 12px; text-align:right;">现价</th><th style="padding:10px 12px; text-align:right;">涨跌幅</th>
        <th style="padding:10px 12px; text-align:right;">成交额</th>
    </tr>
    {active_rows}
</table>

<!-- Footer -->
<div style="border-top: 1px solid #eee; padding-top: 16px; text-align: center; color: #999; font-size:12px;">
    <p style="margin:0;">数据来源：腾讯财经 · 仅供参考，不构成投资建议</p>
    <p style="margin:4px 0 0 0;">由 AI Agent 自动生成并推送</p>
</div>

</div>
</div>
</body>
</html>"""
    return html


def send_report(html_content, date_str):
    """通过 QQ 邮箱 SMTP 发送报告"""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"📊 A股行情简报 - {date_str}"
    msg["From"] = EMAIL_SENDER
    msg["To"] = EMAIL_RECEIVER
    plain = f"A股行情简报 - {date_str}\n\n请使用支持 HTML 的邮件客户端查看完整报告。"
    msg.attach(MIMEText(plain, "plain", "utf-8"))
    msg.attach(MIMEText(html_content, "html", "utf-8"))
    try:
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_SENDER, [EMAIL_RECEIVER], msg.as_string())
        print(f"[OK] 邮件发送成功 -> {EMAIL_RECEIVER}")
        return True
    except Exception as e:
        print(f"[ERROR] 邮件发送失败: {e}")
        return False


# ============ 主流程 ============

def main():
    today = datetime.now()
    date_str = today.strftime("%Y年%m月%d日")

    if today.weekday() >= 5:
        print(f"[SKIP] {date_str} 是周末，跳过推送")
        return

    print(f"[INFO] 开始生成 {date_str} A股行情简报...")

    index_data, stock_data, focus_data = fetch_all_data()

    if not index_data:
        print("[ERROR] 无法获取行情数据")
        return

    print(f"[INFO] 指数 {len(index_data)} 个, 观察池 {len(stock_data)} 只, 重点跟踪 {len(focus_data)} 只")

    html = generate_report(index_data, stock_data, focus_data, date_str)
    success = send_report(html, date_str)
    if success:
        print(f"[DONE] {date_str} 行情简报已推送")
    else:
        print("[FAIL] 推送失败")


if __name__ == "__main__":
    main()
