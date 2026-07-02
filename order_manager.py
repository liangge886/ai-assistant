#!/usr/bin/env python3
"""
个人订单 + 日程提醒管理系统
功能：
  订单管理：
    1. add_order    - 登记新订单
    2. ship_order   - 更新快递单号，标记已发货
    3. list_orders  - 查看订单
    4. check_pending - 检查未发货订单
    5. daily_report - 每日订单汇总邮件

  日程管理：
    6. add_event    - 添加日程提醒
    7. list_events  - 查看日程
    8. check_events - 检查今日待提醒日程
    9. del_event    - 删除日程
   10. daily_briefing - 每日综合简报（订单+日程）邮件
"""

import json
import os
import smtplib
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, date

# ============ 配置 ============
ORDERS_DIR = "/workspace/orders"
ORDERS_FILE = os.path.join(ORDERS_DIR, "orders.json")
EVENTS_FILE = os.path.join(ORDERS_DIR, "events.json")
EMAIL_SENDER = "38797137@qq.com"
EMAIL_PASSWORD = "fpwguhihlqtnbggd"
EMAIL_RECEIVER = "38797137@qq.com"
SMTP_SERVER = "smtp.qq.com"
SMTP_PORT = 465
PUSHPLUS_TOKEN = "204353151f4a4173a18c524def9393c2"


# ============ 数据层 ============

def init_storage():
    os.makedirs(ORDERS_DIR, exist_ok=True)
    if not os.path.exists(ORDERS_FILE):
        with open(ORDERS_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)
    if not os.path.exists(EVENTS_FILE):
        with open(EVENTS_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)


def load_orders():
    init_storage()
    with open(ORDERS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_orders(orders):
    with open(ORDERS_FILE, "w", encoding="utf-8") as f:
        json.dump(orders, f, ensure_ascii=False, indent=2)


def load_events():
    init_storage()
    with open(EVENTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_events(events):
    with open(EVENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(events, f, ensure_ascii=False, indent=2)


def today_str():
    return datetime.now().strftime("%Y-%m-%d")


def now_time():
    return datetime.now().strftime("%H:%M")


def check_last_run(task_name):
    """检查某任务今天是否已执行，未执行返回 True"""
    init_storage()
    tracker_file = os.path.join(ORDERS_DIR, "run_tracker.json")
    if not os.path.exists(tracker_file):
        return True
    with open(tracker_file, "r", encoding="utf-8") as f:
        tracker = json.load(f)
    last_run = tracker.get(task_name, "")
    return last_run != today_str()


def mark_run(task_name):
    """标记某任务今日已执行"""
    init_storage()
    tracker_file = os.path.join(ORDERS_DIR, "run_tracker.json")
    tracker = {}
    if os.path.exists(tracker_file):
        with open(tracker_file, "r", encoding="utf-8") as f:
            tracker = json.load(f)
    tracker[task_name] = today_str()
    with open(tracker_file, "w", encoding="utf-8") as f:
        json.dump(tracker, f, ensure_ascii=False, indent=2)


# ============ 邮件发送 ============

def send_email(subject, html_content, plain_text=""):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = EMAIL_SENDER
    msg["To"] = EMAIL_RECEIVER
    if not plain_text:
        plain_text = subject
    msg.attach(MIMEText(plain_text, "plain", "utf-8"))
    msg.attach(MIMEText(html_content, "html", "utf-8"))
    try:
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_SENDER, [EMAIL_RECEIVER], msg.as_string())
        print(f"✅ 邮件已发送 -> {EMAIL_RECEIVER}")
        return True
    except Exception as e:
        print(f"❌ 邮件发送失败: {e}")
        return False


def push_wechat(title, content):
    """通过 PushPlus 推送微信消息"""
    try:
        r = requests.post(
            "http://www.pushplus.plus/send",
            json={"token": PUSHPLUS_TOKEN, "title": title, "content": content},
            timeout=10
        )
        if r.json().get("code") == 200:
            print(f"✅ 微信推送成功：{title}")
            return True
        else:
            print(f"❌ 微信推送失败: {r.json()}")
            return False
    except Exception as e:
        print(f"❌ 微信推送异常: {e}")
        return False


# ================================================================
#                         订单管理
# ================================================================

def add_order(customer, product, quantity, amount, remark=""):
    orders = load_orders()
    today = today_str()
    year = datetime.now().strftime("%Y")
    year_orders = [o for o in orders if o.get("date", "").startswith(year)]
    short_no = len(year_orders) + 1
    order_id = f"{year}-{short_no:04d}"

    order = {
        "order_id": order_id,
        "short_no": short_no,
        "year": year,
        "date": today,
        "time": now_time(),
        "customer": customer,
        "product": product,
        "quantity": quantity,
        "amount": amount,
        "tracking_no": "",
        "status": "未发货",
        "remark": remark,
    }

    orders.append(order)
    save_orders(orders)

    print(f"✅ 第 {short_no} 号订单已登记（{year}年度）")
    print(f"   客户：{customer}")
    print(f"   商品：{product} × {quantity}")
    print(f"   金额：¥{amount}")
    print(f"   状态：未发货")
    print(f"   💡 发货时请说：{short_no}号单 快递单号XXXX")
    return order_id


def ship_order(short_no=None, customer=None, product=None, tracking_no=""):
    orders = load_orders()
    year = datetime.now().strftime("%Y")
    pending_orders = [o for o in orders if o["status"] == "未发货"]

    if not pending_orders:
        print("❌ 当前没有待发货订单")
        return []

    # 编号精确匹配
    if short_no is not None:
        for o in pending_orders:
            if o.get("year") == year and o.get("short_no") == short_no:
                o["tracking_no"] = tracking_no
                o["status"] = "已发货"
                o["ship_time"] = now_time()
                save_orders(orders)
                print(f"✅ 第 {o['short_no']} 号订单已发货：{o['customer']} 快递单号：{tracking_no}")
                return [o]

    # 多维度模糊匹配
    candidates = []
    for o in pending_orders:
        score = 0
        reasons = []
        if customer and customer in o["customer"]:
            score += 3
            reasons.append("客户名匹配")
        if product and product in o["product"]:
            score += 2
            reasons.append("商品匹配")
        if short_no is not None and str(short_no) in str(o.get("short_no", "")):
            score += 1
            reasons.append("编号部分匹配")
        if score > 0:
            candidates.append((score, o, reasons))

    if len(candidates) == 1:
        _, o, reasons = candidates[0]
        o["tracking_no"] = tracking_no
        o["status"] = "已发货"
        o["ship_time"] = now_time()
        save_orders(orders)
        print(f"✅ 第 {o['short_no']} 号订单已发货：{o['customer']} 快递单号：{tracking_no}")
        print(f"   匹配方式：{' + '.join(reasons)}")
        return [o]
    elif len(candidates) > 1:
        candidates.sort(key=lambda x: -x[0])
        top_score = candidates[0][0]
        top_matches = [c for c in candidates if c[0] == top_score]
        if len(top_matches) == 1 and top_score >= 4:
            _, o, reasons = top_matches[0]
            o["tracking_no"] = tracking_no
            o["status"] = "已发货"
            o["ship_time"] = now_time()
            save_orders(orders)
            print(f"✅ 第 {o['short_no']} 号订单已发货：{o['customer']} 快递单号：{tracking_no}")
            print(f"   匹配方式：{' + '.join(reasons)}")
            return [o]
        print(f"🤔 找到 {len(candidates)} 个待发货订单，请确认：")
        for i, (score, o, reasons) in enumerate(candidates, 1):
            print(f"   {i}. 第 {o['short_no']} 号 | {o['customer']} | {o['product']} × {o['quantity']} | ¥{o['amount']}")
        return []
    else:
        print("❌ 未找到匹配的待发货订单")
        for o in pending_orders:
            print(f"   第 {o['short_no']} 号 | {o['customer']} | {o['product']} × {o['quantity']}")
        return []


def list_orders(target_date=None):
    orders = load_orders()
    if target_date is None:
        target_date = today_str()
    day_orders = [o for o in orders if o.get("date") == target_date]
    if not day_orders:
        print(f"📅 {target_date} 暂无订单")
        return []
    print(f"📅 {target_date} 订单列表（共 {len(day_orders)} 单）")
    print("-" * 85)
    print(f"{'编号':<8} {'客户':<8} {'商品':<16} {'数量':<4} {'金额':<8} {'快递单号':<16} {'状态'}")
    print("-" * 85)
    for o in day_orders:
        tracking = o["tracking_no"] if o["tracking_no"] else "—"
        status_icon = "✅" if o["status"] == "已发货" else "⚠️"
        print(f"{o['short_no']}号      {o['customer']:<8} {o['product']:<16} {o['quantity']:<4} ¥{o['amount']:<7} {tracking:<16} {status_icon} {o['status']}")
    shipped = [o for o in day_orders if o["status"] == "已发货"]
    pending = [o for o in day_orders if o["status"] == "未发货"]
    total = sum(float(o["amount"]) for o in day_orders)
    print("-" * 85)
    print(f"📊 合计 {len(day_orders)} 单 | 已发货 {len(shipped)} | 未发货 {len(pending)} | 总金额 ¥{total}")
    return day_orders


def check_pending():
    orders = load_orders()
    today = today_str()
    pending = [o for o in orders if o["status"] == "未发货" and o.get("date") == today]
    if not pending:
        print("✅ 今日无漏单，全部已发货！")
        return []
    print(f"⚠️ 今日有 {len(pending)} 单未发货：")
    for o in pending:
        print(f"   第 {o['short_no']} 号 | {o['customer']} | {o['product']} × {o['quantity']} | ¥{o['amount']}")
    return pending


# ================================================================
#                       事件管理（待办清单）
# ================================================================

def add_event(title, event_time="", remark=""):
    """
    添加事件/待办
    title: 事件内容
    event_time: 可选，有时间就带，没有就空
    remark: 备注
    """
    events = load_events()

    event_id = len(events) + 1
    event = {
        "event_id": event_id,
        "title": title,
        "time": event_time,
        "remark": remark,
        "created": today_str(),
        "done": False,
        "done_date": "",
    }

    events.append(event)
    save_events(events)

    print(f"✅ 事件已记录（编号 {event_id}）")
    if event_time:
        print(f"   时间：{event_time}")
    print(f"   内容：{title}")
    if remark:
        print(f"   备注：{remark}")
    return event_id


def list_events(show_done=False):
    """查看事件清单"""
    events = load_events()
    
    pending = [e for e in events if not e.get("done")]
    done = [e for e in events if e.get("done")]
    
    if not events:
        print("📝 暂无事件记录")
        return []
    
    print(f"📝 事件清单（待办 {len(pending)} 项 | 已完成 {len(done)} 项）")
    print("-" * 60)
    
    if pending:
        print("⏳ 待办：")
        for e in pending:
            time_str = f" [{e['time']}]" if e.get("time") else ""
            print(f"   {e['event_id']}. {e['title']}{time_str}")
            if e.get("remark"):
                print(f"      备注：{e['remark']}")
    
    if show_done and done:
        print("\n✅ 已完成：")
        for e in done:
            print(f"   {e['event_id']}. {e['title']}（{e.get('done_date','')}完成）")
    
    print("-" * 60)
    return events


def check_events():
    """查看待办事件"""
    events = load_events()
    pending = [e for e in events if not e.get("done")]
    
    if not pending:
        print("✅ 所有事件都已完成！")
        return []
    
    print(f"⏳ 你还有 {len(pending)} 件事没做：")
    for e in pending:
        time_str = f" [{e['time']}]" if e.get("time") else ""
        print(f"   {e['event_id']}. {e['title']}{time_str}")
        if e.get("remark"):
            print(f"      备注：{e['remark']}")
    return pending


def del_event(event_id):
    events = load_events()
    new_events = [e for e in events if e.get("event_id") != int(event_id)]
    if len(new_events) < len(events):
        save_events(new_events)
        print(f"✅ 事件 {event_id} 已删除")
    else:
        print(f"❌ 未找到事件 {event_id}")


def done_event(event_id):
    """标记事件完成"""
    events = load_events()
    for e in events:
        if e.get("event_id") == int(event_id):
            e["done"] = True
            e["done_date"] = today_str()
            save_events(events)
            print(f"✅ 已完成：{e['title']}")
            return
    print(f"❌ 未找到事件 {event_id}")


def event_reminder():
    """微信推送待办事件提醒（每天定时调用）"""
    events = load_events()
    pending = [e for e in events if not e.get("done")]

    if not pending:
        print("✅ 所有事件已完成，无需提醒")
        return

    lines = [f"⏰ 待办提醒 — {today_str()}", ""]
    lines.append(f"你还有 {len(pending)} 件事没做：")
    lines.append("")
    for e in pending:
        t = f"[{e['time']}] " if e.get("time") else ""
        lines.append(f"  {e['event_id']}. {t}{e['title']}")
        if e.get("remark"):
            lines.append(f"     备注：{e['remark']}")

    content = "\n".join(lines)
    push_wechat(f"⏰ 待办提醒（{len(pending)}项）", content)
    print(content)


def order_reminder():
    """微信推送订单漏单提醒"""
    orders = load_orders()
    pending = [o for o in orders if o["status"] == "未发货"]

    if not pending:
        return  # 没漏单不打扰

    lines = [f"⚠️ 漏单提醒 — {today_str()}", ""]
    lines.append(f"还有 {len(pending)} 单未发货：")
    lines.append("")
    for o in pending:
        lines.append(f"  第{o['short_no']}号 {o['customer']} {o['product']}×{o['quantity']} ¥{o['amount']}")

    content = "\n".join(lines)
    push_wechat(f"⚠️ 漏单提醒（{len(pending)}单）", content)


def quick_remind(content):
    """临时提醒 — 立刻推送到微信"""
    push_wechat("🔔 提醒", content)
    print(f"✅ 已推送提醒：{content}")


# ================================================================
#                      每日综合简报邮件
# ================================================================

def daily_briefing():
    """每日综合简报：订单汇总 + 日程提醒，发邮件"""
    today = today_str()

    # 自检：今天是否已执行，未执行才发（防止 cron 失效后重复发送）
    if not check_last_run("briefing"):
        print(f"📋 {today} 简报今日已发送，跳过")
        return

    # === 订单部分 ===
    orders = load_orders()
    today_orders = [o for o in orders if o.get("date") == today]
    shipped = [o for o in today_orders if o["status"] == "已发货"]
    pending = [o for o in today_orders if o["status"] == "未发货"]
    total_amount = sum(float(o["amount"]) for o in today_orders)

    # === 事件部分 ===
    events = load_events()
    pending_events = [e for e in events if not e.get("done")]
    done_events = [e for e in events if e.get("done")]
    today_done = [e for e in done_events if e.get("done_date") == today]

    # === 生成 HTML ===
    
    # 订单统计卡片
    order_cards = f"""
    <div style="display:flex; gap:12px; margin-bottom:20px;">
        <div style="flex:1; background:#f8f9fc; border-radius:8px; padding:14px; text-align:center;">
            <div style="font-size:24px; font-weight:bold; color:#333;">{len(today_orders)}</div>
            <div style="font-size:12px; color:#888;">今日订单</div>
        </div>
        <div style="flex:1; background:#f0fff0; border-radius:8px; padding:14px; text-align:center;">
            <div style="font-size:24px; font-weight:bold; color:#27ae60;">{len(shipped)}</div>
            <div style="font-size:12px; color:#888;">已发货</div>
        </div>
        <div style="flex:1; background:#fff5f5; border-radius:8px; padding:14px; text-align:center;">
            <div style="font-size:24px; font-weight:bold; color:#e74c3c;">{len(pending)}</div>
            <div style="font-size:12px; color:#888;">未发货</div>
        </div>
        <div style="flex:1; background:#fffdf5; border-radius:8px; padding:14px; text-align:center;">
            <div style="font-size:24px; font-weight:bold; color:#f39c12;">¥{total_amount}</div>
            <div style="font-size:12px; color:#888;">总金额</div>
        </div>
    </div>"""

    # 漏单提醒
    alert_section = ""
    if pending:
        alert_items = ""
        for o in pending:
            alert_items += f"<div style='margin:4px 0;'>🔴 第 {o['short_no']} 号 — {o['customer']} — {o['product']} × {o['quantity']}（¥{o['amount']}）</div>"
        alert_section = f"""
        <div style="background:#fff5f5; border-left:4px solid #e74c3c; padding:14px 18px; border-radius:6px; margin-bottom:20px;">
            <div style="font-size:15px; font-weight:bold; color:#e74c3c; margin-bottom:8px;">
                ⚠️ 漏单提醒：{len(pending)} 单未发货
            </div>
            {alert_items}
        </div>"""
    else:
        if today_orders:
            alert_section = """
            <div style="background:#f0fff0; border-left:4px solid #27ae60; padding:14px 18px; border-radius:6px; margin-bottom:20px;">
                <span style="font-size:15px; color:#27ae60; font-weight:bold;">✅ 今日订单全部已发货</span>
            </div>"""

    # 订单明细表
    order_rows = ""
    for o in today_orders:
        tracking = o["tracking_no"] if o["tracking_no"] else "—"
        if o["status"] == "已发货":
            status_html = '<span style="color:#27ae60;font-weight:bold;">✅ 已发货</span>'
            row_bg = "#f0fff0"
        else:
            status_html = '<span style="color:#e74c3c;font-weight:bold;">⚠️ 未发货</span>'
            row_bg = "#fff5f5"
        order_rows += f"""
        <tr style="background:{row_bg};">
            <td style="padding:8px 10px;font-weight:bold;color:#e91e63;">{o['short_no']}号</td>
            <td style="padding:8px 10px;font-weight:bold;">{o['customer']}</td>
            <td style="padding:8px 10px;">{o['product']}</td>
            <td style="padding:8px 10px;text-align:center;">{o['quantity']}</td>
            <td style="padding:8px 10px;text-align:right;">¥{o['amount']}</td>
            <td style="padding:8px 10px;">{tracking}</td>
            <td style="padding:8px 10px;">{status_html}</td>
        </tr>"""

    order_section = f"""
    {order_cards}
    {alert_section}"""
    
    if today_orders:
        order_section += f"""
    <table style="width:100%; border-collapse:collapse; font-size:13px; margin-bottom:20px;">
        <tr style="background:#f8f9fc; color:#666;">
            <th style="padding:8px 10px; text-align:left;">编号</th>
            <th style="padding:8px 10px; text-align:left;">客户</th>
            <th style="padding:8px 10px; text-align:left;">商品</th>
            <th style="padding:8px 10px; text-align:center;">数量</th>
            <th style="padding:8px 10px; text-align:right;">金额</th>
            <th style="padding:8px 10px; text-align:left;">快递单号</th>
            <th style="padding:8px 10px; text-align:left;">状态</th>
        </tr>
        {order_rows}
    </table>"""

    # 事件清单部分
    event_section = ""
    
    # 待办列表
    if pending_events:
        pending_items = ""
        for e in pending_events:
            time_str = f"<span style='color:#4a6cf7;font-weight:bold;'>{e['time']}</span> " if e.get("time") else ""
            remark_str = f"<div style='font-size:12px;color:#888;margin-top:2px;'>{e['remark']}</div>" if e.get("remark") else ""
            pending_items += f"""
            <div style="background:#f0f4ff; border-radius:6px; padding:10px 14px; margin-bottom:8px;">
                <span style="font-weight:bold;color:#e74c3c;">⏳</span>
                <span style="font-size:15px;margin-left:6px;">{time_str}{e['title']}</span>
                {remark_str}
            </div>"""
        event_section = f"""
    <h2 style="font-size:17px; color:#4a6cf7; border-bottom:2px solid #4a6cf7; padding-bottom:8px; margin-bottom:12px;">📝 待办事件（{len(pending_events)} 项未完成）</h2>
    {pending_items}"""
    else:
        event_section = """
    <h2 style="font-size:17px; color:#4a6cf7; border-bottom:2px solid #4a6cf7; padding-bottom:8px; margin-bottom:12px;">📝 待办事件</h2>
    <div style="background:#f8f9fc; padding:14px; border-radius:6px; text-align:center; color:#888; margin-bottom:20px;">
        所有事件都已完成 ✅
    </div>"""

    # 今日已完成
    if today_done:
        done_items = ""
        for e in today_done:
            done_items += f"<div style='margin:4px 0;'>✅ {e['title']}</div>"
        event_section += f"""
    <div style="background:#f0fff0; border-left:4px solid #27ae60; padding:14px 18px; border-radius:6px; margin-bottom:20px;">
        <div style="font-size:14px; font-weight:bold; color:#27ae60; margin-bottom:6px;">🎉 今日已完成（{len(today_done)} 项）</div>
        {done_items}
    </div>"""

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:'Microsoft YaHei',Arial,sans-serif; background:#f5f6fa; padding:20px;">

<div style="max-width:680px; margin:0 auto; background:#fff; border-radius:12px; overflow:hidden; box-shadow:0 2px 12px rgba(0,0,0,0.08);">

<div style="background:linear-gradient(135deg,#2c3e50,#3498db); color:#fff; padding:24px 32px; text-align:center;">
    <h1 style="margin:0 0 4px 0; font-size:22px;">📋 每日简报</h1>
    <p style="margin:0; opacity:0.8; font-size:13px;">{today} · 订单 + 日程</p>
</div>

<div style="padding:24px 32px;">

<!-- 事件部分 -->
{event_section}

<!-- 订单部分 -->
<h2 style="font-size:17px; color:#e91e63; border-bottom:2px solid #e91e63; padding-bottom:8px; margin-bottom:12px;">📦 今日订单</h2>
{order_section}

<div style="border-top:1px solid #eee; padding-top:14px; text-align:center; color:#999; font-size:12px; margin-top:20px;">
    <p style="margin:0;">由 AI Agent 自动生成 · 有疑问随时联系</p>
</div>

</div>
</div>
</body>
</html>"""

    send_email(
        f"📋 每日简报 - {today}",
        html,
        f"每日简报 - {today}\n订单 {len(today_orders)} 单 | 未发货 {len(pending)} | 待办事件 {len(pending_events)} 项 | 今日完成 {len(today_done)} 项"
    )

    # 同时推送微信
    wx_lines = []
    if today_orders:
        wx_lines.append(f"📦 今日订单：{len(today_orders)} 单 | 已发 {len(shipped)} | 未发 {len(pending)} | ¥{total_amount}")
    if pending:
        wx_lines.append("")
        wx_lines.append("⚠️ 漏单：")
        for o in pending:
            wx_lines.append(f"  第{o['short_no']}号 {o['customer']} {o['product']}×{o['quantity']}")
    if pending_events:
        wx_lines.append("")
        wx_lines.append(f"📝 待办（{len(pending_events)}项）：")
        for e in pending_events:
            t = f"[{e['time']}] " if e.get("time") else ""
            wx_lines.append(f"  {e['event_id']}. {t}{e['title']}")
    if today_done:
        wx_lines.append("")
        wx_lines.append(f"🎉 今日完成（{len(today_done)}项）：")
        for e in today_done:
            wx_lines.append(f"  ✅ {e['title']}")
    if not today_orders and not pending_events and not today_done:
        wx_lines.append("今日无订单、无待办事件。")

    push_wechat(f"📋 {today} 简报", "\n".join(wx_lines))


# ================================================================
#                      命令行入口
# ================================================================

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("📋 订单管理：")
        print("  add 客户 商品 数量 金额 [备注]    - 登记订单")
        print("  ship 编号/客户名 快递单号          - 标记发货")
        print("  ship 客户名 商品 快递单号          - 精准匹配发货")
        print("  list [日期]                       - 查看订单")
        print("  pending                           - 查看未发货")
        print()
        print("📝 事件管理：")
        print("  event add 内容                    - 添加事件（无时间）")
        print("  event add 时间 内容               - 添加事件（带时间）")
        print("  event add 时间 内容 备注          - 添加事件（带时间+备注）")
        print("  event list                        - 查看全部事件")
        print("  event check                       - 查看待办事件")
        print("  event done 编号                   - 标记完成")
        print("  event del 编号                    - 删除事件")
        print()
        print("📧 简报：")
        print("  briefing                          - 发送今日综合简报邮件")
        sys.exit(1)

    cmd = sys.argv[1]

    # 订单命令
    if cmd == "add":
        if len(sys.argv) < 6:
            print("❌ 参数不足: add 客户 商品 数量 金额 [备注]")
            sys.exit(1)
        add_order(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], sys.argv[6] if len(sys.argv) > 6 else "")

    elif cmd == "ship":
        if len(sys.argv) < 4:
            print("❌ 参数不足: ship 编号/客户名/[商品] 快递单号")
            sys.exit(1)
        if len(sys.argv) == 4:
            target = sys.argv[2]
            tracking = sys.argv[3]
            if target.isdigit():
                ship_order(short_no=int(target), tracking_no=tracking)
            else:
                ship_order(customer=target, product=target, tracking_no=tracking)
        elif len(sys.argv) == 5:
            ship_order(customer=sys.argv[2], product=sys.argv[3], tracking_no=sys.argv[4])

    elif cmd == "list":
        list_orders(sys.argv[2] if len(sys.argv) > 2 else None)

    elif cmd == "pending":
        check_pending()

    # 事件命令
    elif cmd == "event":
        sub = sys.argv[2] if len(sys.argv) > 2 else ""
        if sub == "add":
            if len(sys.argv) < 4:
                print("❌ 参数不足: event add [时间] 内容 [备注]")
                print("   例: event add 给张三打电话")
                print("   例: event add 14:00 和张三开会")
                print("   例: event add 明天 取快递 别忘了带箱子")
                sys.exit(1)
            # 智能判断：第一个参数如果像时间（含冒号或"明天"/"后天"等），就当作时间
            arg3 = sys.argv[3]
            time_keywords = [":", "今天", "明天", "后天", "下周", "周"]
            is_time = any(k in arg3 for k in time_keywords)
            
            if is_time and len(sys.argv) >= 5:
                event_time = arg3
                title = sys.argv[4]
                remark = sys.argv[5] if len(sys.argv) > 5 else ""
            else:
                event_time = ""
                title = arg3
                remark = sys.argv[4] if len(sys.argv) > 4 else ""
            
            add_event(title, event_time, remark)

        elif sub == "list":
            list_events(show_done=True)

        elif sub == "done":
            if len(sys.argv) < 4:
                print("❌ 参数不足: event done 编号")
                sys.exit(1)
            done_event(sys.argv[3])

        elif sub == "del":
            if len(sys.argv) < 4:
                print("❌ 参数不足: event del 编号")
                sys.exit(1)
            del_event(sys.argv[3])

        elif sub == "check":
            check_events()

        else:
            print("用法: event add/list/check/done/del")

    # 简报
    elif cmd == "briefing":
        daily_briefing()

    # 兼容旧命令
    elif cmd == "report":
        daily_briefing()

    # 微信提醒
    elif cmd == "remind_events":
        event_reminder()
    elif cmd == "remind_orders":
        order_reminder()
    elif cmd == "remind":
        quick_remind(" ".join(sys.argv[2:]))

    else:
        print(f"❌ 未知命令: {cmd}")
