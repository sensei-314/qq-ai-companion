"""
actions.py —— 她的终端操作日志（2026-11-08 主人要求）

记录她在「卧室」里做的事：搜索、记事、翻记录、戳人、发消息、定闹钟……
最近 10 条会进 system prompt（带时间），更早的可以按关键词查。
"""

import json
import os
import time

from config import BASE_DIR

ACTIONS_FILE = os.path.join(BASE_DIR, "actions.jsonl")
MAX_RECENT = 10


def log_action(kind, detail):
    """记录一次操作（追加到 actions.jsonl）。"""
    item = {
        "at": int(time.time() * 1000),
        "kind": str(kind or ""),
        "detail": str(detail or "")[:300],
    }
    try:
        with open(ACTIONS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"[actions] save fail: {e}")
    return item


def load_all():
    out = []
    try:
        with open(ACTIONS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
    except FileNotFoundError:
        pass
    return out


def recent(limit=MAX_RECENT):
    return load_all()[-limit:]


def search(keyword, limit=20):
    kw = str(keyword or "").strip()
    if not kw:
        return recent(limit)
    out = []
    for a in reversed(load_all()):
        if kw in str(a.get("detail") or "") or kw in str(a.get("kind") or ""):
            out.append(a)
            if len(out) >= limit:
                break
    return list(reversed(out))


def for_prompt(limit=MAX_RECENT):
    """给 system prompt 的最近操作（带时间）。"""
    items = recent(limit)
    if not items:
        return "（你最近没做什么特别的事）"
    lines = []
    for a in items:
        t = time.strftime("%m-%d %H:%M", time.localtime((a.get("at") or 0) / 1000))
        lines.append(f"- [{t}] {a.get('kind') or ''}：{a.get('detail') or ''}")
    return "\n".join(lines)
