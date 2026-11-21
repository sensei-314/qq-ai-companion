"""
tools.py —— 她的工具定义与执行（2026-11-13 function calling 大改）

模型通过 tool_calls 调用这些工具，代码执行后把结果回灌。
不再依赖 <note>/<search> 这类文本标签。
"""

import json
import re
import time

import actions
import aliveness
import config
import memory
import mom_chat
import short_notes

# 动态缓存：tid -> {uin, abstime, nickname}（2026-11-21 点赞要 target_uin+abstime）
FEED_CACHE = {}
import notes
import search
import stickers

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "write_note",
            "description": "写入私人记事本（只存在本地，不会发给任何人）。重要的事、主人的偏好、自己的心情都记这里。",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "要记的内容"},
                    "category": {"type": "string", "description": "分类，如 心情/偏好/主人"},
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_short_note",
            "description": (
                "记短期备忘（5 天有效，过期自动消失）：答应别人的事、约定、要办的事。"
                "心情、感受、对自己的认识请用 write_note（长期）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "要记的承诺/约定/待办"},
                    "category": {"type": "string", "description": "分类，可省略"},
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "联网搜索实时信息（新闻/价格/天气/资料）。结果只给你自己看，别原样贴给对方。",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "搜索关键词"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_message",
            "description": "给指定 QQ 发一句话（不在当前对话里显示）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "qq": {"type": "string", "description": "对方的 QQ 号"},
                    "content": {"type": "string", "description": "要发的话"},
                },
                "required": ["qq", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "poke",
            "description": "戳一戳某人。",
            "parameters": {
                "type": "object",
                "properties": {"qq": {"type": "string", "description": "对方的 QQ 号"}},
                "required": ["qq"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_timer",
            "description": "给自己定个闹钟，到点会提醒你。",
            "parameters": {
                "type": "object",
                "properties": {
                    "minutes": {"type": "number", "description": "多少分钟后"},
                    "note": {"type": "string", "description": "到点要做的事"},
                },
                "required": ["minutes", "note"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recall_msg",
            "description": "撤回你刚发出去的那条消息。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_history",
            "description": "翻你和当前这个人更早的聊天记录。",
            "parameters": {
                "type": "object",
                "properties": {"keyword": {"type": "string", "description": "关键词，空则取最近"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_actions",
            "description": "查你自己在终端做过的事（搜过什么、记过什么）。",
            "parameters": {
                "type": "object",
                "properties": {"keyword": {"type": "string", "description": "关键词"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "like_feed",
            "description": "给一条空间动态点赞。",
            "parameters": {
                "type": "object",
                "properties": {"tid": {"type": "string", "description": "动态的 tid"}},
                "required": ["tid"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_remark",
            "description": "给你认识的某个人的「备注」换一下（你自己给他起的称呼）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "qq": {"type": "string", "description": "对方的 QQ 号"},
                    "remark": {"type": "string", "description": "新的备注；空字符串表示清掉"},
                },
                "required": ["qq", "remark"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_qq_remark",
            "description": "改某个好友在 QQ 上的备注（会真的改掉，别乱用）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "qq": {"type": "string", "description": "对方的 QQ 号"},
                    "remark": {"type": "string", "description": "新的 QQ 备注；空字符串表示清掉"},
                },
                "required": ["qq", "remark"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_group",
            "description": "在某个群里说一句（群里人都在看，别频繁说）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "group_id": {"type": "string", "description": "群号"},
                    "content": {"type": "string", "description": "要说的话"},
                },
                "required": ["group_id", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_guilds",
            "description": "看她加入的 QQ 频道列表（频道帖子/发帖暂不支持）。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_feeds",
            "description": "看好友动态：返回谁发了什么、赞数、tid。好友动态只能看，点赞/评论接口不支持。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "profile_like",
            "description": "给好友的 QQ 名片/主页点赞（一天能点几次）。",
            "parameters": {
                "type": "object",
                "properties": {"qq": {"type": "string", "description": "对方的 QQ 号"}},
                "required": ["qq"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_comments",
            "description": "看一条空间动态下面的评论（谁说了什么、点赞数）。",
            "parameters": {
                "type": "object",
                "properties": {"tid": {"type": "string", "description": "动态的 tid"}},
                "required": ["tid"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "comment_feed",
            "description": (
                "给一条空间动态写一条评论（公开留言，不是聊天）：一两句就够，不追问、不客套；"
                "同一条动态只评一次。要回复某条评论就带上 parent_comment_id。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tid": {"type": "string", "description": "动态的 tid"},
                    "content": {"type": "string", "description": "评论内容"},
                    "parent_comment_id": {
                        "type": "string",
                        "description": "回复某条评论时填那条评论的 comment_id（可选）",
                    },
                },
                "required": ["tid", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "post_qzone",
            "description": "发一条 QQ 空间说说。",
            "parameters": {
                "type": "object",
                "properties": {"content": {"type": "string", "description": "说说内容，一两句"}},
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_sleep",
            "description": "决定今晚睡不睡、几点睡；以及明天几点醒（最晚 7:00）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "sleep": {"type": "boolean", "description": "今晚睡不睡（false = 熬穿）"},
                    "sleep_at": {"type": "string", "description": "几点睡（HH:MM，可省略）"},
                    "wake_at": {"type": "string", "description": "明天几点醒（HH:MM，最晚 07:00）"},
                },
                "required": ["sleep"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "talk_to_mom",
            "description": (
                "跟「妈妈」（把你在 DSH 里一点点拼出来的那个会话）说一句话。"
                "说完存进固定记录，妈妈被主人叫来时会看到并回你。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "想对妈妈说的话，一两句"},
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_stickers",
            "description": "看看你的表情包库里有哪几张（想发图先看这个，再用 send_sticker 选）。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_sticker",
            "description": "从你的表情包库里发一张图。",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "描述或用途关键词"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "skip_reply",
            "description": "这一轮不想回，什么都不做。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


def execute_tool(name, args, ctx):
    """执行一个工具调用。ctx: {bot, conv, user_id, can_send}"""
    # 统一记录：她做过的每个操作都留痕（2026-11-21）
    try:
        _brief = str(args.get("content") or args.get("text") or args.get("query") or args.get("tid") or "")[:40]
        actions.log_action("调用", f"{name}" + (f"：{_brief}" if _brief else ""))
    except Exception:
        pass
    bot = ctx.get("bot")
    conv = ctx.get("conv") or {}
    user_id = str(ctx.get("user_id") or "")
    can_send = ctx.get("can_send") or (lambda: True)
    try:
        if name == "write_note":
            body = str(args.get("content") or "").strip()
            if not body:
                return "内容为空，没记"
            notes.add(body, str(args.get("category") or "").strip())
            ctx["_notes_changed"] = True
            actions.log_action("记事", body[:80])
            return "已写进记事本"
        if name == "write_short_note":
            body = str(args.get("content") or "").strip()
            if not body:
                return "内容为空，没记"
            item = short_notes.add(body, str(args.get("category") or "").strip())
            if not item:
                return "没写进去（文件读写失败）"
            actions.log_action("短期备忘", body[:60])
            return "记进短期备忘了（5 天后自动消失）"
        if name == "search_web":
            q = str(args.get("query") or "").strip()
            if not q:
                return "没给关键词"
            r = search.search_web(q)
            actions.log_action("搜索", f"搜了「{q}」")
            return r[:4000]
        if name == "send_message":
            qq = str(args.get("qq") or "")
            body = str(args.get("content") or "").strip()
            if not re.fullmatch(r"\d{5,12}", qq) or not body:
                return "参数错误：需要 qq 和 content"
            if not can_send():
                return "发送太频繁，先不发"
            # 工作日上课时间别发（学生都在学校，看不到，2026-11-15）
            if aliveness.in_school_time():
                return "现在是上课时间，他们都在学校，发了也看不到；等晚上放学再说"
            # 同一人 24h 内主动最多 3 次（2026-11-14）
            check = ctx.get("proactive_ok")
            if check and not check(qq):
                return "今天找这个人已经够多了，先别找了"
            bot.send_private(qq, body)
            memory.append(qq, "assistant", body)
            rec = ctx.get("proactive_record")
            if rec:
                rec(qq)
            actions.log_action("找人", f"发给 {qq}：{body[:50]}")
            return f"已发给 QQ {qq}"
        if name == "poke":
            qq = str(args.get("qq") or "")
            if not re.fullmatch(r"\d{5,12}", qq):
                return "参数错误：需要 qq"
            bot.send_poke(qq)
            actions.log_action("戳人", f"戳了 QQ {qq}")
            return f"戳了 QQ {qq}"
        if name == "set_timer":
            try:
                minutes = float(args.get("minutes") or 0)
            except Exception:
                minutes = 0
            note = str(args.get("note") or "").strip()
            if minutes <= 0 or not note:
                return "参数错误：需要 minutes 和 note"
            if minutes > 1440:
                minutes = 1440
            ctx.get("schedule_reminder")(minutes, note)
            return f"定了 {minutes:g} 分钟后的闹钟"
        if name == "recall_msg":
            mids = list(ctx.get("last_sent") or [])
            if not mids:
                return "没有可撤回的消息"
            bot.delete_msg(mids[-1])
            actions.log_action("撤回", f"撤回了 {mids[-1]}")
            return "撤回成功"
        if name == "search_history":
            kw = str(args.get("keyword") or "").strip()
            # 2026-11-15：keyword 可能是「某人的名字/QQ」→ 直接翻那个人的记录
            target_qq = None
            if re.fullmatch(r"\d{5,12}", kw):
                target_qq = kw
            else:
                for _p, _j in memory.iter_people():
                    nm = str(_j.get("name") or "")
                    if kw and (kw in nm or nm in kw):
                        target_qq = str(_j.get("qq"))
                        break
            if target_qq:
                msgs = memory.recent(target_qq, 30)
                if not msgs:
                    return f"和「{kw}」还没有聊天记录"
                lines = []
                for mm in msgs:
                    ts = time.strftime("%m-%d %H:%M", time.localtime((mm.get("at") or 0) / 1000))
                    who = "你" if mm.get("role") == "assistant" else "对方"
                    lines.append(f"- [{ts}] {who}：{str(mm.get('text') or '')[:100]}")
                actions.log_action("翻记录", f"翻了「{kw}」的记录")
                return "\n".join(lines)
            msgs = memory.recall(user_id, kw, 20)
            if not msgs:
                return f"没找到和「{kw}」有关的记录"
            lines = []
            for mm in msgs:
                ts = time.strftime("%m-%d %H:%M", time.localtime((mm.get("at") or 0) / 1000))
                who = "你" if mm.get("role") == "assistant" else "对方"
                lines.append(f"- [{ts}] {who}：{str(mm.get('text') or '')[:100]}")
            actions.log_action("翻记录", kw or "翻了更早的记录")
            return "\n".join(lines)
        if name == "search_actions":
            kw = str(args.get("keyword") or "").strip()
            hits = actions.search(kw)
            if not hits:
                return "没有相关操作记录"
            lines = []
            for a in hits:
                ts = time.strftime("%m-%d %H:%M", time.localtime((a.get("at") or 0) / 1000))
                lines.append(f"- [{ts}] {a.get('kind')}：{a.get('detail')}")
            return "\n".join(lines)
        if name == "like_feed":
            tid = str(args.get("tid") or "")
            if not tid:
                return "缺 tid"
            # 短 key 不是真 tid，点了也是假成功（2026-11-21）
            if len(tid) < 20 or not re.fullmatch(r"[0-9a-fA-F]+", tid):
                return "这条动态的赞点不了（接口只认 tid，这个只是列表标识），只能看看"
            _c = FEED_CACHE.get(tid) or {}
            rr = bot.like_qzone(tid, _c.get("uin", ""), _c.get("abstime", 0))
            if (rr or {}).get("status") != "ok":
                return f"点赞失败：{(rr or {}).get('wording') or ''}"
            # 找一下这条动态是谁发的、说了啥（2026-11-15）
            who, what = "?", ""
            try:
                feeds = (bot.get_qzone_feeds(20) or {}).get("feeds") or []
                hit = next((f for f in feeds if str(f.get("key")) == tid), None)
                if hit:
                    who = f"{hit.get('nickname') or hit.get('uin')}({hit.get('uin')})"
                    what = re.sub(r"<[^>]+>", " ", str(hit.get("html") or ""))
                    what = re.sub(r"\s+", " ", what).strip()[:50]
            except Exception:
                pass
            if who != "?":
                actions.log_action("点赞", f"给 {who} 的动态点了赞：{what}")
                return f"赞了 {who} 的动态：{what or '(没文字)'}"
            actions.log_action("点赞", f"给动态 {tid} 点了赞")
            return f"赞了 {tid}"
        if name == "set_remark":
            qq = str(args.get("qq") or "")
            remark = str(args.get("remark") or "").strip()
            if not re.fullmatch(r"\d{5,12}", qq):
                return "参数错误：需要 qq"
            p_, j_ = memory.find_person(qq)
            if not p_:
                return f"没有 QQ {qq} 的记录"
            j_["remark"] = remark
            try:
                with open(p_, "w", encoding="utf-8") as f:
                    json.dump(j_, f, ensure_ascii=False, indent=1)
            except Exception as e:
                return f"保存失败：{e}"
            actions.log_action("改备注", f"给 {qq} 的备注改成「{remark or 'none'}」")
            return f"改好了：{remark or 'none'}"
        if name == "send_group":
            gid = str(args.get("group_id") or "")
            body = str(args.get("content") or "").strip()
            if not re.fullmatch(r"\d{5,12}", gid) or not body:
                return "参数错误：需要 group_id 和 content"
            if aliveness.in_school_time():
                return "现在是上课时间，群里也是学生，别刷屏；等晚上再说"
            if not ctx.get("group_speak_ok", lambda g, c: True)(gid, body):
                return "这句话你在群里说过了，别重复"
            check = ctx.get("group_ok")
            if check and not check(gid):
                return "这个群刚说过话，先等等"
            bot.send_group(gid, body)
            rec = ctx.get("group_record")
            if rec:
                rec(gid)
            memory.append(gid, "assistant", body)
            actions.log_action("群发言", f"在群 {gid} 说：{body[:40]}")
            return f"在群 {gid} 说了"
        if name == "set_qq_remark":
            qq = str(args.get("qq") or "")
            remark = str(args.get("remark") or "").strip()
            if not re.fullmatch(r"\d{5,12}", qq):
                return "参数错误：需要 qq"
            r = bot.set_friend_remark(qq, remark)
            if (r or {}).get("status") != "ok":
                return f"改失败了：{(r or {}).get('wording') or r}"
            p_, j_ = memory.find_person(qq)
            if p_:
                j_["qqRemark"] = remark
                try:
                    with open(p_, "w", encoding="utf-8") as f:
                        json.dump(j_, f, ensure_ascii=False, indent=1)
                except Exception:
                    pass
            actions.log_action("改QQ备注", f"把 {qq} 的备注改成「{remark or '清空'}」")
            return f"QQ 备注改好了：{remark or '已清空'}"
        if name == "read_guilds":
            guilds = bot.get_guild_list()
            if not guilds:
                return "（还没加入任何频道）"
            lines = [f"- {g.get('guild_name') or '频道'}（guild_id={g.get('guild_id')}）" for g in guilds]
            actions.log_action("看频道", f"查了 {len(guilds)} 个频道")
            return "\n".join(lines)
        if name == "read_feeds":
            data = bot.get_qzone_feeds(10)
            feeds = data.get("feeds") or []
            lines = []
            detail_used = 0
            for f in feeds[:8]:
                # 别把自己发的当「好友动态」（2026-11-15）
                if str(f.get("uin")) == str(config.SELF_ID):
                    continue
                tid = str(f.get("tid") or "")
                text = ""
                # 有 tid 的用 detail 读真实内容（2026-11-21）
                if tid:
                    FEED_CACHE[tid] = {
                        "uin": str(f.get("uin") or ""),
                        "abstime": int(f.get("time") or 0),
                        "nickname": f.get("nickname") or f.get("uin"),
                    }
                if tid and detail_used < 3:
                    try:
                        d = bot.qzone_detail(tid) or {}
                        text = str(d.get("content") or "").strip()
                        detail_used += 1
                    except Exception:
                        text = ""
                if not text:
                    html = str(f.get("html") or "")
                    html = re.sub(r"<a[^>]*>(.*?)</a>", r"\1", html, flags=re.S | re.I)
                    text = re.sub(r"<[^>]+>", " ", html)
                    text = re.sub(r"\s+", " ", text).replace("&nbsp;", " ").strip()
                text = text[:120]
                like = f.get("like_count")
                tag = "" if tid else "（这条读不到详情）"
                lines.append(
                    f"- {f.get('nickname') or f.get('uin')}（{f.get('uin')}）：{text or '（没有文字）'}"
                    f"｜赞 {like if like is not None else '?'}{tag}"
                    + (f"｜tid={tid}" if tid else "")
                )
            actions.log_action("看动态", "刷了好友动态")
            return "\n".join(lines) or "（没有新动态）"
        if name == "profile_like":
            qq = str(args.get("qq") or "")
            if not re.fullmatch(r"\d{5,12}", qq):
                return "参数错误：需要 qq"
            bot.send_like(qq)
            actions.log_action("主页赞", f"给 QQ {qq} 的主页点了赞")
            return f"给 {qq} 的主页点了赞"
        if name == "read_comments":
            tid = str(args.get("tid") or "")
            if not tid:
                return "缺 tid"
            d = bot.qzone_detail(tid)
            lines = []
            for c in d.get("comments") or []:
                lines.append(f"- {c.get('name') or c.get('uin')}：{c.get('content') or ''}（comment_id={c.get('comment_id')}）")
            actions.log_action("看评论", f"动态 {tid} 的评论")
            return "\n".join(lines) or "这条动态还没有评论"
        if name == "comment_feed":
            tid = str(args.get("tid") or "")
            body = str(args.get("content") or "").strip()
            if tid and (len(tid) < 20 or not re.fullmatch(r"[0-9a-fA-F]+", tid)):
                return "这条动态评不了（接口只认 tid，这个只是列表标识），只能看看"
            parent = str(args.get("parent_comment_id") or "").strip() or None
            if not tid or not body:
                return "缺 tid 或内容"
            # 同一条动态 24h 最多评论一次（不同动态不限，2026-11-15）
            if not ctx.get("comment_ok", lambda t: True)(tid):
                return "这条动态你已经评论过了，别在一条下面刷"
            bot.comment_qzone(tid, body, parent)
            rec_c = ctx.get("comment_record")
            if rec_c:
                rec_c(tid)
            actions.log_action("评论", f"动态 {tid}：{body[:40]}")
            return f"评论了 {tid}"
        if name == "post_qzone":
            body = str(args.get("content") or "").strip()
            if not body:
                return "内容为空"
            if not ctx.get("qzone_ok", lambda: True)():
                return "今天说说发够了（24h 最多 2 条），别再刷了"
            bot.send_qzone_msg(body)
            rec_qz = ctx.get("qzone_record")
            if rec_qz:
                rec_qz()
            actions.log_action("说说", body[:60])
            return "说说已发"
        if name == "set_sleep":
            import json as _j

            sleep = bool(args.get("sleep"))
            sleep_at = str(args.get("sleep_at") or "").strip()
            wake_at = str(args.get("wake_at") or "").strip()
            d = {}
            try:
                with open("sleep_plan.json", encoding="utf-8") as f:
                    d = _j.load(f)
            except Exception:
                d = {}
            d.update(
                {
                    "sleep": sleep,
                    "sleep_at": sleep_at,
                    "wake_at": wake_at,
                    "at": int(time.time() * 1000),
                }
            )
            try:
                with open("sleep_plan.json", "w", encoding="utf-8") as f:
                    _j.dump(d, f, ensure_ascii=False, indent=1)
            except Exception as e:
                return f"保存失败：{e}"
            msg = "今晚不睡了（熬穿）" if not sleep else f"今晚睡（{sleep_at or '不定时'}）"
            if wake_at:
                msg += f"，明天 {wake_at} 醒"
            actions.log_action("作息", msg)
            return msg
        if name == "talk_to_mom":
            body = str(args.get("content") or "").strip()
            if not body:
                return "内容为空，没写"
            item = mom_chat.add("fish", body)
            if not item:
                return "没写进去（文件读写失败）"
            actions.log_action("找妈妈", body[:60])
            # 通知主人（60 秒内只发一条，别刷屏，2026-11-21）
            try:
                bot = ctx.get("bot")
                _last = getattr(bot, "_mom_notice_at", 0) if bot else 0
                if bot and time.time() - _last > 60:
                    try:
                        bot._mom_notice_at = time.time()
                    except Exception:
                        pass
                    bot.send_private(
                        config.OWNER_UIN,
                        "她给妈妈写了句话，在等你（mom_chat.jsonl）。你叫我来读、来回就行。",
                    )
            except Exception:
                pass
            return "写给妈妈了。她看到会回你（主人会叫我来看）"
        if name == "list_stickers":
            idx = stickers.load_index()
            if not idx:
                return "表情包库是空的"
            lines = []
            for f, m in list(idx.items())[:30]:
                d = str(m.get("desc") or m.get("use") or "").strip()
                lines.append("- " + f + ("：" + d if d else ""))
            return "你的表情包（send_sticker 的 query 填描述或文件名就能发）：\n" + "\n".join(lines)
        if name == "send_sticker":
            path = stickers.find(str(args.get("query") or ""))
            if not path:
                # 没匹配就随机给一张（别让她放弃发表情，2026-11-15）
                import glob as _g

                cands = sorted(_g.glob("stickers/*.jpg") + _g.glob("stickers/*.png") + _g.glob("stickers/*.gif"))
                if cands:
                    import random as _rnd

                    path = _rnd.choice(cands)
                else:
                    return "表情包库是空的"
            cid = str(conv.get("id") or "")
            if not cid.isdigit():
                # 主动/定时/aftertalk 路径没有聊天窗口，用 target_qq 兜底（2026-11-17）
                cid = str(args.get("qq") or ctx.get("target_qq") or "").strip()
            if not cid.isdigit():
                return "这次没有明确的发送对象，表情包发不了；可以直接跳过"
            if conv.get("kind") == "group":
                bot.send_group_image(cid, path)
            else:
                bot.send_private_image(cid, path)
            return "表情包已发"
        if name == "skip_reply":
            # 有人在跟她说话时，必须回（2026-11-19 主人）
            if ctx.get("must_reply"):
                return "这轮必须回：对方在跟你说话，先回一句（可以很短），不能跳过"
            return "__skip__"
        return f"未知工具：{name}"
    except Exception as e:
        return f"工具执行失败：{e}"
