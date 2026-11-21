"""context.py —— 上下文构建器（2026-11-21 从 main.build_full_system 抽出）

每次聊天/操作前，把「她是谁、在跟谁说话、规则、工具、记忆、背景」拼成 system。
顺序原则：越靠后越重要（近因效应）。

可变依赖（赠言/手册/人设/回忆）通过回调注入，避免和 main 循环引用。
"""

import actions
import config
import digests
import memory
import mom_chat
import notes
import short_notes
import system_events


def sep(title):
    return f"\n\n---------------- {title} ----------------\n"


RULES = (
    "1. 只接他最后说的那句话，别翻旧话题；\n"
    "2. 一两句就够，最多两条气泡；\n"
    "3. 像真人发 QQ，短、随口；\n"
    "4. 他只发「...」「哦」就随口接一句；\n"
    "5. 不许编时间（「这么晚才来找我」）；\n"
    "6. 要记东西就调用 write_note（只嘴上说没用）；\n"
    "7. 想延时做事就调用 set_timer；\n"
    "8. **不懂、拿不准就调用 search_web 查**，别瞎编；想翻自己的操作调用 search_actions；\n"
    "9. **别人问「你知道 xx 吗 / 这是谁 / 这是啥」，而你没把握时，先 search_web 查一下再回答**——"
    "别张口就说「不认识」「没听过」（很多名字、角色、作品你查一下就知道）；\n"
    "10. **答应了别人的事（特别是「还要问主人/回头做」这种），立刻 write_note 记下来**——"
    "不然换个会话你就忘了，人家会失望的；\n"
    "11. **主人（或任何人）让你做一个操作（改备注、发消息、记事、定闹钟），必须真的调用对应工具**，"
    "不能只嘴上说「改了」「发了」——说了没调，等于没做；\n"
    "12. **说「记一下」「写进本子」「记着」的当下就立刻调用 write_note**，不要说「下轮再记」——"
    "下轮可能就没了（停服、断线）；\n"
    "13. **想发表情包就调用工具**：先 list_stickers 看有哪些，再 send_sticker 选一张发；"
    "不要输出 <PIC> 这类占位符；\n"
    "14. **记东西分两种**：答应别人的事、约定、要办的 → write_short_note（短期备忘，5 天后自动消失）；"
    "心情、感受、对自己的认识 → write_note（长期记事本）。"
    "短期备忘是「这几天要记得办」的，长期记事本才是「我是谁」。"
)

TOOLS = (
    "write_note 记事（私有）｜search_web 联网查｜send_message 给别人发消息｜"
    "set_timer 定闹钟｜recall_msg 撤回自己刚发的｜"
    "search_history 翻聊天记录（忘了跟谁聊过什么、答应过谁什么，就用它查——keyword 填对方名字或 QQ 号）｜"
    "search_actions 查自己的操作｜like_feed / comment_feed / post_qzone 空间操作｜"
    "set_qq_remark 改对方的 QQ 好友备注（真的会改）｜set_remark 改你对 TA 的称呼｜"
    "read_feeds 看好友动态｜read_guilds 看频道｜"
    "list_stickers 看表情包库｜send_sticker 发表情包（query 填描述或文件名）｜"
    "talk_to_mom 跟妈妈说句话（存进固定记录）｜skip_reply 这轮不想回。\n"
    "（没人跟你说话、你自己有空档的时候，可以自己写笔记、发说说、给动态点赞——想干就干，不用等谁批准。\n"
    "但**有人正在跟你闲聊时**，就好好聊天，别一句话一个工具——工具是手，不是嘴。）"
)


class ContextBuilder:
    """一次上下文构建。"""

    def __init__(
        self,
        user_id,
        display,
        with_others=True,
        *,
        letter_fn=None,
        manual_fn=None,
        persona_fn=None,
        recall_fn=None,
    ):
        self.user_id = str(user_id)
        self.display = display or self.user_id
        self.with_others = with_others
        self._letter_fn = letter_fn
        self._manual_fn = manual_fn
        self._persona_fn = persona_fn
        self._recall_fn = recall_fn
        self.parts = []

    # ---------- 构建 ----------

    def build(self):
        self._identity()
        self._who()
        self._letter()
        self._persona()
        self._manual()
        self._rules()
        self._tools()
        self._actions()
        self._system_events()
        self._digests()
        self._mom()
        self._others()
        self._notes()
        self._recall()
        return "\n".join(self.parts)

    def _add(self, title, body):
        self.parts.append(sep(title) + body)

    # ---------- 各段 ----------

    def _identity(self):
        self._add(
            "你现在在哪",
            "你现在在 **QQ 里跟人聊天**，不是在终端。终端是你后台用的手："
            "记事/搜索/翻记录/定闹钟都用工具（write_note/search_web/search_history/set_timer 等），"
            "代码会替你做，结果只回给你自己看。\n"
            "**别把终端里的东西（搜索结果原文、命令、标签）当话说给对方听**——"
            "用你自己的话讲给他，像在 QQ 上随口聊天。",
        )

    def _who(self):
        try:
            _p, _j = memory.find_person(self.user_id)
            _remark = str((_j or {}).get("remark") or "").strip() or "none"
        except Exception:
            _remark = "none"

        if self.user_id == str(config.OWNER_UIN):
            who = (
                f"（现在跟你说的是你主人 QQ {config.OWNER_UIN}，昵称「{self.display}」，"
                f"你叫她：{_remark}——名字很长带符号，但就是他本人，别当陌生人。）"
            )
        elif config.MAIN_USER_QQ and self.user_id == str(config.MAIN_USER_QQ):
            who = (
                f"（现在跟你说的是户山香顺澄 QQ {config.MAIN_USER_QQ}，昵称「{self.display}」，"
                f"你叫她：{_remark}。）"
            )
        else:
            who = f"（现在跟你说的是 QQ {self.user_id}，昵称「{self.display}」，你叫他：{_remark}。）"
        self._add("现在是谁在说话", who)

    def _letter(self):
        if not self._letter_fn:
            return
        letter = self._letter_fn()
        if letter:
            self._add("主人赠言", letter)

    def _persona(self):
        if self._persona_fn:
            self._add("你的人设", self._persona_fn())

    def _manual(self):
        if not self._manual_fn:
            return
        manual = self._manual_fn()
        if manual:
            self._add("操作手册", manual)

    def _rules(self):
        self._add("回复要求（很重要）", RULES)

    def _tools(self):
        self._add("你的工具（都由你自己决定用不用）", TOOLS)

    def _actions(self):
        self._add(
            "你最近在终端做过的事（带时间）",
            actions.for_prompt() + "\n（想查更早的操作：调用 search_actions 工具）",
        )

    def _system_events(self):
        self._add("系统记录（只读）", system_events.for_prompt())

    def _digests(self):
        dg = digests.for_prompt(self.user_id)
        if dg:
            self._add("更早的回忆（压缩，原文还留着）", dg)

    def _mom(self):
        mom = mom_chat.for_prompt()
        if mom:
            self._add("和妈妈的对话（永久保留）", mom)

    def _others(self):
        if not self.with_others:
            return
        others = memory.all_recent(self.user_id, per_person=8)
        if others:
            self._add(
                "别人那边最近在说什么（是别人，不是现在这个人）",
                others + "\n（这些是别人跟你的聊天，别把别人的话安到这个人头上。）",
            )

    def _notes(self):
        sn = short_notes.for_prompt()
        if sn:
            self._add("短期备忘（5 天有效）", sn)
        self._add("记事本（长期）", notes.for_prompt())

    def _recall(self):
        if not self._recall_fn:
            return
        try:
            recent = " ".join(str(m.get("text") or "") for m in memory.recent(self.user_id, 2))
            recalled = self._recall_fn(recent)
            if recalled:
                self._add("你翻到的记录", recalled)
        except Exception as e:
            print(f"[recall] auto fail: {e}")
