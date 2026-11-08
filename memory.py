"""
memory.py —— 记忆（people/*.json）

规则（对齐 DSH 插件）：
  - 一人一个文件，按 QQ 匹配（文件名叫备注/昵称，不靠文件名找）；
  - 联系人就算没聊过也要有文件（sync_contacts 建）；
  - 每条消息带 at 时间戳；
  - 别的会话最近 N 条也能读（跨会话上下文）。
"""

import json
import os
import time

from config import PEOPLE_DIR, OTHER_SESSION_RECENT

GLOBAL_FILE = os.path.join(PEOPLE_DIR, "_global.json")
GLOBAL_LIMIT = 200


def _load_global():
    try:
        with open(GLOBAL_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"messages": []}


def _save_global(data):
    try:
        with open(GLOBAL_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except Exception as e:
        print(f"[memory] global save fail: {e}")


def append_global(role, name, qq, text, at=None, images=None):
    """全局时间线（2026-11-07 主人：「她只是一个人，像在用 QQ」）。

    所有会话的消息按时间进同一条线：role=user（谁说的）/ assistant（她说的，
    记发给谁）。她回答时看的是这条线，而不是某个人的单独历史。
    """
    at = at or int(time.time() * 1000)
    data = _load_global()
    item = {"role": role, "name": str(name or qq), "qq": str(qq or ""), "text": str(text or ""), "at": at}
    if images:
        item["images"] = list(images)
    data.setdefault("messages", []).append(item)
    data["messages"] = data["messages"][-GLOBAL_LIMIT:]
    _save_global(data)
    return item


def recent_global(limit=50):
    return _load_global().get("messages", [])[-limit:]


def sanitize_name(name):
    for ch in '\\/:*?"<>|\r\n\t':
        name = str(name or "").replace(ch, "_")
    return name.strip()[:40]


def ensure_dir():
    os.makedirs(PEOPLE_DIR, exist_ok=True)


def iter_people():
    ensure_dir()
    for fn in os.listdir(PEOPLE_DIR):
        if not fn.endswith(".json"):
            continue
        p = os.path.join(PEOPLE_DIR, fn)
        try:
            with open(p, "r", encoding="utf-8") as f:
                j = json.load(f)
            if isinstance(j, dict):
                yield p, j
        except Exception:
            continue


def find_person(qq):
    qq = str(qq)
    for p, j in iter_people():
        if str(j.get("qq")) == qq:
            return p, j
    return None, None


def ensure_person(qq, name=""):
    qq = str(qq)
    p, j = find_person(qq)
    if p:
        # 名字（备注/昵称）变了就更新，让她看到最新名字（2026-11-08）
        new_name = sanitize_name(name)
        if new_name and str(j.get("name") or "") != new_name:
            j["name"] = new_name
            try:
                with open(p, "w", encoding="utf-8") as f:
                    json.dump(j, f, ensure_ascii=False, indent=1)
            except Exception:
                pass
        return p, j
    ensure_dir()
    base = sanitize_name(name) or f"QQ{qq}"
    path = os.path.join(PEOPLE_DIR, f"{base}.json")
    if os.path.exists(path):
        base = f"{base}_{qq[-4:]}"
        path = os.path.join(PEOPLE_DIR, f"{base}.json")
    data = {"name": base, "qq": qq, "updatedAt": 0, "messages": []}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    return path, data


def append(qq, role, text, images=None, message_id=None):
    """给某人的历史加一条（图片存 URL 列表），同时写全局时间线。"""
    p, data = ensure_person(qq)
    msg = {"role": role, "text": text or "", "at": int(time.time() * 1000)}
    if images:
        msg["images"] = images
    if message_id:
        msg["messageId"] = str(message_id)
    data.setdefault("messages", []).append(msg)
    data["updatedAt"] = msg["at"]
    try:
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except Exception as e:
        print(f"[memory] save fail: {e}")
    # 全局时间线（她"一个人"的视角）
    append_global(role, data.get("name") or qq, qq, text, msg["at"], images)


def mark_recalled(message_id):
    """对方撤回：在原消息后面加标记（2026-11-08 主人要求）。"""
    mid = str(message_id or "")
    if not mid:
        return False
    for p, data in iter_people():
        changed = False
        for m in data.get("messages") or []:
            if str(m.get("messageId") or "") == mid and not m.get("recalled"):
                m["recalled"] = True
                m["text"] = str(m.get("text") or "") + "（原消息已被撤回）"
                changed = True
        if changed:
            try:
                with open(p, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=1)
            except Exception:
                pass
            return True
    return False


def recent(qq, limit):
    _, data = find_person(qq)
    if not data:
        return []
    return (data.get("messages") or [])[-limit:]


def all_recent(exclude_qq, per_person=OTHER_SESSION_RECENT):
    """别的会话最近在说什么（给 system prompt 用）。"""
    lines = []
    for p, j in iter_people():
        qq = str(j.get("qq"))
        if qq == str(exclude_qq):
            continue
        msgs = (j.get("messages") or [])[-per_person:]
        if not msgs:
            continue
        name = j.get("name") or qq
        lines.append(f"【{name}】")
        for m in msgs:
            t = time.strftime("%H:%M", time.localtime((m.get("at") or 0) / 1000))
            who = "你" if m.get("role") == "assistant" else "对方"
            lines.append(f"- {t} {who}：{str(m.get('text') or '')[:80]}")
    return "\n".join(lines)


def recall(qq, keyword, limit=12):
    """关键词检索更早的记录（她想往前翻时用）。"""
    _, data = find_person(qq)
    if not data:
        return []
    kw = str(keyword or "").strip()
    out = []
    for m in reversed(data.get("messages") or []):
        if kw and kw not in str(m.get("text") or ""):
            continue
        out.append(m)
        if len(out) >= limit:
            break
    return list(reversed(out))


def first(qq, limit=10):
    """最早的 N 条（2026-11-08：问「刚加好友时说了什么」用）。"""
    _, data = find_person(qq)
    if not data:
        return []
    return (data.get("messages") or [])[:limit]
