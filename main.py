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

import config
import actions
import file_reader
import memory
import notes
import search
import stickers

LETTER_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "主人赠言.txt")
MANUAL_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "操作手册.md")


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


def handle_reminder_event(bot, payload):
    """闹钟到点：她自己决定做点什么（发消息/记事/不理会）。"""
    note = str(payload.get("note") or "").strip()
    if not note:
        return
    system = build_system(now_text(), events=EVENTS)
    prompt = (
        f"（你之前给自己定了个闹钟：「{note}」。现在到点了。）\n"
        "想做什么就写动作：<send qq=\"对方QQ\">要发的话</send>、<note>要记的</note>；"
        "什么都不想做就只回 <skip/>。不要解释。"
    )
    reply, err = chat(system, [{"role": "user", "content": prompt}], max_tokens=200)
    if not reply or "<skip" in reply.lower():
        log(f"[timer] 到点了，她没打算做什么（{note[:30]}）")
        return
    # 执行她决定的动作
    for m in re.finditer(r'<send\s+qq="?(\d{5,12})"?\s*>([\s\S]*?)</send>', reply, re.I):
        target, body = m.group(1), m.group(2).strip()
        if body and is_safe(body) and can_send():
            memory.append(target, "assistant", body)
            for piece in split_bubbles(body):
                if is_safe(piece):
                    bot.send_private(target, piece)
                    time.sleep(bubble_gap())
            log(f"[timer] 主动发 → {target}: {body[:40]}")
    for m in re.finditer(r'<note(?:\s+cat="([^"]*)")?\s*>([\s\S]*?)</note>', reply, re.I):
        cat, body = m.group(1), m.group(2).strip()
        if body:
            notes.add(body, str(cat or "").strip())
            log(f"[timer][note] 记下：{body[:40]}")


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
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def record_event(text):
    with LOCK:
        EVENTS.append(text)
        del EVENTS[:-20]


def now_text():
    return datetime.now().strftime("%Y-%m-%d %A %H:%M:%S")


# ==================== 发送 ====================
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
            "想补就直接写要补的那句话（别重复刚才的、别和前面矛盾）；不想补就只回 <skip/>。不要解释。）",
        }
    )
    reply, err = chat(system, ctx, max_tokens=150)
    if not reply:
        return None
    r = reply.strip()
    if "<skip" in r.lower() or len(r) > 200:
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
        r'<send\s+(?:qq=["\']?(\d{5,12})["\']?|name=["\']?([^"\'>\s]+)["\']?)\s*>\s*([\s\S]*?)\s*</send>',
        take_send,
        reply,
        flags=re.I,
    )
    reply = re.sub(r"<sep\s*/?>", "\n", reply)
    # 戳一戳 / 撤回自己刚发的（2026-11-08）
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
    reply = re.sub(r"<sticker>\s*[^<]*?\s*</sticker>", "", reply, flags=re.I)
    sticker_notes = re.findall(r'<sticker-note\s+file="([^"]+)"\s*>\s*([^<]*?)\s*</sticker-note>', reply, re.I)
    reply = re.sub(r'<sticker-note\s+file="[^"]+"\s*>\s*[^<]*?\s*</sticker-note>', "", reply, flags=re.I)
    for fname, body in sticker_notes:
        bits = body.split("|", 1)
        stickers.describe(fname.strip(), bits[0].strip(), bits[1].strip() if len(bits) > 1 else "")

    pieces = split_bubbles(reply)
    sent = 0
    i = 0
    while i < len(pieces) and sent < config.MAX_BUBBLES:
        piece = pieces[i]
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
        log(f"→ {conv['id']}: {piece[:40]}")
        sent += 1
        if i < len(pieces):
            time.sleep(bubble_gap())
        elif system and sent < config.MAX_BUBBLES:
            extra = confirm_continue(system, piece, context)
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
        target = qq or resolve_qq_by_name(bot, name)
        if target:
            bot.send_private(target, body)
            memory.append(target, "assistant", body)
            log(f"→ 定向 {target}: {body[:40]}")

    for q in sticker_hits[:1]:
        path = stickers.find(q)
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
    urls, sticker_urls = [], []
    for seg in ev.get("message") or []:
        if not isinstance(seg, dict):
            continue
        if seg.get("type") == "image":
            data = seg.get("data") or {}
            url = data.get("url") or data.get("file")
            if not url:
                continue
            urls.append(str(url))
            if data.get("sub_type") == 1:
                sticker_urls.append(str(url))
        elif seg.get("type") == "video":
            # 视频（2026-11-08）：URL 存进 images，llm 侧会 ffmpeg 抽帧
            data = seg.get("data") or {}
            url = data.get("url") or data.get("file")
            if url:
                urls.append(str(url))
    return urls, sticker_urls


def extract_files(ev):
    """QQ 文件消息（2026-11-08 主人：让她看得懂文件）。"""
    out = []
    for seg in ev.get("message") or []:
        if not isinstance(seg, dict) or seg.get("type") != "file":
            continue
        data = seg.get("data") or {}
        url = data.get("url") or data.get("file")
        name = data.get("name") or data.get("file") or ""
        if url:
            out.append({"url": str(url), "name": str(name)})
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
        t = time.strftime("%m-%d %H:%M", time.localtime((m.get("at") or 0) / 1000))
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
            ts = time.strftime("%m-%d %H:%M", time.localtime((m.get("at") or 0) / 1000))
            who = "你" if m.get("role") == "assistant" else "对方"
            lines.append(f"- [{ts}] {who}：{str(m.get('text') or '')[:100]}")
        return "（你们最早聊的内容，翻到了：\n" + "\n".join(lines) + "）"
    if re.search(r"之前|上次|以前|记得|说过|翻[一翻下]|记录", t):
        msgs = memory.recall(user_id, "", limit=20)
        if not msgs:
            return ""
        lines = []
        for m in msgs:
            ts = time.strftime("%m-%d %H:%M", time.localtime((m.get("at") or 0) / 1000))
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
    images, sticker_urls = extract_images(ev)
    # 引用回复：把被引用的原话拼进正文，她就知道在回哪句（2026-11-08）
    quote = extract_quote(bot, ev)
    if quote:
        text = f"（他回复的是：「{quote}」）{text}"
    # 文件消息：下载并解析（2026-11-08 让她看得懂文件）
    for f in extract_files(ev)[:2]:
        content, ferr = file_reader.read_remote_file(f["url"], f["name"])
        if content:
            text += f"\n（他发来文件「{f['name']}」，内容如下：\n{content}\n）"
            log(f"[file] 读了：{f['name']}（{len(content)} 字）")
        else:
            text += f"\n（他发来文件「{f['name']}」，但{ferr}）"
            log(f"[file] 读不了：{f['name']}（{ferr}）")
    sender = ev.get("sender") or {}
    display = sender.get("card") or sender.get("nickname") or user_id

    if group_id and f"[CQ:at,qq={config.SELF_ID}]" not in text and config.SELF_ID not in text:
        return
    if group_id:
        text = text.replace(f"[CQ:at,qq={config.SELF_ID}]", "").strip()
    if not text and not images:
        return

    log(f"← {user_id}{'@' + group_id if group_id else ''}: {text[:40]}")
    if not group_id:
        memory.ensure_person(user_id, display)
    if config.STICKER_LEARN:
        for u in sticker_urls[:2]:
            stickers.learn(u, sender.get("nickname") or "")
    memory.append(user_id, "user", text, images, message_id=ev.get("message_id"))

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


def handle_aftertalk_event(bot, payload):
    """聊完之后的自由发言（2026-11-08 主人：聊完可以找任何人吐槽/分享，她决定）。"""
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
            msgs = j.get("messages") or []
            if not msgs:
                continue
            last = max((m.get("at") or 0) for m in msgs) / 1000
            if now - last < 86400:
                candidates.append((qq, j.get("name") or qq))
        if not candidates:
            return
        pool = "\n".join(f"- {name}（QQ {qq}）" for qq, name in candidates[:8])
        system = build_system(now_text(), events=EVENTS)
        prompt = (
            f"你刚跟「{with_name}」聊完。现在你有空，想不想跟别人说点什么？\n"
            f"可以找的人：\n{pool}\n\n"
            '想发就写 <send qq="对方的QQ号">要发的话</send>（可以吐槽、分享、想说什么说什么）；'
            "不想发就只回 <skip/>。不要解释。"
        )
        reply, err = chat(system, [{"role": "user", "content": prompt}], max_tokens=250)
        if not reply or "<skip" in reply.lower():
            return
        if not is_safe(reply) or not can_send():
            return
        LAST_AFTERTALK[0] = now
        for m in re.finditer(r'<send\s+qq="?(\d{5,12})"?\s*>([\s\S]*?)</send>', reply, re.I):
            target, body = m.group(1), m.group(2).strip()
            if not body or not is_safe(body):
                continue
            memory.append(target, "assistant", body)
            for piece in split_bubbles(body):
                if is_safe(piece):
                    bot.send_private(target, piece)
                    time.sleep(bubble_gap())
            log(f"[aftertalk] → {target}: {body[:40]}")
    except Exception as e:
        log(f"[aftertalk] {e}")


def sep(title):
    return f"\n\n---------------- {title} ----------------\n"


def build_full_system(user_id, display):
    """统一组装上下文（2026-11-08 主人定的顺序：赠言→人设→记事本→手册→认人→操作→要求→别人）。"""
    parts = []
    letter = load_letter()
    if letter:
        parts.append(sep("主人赠言") + letter)
    parts.append(sep("你的人设") + build_system(now_text(), events=EVENTS))
    # 早安/晚安提示（2026-11-08：她可以自己决定说）
    hour = datetime.now().hour
    if 6 <= hour <= 9:
        parts.append(sep("现在是早上") + "（想跟谁问声早安就自己说，不想说就不说，没人逼你。）")
    elif 21 <= hour <= 23:
        parts.append(sep("现在是晚上") + "（想跟谁说晚安就自己说，不想说就不说。）")
    parts.append(sep("记事本") + notes.for_prompt())
    manual = load_manual()
    if manual:
        parts.append(sep("操作手册") + manual)
    if str(user_id) == config.OWNER_UIN:
        who = (
            f"（现在跟你说的是你主人 QQ {config.OWNER_UIN}，昵称「{display}」——"
            "名字很长带符号，但就是他本人，别当陌生人。）"
        )
    elif str(user_id) == config.MAIN_USER_QQ:
        who = f"（现在跟你说的是户山香顺澄 QQ {config.MAIN_USER_QQ}，昵称「{display}」，老熟人。）"
    else:
        who = f"（现在跟你说的是 QQ {user_id}，昵称「{display}」。）"
    parts.append(sep("现在是谁在说话") + who)
    parts.append(
        sep("你最近在终端做过的事（带时间）")
        + actions.for_prompt()
        + "\n（想查更早的操作：<actions>关键词</actions>）"
    )
    parts.append(
        sep("回复要求（很重要）")
        + (
            "1. 只接他最后说的那句话，别翻旧话题；\n"
            "2. 一两句就够，最多两条气泡；\n"
            "3. 像真人发 QQ，短、随口；\n"
            "4. 他只发「...」「哦」就随口接一句；\n"
            "5. 不许编时间（「这么晚才来找我」）；\n"
            "6. 要记事必须写 <note>内容</note>（只嘴上说没用）；\n"
            "7. 想延时用 <timer minutes=\"2\">要做的事</timer>；\n"
            "8. 查东西用 <search>关键词</search>，翻自己操作 <actions>关键词</actions>。"
        )
    )
    others = memory.all_recent(user_id)
    if others:
        parts.append(
            sep("别人那边最近在说什么（是别人，不是现在这个人）")
            + others
            + "\n（这些是别人跟你的聊天，别把别人的话安到这个人头上。）"
        )
    try:
        recent_user_text = " ".join(str(m.get("text") or "") for m in memory.recent(user_id, 2))
        recalled = auto_recall(user_id, recent_user_text)
        if recalled:
            parts.append(sep("你翻到的记录") + recalled)
    except Exception as e:
        log(f"[recall] auto fail: {e}")
    return "\n".join(parts)


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

    system = build_full_system(user_id, slot.get("display") or user_id)

    # 本对话最近 25 条上文（其他对话已在 system 里）
    msgs = [
        {"role": m.get("role"), "text": m.get("text"), "images": m.get("images") or []}
        for m in memory.recent(user_id, config.CONTEXT_LIMIT)
    ]

    time.sleep(reaction_delay())
    reply, err = chat(system, msgs)
    if not reply:
        log(f"[model] {err}")
        return
    # 查更早的操作（2026-11-08 主人要求）
    for _ in range(2):
        m = re.search(r"<actions>\s*(.*?)\s*</actions>", reply, re.I | re.S)
        if not m:
            break
        kw = m.group(1).strip()
        log(f"[actions] 查：{kw}")
        hits = actions.search(kw)
        lines = []
        for a in hits:
            ts = time.strftime("%m-%d %H:%M", time.localtime((a.get("at") or 0) / 1000))
            lines.append(f"- [{ts}] {a.get('kind')}：{a.get('detail')}")
        reply = re.sub(r"<actions>\s*.*?\s*</actions>", "", reply, flags=re.I | re.S).strip()
        msgs = msgs + [
            {"role": "assistant", "text": f"<actions>{kw}</actions>"},
            {"role": "user", "text": "（你查到更早的操作：\n" + ("\n".join(lines) or "没有相关记录") + "）"},
        ]
        reply2, err2 = chat(system, msgs)
        if not reply2:
            break
        reply = reply2

    # 翻聊天记录（她主动查，最多 2 轮；2026-11-08 主人：她老说自己翻不到）
    for _ in range(2):
        m = re.search(r"<recall>\s*(.*?)\s*</recall>", reply, re.I | re.S)
        if not m:
            break
        kw = m.group(1).strip()
        log(f"[recall] 翻：{kw}")
        actions.log_action("翻记录", kw or "翻了更早的记录")
        results = recall_for_model(user_id, kw)
        reply = re.sub(r"<recall>\s*.*?\s*</recall>", "", reply, flags=re.I | re.S).strip()
        msgs = msgs + [
            {"role": "assistant", "text": f"<recall>{kw}</recall>"},
            {"role": "user", "text": f"（你翻到的聊天记录：\n{results}）"},
        ]
        reply2, err2 = chat(system, msgs)
        if not reply2:
            break
        reply = reply2

    # 联网搜索（她主动搜，最多 2 轮）
    for _ in range(2):
        m = re.search(r"<search>\s*(.*?)\s*</search>", reply, re.I | re.S)
        if not m:
            break
        q = m.group(1).strip()
        if not q:
            break
        log(f"[search] 搜：{q}")
        actions.log_action("搜索", f"搜了「{q}」")
        results = search.search_web(q)
        reply = re.sub(r"<search>\s*.*?\s*</search>", "", reply, flags=re.I | re.S).strip()
        msgs = msgs + [
            {"role": "assistant", "text": f"<search>{q}</search>"},
            {"role": "user", "text": f"（你搜「{q}」的结果：\n{results}）"},
        ]
        reply2, err2 = chat(system, msgs)
        if not reply2:
            log(f"[search] 二次生成失败：{err2}")
            break
        reply = reply2
    log(f"← 模型: {reply[:60]}")

    # 她可以选择不回（拒绝权，2026-11-08）
    if re.search(r"<skip\s*/?>", reply, re.I) and not re.search(r"[\u4e00-\u9fa5A-Za-z0-9]{2,}", re.sub(r"<skip\s*/?>", "", reply, flags=re.I)):
        log("[skip] 她这轮不想回")
        return

    conv = {"kind": "group" if group_id else "private", "id": group_id or user_id, "user_id": user_id}
    send_reply(bot, conv, reply, system=system, context=msgs)
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


def handle_opportunity_event(bot):
    """每小时的机会：她自己在卧室里决定——发说说 / 点赞动态 / 找人 / 跳过（2026-11-08）。"""
    try:
        if in_sleep():
            return
        now = time.time()
        gap = config.PROACTIVE_MIN_GAP_MINUTES * 60 * random.uniform(
            1 - config.PROACTIVE_GAP_JITTER, 1 + config.PROACTIVE_GAP_JITTER
        )
        if now - LAST_PROACTIVE[0] < gap:
            return

        # 可以找的人
        candidates = []
        for p, j in memory.iter_people():
            qq = str(j.get("qq") or "")
            if not re.fullmatch(r"\d{5,12}", qq):
                continue
            msgs = j.get("messages") or []
            if not msgs:
                continue
            last = max((m.get("at") or 0) for m in msgs) / 1000
            if now - last > 600:
                candidates.append((qq, j.get("name") or qq))
        pool = "\n".join(f"- {name}（QQ {qq}）" for qq, name in candidates[:8]) or "（暂时没人）"

        # 空间动态（看 + 可以点赞）
        feed_lines = []
        try:
            data = bot.get_qzone_msg_list(count=6)
            for f in (data.get("msglist") or [])[:6]:
                feed_lines.append(
                    f"- tid={f.get('tid')}：{str(f.get('content') or '')[:60]}"
                )
        except Exception as e:
            log(f"[qzone] 拉动态失败：{e}")
        feed_text = "\n".join(feed_lines) or "（空间里没有动态）"

        system = build_system(now_text(), events=EVENTS)
        prompt = (
            f"现在是 {now_text()}。你有空，想做什么由你自己决定（只做一件事，或跳过）：\n"
            '1. 发条说说：<qzone>内容</qzone>\n'
            '2. 给喜欢的动态点个赞：<like tid="动态的tid"/>\n'
            '3. 给动态写句评论：<comment tid="动态的tid">评论内容</comment>\n'
            '4. 找人说句话：<send qq="对方的QQ号">要发的话</send>\n'
            "5. 什么都不想做：<skip/>\n\n"
            f"# 你的空间动态\n{feed_text}\n\n# 可以找的人\n{pool}\n\n"
            "不要解释。"
        )
        reply, err = chat(system, [{"role": "user", "content": prompt}], max_tokens=300)
        if not reply or "<skip" in reply.lower():
            return

        acted = False
        # 1) 发说说
        m = re.search(r"<qzone>\s*([\s\S]*?)\s*</qzone>", reply, re.I)
        if m:
            body = m.group(1).strip()
            if body and is_safe(body):
                bot.send_qzone_msg(body)
                record_event(f"你发了一条说说：{body[:40]}")
                actions.log_action("说说", body[:60])
                log(f"[qzone] 说说 → {body[:40]}")
                acted = True
        # 2) 点赞
        for m in re.finditer(r'<like\s+tid=["\']?([0-9a-zA-Z]+)["\']?\s*/?>', reply, re.I):
            tid = m.group(1)
            bot.like_qzone(tid)
            actions.log_action("点赞", f"给动态 {tid} 点了赞")
            log(f"[qzone] 点赞 {tid}")
            acted = True
        # 3) 评论
        for m in re.finditer(
            r'<comment\s+tid=["\']?([0-9a-zA-Z]+)["\']?\s*>([\s\S]*?)</comment>', reply, re.I
        ):
            tid, body = m.group(1), m.group(2).strip()
            if body and is_safe(body):
                bot.comment_qzone(tid, body)
                actions.log_action("评论", f"评论动态 {tid}：{body[:40]}")
                log(f"[qzone] 评论 {tid}")
                acted = True
        # 3) 找人
        for m in re.finditer(r'<send\s+qq="?(\d{5,12})"?\s*>([\s\S]*?)</send>', reply, re.I):
            target = m.group(1)
            body = m.group(2).strip()
            if not body or not is_safe(body):
                continue
            if in_school_time() and target == config.MAIN_USER_QQ and random.random() > config.SCHOOL_BREAK_CHANCE:
                continue
            memory.append(target, "assistant", body)
            for piece in split_bubbles(body):
                if is_safe(piece):
                    bot.send_private(target, piece)
                    time.sleep(bubble_gap())
            actions.log_action("找人", f"发给 {target}：{body[:50]}")
            log(f"主动 → {target}: {body[:40]}")
            acted = True

        if acted:
            LAST_PROACTIVE[0] = now
    except Exception as e:
        log(f"[opportunity] {e}")


# ==================== 启动 ====================
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
