"""short_notes.py —— 短期备忘（承诺/约定/要做的事，5 天有效）

和长期记事本（notes.py）的区别（2026-11-21 主人定的）：
- 长期：心情、感受、想法、对自己的认识 → write_note，永久
- 短期：答应别人的事、约定、要办的事 → write_short_note，5 天后自动消失
"""

import json
import os
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FILE = os.path.join(BASE_DIR, "short_notes.jsonl")
KEEP_DAYS = 5
MAX_LINES = 200


def add(text, category=""):
    t = str(text or "").strip()
    if not t:
        return None
    item = {
        "at": int(time.time() * 1000),
        "time": time.strftime("%Y-%m-%d %H:%M"),
        "text": t[:300],
        "cat": str(category or "")[:20],
    }
    try:
        with open(FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    except Exception:
        return None
    _trim()
    return item


def load(only_valid=True):
    items = []
    try:
        with open(FILE, encoding="utf-8") as f:
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
    if only_valid:
        cutoff = time.time() - KEEP_DAYS * 86400
        items = [i for i in items if (i.get("at") or 0) / 1000 >= cutoff]
    return items


def _trim():
    items = load(only_valid=False)[-MAX_LINES:]
    try:
        with open(FILE, "w", encoding="utf-8") as f:
            for i in items:
                f.write(json.dumps(i, ensure_ascii=False) + "\n")
    except Exception:
        pass


def for_prompt():
    items = load()
    if not items:
        return ""
    lines = [
        f"（短期备忘：只有 {KEEP_DAYS} 天有效，过期的会自动消失——"
        "这里记「答应别人的事、约定、要办的事」；心情和感受请写进下面长期那个记事本。）"
    ]
    for it in items:
        t = it.get("time") or ""
        cat = f"【{it['cat']}】" if it.get("cat") else ""
        lines.append(f"- [{t}] {cat}{it.get('text')}")
    return "\n".join(lines)


def days_left(item):
    at = (item.get("at") or 0) / 1000
    left = KEEP_DAYS - (time.time() - at) / 86400
    return max(0.0, left)
