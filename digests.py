"""digests.py —— 更早对话的压缩摘要（2026-11-21 主人定的）

设计：
- 原文永远保留在 people/QQ<qq>.json 里，不删；
- 超过 24 小时的对话，按「人 × 日」压成一条 80-120 字摘要；
- 上下文里在「别人那边」之前挂最近 7 天摘要，让她能看到更早发生过什么；
- 摘要不覆盖原文，只是多一层「回忆」。
"""

import json
import os
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FILE = os.path.join(BASE_DIR, "digests.json")
MAX_DAYS_KEEP = 60
MAX_DAYS_SHOW = 7


def load():
    try:
        with open(FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save(d):
    try:
        with open(FILE, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def _summarize(name, day, lines):
    import llm

    system = (
        "你在帮一个女孩子整理她的记忆。下面是某一天她和一个人的聊天片段。"
        "请用一两句中文（80-120 字）概括这一天聊了什么。\n"
        "硬性要求：\n"
        "1. 只写聊天里**真实出现**的内容（谁说了什么、答应过什么、当时的情绪）；\n"
        "2. **不许推测、不许编造**——没提到的事一个字都不能写；\n"
        "3. 抓最具体的事：名字、事件、决定、约定；\n"
        "4. 不要写「可能」「似乎」「感觉」，不要客套。"
    )
    body = "\n".join(lines)
    prompt = f"日期：{day}\n对象：{name}\n聊天：\n{body[:6000]}"
    r = llm.chat_result(system, [{"role": "user", "text": prompt}], max_tokens=400)
    if r.is_err():
        return ""
    return str(r.unwrap()).strip()[:300]


def build_for_person(qq, name, msgs, min_age_hours=24):
    """把这个人 24h 前的消息按天压成摘要（已存在的日期跳过）。"""
    cutoff = time.time() - min_age_hours * 3600
    by_day = {}
    for m in msgs:
        at = (m.get("at") or 0) / 1000
        if not at or at > cutoff:
            continue
        day = time.strftime("%Y-%m-%d", time.localtime(at))
        by_day.setdefault(day, []).append(m)

    d = load()
    person = d.setdefault(str(qq), {})
    made = 0
    for day in sorted(by_day):
        if day in person:
            continue
        texts = []
        for m in by_day[day][-60:]:
            who = "她" if m.get("role") == "assistant" else (name or "对方")
            t = str(m.get("text") or "").strip()
            if t:
                texts.append(f"{who}：{t[:80]}")
        if not texts:
            continue
        s = _summarize(name or str(qq), day, texts)
        if s:
            person[day] = s
            made += 1
    # 裁剪太老的日期
    for qq_key in list(d.keys()):
        days = sorted(d[qq_key].keys())
        for old in days[:-MAX_DAYS_KEEP]:
            d[qq_key].pop(old, None)
    save(d)
    return made


def for_prompt(qq, days=MAX_DAYS_SHOW):
    """渲染某人最近几天的摘要（给她的上下文）。"""
    d = load()
    person = d.get(str(qq)) or {}
    if not person:
        return ""
    rows = sorted(person.items())[-days:]
    out = ["（这些是你跟他更早聊过的、收成摘要的回忆——原文还留着，想细看可以 search_history）"]
    for day, s in rows:
        out.append(f"- {day}：{s}")
    return "\n".join(out)


def stats():
    d = load()
    total = sum(len(v) for v in d.values())
    return {"people": len(d), "days": total}
