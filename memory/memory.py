#!/usr/bin/env python3
"""
第二大脑 · 记忆库 + 待办清单
==================================================
帮你记住零碎事情，随时问、随时查、随时提醒。

命令：
  memory add <内容> [--tag 标签1,标签2]     记一条知识/事情
  memory list [--all]                        列出全部记忆（默认仅未归档）
  memory search <关键词>                     模糊搜索记忆（内容+标签）
  memory get <id>                            查看某条记忆详情
  memory archive <id>                        归档（不再默认显示）
  memory del <id>                            删除一条记忆

  todo add <任务> [--due YYYY-MM-DD]         加一条待办
  todo done <id>                             标记完成
  todo undone <id>                           撤销完成
  todo list [--all]                          列待办（默认仅未完成）
  todo check <关键词>                        问“我做了X吗？”→ 返回匹配待办及状态
  todo del <id>                              删除一条待办

说明：
  - 数据持久化在脚本同目录 memory/memory.json
  - 每次改动自动镜像并推送到 GitHub 仓库（/tmp/ai-assistant），跨会话不丢
  - 时间点提醒请用：python3 order_manager.py event add <日期> <时间> <事>
"""

import json
import os
import sys
import shutil
import subprocess
from datetime import datetime, date

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORY_FILE = os.path.join(BASE_DIR, "memory", "memory.json")
REPO_DIR = "/tmp/ai-assistant"  # 镜像到 GitHub 仓库，实现跨会话持久化


# ============ 数据层 ============
def init():
    os.makedirs(os.path.dirname(MEMORY_FILE), exist_ok=True)
    if not os.path.exists(MEMORY_FILE):
        json.dump({"memories": [], "todos": []}, open(MEMORY_FILE, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)


def load():
    init()
    with open(MEMORY_FILE, encoding="utf-8") as f:
        return json.load(f)


def save(d):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
    sync_github()


def next_id(lst):
    return max([x.get("id", 0) for x in lst], default=0) + 1


def today_str():
    return datetime.now().strftime("%Y-%m-%d")


def sync_github():
    """把 memory.json 与 memory.py 镜像到仓库并推送（失败静默，不影响本地）"""
    try:
        if not os.path.isdir(os.path.join(REPO_DIR, ".git")):
            return
        dst_dir = os.path.join(REPO_DIR, "memory")
        os.makedirs(dst_dir, exist_ok=True)
        shutil.copy(MEMORY_FILE, os.path.join(dst_dir, "memory.json"))
        shutil.copy(os.path.abspath(__file__), os.path.join(dst_dir, "memory.py"))
        g = ["git", "--git-dir", os.path.join(REPO_DIR, ".git"), "--work-tree", REPO_DIR]
        subprocess.run(g + ["add", "memory/memory.json", "memory/memory.py"],
                       check=True, capture_output=True)
        # 仅在确有改动时才提交推送
        diff = subprocess.run(g + ["diff", "--cached", "--quiet"], capture_output=True)
        if diff.returncode != 0:
            subprocess.run(g + ["commit", "-m", "memory: 自动同步记忆库/待办"],
                           check=True, capture_output=True)
            subprocess.run(g + ["push", "origin", "main"], check=True, capture_output=True)
    except Exception:
        pass


# ============ 记忆命令 ============
def memory_add(content, tags):
    d = load()
    item = {
        "id": next_id(d["memories"]),
        "content": content,
        "tags": tags,
        "created": today_str(),
        "updated": today_str(),
        "archived": False,
    }
    d["memories"].append(item)
    save(d)
    print(f"✅ 已记住 [{item['id']}] {content}" + (f"  #标签:{','.join(tags)}" if tags else ""))


def memory_list(show_all):
    d = load()
    items = [m for m in d["memories"] if show_all or not m.get("archived")]
    if not items:
        print("📭 暂无记忆")
        return
    print(f"🧠 记忆库（共 {len(items)} 条）")
    print("-" * 50)
    for m in sorted(items, key=lambda x: x.get("id", 0)):
        flag = "🗄️" if m.get("archived") else "•"
        tagstr = f"  #{','.join(m.get('tags', []))}" if m.get("tags") else ""
        print(f"{flag} [{m['id']}] {m['content']}{tagstr}")


def memory_search(kw):
    d = load()
    kw = kw.lower()
    hits = [m for m in d["memories"]
            if kw in m.get("content", "").lower() or any(kw in t.lower() for t in m.get("tags", []))]
    if not hits:
        print(f"🔍 没找到和「{kw}」相关的记忆")
        return
    print(f"🔍 搜索「{kw}」命中 {len(hits)} 条：")
    print("-" * 50)
    for m in hits:
        tagstr = f"  #{','.join(m.get('tags', []))}" if m.get("tags") else ""
        print(f"• [{m['id']}] {m['content']}{tagstr}")


def memory_get(mid):
    d = load()
    m = next((x for x in d["memories"] if x.get("id") == mid), None)
    if not m:
        print(f"❌ 找不到 id={mid} 的记忆")
        return
    print(f"🧠 [{m['id']}] {m['content']}")
    print(f"   标签: {','.join(m.get('tags', [])) or '无'}")
    print(f"   创建: {m.get('created')}  更新: {m.get('updated')}  归档: {m.get('archived')}")


def memory_archive(mid):
    d = load()
    m = next((x for x in d["memories"] if x.get("id") == mid), None)
    if not m:
        print(f"❌ 找不到 id={mid} 的记忆")
        return
    m["archived"] = True
    save(d)
    print(f"🗄️ 已归档 [{mid}] {m['content']}")


def memory_del(mid):
    d = load()
    before = len(d["memories"])
    d["memories"] = [x for x in d["memories"] if x.get("id") != mid]
    if len(d["memories"]) == before:
        print(f"❌ 找不到 id={mid} 的记忆")
        return
    save(d)
    print(f"🗑️ 已删除 id={mid}")


# ============ 待办命令 ============
def todo_add(task, due):
    d = load()
    item = {
        "id": next_id(d["todos"]),
        "task": task,
        "done": False,
        "created": today_str(),
        "done_date": "",
        "due": due or "",
    }
    d["todos"].append(item)
    save(d)
    duestr = f"  截止:{due}" if due else ""
    print(f"✅ 已添加待办 [{item['id']}] {task}{duestr}")


def todo_done(tid):
    d = load()
    t = next((x for x in d["todos"] if x.get("id") == tid), None)
    if not t:
        print(f"❌ 找不到 id={tid} 的待办")
        return
    t["done"] = True
    t["done_date"] = today_str()
    save(d)
    print(f"✔️ 已标记完成 [{tid}] {t['task']}")


def todo_undone(tid):
    d = load()
    t = next((x for x in d["todos"] if x.get("id") == tid), None)
    if not t:
        print(f"❌ 找不到 id={tid} 的待办")
        return
    t["done"] = False
    t["done_date"] = ""
    save(d)
    print(f"↩️ 已撤销完成 [{tid}] {t['task']}")


def todo_list(show_all):
    d = load()
    items = [t for t in d["todos"] if show_all or not t.get("done")]
    if not items:
        print("📭 暂无待办")
        return
    print(f"📋 待办清单（显示 {len(items)} 条）")
    print("-" * 50)
    for t in sorted(items, key=lambda x: (x.get("done"), x.get("id", 0))):
        status = "✔️" if t.get("done") else "•"
        due = f"  截止:{t['due']}" if t.get("due") else ""
        done = f"  (完成于{t['done_date']})" if t.get("done") else ""
        print(f"{status} [{t['id']}] {t['task']}{due}{done}")


def todo_check(kw):
    d = load()
    kw = kw.lower()
    hits = [t for t in d["todos"] if kw in t.get("task", "").lower()]
    if not hits:
        print(f"🤔 没找到和「{kw}」相关的待办记录。要我记一条吗？")
        return
    print(f"🔎 关于「{kw}」的待办：")
    print("-" * 50)
    for t in hits:
        if t.get("done"):
            print(f"✔️ 已完成：[{t['id']}] {t['task']}（{t['done_date']} 完成）")
        else:
            due = f"，截止 {t['due']}" if t.get("due") else ""
            print(f"⏳ 还没做：[{t['id']}] {t['task']}{due}")


def todo_del(tid):
    d = load()
    before = len(d["todos"])
    d["todos"] = [x for x in d["todos"] if x.get("id") != tid]
    if len(d["todos"]) == before:
        print(f"❌ 找不到 id={tid} 的待办")
        return
    save(d)
    print(f"🗑️ 已删除待办 id={tid}")


# ============ CLI ============
def parse_tags(argv):
    tags = []
    rest = []
    for a in argv:
        if a.startswith("--tag"):
            val = a.split("=", 1)[1] if "=" in a else None
            if val:
                tags += [t.strip() for t in val.split(",") if t.strip()]
        else:
            rest.append(a)
    return tags, rest


def parse_due(argv):
    due = ""
    rest = []
    for a in argv:
        if a.startswith("--due"):
            val = a.split("=", 1)[1] if "=" in a else None
            if val:
                due = val.strip()
        else:
            rest.append(a)
    return due, rest


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    args = sys.argv[2:]

    if cmd == "memory":
        sub = args[0] if args else ""
        if sub == "add":
            tags, rest = parse_tags(args[1:])
            content = " ".join(rest).strip()
            if not content:
                print("❌ 用法: memory add <内容> [--tag 标签1,标签2]")
                return
            memory_add(content, tags)
        elif sub == "list":
            memory_list("--all" in args)
        elif sub == "search":
            kw = " ".join(args[1:]).strip()
            memory_search(kw) if kw else print("❌ 用法: memory search <关键词>")
        elif sub == "get":
            memory_get(int(args[1])) if len(args) > 1 else print("❌ 用法: memory get <id>")
        elif sub == "archive":
            memory_archive(int(args[1])) if len(args) > 1 else print("❌ 用法: memory archive <id>")
        elif sub == "del":
            memory_del(int(args[1])) if len(args) > 1 else print("❌ 用法: memory del <id>")
        else:
            print(__doc__)

    elif cmd == "todo":
        sub = args[0] if args else ""
        if sub == "add":
            due, rest = parse_due(args[1:])
            task = " ".join(rest).strip()
            if not task:
                print("❌ 用法: todo add <任务> [--due YYYY-MM-DD]")
                return
            todo_add(task, due)
        elif sub == "done":
            todo_done(int(args[1])) if len(args) > 1 else print("❌ 用法: todo done <id>")
        elif sub == "undone":
            todo_undone(int(args[1])) if len(args) > 1 else print("❌ 用法: todo undone <id>")
        elif sub == "list":
            todo_list("--all" in args)
        elif sub == "check":
            kw = " ".join(args[1:]).strip()
            todo_check(kw) if kw else print("❌ 用法: todo check <关键词>")
        elif sub == "del":
            todo_del(int(args[1])) if len(args) > 1 else print("❌ 用法: todo del <id>")
        else:
            print(__doc__)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
