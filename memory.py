"""
memory.py —— 记忆：每个人的历史 + 全局时间线（2026-11-14 干净重写）

文件名固定 QQ<qq>.json，避免同一个人分裂成多个文件。
"""

import glob
import json
import os
import time

import config
from config import PEOPLE_DIR, OTHER_SESSION_RECENT


def ensure_dir():
    os.makedirs(PEOPLE_DIR, exist_ok=True)


def iter_people():
    """遍历所有联系人文件（只认 QQ<qq>.json，忽略旧的名字文件）。"""
    ensure_dir()
    self_id = str(getattr(config, "SELF_ID", "") or "")
    for p in sorted(glob.glob(os.path.join(PEOPLE_DIR, "QQ*.json"))):
        fn = os.path.basename(p)
        if not fn.startswith("QQ"):
            continue
        try:
            with open(p, "r", encoding="utf-8") as f:
                j = json.load(f)
        except Exception:
            continue
        if not isinstance(j, dict):
            continue
        if str(j.get("qq") or "") == self_id:
            continue
        yield p, j


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
        new_name = str(name or "").strip()
        if new_name and str(j.get("name") or "") != new_name:
            j["name"] = new_name
            try:
                with open(p, "w", encoding="utf-8") as f:
                    json.dump(j, f, ensure_ascii=False, indent=1)
            except Exception:
                pass
        return p, j
    ensure_dir()
    path = os.path.join(PEOPLE_DIR, f"QQ{qq}.json")
    data = {
        "name": str(name or "").strip() or qq,
        "qq": qq,
        "remark": "",
        "updatedAt": 0,
        "messages": [],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    return path, data


def append_global(role, name, qq, text, at=None, images=None):
    """全局时间线：她是一个人，按时间看所有会话。"""
    at = at or int(time.time() * 1000)
    path = os.path.join(PEOPLE_DIR, "_global.json")
    try:
        data = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {"items": []}
    except Exception:
        data = {"items": []}
    data.setdefault("items", []).append(
        {"role": role, "name": name, "qq": qq, "text": text or "", "at": at, "images": images or [], "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(at / 1000))}
    )
    data["items"] = data["items"][-400:]
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
    except Exception as e:
        print(f"[memory] global save fail: {e}")


def append(qq, role, text, images=None, message_id=None):
    """给某人的历史加一条，同时写全局时间线。"""
    p, data = ensure_person(qq)
    _now = time.time()
    msg = {
        "role": role,
        "text": text or "",
        "at": int(_now * 1000),
        "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(_now)),
    }
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
    append_global(role, data.get("name") or qq, qq, text, msg["at"], images)


def mark_recalled(message_id):
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


def clear_images(qq, message_id=""):
    """图片看完后清空 images（2026-11-14：不再重复加载原图，描述留在回复里）。

    message_id 为空时清该人所有图片引用。
    """
    mid = str(message_id or "")
    p, data = find_person(qq)
    if not data:
        return
    changed = False
    for m in data.get("messages") or []:
        if mid and str(m.get("messageId") or "") != mid:
            continue
        if m.get("images"):
            m["images"] = []
            changed = True
    if changed:
        try:
            with open(p, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
        except Exception:
            pass


def first(qq, n=12):
    """最早的几条（2026-11-14：auto_recall 用）。"""
    p, data = find_person(qq)
    if not data:
        return []
    return (data.get("messages") or [])[:n]


def recent(qq, n=60):
    p, data = find_person(qq)
    if not data:
        return []
    return (data.get("messages") or [])[-n:]


def recall(qq, keyword, limit=12):
    p, data = find_person(qq)
    if not data:
        return []
    kw = str(keyword or "").strip()
    hits = []
    for m in reversed(data.get("messages") or []):
        t = str(m.get("text") or "")
        if kw and kw not in t:
            continue
        hits.append(m)
        if len(hits) >= limit:
            break
    hits.reverse()
    return hits


def all_recent(exclude_qq, per_person=None, total=None):
    """别的会话最近在说什么（2026-11-15：3 天内活跃 150 条/人，更早 50 条/人）。"""
    try:
        from config import OTHER_SESSION_ACTIVE, OTHER_SESSION_IDLE
    except Exception:
        OTHER_SESSION_ACTIVE, OTHER_SESSION_IDLE = 150, 50
    now = time.time()
    lines = []
    for p, j in iter_people():
        qq = str(j.get("qq"))
        if qq == str(exclude_qq):
            continue
        msgs = j.get("messages") or []
        if not msgs:
            continue
        last = (msgs[-1].get("at") or 0) / 1000
        active = now - last <= 3 * 86400
        n = per_person or (OTHER_SESSION_ACTIVE if active else OTHER_SESSION_IDLE)
        name = j.get("name") or qq
        remark = str(j.get("remark") or "").strip() or "none"
        lines.append(f"【{name}（QQ {qq}，你叫她：{remark}）{'最近聊过' if active else '很久没聊'}】")
        for m in msgs[-n:]:
            t = time.strftime("%Y-%m-%d %H:%M", time.localtime((m.get("at") or 0) / 1000))
            who = "你" if m.get("role") == "assistant" else "对方"
            lines.append(f"- {t} {who}：{str(m.get('text') or '')[:80]}")
    return "\n".join(lines)


