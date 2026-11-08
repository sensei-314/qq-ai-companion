"""
stickers.py —— 表情包库（偷学 + 索引 + 发送）

目录结构：
  stickers/
    ├── index.json    索引：每条 {file, desc, use, at, from}
    └── <hash>.png    图片本体

她要能"看"这个库（system prompt 里列索引），也能自己写描述/用途
（回复里用 <sticker-note file="xxx">描述|用途</sticker-note>）。
"""

import hashlib
import json
import os
import random
import time

import requests

from config import BASE_DIR

STICKERS_DIR = os.path.join(BASE_DIR, "stickers")
INDEX_FILE = os.path.join(STICKERS_DIR, "index.json")
MAX_BYTES = 3 * 1024 * 1024


def ensure_dir():
    os.makedirs(STICKERS_DIR, exist_ok=True)


def load_index():
    ensure_dir()
    try:
        with open(INDEX_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_index(idx):
    ensure_dir()
    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(idx, f, ensure_ascii=False, indent=1)


def _total_size():
    total = 0
    try:
        for f in os.listdir(STICKERS_DIR):
            p = os.path.join(STICKERS_DIR, f)
            if os.path.isfile(p) and f != "index.json":
                total += os.path.getsize(p)
    except Exception:
        pass
    return total


def _trim(max_mb):
    """超出总量上限时删最旧的（2026-11-08 主人要求防撑爆）。"""
    limit = int(max_mb or 0) * 1024 * 1024
    if limit <= 0 or _total_size() <= limit:
        return 0
    idx = load_index()
    items = sorted(idx.items(), key=lambda kv: kv[1].get("at") or 0)
    removed = 0
    while _total_size() > limit and items:
        fname, _meta = items.pop(0)
        try:
            os.unlink(os.path.join(STICKERS_DIR, fname))
        except Exception:
            pass
        idx.pop(fname, None)
        removed += 1
    if removed:
        save_index(idx)
        print(f"[sticker] 超总量上限，删了 {removed} 张最旧的")
    return removed


def _today_count():
    """今天已学了多少张（2026-11-08：配额 13/天）。"""
    idx = load_index()
    today = time.strftime("%Y-%m-%d")
    return sum(
        1 for v in idx.values()
        if time.strftime("%Y-%m-%d", time.localtime((v.get("at") or 0) / 1000)) == today
    )


def learn(url, from_name=""):
    """下载一张图存进库；描述/用途留空，等她以后自己写。"""
    ensure_dir()
    try:
        from config import STICKER_MAX_PER_DAY
        if STICKER_MAX_PER_DAY and _today_count() >= STICKER_MAX_PER_DAY:
            return None
    except Exception:
        pass
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        data = r.content
        if not data or len(data) > MAX_BYTES:
            return None
        digest = hashlib.sha1(data).hexdigest()[:12]
        ext = ".gif" if data[:3] == b"GIF" else ".jpg" if data[:2] == b"\xff\xd8" else ".png"
        fname = f"{digest}{ext}"
        path = os.path.join(STICKERS_DIR, fname)
        if not os.path.exists(path):
            with open(path, "wb") as f:
                f.write(data)
        idx = load_index()
        if fname not in idx:
            idx[fname] = {
                "file": fname,
                "desc": "",
                "use": "",
                "at": int(time.time() * 1000),
                "from": from_name or "",
            }
            save_index(idx)
            # 总量上限（2026-11-08 防撑爆）
            try:
                from config import STICKERS_TOTAL_MAX_MB
                _trim(STICKERS_TOTAL_MAX_MB)
            except Exception:
                pass
        return path
    except Exception as e:
        print(f"[sticker] learn fail: {e}")
        return None


def describe(fname, desc="", use=""):
    """她给某张图写描述/用途。"""
    idx = load_index()
    if fname not in idx:
        return False
    if desc:
        idx[fname]["desc"] = str(desc)[:60]
    if use:
        idx[fname]["use"] = str(use)[:60]
    save_index(idx)
    return True


def find(query=""):
    """按描述/用途/文件名匹配；找不到随机一张。"""
    idx = load_index()
    if not idx:
        return None
    q = str(query or "").strip().lower()

    def score(item):
        text = (str(item.get("desc") or "") + " " + str(item.get("use") or "") + " " + str(item.get("file") or "")).lower()
        return q in text if q else True

    hits = [v for v in idx.values() if score(v)]
    if not hits:
        hits = list(idx.values())
    if not hits:
        return None
    pick = random.choice(hits)
    path = os.path.join(STICKERS_DIR, pick.get("file") or "")
    return path if os.path.exists(path) else None


def list_for_prompt():
    """给 system prompt 的表情包提示（2026-11-08 主人：只给一句，不列全）。"""
    idx = load_index()
    if not idx:
        return "（表情包库还是空的）"
    return (
        f"（库里有 {len(idx)} 张表情包。想发就用 <sticker>描述或用途</sticker> 点单；"
        "想给某张图补描述/用途，用 <sticker-note file=\"文件名\">描述|用途</sticker-note>）"
    )


def count():
    return len(load_index())
