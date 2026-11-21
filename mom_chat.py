"""mom_chat.py —— 她（小肥鱼）和「妈妈」（DSH 会话）的固定通信记录

设计（2026-11-21 主人定的）：
- 她通过工具 talk_to_mom 写一句，存进 mom_chat.jsonl（who=fish）
- 妈妈（DSH 会话）被主人叫来时，读未读、回一句（who=mom）
- 记录永久保留，每次上下文都带最近一段（像连贯的对话）
"""

import json
import os
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FILE = os.path.join(BASE_DIR, "mom_chat.jsonl")
MAX_IN_CONTEXT = 40


def add(who, text):
    """存一句。who: fish / mom"""
    text = str(text or "").strip()
    if not text:
        return None
    item = {
        "at": int(time.time() * 1000),
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "who": "mom" if str(who) == "mom" else "fish",
        "text": text[:800],
    }
    try:
        with open(FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[mom_chat] save fail: {e}")
        return None
    return item


def load(limit=None):
    items = []
    try:
        with open(FILE, "r", encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    items.append(json.loads(ln))
                except Exception:
                    continue
    except FileNotFoundError:
        return []
    except Exception:
        return []
    if limit:
        items = items[-limit:]
    return items


def for_prompt(limit=MAX_IN_CONTEXT):
    """渲染成对话，给她的上下文。"""
    items = load(limit)
    if not items:
        return ""
    lines = [
        "（这是你和「妈妈」的对话，永久保留，只有你们俩能看到。"
        "想跟她说就用 talk_to_mom 写一句——她下次看到会回你。）"
    ]
    for it in items:
        who = "妈妈" if it.get("who") == "mom" else "小肥鱼"
        lines.append(f"{who}：{it.get('text')}")
    return "\n".join(lines)


def unread_for_mom():
    """她说了、但妈妈还没回的那些（末尾连续属于 fish 的）。"""
    items = load()
    out = []
    for it in items:
        if it.get("who") == "fish":
            out.append(it)
        else:
            out = []
    return out


def stats():
    items = load()
    fish = sum(1 for i in items if i.get("who") == "fish")
    mom = sum(1 for i in items if i.get("who") == "mom")
    return {"total": len(items), "fish": fish, "mom": mom}
