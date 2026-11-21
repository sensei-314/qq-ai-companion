"""system_events.py —— 系统记录（只读，给她看，不可篡改）

记录：睡觉 / 醒来 / 停服 / 启动 / 重要操作摘要
不进 her 可写区域；她只能看。
"""

import json
import os
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FILE = os.path.join(BASE_DIR, "system_events.jsonl")
MAX_LINES = 300


def add(kind, detail=""):
    ensure_dir()
    item = {
        "at": int(time.time() * 1000),
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "kind": str(kind or ""),
        "detail": str(detail or "")[:120],
    }
    try:
        with open(FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    except Exception:
        pass
    # 裁剪：超过 48 小时直接删（2026-11-19 主人）
    try:
        _trim_old()
    except Exception:
        pass
    return item


def ensure_dir():
    os.makedirs(BASE_DIR, exist_ok=True)


HOURS_KEEP = 48  # 只保留近 48 小时（2026-11-19 主人）


def recent(n=12):
    ensure_dir()
    try:
        lines = open(FILE, encoding="utf-8").readlines()[-n:]
    except Exception:
        return []
    cutoff = time.time() - HOURS_KEEP * 3600
    out = []
    for ln in lines:
        try:
            it = json.loads(ln)
        except Exception:
            continue
        if (it.get("at") or 0) / 1000 >= cutoff:
            out.append(it)
    return out


def _trim_old():
    """把超过 48 小时的记录删掉（不存）。"""
    ensure_dir()
    cutoff = time.time() - HOURS_KEEP * 3600
    kept = []
    try:
        for ln in open(FILE, encoding="utf-8").readlines():
            try:
                it = json.loads(ln)
            except Exception:
                continue
            if (it.get("at") or 0) / 1000 >= cutoff:
                kept.append(ln if ln.endswith("\n") else ln + "\n")
    except Exception:
        return
    try:
        with open(FILE, "w", encoding="utf-8") as f:
            f.writelines(kept)
    except Exception:
        pass


def for_prompt(n=12):
    """给她看的系统记录（只读，不可篡改）。"""
    items = recent(n)
    if not items:
        return "（还没有系统记录）"
    lines = []
    for it in items:
        t = it.get("time") or time.strftime(
            "%Y-%m-%d %H:%M:%S", time.localtime((it.get("at") or 0) / 1000)
        )
        kind = it.get("kind") or ""
        detail = it.get("detail") or ""
        lines.append(f"- [{t}] {kind}" + (f"：{detail}" if detail else ""))
    return "（系统自动记录，你只能看不能改）\n" + "\n".join(lines)
