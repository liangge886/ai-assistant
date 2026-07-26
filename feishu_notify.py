#!/usr/bin/env python3
"""
飞书(Feishu/Lark)消息推送模块
==================================================
支持飞书「群机器人」(自定义机器人) 文本 / 富文本(post) 推送。
配置方式（推荐用 GitHub Actions Secret，避免明文）：
    export FEISHU_WEBHOOK="https://open.feishu.cn/open-apis/bot/v2/hook/xxxx"
    export FEISHU_SECRET="签名密钥（可选，安全设置里开启才需要）"

未配置 FEISHU_WEBHOOK 时，所有发送函数安全跳过（返回 None）。
"""
import os
import json
import time
import hashlib
import hmac
import urllib.request


def _sign(secret: str, timestamp: str) -> str:
    """飞书签名机器人：HMAC-SHA256(timestamp + '\n' + secret)"""
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(secret.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha256).digest()
    return hmac_code.hex()


def _post(webhook: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        webhook, data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _auth(payload: dict, secret: str | None):
    if secret:
        ts = str(int(time.time()))
        payload["timestamp"] = ts
        payload["sign"] = _sign(secret, ts)
    return payload


def send_text(text: str, webhook: str | None = None, secret: str | None = None) -> dict | None:
    webhook = webhook or os.environ.get("FEISHU_WEBHOOK")
    secret = secret or os.environ.get("FEISHU_SECRET")
    if not webhook:
        print("[INFO] 未配置 FEISHU_WEBHOOK，跳过飞书推送")
        return None
    payload = _auth({"msg_type": "text", "content": {"text": text}}, secret)
    return _post(webhook, payload)


def send_post(title: str, lines: list, webhook: str | None = None, secret: str | None = None) -> dict | None:
    webhook = webhook or os.environ.get("FEISHU_WEBHOOK")
    secret = secret or os.environ.get("FEISHU_SECRET")
    if not webhook:
        print("[INFO] 未配置 FEISHU_WEBHOOK，跳过飞书推送")
        return None
    content = [[{"tag": "text", "text": ln}] for ln in lines]
    payload = _auth({
        "msg_type": "post",
        "content": {"post": {"zh_cn": {"title": title, "content": content}}},
    }, secret)
    return _post(webhook, payload)


def send_report(summary_text: str, date_str: str) -> dict | None:
    """把「每日营业总结」以飞书富文本推送。"""
    webhook = os.environ.get("FEISHU_WEBHOOK")
    secret = os.environ.get("FEISHU_SECRET")
    if not webhook:
        print("[INFO] 未配置 FEISHU_WEBHOOK，跳过飞书推送")
        return None
    lines = [ln.rstrip() for ln in summary_text.split("\n") if ln.strip()]
    title = f"觉爱家纺·每日经营分析 {date_str}"
    return send_post(title, lines, webhook, secret)


if __name__ == "__main__":
    # 自测：python3 feishu_notify.py （需先 export FEISHU_WEBHOOK）
    r = send_text("飞书推送测试 ✅ 觉爱家纺经营报表通道已接通")
    print(r)
