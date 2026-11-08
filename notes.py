"""
notes.py —— 她的私人记事本（2026-11-08 主人要求）

- 纯本地文件 notes.json，跟 QQ/腾讯完全无关（不发送、不上传、不交互）；
- 她觉得重要的事可以自己写进来（回复里用 <note>内容</note>）；
- 每轮 system prompt 带最近几条，让她记得自己写过什么。
"""

import json
import os
import time

from config import BASE_DIR

NOTES_FILE = os.path.join(BASE_DIR, "notes.json")
MAX_NOTES = 500


def load():
    try:
        with open(NOTES_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("notes"), list):
            return data
    except Exception:
        pass
    return {"notes": []}


def save(data):
    try:
        with open(NOTES_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except Exception as e:
        print(f"[notes] save fail: {e}")


def add(text, cat=""):
    t = str(text or "").strip()
    if not t:
        return None
    data = load()
    item = {"at": int(time.time() * 1000), "text": t[:500], "cat": str(cat or "")[:20]}
    data["notes"].append(item)
    if len(data["notes"]) > MAX_NOTES:
        data["notes"] = data["notes"][-MAX_NOTES:]
    save(data)
    return item


def recent(limit=20):
    return load().get("notes", [])[-limit:]


def search(keyword, limit=10):
    kw = str(keyword or "").strip()
    if not kw:
        return []
    out = []
    for n in reversed(load().get("notes", [])):
        if kw in str(n.get("text") or ""):
            out.append(n)
            if len(out) >= limit:
                break
    return list(reversed(out))


def for_prompt():
    """给 system prompt 的记事本内容：全文，不截取（2026-11-08 主人要求）。"""
    items = load().get("notes", [])
    if not items:
        return "（记事本还是空的）"
    lines = []
    for n in items:
        t = time.strftime("%m-%d %H:%M", time.localtime((n.get("at") or 0) / 1000))
        cat = f"【{n['cat']}】" if n.get("cat") else ""
        lines.append(f"- [{t}] {cat}{n.get('text') or ''}")
    return "\n".join(lines)
