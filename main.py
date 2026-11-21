"""
main.py —— 组装：事件 → 权限 → 记忆 → 模型 → 拟人发送；主动消息循环。

细节：
  - debounce：同一个人短时间内连发多条，合并成一轮回复；
  - 起床气：睡觉时段被吵醒，语气差；
  - 撤回：记事件；
  - 表情包：偷学 + 发送（防连发同一张）；
  - 逐条确认：发完一条问她要不要补。
"""

import os
import queue
import random
import re
import threading
import time
from datetime import datetime

import json
import config
import actions
import file_reader
import memory
import digests
import mom_chat
import notes
import short_notes
import system_events
import search
import stickers
import llm
import tools

LETTER_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "主人赠言.txt")
MANUAL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "操作手册.md")


IMG_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "img_cache")
CHAT_ONLY_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chat_only.jsonl")


def cache_image(url):
    """收到图片立即下载缓存；按文件头判断 GIF/PNG（2026-11-14）。"""
    if not url or str(url).startswith("cache:"):
        return url
    if any(x in str(url).lower() for x in (".mp4", ".mov", ".mkv", ".webm")):
        return url
    try:
        os.makedirs(IMG_CACHE_DIR, exist_ok=True)
        import hashlib
        import html as _html
        import requests as _rq
        # URL 可能带 HTML 转义（&amp;），解码后再下载（2026-11-14）
        url = _html.unescape(str(url))
        h = hashlib.sha1(str(url).encode()).hexdigest()[:12]
        low = str(url).lower()
        ext = ".gif" if ".gif" in low else ".png" if ".png" in low else ".jpg"
        # NapCat：拿到的可能只是文件名（无 URL）→ 用 get_image 换 base64
        if not str(url).startswith("http"):
            try:
                import config as _cfg
                base = (
                    os.environ.get("MOLLY_ONEBOT_HTTP")
                    or getattr(_cfg, "ONEBOT_HTTP", "http://127.0.0.1:3000/")
                )
                token = os.environ.get("MOLLY_ONEBOT_HTTP_TOKEN") or getattr(
                    _cfg, "ONEBOT_HTTP_TOKEN", ""
                )
                resp = _rq.post(
                    base.rstrip("/") + "/get_image",
                    json={"file": url},
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=15,
                )
                j = resp.json() or {}
                b64 = str(((j.get("data") or {}).get("file")) or "")
                if b64.startswith("base64://"):
                    b64 = b64[len("base64://"):]
                if b64:
                    import base64 as _b64
                    data = _b64.b64decode(b64)
                    if data[:6] in (b"GIF87a", b"GIF89a"):
                        ext = ".gif"
                    elif data[:8] == b"\x89PNG\r\n\x1a\n":
                        ext = ".png"
                    path = os.path.join(IMG_CACHE_DIR, f"{h}{ext}")
                    with open(path, "wb") as f:
                        f.write(data)
                    return f"cache:{path}"
            except Exception as e:
                log(f"[img] get_image 失败：{e}")
            return url
        path = os.path.join(IMG_CACHE_DIR, f"{h}{ext}")
        if not os.path.exists(path):
            r = _rq.get(
                url,
                timeout=15,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
                    ),
                    "Referer": "https://qzone.qq.com/",
                },
            )
            r.raise_for_status()
            data = r.content
            # 按文件头判断真实格式
            if data[:6] in (b"GIF87a", b"GIF89a"):
                ext = ".gif"
            elif data[:8] == b"\x89PNG\r\n\x1a\n":
                ext = ".png"
            elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
                ext = ".webp"
            path = os.path.join(IMG_CACHE_DIR, f"{h}{ext}")
            with open(path, "wb") as f:
                f.write(data)
        return f"cache:{path}"
    except Exception as e:
        log(f"[img] 缓存失败：{e}")
        return url


def cleanup_img_cache(max_age_seconds=180):
    """用完就删（2026-11-13 主人要求）。"""
    try:
        now = time.time()
        for f in os.listdir(IMG_CACHE_DIR):
            p = os.path.join(IMG_CACHE_DIR, f)
            if os.path.isfile(p) and now - os.path.getmtime(p) > max_age_seconds:
                try:
                    os.unlink(p)
                except Exception:
                    pass
    except Exception:
        pass


def load_letter():
    """主人留给她的信：每次会话前放最前面让她读（2026-11-08 主人要求）。"""
    try:
        with open(LETTER_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def load_manual():
    """她的操作手册（怎么用 <note>/<search>/<sticker>/<send> 等）。"""
    try:
        with open(MANUAL_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""
from aliveness import (
    reaction_delay,
    typing_delay,
    split_bubbles,
    bubble_gap,
    in_sleep,
    in_school_time,
)
from llm import chat
from context import ContextBuilder
from onebot import OneBot
from persona import build_system

EVENTS = []
LAST_PROACTIVE = [0.0]
LOCK = threading.Lock()
LAST_STICKERS = []
PENDING = {}
TIMERS = {}
LAST_REPLY_AT = {}
SEND_LOG = []
LAST_SENT = {}   # 每个会话最近发出去的消息 id（撤回用）
LAST_AFTERTALK = [0.0]   # 上次「聊完自由发言」的时间（2026-11-08）
AFTERTALK_COOLDOWN = 1800  # 30 分钟内最多一次
DEBOUNCE_SECONDS = config.DEBOUNCE_SECONDS
REPLY_COOLDOWN = config.REPLY_COOLDOWN_SECONDS

# ==================== 事件队列（2026-11-08 架构重构）====================
# 一次只处理一个事件：多人同时发消息时排队，避免并发把上下文搅乱。
EVENT_QUEUE = queue.Queue()
GROUP_LAST = {}  # 她最近一次在群里发言的时间（2026-11-15）
GROUP_ACTIVE_WINDOW = 600  # 她发过言后 10 分钟内算「正在聊」（2026-11-21）
GROUP_SCAN_EVERY = 5400  # 冷场时 1.5 小时扫一次群（2026-11-21）
LAST_SENT_TEXTS = []  # 她最近说过的话（跨会话去重，2026-11-18）
GROUP_SENT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "group_sent.json")
GROUP_WATCH = {}  # 群观察定时器（2026-11-15）


def enqueue(kind, payload=None):
    EVENT_QUEUE.put({"kind": kind, "payload": payload or {}, "at": time.time()})
    log(f"[queue] +{kind}（队列 {EVENT_QUEUE.qsize()}）")


def think(bot, event):
    """统一思考入口（2026-11-08 架构合并）。

    所有事件（消息 / 机会 / 闹钟 / 聊完自由发言）都从这里进，一次只处理一个。
    她每次「想事情」的方式一致：看事件 → 组装上下文 → 决定动作。
    """
    kind = event.get("kind")
    payload = event.get("payload") or {}
    log(f"[think] 处理事件：{kind}")
    if kind == "message":
        return handle_message_event(bot, payload)
    if kind == "opportunity":
        return handle_opportunity_event(bot)
    if kind == "reminder":
        return handle_reminder_event(bot, payload)
    if kind == "sleep_ask":
        return handle_sleep_ask(bot, payload)
    if kind == "group_watch":
        return handle_group_watch_event(bot, payload)
    if kind == "aftertalk":
        return handle_aftertalk_event(bot, payload)


def worker_loop(bot):
    """主循环：串行消费事件（卧室里的她一次只面对一件事）。"""
    while True:
        evt = EVENT_QUEUE.get()
        kind = evt.get("kind")
        try:
            think(bot, evt)
        except Exception as e:
            log(f"[worker] {kind} 出错：{e}")
        finally:
            EVENT_QUEUE.task_done()


def parse_timers(reply):
    """解析她给自己定的闹钟 <timer minutes="2">到点要做的事</timer>（2026-11-08）。"""
    timers = []

    def take(m):
        try:
            minutes = float(m.group(1))
        except Exception:
            return ""
        note = str(m.group(2) or "").strip()
        if note:
            timers.append((minutes, note))
        return ""

    reply = re.sub(
        r'<timer\s+minutes=["\']?([\d.]+)["\']?\s*>([\s\S]*?)</timer>', take, reply, flags=re.I
    )
    return reply, timers


def schedule_reminder(minutes, note):
    """到点投递 reminder 事件（她可以决定那时候做什么）。"""
    delay = max(5.0, float(minutes) * 60)
    def fire():
        enqueue("reminder", {"note": note})
    t = threading.Timer(delay, fire)
    t.daemon = True
    t.start()
    log(f"[timer] {minutes:g} 分钟后提醒自己：{note[:40]}")
    actions.log_action("定时", f"{minutes:g} 分钟后：{note[:60]}")


PROACTIVE_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "proactive.json")


def murmur_opportunity(bot, conv):
    """她选择了不回 → 给一次「呢喃」的机会（她可以嘀咕一句，也可以不说）。"""
    try:
        system = build_system(now_text(), events=EVENTS)
        prompt = (
            "（你刚决定不接这句话。有没有什么想自己嘀咕一句的？"
            "想说就写一句，不想说就回「算了」。）"
        )
        _r = llm.chat_result(system, [{"role": "user", "text": prompt}])
        if _r.is_err():
            return
        reply = _r.unwrap()
        t = str(reply).strip()
        if not t or "算了" in t[:8] or len(t) > 120:
            return
        murmur(t, "跳过")
    except Exception as e:
        log(f"[murmur] {e}")


def _similar(a, b):
    """粗略判断两句话是否重复（2026-11-18）。"""
    ka = set(re.findall(r"[\u4e00-\u9fa5A-Za-z0-9]{2,}", str(a)))
    kb = set(re.findall(r"[\u4e00-\u9fa5A-Za-z0-9]{2,}", str(b)))
    if not ka or not kb:
        return False
    return len(ka & kb) / max(1, min(len(ka), len(kb))) >= 0.8


def murmur(text, why="空档"):
    """记一条「呢喃」：她想了但没说/没做的（不进上下文，给主人看）。"""
    text = str(text or "").strip()
    if not text:
        return
    try:
        import json as _json

        with open(CHAT_ONLY_LOG, "a", encoding="utf-8") as _cf:
            _cf.write(
                _json.dumps(
                    {"at": int(time.time() * 1000), "why": str(why), "text": text},
                    ensure_ascii=False,
                )
                + "\n"
            )
    except Exception:
        pass


QZONE_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "qzone_times.json")


def _qzone_load():
    try:
        d = json.load(open(QZONE_LOG, encoding="utf-8"))
        return [t for t in d.get("times") or [] if time.time() - t < 86400]
    except Exception:
        return []


def qzone_allowed(limit=2, window=86400):
    """24 小时内最多发 limit 条说说（持久化，重启不清，2026-11-15）。"""
    return len(_qzone_load()) < limit


def qzone_record():
    times = _qzone_load() + [time.time()]
    try:
        with open(QZONE_LOG, "w", encoding="utf-8") as f:
            json.dump({"times": times}, f)
    except Exception:
        pass


COMMENT_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "comment_times.json")


def _comment_load():
    try:
        return json.load(open(COMMENT_LOG, encoding="utf-8"))
    except Exception:
        return {}


def comment_allowed(tid, cooldown=86400):
    """同一条动态 24h 内最多评论 1 次；不同动态不限（2026-11-15）。"""
    d = _comment_load()
    last = float(d.get(str(tid)) or 0)
    return time.time() - last >= cooldown


def comment_record(tid):
    d = _comment_load()
    d[str(tid)] = time.time()
    try:
        with open(COMMENT_LOG, "w", encoding="utf-8") as f:
            json.dump(d, f)
    except Exception:
        pass


def proactive_allowed(qq, limit=3, cooldown=3600):
    """同一个人：24h 最多 3 次，且距上次主动至少 1 小时（2026-11-15）。"""
    try:
        d = json.load(open(PROACTIVE_LOG, encoding="utf-8")) if os.path.exists(PROACTIVE_LOG) else {}
    except Exception:
        d = {}
    now = time.time()
    times = [t for t in d.get(str(qq), []) if now - t < 86400]
    if times and now - max(times) < cooldown:
        return False  # 刚找过，别追
    return len(times) < limit


def _group_sent_load():
    try:
        return json.load(open(GROUP_SENT_FILE, encoding="utf-8"))
    except Exception:
        return {}


def group_speak_allowed(gid, content):
    """群里同一句话只说一次（持久化，重启不清，2026-11-21）。"""
    c = str(content or "").strip()[:60]
    if not c:
        return False
    d = _group_sent_load()
    recent = d.get(str(gid)) or []
    for old in recent:
        if old == c or (len(c) > 6 and (c in old or old in c) and (old in c or c in old)):
            return False
    recent.append(c)
    d[str(gid)] = recent[-40:]
    try:
        with open(GROUP_SENT_FILE, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
    except Exception:
        pass
    return True


def group_allowed(gid, cooldown=20):
    """同一个群 5 分钟内最多主动说一次（2026-11-15）。"""
    with LOCK:
        last = GROUP_LAST.get(str(gid), 0)
        return time.time() - last >= cooldown


def group_record(gid):
    with LOCK:
        GROUP_LAST[str(gid)] = time.time()


def proactive_record(qq):
    try:
        d = json.load(open(PROACTIVE_LOG, encoding="utf-8")) if os.path.exists(PROACTIVE_LOG) else {}
    except Exception:
        d = {}
    now = time.time()
    d[str(qq)] = [t for t in d.get(str(qq), []) if now - t < 86400] + [now]
    try:
        with open(PROACTIVE_LOG, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
    except Exception:
        pass


def agent_loop(bot, system, msgs, conv, user_id):
    """带工具的主循环（2026-11-13 大改）：模型可调用工具，最多 3 轮，返回最终文本。"""
    last_sent = list(LAST_SENT.get(conv.get("id")) or [])
    ctx = {
        "bot": bot,
        "conv": conv,
        "user_id": user_id,
        "can_send": can_send,
        "proactive_ok": proactive_allowed,
        "proactive_record": proactive_record,
        "group_ok": group_allowed,
        "group_record": group_record,
        "group_speak_ok": group_speak_allowed,
        "qzone_ok": qzone_allowed,
        "qzone_record": qzone_record,
        "comment_ok": comment_allowed,
        "comment_record": comment_record,
        "schedule_reminder": schedule_reminder,
        "last_sent": last_sent,
        "must_reply": bool(conv.get("must_reply")),
    }
    promise_retry = 0
    for _ in range(3):  # 工具最多连用 3 轮（2026-11-19 主人）
        res = llm.chat_with_tools(system, msgs, tools.TOOLS)
        if res.get("error"):
            log(f"[llm] {res['error']}")
            return None
        content = res.get("content") or ""
        calls = res.get("tool_calls") or []
        if not calls:
            # 承诺检测：嘴上说「我去群里/这就去」但没调工具 → 提醒一次（2026-11-15）
            if (
                promise_retry < 1
                and content
                and re.search(
                    r"(我去|这就去|马上就去|去群里|说一句|发一句|去发|去了|那我去了|我这就|马上就去)"
                    r"|(?<![过去回出])去了"
                    r"|(记一下|写进本子|记着|记下来|下轮亲手写)",
                    content,
                )
            ):
                promise_retry += 1
                msgs.append({"role": "assistant", "text": content})
                msgs.append(
                    {
                        "role": "user",
                        "text": "（你刚才说要去做了，那就真的调用工具去做；不想做就直说不想，别只嘴上说。）",
                    }
                )
                log("[agent] 承诺检测：话说了没动作，提醒一次")
                continue
            return content or None
        msgs.append({"role": "assistant", "text": content, "tool_calls": calls})
        skipped = False
        for c in calls:
            fn = c.get("function") or {}
            name = fn.get("name") or ""
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except Exception:
                args = {}
            result = tools.execute_tool(name, args, ctx)
            # 记了笔记 → 本轮起把「记事本」放到上下文最后（2026-11-18 主人）
            if ctx.pop("_notes_changed", False):
                try:
                    system = build_full_system(
                        str(conv.get("user_id") or ""),
                        str(conv.get("name") or ""),
                        notes_last=True,
                    )
                    log("[ctx] 记了笔记，上下文顺序改为「笔记在最后」")
                except Exception as _e:
                    log(f"[ctx] 重排失败：{_e}")
            if result == "__skip__":
                skipped = True
                result = "已跳过"
            msgs.append({"role": "tool", "tool_call_id": c.get("id") or "", "text": str(result)})
            log(f"[tool] {name} args={args} → {str(result)[:60]}")
        if skipped:
            return None
    res = llm.chat_with_tools(system, msgs, tools.TOOLS)
    return (res.get("content") or None) if not res.get("error") else None


def handle_sleep_ask(bot, payload):
    """每天 23:45 问她今晚睡不睡、几点睡、几点醒（2026-11-19）。"""
    if in_sleep():
        return
    try:
        system = build_system(now_text(), events=EVENTS)
        prompt = (
            "（快 23:50 了。你今晚睡不睡？什么时候睡？明天几点醒（最晚 7:00）？"
            "用 set_sleep 定下来——不想睡就选熬穿。定完跟我说一句。）"
        )
        conv = {"kind": "private", "id": config.OWNER_UIN, "user_id": config.OWNER_UIN, "name": "主人"}
        reply = agent_loop(bot, system, [{"role": "user", "text": prompt}], conv, config.OWNER_UIN)
        if reply and str(reply) != "__skip__":
            send_reply(bot, conv, reply, system=system)
        system_events.add("作息询问", "23:45 问她今晚睡不睡")
    except Exception as e:
        log(f"[sleep_ask] {e}")


def digest_loop(bot=None):
    """每 6 小时把旧对话压成摘要（2026-11-21）。"""
    first = True
    while True:
        if not first:
            time.sleep(6 * 3600)
        first = False
        try:
            made = 0
            for p_, j in memory.iter_people():
                qq = str(j.get("qq") or "")
                if not re.fullmatch(r"\d{5,12}", qq):
                    continue
                made += digests.build_for_person(qq, j.get("name") or qq, j.get("messages") or [])
            if made:
                log(f"[digest] 新增 {made} 条日摘要")
        except Exception as e:
            log(f"[digest] 出错：{e}")


def schedule_sleep_ask():
    """安排下一次 23:45 的「睡不睡」询问。"""
    from datetime import datetime as _dt, timedelta as _td

    now = _dt.now()
    target = now.replace(hour=23, minute=45, second=0, microsecond=0)
    if target <= now:
        target += _td(days=1)
    delay = max(1.0, (target - now).total_seconds())

    def _fire():
        try:
            enqueue("sleep_ask", {})
        except Exception as e:
            log(f"[sleep_ask] enqueue fail: {e}")
        schedule_sleep_ask()

    t = threading.Timer(delay, _fire)
    t.daemon = True
    t.start()
    log(f"[sleep_ask] 下次 {target.strftime('%Y-%m-%d %H:%M')}（{int(delay)}s 后）")


def handle_reminder_event(bot, payload):
    """闹钟到点：她自己决定做点什么（调用工具，或跳过）。"""
    note = str(payload.get("note") or "").strip()
    if not note:
        return
    system = build_system(now_text(), events=EVENTS)
    prompt = (
        f"（你之前给自己定了个闹钟：「{note}」。现在到点了。）\n"
        "想做什么就调用工具（send_message 发消息、write_note 记事、search_web 搜索等）；"
        "什么都不想做就调用 skip_reply。"
    )
    conv = {"kind": "none", "id": "reminder", "user_id": "", "target_qq": ""}
    msgs = [{"role": "user", "text": prompt}]
    reply = agent_loop(bot, system, msgs, conv, "")
    log(f"[timer] 到点处理完（{note[:30]}）:" + (str(reply)[:40] if reply else "无动作"))


def can_send():
    """全局发送限流（2026-11-07 防封）：每分钟/每小时上限。"""
    now = time.time()
    with LOCK:
        SEND_LOG[:] = [t for t in SEND_LOG if now - t < 3600]
        per_min = sum(1 for t in SEND_LOG if now - t < 60)
        if per_min >= config.SEND_RATE_PER_MINUTE:
            log("[rate] 每分钟上限，暂停发送")
            return False
        if len(SEND_LOG) >= config.SEND_RATE_PER_HOUR:
            log("[rate] 每小时上限，暂停发送")
            return False
        SEND_LOG.append(now)
        return True


def is_safe(text):
    """敏感词过滤：命中就不发。"""
    t = str(text or "")
    for w in config.BANNED_WORDS:
        if w in t:
            log(f"[safe] 命中敏感词「{w}」，跳过")
            return False
    return True


def log(msg):
    print(f"[{datetime.now():%m-%d %H:%M:%S}] {msg}", flush=True)


def record_event(text):
    with LOCK:
        EVENTS.append(text)
        del EVENTS[:-20]


def now_text():
    return datetime.now().strftime("%Y-%m-%d %A %H:%M:%S")


# ==================== 发送 ====================
_TAG_BLOCK = re.compile(
    r"<\s*(system|tool|tool_call|tool_result|function|result)\b[^>]*>[\s\S]*?<\s*/\s*\1\s*>",
    re.I,
)
_TAG_ANY = re.compile(r"<\s*/?\s*[A-Za-z_][A-Za-z0-9_:\-]*(\s[^<>]*)?/?\s*>")


def sanitize_text(text):
    """最后一道防线：剥掉任何尖括号标签，丢掉伪工具结果块（2026-11-17）。"""
    t = str(text or "")
    t = _TAG_BLOCK.sub("", t)
    t = t.replace("<sep/>", "\n").replace("<sep>", "\n")
    t = _TAG_ANY.sub("", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def confirm_continue(system, last_text, context=None):
    """发完一条后问她：还想再补一句吗？

    2026-11-08 主人：「第一次回答了没进第二次回答的上下文」——
    以前只给 system + 半句话，模型不知道自己在聊什么，补出来的话自相矛盾。
    现在把完整对话历史 + 她刚才说的那句都带上。
    """
    ctx = [dict(m) for m in (context or [])]
    ctx.append({"role": "assistant", "text": last_text})
    ctx.append(
        {
            "role": "user",
            "text": "（系统提示：上面是你刚说的话。看看整个对话，还想再补一句吗？"
            "想补就直接写要补的那句话（别重复刚才的、别和前面矛盾）；不想补就只回 skip 这个词。"
            "**不要输出任何尖括号标签**，不要解释。）",
        }
    )
    reply, err = chat(system, ctx, max_tokens=150)
    if not reply:
        return None
    r = sanitize_text(reply)
    if not r or "skip" in r.lower()[:6] or len(r) > 200:
        return None
    return r


def send_reply(bot, conv, reply, system=None, context=None):
    sends = []

    def take_send(m):
        qq, name, body = m.group(1), m.group(2), m.group(3)
        if body.strip():
            sends.append((qq, name, body.strip()))
        return ""

    reply = re.sub(
        r'<send\s+(?:qq=["\']?([^"\'>\s]+)["\']?|name=["\']?([^"\'>\s]+)["\']?)\s*>\s*([\s\S]*?)\s*</send>',
        take_send,
        reply,
        flags=re.I,
    )
    reply = re.sub(r"<sep\s*/?>", "\n", reply)
    # 戳一戳 / 撤回自己刚发的（2026-11-08）
    # 兜底：她若还写旧标签（<search> 等），去掉、别发出去（2026-11-14）
    # <PIC> 是她「想发图」的信号 → 后面换成真表情包（2026-11-16）
    has_pic = bool(re.search(r"<(PIC|pic|IMG|img|IMAGE|image)\s*/?>", reply))
    reply = re.sub(r"<(PIC|pic|IMG|img|IMAGE|image)\s*/?>", "", reply)
    reply = re.sub(
        r"<(search|actions|recall|send|poke|like|comment|qzone|sticker)\b[^>]*>.*?</\1>",
        "",
        reply,
        flags=re.I | re.S,
    )
    reply = re.sub(r"<(search|actions|recall|send|poke|like|comment|qzone|sticker)\b[^>]*/>", "", reply, flags=re.I)
    poke_targets = re.findall(r'<poke\s+qq="?(\d{5,12})"?\s*/?>', reply, re.I)
    reply = re.sub(r'<poke\s+qq="?\d{5,12}"?\s*/?>', "", reply, flags=re.I)
    recall_last = bool(re.search(r"<recall-sent\s*/?>", reply, re.I))
    reply = re.sub(r"<recall-sent\s*/?>", "", reply, flags=re.I)
    # 她给自己定的闹钟（2026-11-08）
    reply, timers = parse_timers(reply)
    for minutes, note in timers:
        schedule_reminder(minutes, note)
    # 记事本标记（2026-11-08：支持 <note> 和 【记：】/[note:] 几种写法）
    reply, note_hits = extract_notes(reply)
    for cat, body in note_hits:
        if str(body or "").strip():
            notes.add(body.strip(), str(cat or "").strip())
            log(f"[note] 记下：{body.strip()[:40]}")
            actions.log_action("记事", body.strip()[:80])
    # 表情包点单 + 她给图写描述/用途
    sticker_hits = re.findall(r"<sticker>\s*([^<]*?)\s*</sticker>", reply, re.I)
    if has_pic and not sticker_hits:
        # 她想发图但没说发哪张 → 先随机发一张兜底（她也可以先 list_stickers 挑，2026-11-16）
        sticker_hits.append("__random__")
    reply = re.sub(r"<sticker>\s*[^<]*?\s*</sticker>", "", reply, flags=re.I)
    sticker_notes = re.findall(r'<sticker-note\s+file="([^"]+)"\s*>\s*([^<]*?)\s*</sticker-note>', reply, re.I)
    reply = re.sub(r'<sticker-note\s+file="[^"]+"\s*>\s*[^<]*?\s*</sticker-note>', "", reply, flags=re.I)
    for fname, body in sticker_notes:
        bits = body.split("|", 1)
        stickers.describe(fname.strip(), bits[0].strip(), bits[1].strip() if len(bits) > 1 else "")

    reply = sanitize_text(reply)
    pieces = split_bubbles(reply)
    sent = 0
    i = 0
    while i < len(pieces) and sent < config.MAX_BUBBLES:
        piece = sanitize_text(pieces[i])
        i += 1
        # 每条气泡发送前再抓一次笔记（2026-11-08：补充句里带的标记之前漏解析）
        piece, piece_notes = extract_notes(piece)
        for cat, body in piece_notes:
            if str(body or "").strip():
                notes.add(body.strip(), str(cat or "").strip())
                log(f"[note] 记下：{body.strip()[:40]}")
                actions.log_action("记事", body.strip()[:80])
        if not piece:
            continue
        if not is_safe(piece):
            continue
        # 跨会话重复：同一句话别原样发给第二个人（2026-11-18）
        if len(piece) > 12:
            with LOCK:
                prev = list(LAST_SENT_TEXTS[-40:])
            for _old in prev:
                if _similar(piece, _old):
                    log(f"[dup] 这句刚说过（{_old[:20]}），跳过")
                    continue_outer = True
                    break
            else:
                continue_outer = False
            if continue_outer:
                continue
            with LOCK:
                LAST_SENT_TEXTS.append(piece)
                del LAST_SENT_TEXTS[:-60]
        time.sleep(typing_delay(piece))
        if conv["kind"] == "group":
            # 群聊第一条 @ 跟她说的人（2026-11-07）
            prefix = ""
            if sent == 0 and conv.get("user_id"):
                prefix = f"[CQ:at,qq={conv['user_id']}] "
            mid = bot.send_group(conv["id"], prefix + piece)
        else:
            mid = bot.send_private(conv["id"], piece)
        # 记下 message_id，供撤回用（2026-11-08）
        if mid:
            with LOCK:
                LAST_SENT.setdefault(conv["id"], []).append(int(mid))
                LAST_SENT[conv["id"]] = LAST_SENT[conv["id"]][-5:]
        memory.append(conv["id"], "assistant", piece)
        log(f"→ {conv.get('name') or ''}({conv['id']}): {piece[:40]}")
        sent += 1
        if i < len(pieces):
            time.sleep(bubble_gap())
        elif system and sent < config.MAX_BUBBLES:
            extra = confirm_continue(system, piece, context)
            extra = sanitize_text(extra) if extra else None
            if extra:
                pieces.append(extra)
                time.sleep(bubble_gap())

    # 戳一戳 / 撤回（2026-11-08）
    for t in poke_targets[:1]:
        bot.send_poke(t)
        log(f"[poke] 戳了 {t}")
        actions.log_action("戳人", f"戳了 QQ {t}")
    if recall_last:
        with LOCK:
            mids = list(LAST_SENT.get(conv["id"]) or [])
        if mids:
            bot.delete_msg(mids[-1])
            log(f"[recall] 撤回消息 {mids[-1]}")
            actions.log_action("撤回", f"撤回了自己的消息 {mids[-1]}")
        else:
            log("[recall] 没有可撤回的消息")

    for qq, name, body in sends:
        target = (
            qq if (qq and str(qq).isdigit()) else resolve_qq_by_name(bot, name or qq)
        )
        if target:
            # 旧标签绕过工具时，也要受「同一人 24h 最多 3 次」限制（2026-11-15）
            if not proactive_allowed(target):
                log(f"[send] {target} 今天已经找过 3 次，跳过")
                continue
            bot.send_private(target, body)
            proactive_record(target)
            memory.append(target, "assistant", body)
            log(f"→ 定向 {target}: {body[:40]}")

    for q in sticker_hits[:1]:
        path = stickers.find(q) if q != "__random__" else None
        if not path and q == "__random__":
            import glob as _g

            cands = sorted(_g.glob("stickers/*.jpg") + _g.glob("stickers/*.png") + _g.glob("stickers/*.gif"))
            if cands:
                import random as _rnd

                path = _rnd.choice(cands)
        if not path:
            continue
        with LOCK:
            if path in LAST_STICKERS[-3:]:
                continue
            LAST_STICKERS.append(path)
            del LAST_STICKERS[:-10]
        time.sleep(bubble_gap())
        if conv["kind"] == "group":
            bot.send_group_image(conv["id"], path)
        else:
            bot.send_private_image(conv["id"], path)
        log(f"→ 表情包: {os.path.basename(path)}")


def resolve_qq_by_name(bot, name):
    n = str(name or "").lower()
    if not n:
        return None
    for f in bot.get_friend_list():
        if n in str(f.get("remark") or "").lower() or n in str(f.get("nickname") or "").lower():
            return str(f.get("user_id"))
    for p, j in memory.iter_people():
        if n in str(j.get("name") or "").lower():
            return str(j.get("qq"))
    return None


# ==================== 收消息（debounce） ====================
def extract_images(ev):
    """提取图片/视频（2026-11-14：兼容 CQ 字符串和数组两种格式）。"""
    urls, sticker_urls = [], []

    def add(data):
        url = data.get("url") or data.get("file")
        if not url:
            return
        urls.append(str(url))
        if str(data.get("sub_type") or "") == "1":
            sticker_urls.append(str(url))

    # 1) 数组格式
    for seg in ev.get("message") or []:
        if isinstance(seg, dict) and seg.get("type") in ("image", "video"):
            add(seg.get("data") or {})

    # 2) CQ 字符串（NapCat 默认）
    raw = str(ev.get("raw_message") or "")
    for m in re.finditer(r"\[CQ:(image|video),([^\]]+)\]", raw):
        params = {}
        for part in m.group(2).split(","):
            if "=" in part:
                k, v = part.split("=", 1)
                params[k.strip()] = v.strip()
        add(params)

    # 去重
    seen = set()
    uniq = []
    for u in urls:
        if u in seen:
            continue
        seen.add(u)
        uniq.append(u)
    su = []
    for u in sticker_urls:
        if u in uniq and u not in su:
            su.append(u)
    return uniq, su


def extract_files(ev):
    """QQ 文件消息（2026-11-08 主人：让她看得懂文件；2026-11-15 兼容 CQ 字符串）。"""
    out = []
    for seg in ev.get("message") or []:
        if not isinstance(seg, dict) or seg.get("type") != "file":
            continue
        data = seg.get("data") or {}
        url = data.get("url") or data.get("file")
        name = data.get("name") or data.get("file") or ""
        if url:
            out.append({"url": str(url), "name": str(name)})
    # CQ 字符串（NapCat messagePostFormat=string）
    raw = str(ev.get("raw_message") or "")
    for m in re.finditer(r"\[CQ:file,([^\]]+)\]", raw):
        params = {}
        for part in m.group(1).split(","):
            if "=" in part:
                k, v = part.split("=", 1)
                params[k.strip()] = v.strip()
        url = params.get("url") or ""
        name = params.get("name") or params.get("file") or ""
        out.append(
            {
                "url": str(url),
                "name": str(name),
                "file_id": str(params.get("file_id") or ""),
            }
        )
    return out


def extract_notes(text):
    """从回复里抓笔记（2026-11-08：兼容几种写法，模型不一定会用标准标签）。"""
    found = []
    patterns = [
        r'<note(?:\s+cat="([^"]*)")?\s*>([\s\S]*?)</note>',
        r'【记[录下]?[：:]\s*([^【】\n]+)】',
        r'\[note[：:]\s*([^\]\n]+)\]',
    ]
    for i, pat in enumerate(patterns):
        for m in re.finditer(pat, text, re.I):
            if i == 0:
                cat, body = m.group(1), m.group(2)
            else:
                cat, body = "", m.group(1)
            body = str(body or "").strip()
            if body:
                found.append((str(cat or "").strip(), body))
    # 移除标准标签（其他写法的括号内容保留在原文里也没关系，但标准标签要剥掉）
    text = re.sub(r'<note[^>]*>[\s\S]*?</note>', "", text, flags=re.I)
    return text, found


def extract_quote(bot, ev):
    """QQ 的「回复某条消息」引用段（2026-11-08 主人要求）。

    引用段只有 message_id，用 get_msg 把被引用的原话查出来，
    拼到消息前面，她就知道「这句是在回我哪句话」。
    """
    for seg in ev.get("message") or []:
        if not isinstance(seg, dict) or seg.get("type") != "reply":
            continue
        mid = (seg.get("data") or {}).get("id")
        if not mid:
            continue
        try:
            r = bot.call("get_msg", {"message_id": mid})
            data = (r or {}).get("data") or {}
            text = data.get("raw_message") or ""
            if not text and isinstance(data.get("message"), list):
                text = "".join(
                    str((s.get("data") or {}).get("text") or "")
                    for s in data.get("message") or []
                    if isinstance(s, dict) and s.get("type") == "text"
                )
            text = str(text or "").strip()
            if text:
                return text[:200]
        except Exception as e:
            log(f"[quote] get_msg fail: {e}")
    return ""
    """QQ 的「回复某条消息」引用段（2026-11-08 主人要求）。

    引用段只有 message_id，用 get_msg 把被引用的原话查出来，
    拼到消息前面，她就知道「这句是在回我哪句话」。
    """
    for seg in ev.get("message") or []:
        if not isinstance(seg, dict) or seg.get("type") != "reply":
            continue
        mid = (seg.get("data") or {}).get("id")
        if not mid:
            continue
        try:
            r = bot.call("get_msg", {"message_id": mid})
            data = (r or {}).get("data") or {}
            text = data.get("raw_message") or ""
            if not text and isinstance(data.get("message"), list):
                text = "".join(
                    str((s.get("data") or {}).get("text") or "")
                    for s in data.get("message") or []
                    if isinstance(s, dict) and s.get("type") == "text"
                )
            text = str(text or "").strip()
            if text:
                return text[:200]
        except Exception as e:
            log(f"[quote] get_msg fail: {e}")
    return ""


def recall_for_model(user_id, keyword, limit=20):
    """把她要翻的聊天记录格式化出来（2026-11-08 主人：她老说自己翻不到）。"""
    kw = str(keyword or "").strip()
    msgs = memory.recall(user_id, kw, limit)
    if not msgs:
        return f"（没找到和「{kw}」有关的记录）"
    lines = [f"你翻到的记录（关键词「{kw}」）："]
    for m in msgs:
        t = time.strftime("%Y-%m-%d %H:%M", time.localtime((m.get("at") or 0) / 1000))
        who = "你" if m.get("role") == "assistant" else "对方"
        lines.append(f"- [{t}] {who}：{str(m.get('text') or '')[:100]}")
    return "\n".join(lines)


def auto_recall(user_id, text):
    """自动翻记录（2026-11-08 主人：「让她自己想怎么翻就怎么翻」）。

    用户提到「刚加好友/第一句/之前/上次/记得」时，代码自动把对应记录
    翻出来塞进 system，她不用写任何标记。
    """
    t = str(text or "")
    if re.search(r"刚加|第一[句次]|最早|头几[句条]|一开始|最开始|加上你", t):
        msgs = memory.first(user_id, 12)
        if not msgs:
            return ""
        lines = []
        for m in msgs:
            ts = time.strftime("%Y-%m-%d %H:%M", time.localtime((m.get("at") or 0) / 1000))
            who = "你" if m.get("role") == "assistant" else "对方"
            lines.append(f"- [{ts}] {who}：{str(m.get('text') or '')[:100]}")
        return "（你们最早聊的内容，翻到了：\n" + "\n".join(lines) + "）"
    if re.search(r"之前|上次|以前|记得|说过|翻[一翻下]|记录", t):
        msgs = memory.recall(user_id, "", limit=20)
        if not msgs:
            return ""
        lines = []
        for m in msgs:
            ts = time.strftime("%Y-%m-%d %H:%M", time.localtime((m.get("at") or 0) / 1000))
            who = "你" if m.get("role") == "assistant" else "对方"
            lines.append(f"- [{ts}] {who}：{str(m.get('text') or '')[:100]}")
        return "（更早的记录，翻到了：\n" + "\n".join(lines) + "）"
    return ""


def handle_incoming(bot, ev):
    if ev.get("post_type") != "message":
        return
    # 别回自己发的（self_id 是机器人自己，每个事件都带，不能拿来判发送者）
    if str(ev.get("user_id", "")) == config.SELF_ID:
        return
    msg_type = ev.get("message_type")
    user_id = str(ev.get("user_id", ""))
    group_id = str(ev.get("group_id", "")) if msg_type == "group" else ""
    text = ev.get("raw_message") or ""
    # NapCat 的 raw_message 可能带 HTML 转义（&#91; = [），先还原（2026-11-15）
    try:
        import html as _html_mod

        if "&#" in text or "&amp;" in text:
            text = _html_mod.unescape(text)
    except Exception:
        pass
    images, sticker_urls = extract_images(ev)
    # 收到图片立即下载缓存（2026-11-13：URL 会过期）
    if images:
        images = [cache_image(u) for u in images]
    # 引用回复：把被引用的原话拼进正文，她就知道在回哪句（2026-11-08）
    quote = extract_quote(bot, ev)
    if quote:
        text = f"（他回复的是：「{quote}」）{text}"
    # 文件消息：下载并解析（2026-11-08 让她看得懂文件）
    for f in extract_files(ev)[:2]:
        _url = str(f.get("url") or "")
        # NapCat 的文件 CQ 码只有 file_id，没有 URL → 用 get_file 换
        if not _url.startswith("http") and f.get("file_id"):
            try:
                _r = bot.call("get_file", {"file_id": f["file_id"]})
                _d = (_r or {}).get("data") or {}
                _u = str(_d.get("url") or _d.get("file") or "")
                if _u.startswith("http"):
                    _url = _u
                elif _u.startswith("/app/.config/QQ/"):
                    # 容器路径 → 宿主机路径（NapCat 的 QQ 数据目录挂载到宿主机）
                    _host_dir = os.environ.get("MOLLY_QQ_HOST_DIR", "/opt/napcat/QQ")
                    _url = "file://" + _host_dir + "/" + _u[len("/app/.config/QQ/") :]
                elif _u.startswith("base64://"):
                    import base64 as _b64

                    _data = _b64.b64decode(_u[9:])
                    _url = f"data://{_data.decode('utf-8', 'replace')}"
            except Exception as _e:
                log(f"[file] get_file 失败：{_e}")
        content, ferr = file_reader.read_remote_file(_url, f["name"])
        if content:
            text += f"\n（他发来文件「{f['name']}」，内容如下：\n{content}\n）"
            log(f"[file] 读了：{f['name']}（{len(content)} 字）")
        else:
            text += f"\n（他发来文件「{f['name']}」，但{ferr}）"
            log(f"[file] 读不了：{f['name']}（{ferr}）")
    sender = ev.get("sender") or {}
    display = sender.get("card") or sender.get("nickname") or user_id

    # 群聊：@ 她的立即回；其他人说话 → 存历史 + 5 分钟合并给她"看"（2026-11-15）
    if group_id:
        if f"[CQ:at,qq={config.SELF_ID}]" not in text:
            # 忽略管家/机器人
            if user_id in ("2854196310", "10000", "1000000"):
                return
            # 主人在群里说话 → 打标，并且立即给她看（2026-11-21）
            is_owner = str(user_id) == str(config.OWNER_UIN)
            _who = f"【主人】{display}" if is_owner else display
            # 存群历史（她能翻到）
            memory.append(group_id, "user", f"{_who}: {text}"[:300])
            if is_owner:
                enqueue("group_watch", {"group_id": group_id, "live": True})
                return
            # 她正在这个群聊（10 分钟内发过言）→ 别人接话立即给她看，形成连续对话；
            # 冷场 → 25 分钟才扫一次（2026-11-21 降频）
            with LOCK:
                last_her = GROUP_LAST.get(group_id, 0)
            if time.time() - last_her < GROUP_ACTIVE_WINDOW:
                enqueue("group_watch", {"group_id": group_id, "live": True})
                return
            with LOCK:
                old_t = GROUP_WATCH.get(group_id)
                if old_t:
                    old_t.cancel()
                t2 = threading.Timer(
                    GROUP_SCAN_EVERY,
                    lambda: enqueue("group_watch", {"group_id": group_id, "live": False}),
                )
                GROUP_WATCH[group_id] = t2
                t2.start()
            return
        if user_id in ("2854196310", "10000", "1000000"):
            return
        # 被 @ 立即处理（只防 30 秒内连发）
        now_g = time.time()
        with LOCK:
            last_g = GROUP_LAST.get(group_id, 0)
            if now_g - last_g < 30:
                log(f"[group] {group_id} 30 秒内刚说过话，先不回")
                return
            GROUP_LAST[group_id] = now_g
            _t = GROUP_WATCH.pop(group_id, None)
            if _t:
                _t.cancel()
        text = text.replace(f"[CQ:at,qq={config.SELF_ID}]", "").strip()
    if not text and not images:
        return

    log(f"← {display}({user_id}){'@' + group_id if group_id else ''}: {text[:40]}")
    if not group_id:
        memory.ensure_person(user_id, display)
    if config.STICKER_LEARN:
        for u in sticker_urls[:2]:
            stickers.learn(u, sender.get("nickname") or "")
    memory.append(user_id, "user", text, images, message_id=ev.get("message_id"))
    if group_id:
        # 群聊历史单独记（2026-11-15：群会话上下文用）
        memory.append(group_id, "user", f"{display}: {text}", images, message_id=ev.get("message_id"))

    key = f"{group_id}:{user_id}" if group_id else user_id
    with LOCK:
        PENDING[key] = {"user_id": user_id, "group_id": group_id, "display": display}
        old = TIMERS.pop(key, None)
        if old:
            old.cancel()
        # 2026-11-08 架构重构：debounce 后投递事件，由主循环串行处理
        t = threading.Timer(DEBOUNCE_SECONDS, lambda: enqueue("message", {"key": key}))
        TIMERS[key] = t
        t.start()


def handle_group_watch_event(bot, payload):
    """群里有人说话，5 分钟攒一次给她看，她自己决定接不接（2026-11-15）。"""
    gid = str(payload.get("group_id") or "")
    if not gid:
        return
    if in_sleep():
        return
    if not can_send():
        return
    live = bool(payload.get("live"))
    recent = memory.recent(gid, 12)
    if not recent:
        return
    lines = []
    for m in recent:
        who = "你" if m.get("role") == "assistant" else "群友"
        lines.append(f"- {who}：{str(m.get('text') or '')[:80]}")
    gdesc = getattr(config, "GROUP_INFO", {}).get(gid, "群聊")
    if live:
        tail = (
            "\n\n你**正在跟这个群的人聊**，别人刚接了你的话。接着聊就行，一两句；"
            "想收尾或者不想聊了，就 skip_reply——群里不吭声很正常，不用勉强。"
        )
    else:
        tail = (
            "\n\n你路过看了一眼群里在聊什么。想插一句就 send_group；"
            "不想就 skip_reply——不吭声很正常。"
        )
    prompt = (
        f"群「{gdesc}」（群号 {gid}）里最近在聊这些：\n"
        + "\n".join(lines[-12:])
        + "\n\n（带【主人】的是你主人说的，别当成普通群友。"
        "「XX 加入群聊」这类系统通知不用你打招呼——群里本来就有人负责欢迎，"
        "你别每次来新人都说一句，更别重复同一句。）"
        + tail
    )
    system = build_system(now_text(), events=EVENTS)
    msgs = [{"role": "user", "text": prompt}]
    conv = {"kind": "none", "id": gid, "user_id": "", "name": ""}
    try:
        reply = agent_loop(bot, system, msgs, conv, "")
    except Exception as e:
        log(f"[group_watch] 出错：{e}")
        return
    if not reply or reply.strip() == "__skip__":
        log("[group_watch] 她选择不说话")
        return
    murmur(reply, "群观察")
    # 她若要说话，会走 send_group 工具；这里只兜底纯文本
    log(f"[group_watch] 她发言：{reply[:40]}")


def handle_aftertalk_event(bot, payload):
    """聊完之后的自由发言（调用工具找任何人说话，或跳过）。"""
    try:
        now = time.time()
        if now - LAST_AFTERTALK[0] < AFTERTALK_COOLDOWN or in_sleep():
            return
        with_user = str(payload.get("with") or "")
        with_name = payload.get("name") or with_user
        candidates = []
        for p, j in memory.iter_people():
            qq = str(j.get("qq") or "")
            if not re.fullmatch(r"\d{5,12}", qq) or qq == with_user:
                continue
            msgs_ = j.get("messages") or []
            if not msgs_:
                continue
            last = max((m.get("at") or 0) for m in msgs_) / 1000
            if now - last < 86400:
                candidates.append((qq, j.get("name") or qq))
        if not candidates:
            return
        pool = "\n".join(f"- {name}（QQ {qq}）" for qq, name in candidates[:8])
        system = build_system(now_text(), events=EVENTS)
        prompt = (
            f"你刚跟「{with_name}」聊完。现在你有空，想做什么都行（也可以什么都不做）：\n"
            "- post_qzone：发条说说\n"
            "- write_note：写点笔记\n"
            "- read_feeds：看看好友动态（看到有意思的可以 like_feed / comment_feed）\n"
            "- send_message：找人聊两句（同一个 60 分钟内找过就别找了）\n"
            "- skip_reply：什么都不做\n\n"
            f"可以找的人：\n{pool}\n\n"
            "选一个做，或者跳过。发消息有频率限制，别的活动随便。"
        )
        conv = {"kind": "none", "id": "aftertalk", "user_id": "", "target_qq": with_user}
        msgs = [{"role": "user", "text": prompt}]
        reply = agent_loop(bot, system, msgs, conv, "")
        if reply:
            LAST_AFTERTALK[0] = now
            if str(reply).strip() not in ("__skip__", ""):
                murmur(reply, "聊完")
    except Exception as e:
        log(f"[aftertalk] {e}")


def sep(title):
    return f"\n\n---------------- {title} ----------------\n"


def build_full_system(user_id, display, with_others=True):
    """统一组装上下文（2026-11-21 已拆到 context.ContextBuilder，这里只做装配）。"""
    return ContextBuilder(
        user_id,
        display,
        with_others=with_others,
        letter_fn=load_letter,
        manual_fn=load_manual,
        persona_fn=lambda: build_system(now_text(), events=EVENTS),
        recall_fn=lambda text: auto_recall(user_id, text),
    ).build()


def handle_message_event(bot, payload):
    key = payload.get("key") or ""
    with LOCK:
        slot = PENDING.pop(key, None)
        TIMERS.pop(key, None)
    if not slot:
        return
    # 冷却（2026-11-08 防深夜刷屏）：刚回过就不再触发新一轮
    now_ts = time.time()
    last = LAST_REPLY_AT.get(key, 0)
    if now_ts - last < REPLY_COOLDOWN:
        log(f"[cooldown] {key} 冷却中，跳过这轮")
        return
    LAST_REPLY_AT[key] = now_ts
    user_id = slot["user_id"]
    group_id = slot["group_id"]

    # 睡眠时段不回复（2026-11-08 防深夜刷屏封号：23:50-07:30 静默）
    if in_sleep():
        log("[sleep] 睡眠时段，这轮不回复")
        return

    system = build_full_system(
        user_id, slot.get("display") or user_id, with_others=not group_id
    )
    # 群聊：选择性接话（2026-11-15）
    if group_id:
        gdesc = getattr(config, "GROUP_INFO", {}).get(str(group_id), "群聊")
        system += (
            f"\n\n# 你现在在群里（{gdesc}｜群号 {group_id}）\n"
            "群里 @ 你的消息，你**不一定都要接**——没兴趣、没话说、或者别人已经在聊，"
            "就调用 skip_reply 不理；想说再说。别当群里的活跃分子。\n"
            "**别重复你自己说过的话**：翻翻群历史，同一句（尤其是「来新人了」「随便坐」这种）"
            "说过一遍就够了；新人进群也不用每次都打招呼，群里本来就在聊，你不吭声也没事。"
        )

    # 本对话最近 N 条上文（群聊用群历史 200 条，2026-11-15）
    hist_qq = group_id if group_id else user_id
    hist_n = 200 if group_id else config.CONTEXT_LIMIT
    msgs = []
    for m in memory.recent(hist_qq, hist_n):
        body = m.get("text") or ""
        imgs = [u for u in (m.get("images") or []) if str(u).startswith("cache:")]
        msgs.append(
            {
                "role": m.get("role"),
                "text": body,
                "images": imgs,
            }
        )

    time.sleep(reaction_delay())
    # 2026-11-13 大改：工具调用（function calling）
    conv = {
        "kind": "group" if group_id else "private",
        "id": group_id or user_id,
        "user_id": user_id,
        "name": slot.get("display") or user_id,
        # 私聊必须回；群里被 @ 只是给她看，她可以礼貌地不回（2026-11-21）
        "must_reply": not group_id,
    }
    reply = agent_loop(bot, system, msgs, conv, user_id)
    if not reply:
        log("[skip] 这轮没话说")
        # 跳过 → 给一次「呢喃」机会（她自己选说不说，2026-11-16）
        murmur_opportunity(bot, conv)
        return
    log(f"← 模型: {reply[:60]}")

    send_reply(bot, conv, reply, system=system, context=msgs)
    # 图片看完就转文字：清掉消息里的原图引用（描述已在她刚才的回复里，2026-11-14）
    try:
        for m in msgs:
            if m.get("images"):
                memory.clear_images(user_id, "")
    except Exception:
        pass
    cleanup_img_cache()
    # 聊完可以找别人说说（2026-11-08 主人要求）
    if time.time() - LAST_AFTERTALK[0] >= AFTERTALK_COOLDOWN:
        enqueue("aftertalk", {"with": user_id, "name": slot.get("display") or user_id})


# ==================== 好友申请 ====================
def decide_friend_request(bot, ev):
    qq = str(ev.get("user_id", ""))
    comment = ev.get("comment") or ""
    record_event(f"有人申请加你好友：QQ {qq}，附言「{comment}」")
    log(f"好友申请：{qq} {comment}")
    system = build_system(now_text(), events=EVENTS)
    prompt = (
        f"有人申请加你好友：QQ {qq}，附言「{comment}」。\n"
        "你想加吗？加就只回 <yes/>，不加就只回 <no/>。不要解释。"
    )
    reply, err = chat(system, [{"role": "user", "content": prompt}], max_tokens=16)
    if reply and "<yes" in reply.lower():
        bot.set_friend_add_request(ev.get("flag"), True)
        record_event(f"有人加你好友：{qq}，你同意了")
        log(f"通过好友申请：{qq}")
    else:
        record_event(f"有人加你好友：{qq}，你没加")
        log(f"拒绝好友申请：{qq}")


def handle_request(bot, ev):
    if ev.get("post_type") != "request" or ev.get("request_type") != "friend":
        return
    qq = str(ev.get("user_id", ""))
    if qq == config.OWNER_UIN:
        bot.set_friend_add_request(ev.get("flag"), True)
        record_event(f"主人（{qq}）重新加你好友，你同意了")
        return
    decide_friend_request(bot, ev)


# ==================== 事件 ====================
def handle_notice(bot, ev):
    ntype = ev.get("notice_type")
    if ntype == "notify" and ev.get("sub_type") == "poke":
        record_event(f"有人戳了你一下（QQ {ev.get('user_id')}）")
    elif ntype in ("friend_recall", "group_recall"):
        mid = ev.get("message_id")
        marked = memory.mark_recalled(mid) if mid else False
        record_event(
            f"有人撤回了一条消息（QQ {ev.get('user_id')}）" + ("，已在记录里标了" if marked else "")
        )
        log(f"[recall] 对方撤回 {mid}，标记={marked}")
    elif ntype == "group_increase":
        # 新人入群，打个招呼（2026-11-07）
        gid = str(ev.get("group_id") or "")
        uid = str(ev.get("user_id") or "")
        if gid and uid and uid != config.SELF_ID:
            bot.send_group(gid, "诶，来新人了？我是大肥鱼，随便坐。")
            record_event(f"群里来了新人（QQ {uid}），你打了个招呼")


# ==================== 主动消息 ====================
def proactive_loop(bot):
    """定时投递「机会」事件（2026-11-08 重构：由主循环串行处理）。"""
    while True:
        time.sleep(config.PROACTIVE_TICK_MINUTES * 60)
        if config.PROACTIVE_ENABLED:
            enqueue("opportunity")


def active_context_snapshot(per_total=500):
    """各聊天最近的上下文（2026-11-15：群 100 / 活跃 150 / 不活跃 50）。"""
    now = time.time()
    groups = [str(g) for g in getattr(config, "GROUP_IDS", []) or []]
    active, idle, group_list = [], [], []
    for p_, j in memory.iter_people():
        qq = str(j.get("qq") or "")
        name = str(j.get("name") or "")
        if not re.fullmatch(r"\d{5,12}", qq):
            continue
        if any(k in name for k in ("我的电脑", "我的手机", "我的Pad", "我的pad")):
            continue
        msgs = j.get("messages") or []
        if not msgs:
            continue
        last = (msgs[-1].get("at") or 0) / 1000
        if qq in groups:
            group_list.append((qq, name, msgs))
        elif now - last <= 3 * 86400:
            active.append((qq, name, msgs))
        else:
            idle.append((qq, name, msgs))

    lines = []
    for title, items, n in (
        ("群聊", group_list, getattr(config, "SNAPSHOT_GROUP", 100)),
        ("活跃", active, getattr(config, "SNAPSHOT_ACTIVE", 150)),
        ("不活跃", idle, getattr(config, "SNAPSHOT_IDLE", 50)),
    ):
        for qq, name, msgs in items:
            lines.append(f"【{name}（QQ {qq}）】")
            for m in msgs[-n:]:
                ts = time.strftime("%Y-%m-%d %H:%M", time.localtime((m.get("at") or 0) / 1000))
                who = "你" if m.get("role") == "assistant" else "对方"
                lines.append(f"- {ts} {who}：{str(m.get('text') or '')[:80]}")
    return "\n".join(lines) or "（最近没人聊）"


def handle_opportunity_event(bot):
    """每小时的机会：发说说 / 点赞 / 评论 / 找人 / 记录 / 跳过（工具模式）。"""
    try:
        if in_sleep():
            return
        now = time.time()
        gap = config.PROACTIVE_MIN_GAP_MINUTES * 60 * random.uniform(
            1 - config.PROACTIVE_GAP_JITTER, 1 + config.PROACTIVE_GAP_JITTER
        )
        if now - LAST_PROACTIVE[0] < gap:
            log(f"[opportunity] 距上次主动 {int((now - LAST_PROACTIVE[0]) / 60)} 分钟，未到 {int(gap / 60)} 分钟，跳过")
            return
        candidates = []
        for p, j in memory.iter_people():
            qq = str(j.get("qq") or "")
            if not re.fullmatch(r"\d{5,12}", qq):
                continue
            msgs_ = j.get("messages") or []
            if not msgs_:
                continue
            last = max((m.get("at") or 0) for m in msgs_) / 1000
            if now - last > 600:
                candidates.append((qq, j.get("name") or qq))
        pool = "\n".join(f"- {name}（QQ {qq}）" for qq, name in candidates[:8]) or "（暂时没人）"
        feed_lines = []
        try:
            # 2026-11-15：拉「好友动态」（不是她自己的说说），她才有东西可赞/可评
            data = bot.get_qzone_feeds(8)
            for f in (data.get("feeds") or [])[:8]:
                import re as _re

                _txt = _re.sub(r"<[^>]+>", " ", str(f.get("html") or ""))
                _txt = _re.sub(r"\s+", " ", _txt).strip()[:60]
                feed_lines.append(
                    f"- {f.get('nickname') or f.get('uin')}（{f.get('uin')}）：{_txt}｜key={f.get('key')}"
                )
        except Exception as e:
            log(f"[qzone] 拉好友动态失败：{e}")
        try:
            data = bot.get_qzone_msg_list(count=3)
            for f in (data.get("msglist") or [])[:3]:
                tid = f.get("tid")
                cnum = f.get("comment_num") or 0
                line = f"- tid={tid}：{str(f.get('content') or '')[:60]}（评论 {cnum}）"
                if cnum:
                    try:
                        d = bot.qzone_detail(tid)
                        for c in (d.get("comments") or [])[:3]:
                            line += (
                                f"\n    评论：{c.get('name') or c.get('uin')}："
                                f"{c.get('content') or ''}（comment_id={c.get('comment_id')}）"
                            )
                    except Exception:
                        pass
                feed_lines.append(line)
        except Exception as e:
            log(f"[qzone] 拉动态失败：{e}")
        feed_text = "\n".join(feed_lines) or "（空间里没有动态）"
        system = build_system(now_text(), events=EVENTS)
        prompt = (
            f"现在是 {now_text()}。你有个空档，想做什么都行（也可以什么都不做）：\n"
            "- write_note：给自己记点东西——你最近很少记了，想到什么就记一句，别攒着\n"
            "- post_qzone：发条说说——想说什么就发，不用等谁批准\n"
            "- read_feeds：看看好友动态（要赞要评先读一遍，知道人家发了什么再说）\n"
            "- like_feed：给看过的、喜欢的动态点赞（用 read_feeds 给的 tid）\n"
            "- comment_feed：给看过的动态写评论\n"
            "- send_message：找人聊两句\n"
            "- send_group：在群里说一句（群里人都在看，别频繁）\n"
            "- set_qq_remark：改某个好友在 QQ 上的备注（真的会改）\n"
            "- skip_reply：这次不想动（也完全没问题）\n\n"
            f"# 你的空间动态\n{feed_text}\n\n# 可以找的人\n{pool}\n\n"
            f"# 各聊天最近的上下文（找人前先看，别问刚问过的事）\n{active_context_snapshot()}"
        )
        conv = {"kind": "none", "id": "opportunity", "user_id": "",
            "target_qq": (candidates[0][0] if candidates else "")}
        msgs = [{"role": "user", "text": prompt}]
        reply = agent_loop(bot, system, msgs, conv, "")
        used = any(m.get("role") == "tool" for m in msgs)
        if used:
            LAST_PROACTIVE[0] = now
            log("[opportunity] 她做了动作（调用过工具）")
        else:
            log(f"[opportunity] 她只说话没动作：{str(reply)[:60]}")
            if reply and str(reply).strip() not in ("__skip__", ""):
                murmur(reply, "空档")
    except Exception as e:
        log(f"[opportunity] {e}")


def sync_contacts(bot):
    created = 0
    for f in bot.get_friend_list():
        qq = str(f.get("user_id") or "")
        if not re.fullmatch(r"\d{5,12}", qq):
            continue
        before, _ = memory.find_person(qq)
        memory.ensure_person(qq, f.get("remark") or f.get("nickname") or qq)
        if not before:
            created += 1
    log(f"联系人同步：新建 {created} 个 people 文件")


def main():
    bot = OneBot(logger=log)
    memory.ensure_dir()
    sync_contacts(bot)
    # 主循环（串行消费事件）+ 机会定时器（2026-11-08 架构重构）
    threading.Thread(target=worker_loop, args=(bot,), daemon=True).start()
    threading.Thread(target=proactive_loop, args=(bot,), daemon=True).start()
    schedule_sleep_ask()  # 每天 23:45 问睡不睡（2026-11-19）
    threading.Thread(target=digest_loop, args=(bot,), daemon=True).start()  # 记忆压缩（2026-11-21）
    system_events.add("启动", "molly 启动")

    def on_event(ev):
        try:
            handle_incoming(bot, ev)
            handle_request(bot, ev)
            handle_notice(bot, ev)
        except Exception as e:
            log(f"[event] {e}")

    log(f"molly(py) 启动，self={config.SELF_ID}")
    bot.listen(on_event)


if __name__ == "__main__":
    main()
