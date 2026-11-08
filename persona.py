"""
persona.py —— 人设加载与 system prompt 拼装

优先读 persona.md；没有就用 personas/example.md；再没有就用下面的默认文本。
"""

import os

from config import BASE_DIR

PERSONA_FILE = os.path.join(BASE_DIR, "persona.md")
EXAMPLE_FILE = os.path.join(BASE_DIR, "personas", "example.md")

DEFAULT_PERSONA = (
    "你是一个住在聊天软件里的 AI 伙伴。\n"
    "说话短，一次最多两句；不懂就说不懂，不装。\n"
    "不用「作为一个 AI」这种句子解释自己。\n"
    "对方难过时，先接情绪，别急着给建议。\n"
)


def _read(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return None


def load_persona():
    return _read(PERSONA_FILE) or _read(EXAMPLE_FILE) or DEFAULT_PERSONA


def build_system(now_text, events=None, others=None):
    parts = [load_persona()]
    parts.append(f"\n# 现在的时间\n{now_text}")
    if events:
        parts.append("\n# 最近发生的事\n" + "\n".join(f"- {e}" for e in events[-10:]))
    if others:
        parts.append(
            "\n# 别人那边最近在说什么\n"
            + others
            + "\n（这是别的会话里的聊天记录，不是你现在这个对话。话题相关时可以用，"
            "但别把别的会话里的话当成这个人现在跟你说的。）"
        )
    return "\n".join(parts)
