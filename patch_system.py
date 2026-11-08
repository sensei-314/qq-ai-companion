import io
import os

P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")
s = io.open(P, encoding="utf-8").read()

FUNC = '''def sep(title):
    return f"\\n\\n---------------- {title} ----------------\\n"


def build_full_system(user_id, display):
    """统一组装上下文（2026-11-08 主人定的顺序：赠言→人设→记事本→手册→认人→操作→要求→别人）。"""
    parts = []
    letter = load_letter()
    if letter:
        parts.append(sep("主人赠言") + letter)
    parts.append(sep("你的人设") + build_system(now_text(), events=EVENTS))
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
        + "\\n（想查更早的操作：<actions>关键词</actions>）"
    )
    parts.append(
        sep("回复要求（很重要）")
        + (
            "1. 只接他最后说的那句话，别翻旧话题；\\n"
            "2. 一两句就够，最多两条气泡；\\n"
            "3. 像真人发 QQ，短、随口；\\n"
            "4. 他只发「...」「哦」就随口接一句；\\n"
            "5. 不许编时间（「这么晚才来找我」）；\\n"
            "6. 要记事必须写 <note>内容</note>（只嘴上说没用）；\\n"
            "7. 想延时用 <timer minutes=\\"2\\">要做的事</timer>；\\n"
            "8. 查东西用 <search>关键词</search>，翻自己操作 <actions>关键词</actions>。"
        )
    )
    others = memory.all_recent(user_id)
    if others:
        parts.append(
            sep("别人那边最近在说什么（是别人，不是现在这个人）")
            + others
            + "\\n（这些是别人跟你的聊天，别把别人的话安到这个人头上。）"
        )
    try:
        recent_user_text = " ".join(str(m.get("text") or "") for m in memory.recent(user_id, 2))
        recalled = auto_recall(user_id, recent_user_text)
        if recalled:
            parts.append(sep("你翻到的记录") + recalled)
    except Exception as e:
        log(f"[recall] auto fail: {e}")
    return "\\n".join(parts)


def handle_message_event(bot, payload):'''

if "def build_full_system" not in s:
    s = s.replace("def handle_message_event(bot, payload):", FUNC, 1)

start = s.find("    system = build_system(\n        now_text(),")
end = s.find("    # 本对话最近 25 条上文")
if start > 0 and end > start:
    s = (
        s[:start]
        + '    system = build_full_system(user_id, slot.get("display") or user_id)\n\n'
        + s[end:]
    )
    print("replaced assemble block")
else:
    print("WARN: block not found", start, end)

io.open(P, "w", encoding="utf-8", newline="\n").write(s)
print("done")
