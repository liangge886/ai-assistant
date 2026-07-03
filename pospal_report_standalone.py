"""
银豹(PosPal)日报自动生成脚本 - 多门店版（自包含）
- 所有配置内嵌，单文件即可运行
- 从银豹开放平台API拉取各门店销售数据和库存数据
- 生成HTML日报，按门店分版块展示
- 通过QQ邮箱SMTP发送报表
- 用法：python pospal_report_standalone.py
"""

import json
import hashlib
import time
import urllib.request
import urllib.error
import gzip
import ssl
import smtplib
import os
import sys
from email.mime.text import MIMEText
from datetime import datetime, timedelta
from collections import defaultdict

# ============================================================
# 配置（内嵌，无需外部config.json）
# ============================================================
CONFIG = {
    "stores": [
        {
            "name": "觉爱家纺禹城店",
            "pospal": {
                "app_id": "3DA496835BD205B0751AA6839965B761",
                "app_key": "492115768968484214",
                "url_prefix": "https://area50-win.pospal.cn:443/",
            },
        },
        {
            "name": "觉爱家纺泰安店（新时代徐家楼店）",
            "pospal": {
                "app_id": "915ADA71FF4CC86CEFA9738690788CBD",
                "app_key": "3535074855765985",
                "url_prefix": "https://area50-win.pospal.cn:443/",
            },
        },
        {
            "name": "觉爱家纺肥城店",
            "pospal": {
                "app_id": "C86C896F55B1D5B1837EA99F2FD50765",
                "app_key": "443475189815541669",
                "url_prefix": "https://area25-win.pospal.cn:443/",
            },
        },
    ],
    "email": {
        "smtp_host": "smtp.qq.com",
        "smtp_port": 465,
        "sender_email": "38797137@qq.com",
        "sender_password": "hnjlpudftazgbigg",
        "receiver_email": "38797137@qq.com",
    },
}

# 脚本所在目录（用于保存本地报表备份）
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


# ============================================================
# 银豹API核心：签名计算与请求
# ============================================================
def calc_signature(app_key: str, body: str) -> str:
    """data-signature = MD5(appKey + 请求体原文), 32位大写"""
    raw = app_key + body
    return hashlib.md5(raw.encode("utf-8")).hexdigest().upper()


def pospal_request(url_prefix: str, app_id: str, app_key: str, api_path: str, payload: dict) -> dict:
    """通用银豹API请求方法"""
    payload["appId"] = app_id
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    timestamp = str(int(time.time() * 1000))
    signature = calc_signature(app_key, body)

    url = url_prefix.rstrip("/") + api_path

    headers = {
        "User-Agent": "openApi",
        "Content-Type": "application/json; charset=utf-8",
        "accept-encoding": "gzip,deflate",
        "time-stamp": timestamp,
        "data-signature": signature,
    }

    req = urllib.request.Request(url, data=body.encode("utf-8"), headers=headers, method="POST")

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    try:
        with urllib.request.urlopen(req, context=ctx) as resp:
            raw = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            result = json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} - {e.reason}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"连接失败: {e.reason}")

    if result.get("status", "").lower() != "success":
        msgs = result.get("messages", [])
        err_code = result.get("errorCode", "")
        raise RuntimeError(f"API错误: code={err_code}, msg={msgs}")

    return result


# ============================================================
# 分页遍历所有数据
# ============================================================
def fetch_all_pages(url_prefix: str, app_id: str, app_key: str, api_path: str, base_payload: dict) -> list:
    """遍历银豹分页API的所有页"""
    all_items = []
    payload = dict(base_payload)

    while True:
        resp = pospal_request(url_prefix, app_id, app_key, api_path, payload)
        data = resp.get("data", resp)

        items = data.get("result", data) if isinstance(data, dict) else data
        if isinstance(items, list):
            all_items.extend(items)
        else:
            break

        post_back = data.get("postBackParameter") if isinstance(data, dict) else None
        if not post_back:
            break
        page_size = data.get("pageSize", 100) if isinstance(data, dict) else 100
        if len(items) < page_size:
            break

        payload = dict(base_payload)
        payload["postBackParameter"] = post_back

    return all_items


# ============================================================
# 数据拉取
# ============================================================
def fetch_sales_data(store_cfg: dict, date_str: str) -> list:
    """拉取指定日期的销售单据"""
    payload = {
        "startTime": f"{date_str} 00:00:00",
        "endTime": f"{date_str} 23:59:59",
    }
    return fetch_all_pages(
        store_cfg["url_prefix"], store_cfg["app_id"], store_cfg["app_key"],
        "/pospal-api2/openapi/v1/ticketOpenApi/queryTicketPages",
        payload,
    )


def fetch_yearly_sales_data(store_cfg: dict, year: int) -> list:
    """拉取指定年份的全部销售单据"""
    now = datetime.now()
    end_time = now.strftime("%Y-%m-%d 23:59:59") if now.year == year else f"{year}-12-31 23:59:59"
    payload = {
        "startTime": f"{year}-01-01 00:00:00",
        "endTime": end_time,
        "noLimitTimeRange": 1,
    }
    return fetch_all_pages(
        store_cfg["url_prefix"], store_cfg["app_id"], store_cfg["app_key"],
        "/pospal-api2/openapi/v1/ticketOpenApi/queryTicketPages",
        payload,
    )


def fetch_monthly_sales_data(store_cfg: dict, date_str: str) -> list:
    """拉取指定日期所在月份的全部销售单据"""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    payload = {
        "startTime": f"{dt.year}-{dt.month:02d}-01 00:00:00",
        "endTime": f"{date_str} 23:59:59",
        "noLimitTimeRange": 1,
    }
    return fetch_all_pages(
        store_cfg["url_prefix"], store_cfg["app_id"], store_cfg["app_key"],
        "/pospal-api2/openapi/v1/ticketOpenApi/queryTicketPages",
        payload,
    )


def fetch_inventory_data(store_cfg: dict) -> list:
    """拉取全部商品库存信息"""
    payload = {}
    return fetch_all_pages(
        store_cfg["url_prefix"], store_cfg["app_id"], store_cfg["app_key"],
        "/pospal-api2/openapi/v1/productOpenApi/queryProductPages",
        payload,
    )


# ============================================================
# 数据分析
# ============================================================
def calc_period_summary(tickets: list) -> dict:
    """计算周期汇总（销售额、退款额、净利润）"""
    total_sales = 0.0
    total_refund = 0.0
    total_profit = 0.0

    for t in tickets:
        ticket_type = t.get("ticketType", "")
        invalid = t.get("invalid", 0)
        total_amount = float(t.get("totalAmount", 0) or 0)
        total_profit_val = float(t.get("totalProfit", 0) or 0)

        if ticket_type == "SELL_RETURN":
            total_refund += abs(total_amount)
            continue
        if ticket_type == "SELL" and invalid == 0:
            total_sales += total_amount
            total_profit += total_profit_val

    return {
        "total_sales": total_sales,
        "total_refund": total_refund,
        "net_sales": total_sales - total_refund,
        "total_profit": total_profit,
    }


def analyze_sales(tickets: list) -> dict:
    """分析销售单据"""
    total_sales = 0.0
    total_refund = 0.0
    total_profit = 0.0
    sell_count = 0
    refund_count = 0
    valid_count = 0

    product_sales = defaultdict(lambda: {"name": "", "quantity": 0.0, "amount": 0.0, "profit": 0.0, "barcode": ""})

    for t in tickets:
        ticket_type = t.get("ticketType", "")
        invalid = t.get("invalid", 0)
        total_amount = float(t.get("totalAmount", 0) or 0)
        total_profit_val = float(t.get("totalProfit", 0) or 0)

        if ticket_type == "SELL_RETURN":
            refund_count += 1
            total_refund += abs(total_amount)
            continue
        if ticket_type == "SELL":
            sell_count += 1
            if invalid == 0:
                valid_count += 1
                total_sales += total_amount
                total_profit += total_profit_val
                items = t.get("items", [])
                for item in items:
                    puid = item.get("productUid", "")
                    product_sales[puid]["name"] = item.get("name", "")
                    product_sales[puid]["barcode"] = item.get("productBarcode", "")
                    product_sales[puid]["quantity"] += float(item.get("quantity", 0) or 0)
                    product_sales[puid]["amount"] += float(item.get("totalAmount", 0) or 0)
                    product_sales[puid]["profit"] += float(item.get("totalProfit", 0) or 0)

    avg_price = total_sales / valid_count if valid_count > 0 else 0
    products_by_amount = sorted(product_sales.values(), key=lambda x: x["amount"], reverse=True)

    return {
        "total_sales": total_sales,
        "total_refund": total_refund,
        "total_profit": total_profit,
        "net_sales": total_sales - total_refund,
        "sell_count": sell_count,
        "valid_sell_count": valid_count,
        "refund_count": refund_count,
        "avg_price": avg_price,
        "products_by_amount": products_by_amount[:15],
    }


def analyze_yearly_products(tickets: list) -> list:
    """年度商品销量排行TOP30"""
    product_sales = defaultdict(lambda: {"name": "", "quantity": 0.0, "amount": 0.0, "profit": 0.0, "barcode": ""})

    for t in tickets:
        if t.get("ticketType") != "SELL" or t.get("invalid", 0) != 0:
            continue
        for item in t.get("items", []):
            puid = item.get("productUid", "")
            product_sales[puid]["name"] = item.get("name", "")
            product_sales[puid]["barcode"] = item.get("productBarcode", "")
            product_sales[puid]["quantity"] += float(item.get("quantity", 0) or 0)
            product_sales[puid]["amount"] += float(item.get("totalAmount", 0) or 0)
            product_sales[puid]["profit"] += float(item.get("totalProfit", 0) or 0)

    return sorted(product_sales.values(), key=lambda x: x["quantity"], reverse=True)[:30]


def analyze_inventory(products: list) -> dict:
    """分析库存数据"""
    total_products = len(products)
    enabled_products = len([p for p in products if p.get("enable") == 1])
    low_stock_list = []
    zero_stock_list = []
    stock_summary = []

    for p in products:
        if p.get("enable") != 1 or p.get("noStock") == 1:
            continue
        name = p.get("name", "")
        barcode = p.get("barcode", "")
        stock = float(p.get("stock", 0) or 0)
        min_stock = float(p.get("minStock", 0) or 0)
        max_stock = float(p.get("maxStock", 0) or 0)
        buy_price = float(p.get("buyPrice", 0) or 0)
        sell_price = float(p.get("sellPrice", 0) or 0)

        stock_summary.append({
            "name": name, "barcode": barcode, "stock": stock,
            "min_stock": min_stock, "max_stock": max_stock,
            "buy_price": buy_price, "sell_price": sell_price,
        })

        if stock <= 0:
            zero_stock_list.append({"name": name, "barcode": barcode, "stock": stock})
        elif min_stock > 0 and stock < min_stock:
            low_stock_list.append({"name": name, "barcode": barcode, "stock": stock, "min_stock": min_stock, "gap": min_stock - stock})

    return {
        "total_products": total_products,
        "enabled_products": enabled_products,
        "tracked_products": len(stock_summary),
        "zero_stock_count": len(zero_stock_list),
        "low_stock_count": len(low_stock_list),
        "low_stock_list": low_stock_list[:20],
        "zero_stock_list": zero_stock_list[:20],
        "stock_summary": sorted(stock_summary, key=lambda x: x["stock"], reverse=True)[:50],
    }


# ============================================================
# HTML报表生成
# ============================================================
def format_money(v: float) -> str:
    return f"¥{v:,.2f}"


def generate_store_section(store_name, date_str, sales, monthly_summary, yearly_summary, yearly_products, inventory, year):
    html = f"""
<div class="store-divider">
  <div class="store-tag">{store_name}</div>
</div>

<div class="section">
  <h2>📈 销售汇总</h2>
  <div class="kpi-grid">
    <div class="kpi-card"><div class="label">有效销售额</div><div class="value">{format_money(sales['total_sales'])}</div></div>
    <div class="kpi-card"><div class="label">退款总额</div><div class="value red">{format_money(sales['total_refund'])}</div></div>
    <div class="kpi-card"><div class="label">净利润</div><div class="value green">{format_money(sales['total_profit'])}</div></div>
  </div>
  <div class="kpi-grid">
    <div class="kpi-card"><div class="label">有效单数</div><div class="value">{sales['valid_sell_count']}</div></div>
    <div class="kpi-card"><div class="label">退款单数</div><div class="value red">{sales['refund_count']}</div></div>
    <div class="kpi-card"><div class="label">客单价</div><div class="value">{format_money(sales['avg_price'])}</div></div>
  </div>
  <div class="kpi-grid">
    <div class="kpi-card"><div class="label">本月销售总额</div><div class="value">{format_money(monthly_summary['total_sales'])}</div></div>
    <div class="kpi-card"><div class="label">{year}年度销售总额</div><div class="value">{format_money(yearly_summary['total_sales'])}</div></div>
    <div class="kpi-card"><div class="label">{year}年度净利润</div><div class="value green">{format_money(yearly_summary['total_profit'])}</div></div>
  </div>
</div>

<div class="section">
  <h2>🏆 商品明细排行（TOP 15）</h2>
  <table>
    <tr><th>排名</th><th>商品名称</th><th>条码</th><th>销量</th><th>销售额</th><th>利润</th></tr>
"""
    for i, p in enumerate(sales["products_by_amount"][:15], 1):
        html += f'    <tr><td>{i}</td><td>{p["name"]}</td><td>{p["barcode"]}</td><td>{p["quantity"]}</td><td>{format_money(p["amount"])}</td><td>{format_money(p["profit"])}</td></tr>\n'

    html += f"""  </table>
</div>

<div class="section">
  <h2>🔥 {year}年度商品总销量排行（TOP 30）</h2>
  <table>
    <tr><th>排名</th><th>商品名称</th><th>条码</th><th>总销量</th><th>总销售额</th><th>总利润</th><th>利润率</th></tr>
"""
    for i, p in enumerate(yearly_products[:30], 1):
        profit_rate = (p["profit"] / p["amount"] * 100) if p["amount"] > 0 else 0
        html += f'    <tr><td>{i}</td><td>{p["name"]}</td><td>{p["barcode"]}</td><td>{p["quantity"]}</td><td>{format_money(p["amount"])}</td><td>{format_money(p["profit"])}</td><td>{profit_rate:.1f}%</td></tr>\n'

    html += f"""  </table>
</div>

<div class="section">
  <h2>📦 库存现状</h2>
  <div class="kpi-grid">
    <div class="kpi-card"><div class="label">在售商品数</div><div class="value">{inventory['enabled_products']}</div></div>
    <div class="kpi-card"><div class="label">记库存商品数</div><div class="value">{inventory['tracked_products']}</div></div>
    <div class="kpi-card"><div class="label">零库存商品</div><div class="value red">{inventory['zero_stock_count']}</div></div>
  </div>
"""
    if inventory["low_stock_list"]:
        html += '  <h2 style="margin-top:16px;">⚠️ 低库存预警</h2>\n  <table>\n    <tr><th>商品名称</th><th>条码</th><th>当前库存</th><th>下限</th><th>缺口</th></tr>\n'
        for item in inventory["low_stock_list"]:
            html += f'    <tr><td>{item["name"]}</td><td>{item["barcode"]}</td><td><span class="tag warn">{item["stock"]}</span></td><td>{item["min_stock"]}</td><td>{item["gap"]}</td></tr>\n'
        html += "  </table>\n"

    if inventory["zero_stock_list"]:
        html += '  <h2 style="margin-top:16px;">🔴 零库存清单</h2>\n  <table>\n    <tr><th>商品名称</th><th>条码</th><th>库存</th></tr>\n'
        for item in inventory["zero_stock_list"]:
            html += f'    <tr><td>{item["name"]}</td><td>{item["barcode"]}</td><td><span class="tag danger">0</span></td></tr>\n'
        html += "  </table>\n"

    html += '  <h2 style="margin-top:16px;">📋 库存概览（库存量 TOP 30）</h2>\n  <table>\n    <tr><th>商品名称</th><th>条码</th><th>库存</th><th>下限</th><th>上限</th><th>进货价</th><th>销售价</th></tr>\n'
    for item in inventory["stock_summary"][:30]:
        stock_tag = "ok" if item["stock"] > (item["min_stock"] or 0) else "warn"
        html += f'    <tr><td>{item["name"]}</td><td>{item["barcode"]}</td><td><span class="tag {stock_tag}">{item["stock"]}</span></td><td>{item["min_stock"]}</td><td>{item["max_stock"]}</td><td>{format_money(item["buy_price"])}</td><td>{format_money(item["sell_price"])}</td></tr>\n'

    html += "  </table>\n</div>\n"
    return html


def generate_html_report(date_str, stores_data, year):
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>银豹日报 - {date_str}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, "Microsoft YaHei", sans-serif; background: #f5f5f5; color: #333; padding: 20px; }}
  .container {{ max-width: 800px; margin: 0 auto; }}
  .header {{ background: #1a73e8; color: #fff; padding: 24px 32px; border-radius: 8px 8px 0 0; }}
  .header h1 {{ font-size: 22px; margin-bottom: 6px; }}
  .header .meta {{ font-size: 13px; opacity: 0.85; }}
  .store-divider {{ margin: 32px 0 16px 0; text-align: center; }}
  .store-tag {{ display: inline-block; background: #1a73e8; color: #fff; padding: 10px 24px; border-radius: 20px; font-size: 16px; font-weight: 700; }}
  .section {{ background: #fff; padding: 24px 32px; margin-bottom: 16px; border-radius: 8px; }}
  .section h2 {{ font-size: 18px; color: #1a73e8; border-bottom: 2px solid #e8f0fe; padding-bottom: 8px; margin-bottom: 16px; }}
  .kpi-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-bottom: 16px; }}
  .kpi-card {{ background: #f8f9fa; border-radius: 6px; padding: 16px; text-align: center; }}
  .kpi-card .label {{ font-size: 12px; color: #666; }}
  .kpi-card .value {{ font-size: 24px; font-weight: 700; color: #1a73e8; }}
  .kpi-card .value.red {{ color: #d32f2f; }}
  .kpi-card .value.green {{ color: #388e3c; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th {{ background: #e8f0fe; padding: 10px 12px; text-align: left; font-weight: 600; }}
  td {{ padding: 8px 12px; border-bottom: 1px solid #eee; }}
  tr:hover td {{ background: #f8f9fa; }}
  .tag {{ display: inline-block; padding: 2px 8px; border-radius: 3px; font-size: 11px; }}
  .tag.warn {{ background: #fff3e0; color: #e65100; }}
  .tag.danger {{ background: #ffebee; color: #c62828; }}
  .tag.ok {{ background: #e8f5e9; color: #2e7d32; }}
  .footer {{ text-align: center; color: #999; font-size: 12px; padding: 16px; }}
</style>
</head>
<body>
<div class="container">
<div class="header">
  <h1>📊 银豹经营日报</h1>
  <div class="meta">日期：{date_str} | 生成时间：{now_str}</div>
</div>
"""
    for store in stores_data:
        html += generate_store_section(
            store["name"], date_str, store["sales"],
            store["monthly_summary"], store["yearly_summary"],
            store["yearly_products"], store["inventory"], year,
        )

    html += """<div class="footer">此报表由银豹日报脚本自动生成 | 数据来源：银豹(PosPal)开放平台API</div>
</div>
</body>
</html>
"""
    return html


# ============================================================
# 邮件发送
# ============================================================
def send_email(html_content: str, date_str: str):
    email_cfg = CONFIG["email"]
    msg = MIMEText(html_content, "html", "utf-8")
    msg["Subject"] = f"银豹经营日报 - {date_str}"
    msg["From"] = email_cfg["sender_email"]
    msg["To"] = email_cfg["receiver_email"]

    with smtplib.SMTP_SSL(email_cfg["smtp_host"], email_cfg["smtp_port"]) as server:
        server.login(email_cfg["sender_email"], email_cfg["sender_password"])
        server.sendmail(email_cfg["sender_email"], [email_cfg["receiver_email"]], msg.as_string())
    print(f"[OK] 邮件已发送到 {email_cfg['receiver_email']}")


# ============================================================
# 主流程
# ============================================================
def main():
    # 解决Windows控制台编码问题
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    print("=" * 60)
    print("  银豹(PosPal)日报自动生成 - 多门店版")
    print("=" * 60)

    # 日报日期：凌晨0-6点算前一天，其余算当天
    now = datetime.now()
    if now.hour < 6:
        report_date = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        report_date = now.strftime("%Y-%m-%d")
    year = int(report_date[:4])
    print(f"[INFO] 报表日期: {report_date}")

    stores_data = []
    for store_cfg in CONFIG["stores"]:
        store_name = store_cfg["name"]
        pospal = store_cfg["pospal"]
        print(f"\n[INFO] ===== {store_name} =====")

        # 当日销售
        print("[INFO] 拉取当日销售数据...")
        try:
            tickets = fetch_sales_data(pospal, report_date)
            print(f"[OK] {len(tickets)} 条单据")
        except Exception as e:
            print(f"[ERROR] {e}")
            tickets = []

        # 年度销售
        print(f"[INFO] 拉取{year}年度销售数据...")
        try:
            yearly_tickets = fetch_yearly_sales_data(pospal, year)
            print(f"[OK] {len(yearly_tickets)} 条单据")
        except Exception as e:
            print(f"[WARN] {e}")
            yearly_tickets = []

        # 本月销售
        print("[INFO] 拉取本月销售数据...")
        try:
            monthly_tickets = fetch_monthly_sales_data(pospal, report_date)
            print(f"[OK] {len(monthly_tickets)} 条单据")
        except Exception as e:
            print(f"[WARN] {e}")
            monthly_tickets = []

        # 库存
        print("[INFO] 拉取库存数据...")
        try:
            products = fetch_inventory_data(pospal)
            print(f"[OK] {len(products)} 个商品")
        except Exception as e:
            print(f"[ERROR] {e}")
            products = []

        # 分析
        print("[INFO] 分析数据...")
        sales_analysis = analyze_sales(tickets)
        monthly_summary = calc_period_summary(monthly_tickets)
        yearly_summary = calc_period_summary(yearly_tickets)
        yearly_product_ranking = analyze_yearly_products(yearly_tickets)
        inventory_analysis = analyze_inventory(products)

        stores_data.append({
            "name": store_name,
            "sales": sales_analysis,
            "monthly_summary": monthly_summary,
            "yearly_summary": yearly_summary,
            "yearly_products": yearly_product_ranking,
            "inventory": inventory_analysis,
        })

    if not stores_data:
        print("[ERROR] 无门店数据")
        return

    # 生成报表
    print("\n[INFO] 生成HTML报表...")
    html = generate_html_report(report_date, stores_data, year)

    # 保存本地备份
    report_path = os.path.join(SCRIPT_DIR, f"report_{report_date}.html")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[OK] 本地报表: {report_path}")

    # 发送邮件
    print("[INFO] 发送邮件...")
    try:
        send_email(html, report_date)
    except Exception as e:
        print(f"[ERROR] 邮件发送失败: {e}")
        print(f"  本地报表已保存: {report_path}")
        return

    print("=" * 60)
    print("  日报生成完毕！")
    print("=" * 60)


if __name__ == "__main__":
    main()
