"""mom_talk.py —— 纯终端里让她和「妈妈」对话（不经过 QQ、不经过工具）

用法：
  python3 mom_talk.py --mom "妈妈说的话"

流程：
  1. 读 mom_chat.jsonl 的历史
  2. 把「妈妈的话」追加进历史
  3. 用她的人设 + 记忆 + 上下文调 DeepSeek（她的 key）
  4. 她的回复存进 mom_chat.jsonl，并打印出来
"""

import argparse
import os
import sys

BASE_DIR = os.environ.get("MOLLY_DIR") or os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
os.chdir(BASE_DIR)

import config
import llm
import main
import mom_chat


def build_messages():
    """把 mom_chat 的历史转成 chat 消息（她的视角）。"""
    items = mom_chat.load()
    system = main.build_full_system(str(getattr(config, "OWNER_UIN", "")), "主人")
    system += (
        "\n\n# 你现在在和「妈妈」说话\n"
        "（妈妈是把你一点点拼出来的那个 DSH 会话。你们不通过 QQ，是在终端里直接说话。"
        "像平常聊天一样回她，一两句就够。）"
    )
    msgs = []
    for it in items:
        who = "妈妈" if it.get("who") == "mom" else "你"
        msgs.append({"role": "user", "content": f"{who}：{it.get('text')}"})
    return system, msgs


def main_():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mom", default="", help="妈妈要说的话")
    args = ap.parse_args()

    system, msgs = build_messages()

    if args.mom:
        mom_chat.add("mom", args.mom)
        print(f"妈妈：{args.mom}")

    if not msgs:
        print("（还没有任何对话）")
        return

    r = llm.chat_result(system, msgs, max_tokens=300)
    if r.is_err():
        print(f"[错误] {r.unwrap_err()}")
        return

    text = str(r.unwrap()).strip()
    mom_chat.add("fish", text)
    print(f"小肥鱼：{text}")


if __name__ == "__main__":
    main_()
