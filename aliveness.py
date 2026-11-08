"""
aliveness.py —— 拟人化：反应延迟、打字延迟、分条、时段判断

对齐 DSH 插件的 planDelivery / aliveness：
  - 看到消息后 0.5~3 秒开始回，偶尔「在忙」「走神」（长尾）；
  - 按字数算打字时间；
  - 一轮最多 3 条气泡，条与条之间有间隔。
"""

import random
import time
from datetime import datetime

from config import (
    REACTION_MIN_SECONDS,
    REACTION_MAX_SECONDS,
    REACTION_BUSY_CHANCE,
    REACTION_BUSY_EXTRA,
    REACTION_DISTRACT_CHANCE,
    REACTION_DISTRACT_EXTRA,
    TYPING_CHARS_PER_SECOND,
    MAX_BUBBLES,
    BUBBLE_GAP_SECONDS,
    SLEEP_START,
    SLEEP_END,
    SCHOOL_START,
    SCHOOL_END,
)


def reaction_delay():
    """看到消息 → 开始打字的时间。"""
    base = random.uniform(REACTION_MIN_SECONDS, REACTION_MAX_SECONDS)
    r = random.random()
    if r < REACTION_BUSY_CHANCE:
        base += random.uniform(*REACTION_BUSY_EXTRA)
    elif r < REACTION_BUSY_CHANCE + REACTION_DISTRACT_CHANCE:
        base += random.uniform(*REACTION_DISTRACT_EXTRA)
    return base


def typing_delay(text):
    return max(0.4, min(6.0, len(str(text)) / TYPING_CHARS_PER_SECOND))


def split_bubbles(text, max_bubbles=MAX_BUBBLES):
    """把回复切成 1~3 条气泡；超长句再按标点拆。"""
    parts = []
    for chunk in str(text or "").replace("\r", "").split("\n\n"):
        for line in chunk.split("\n"):
            line = line.strip()
            if not line:
                continue
            # 超长单行（>200 字）按句末标点拆开
            while len(line) > 200:
                cut = max(line.rfind("。", 0, 200), line.rfind("！", 0, 200), line.rfind("？", 0, 200))
                if cut < 60:
                    break
                parts.append(line[: cut + 1].strip())
                line = line[cut + 1 :].strip()
            if line:
                parts.append(line)
    return parts[:max_bubbles]


def bubble_gap():
    return random.uniform(*BUBBLE_GAP_SECONDS)


def _now_hm():
    return datetime.now().strftime("%H:%M")


def _in_range(hm, start, end):
    # 支持跨午夜（如 23:50 - 07:30）
    if start <= end:
        return start <= hm < end
    return hm >= start or hm < end


def in_sleep():
    return _in_range(_now_hm(), SLEEP_START, SLEEP_END)


def in_school_time():
    """工作日 7:30-18:30 是主用户在学校的时间。"""
    now = datetime.now()
    if now.weekday() >= 5:  # 周六周日
        return False
    return _in_range(now.strftime("%H:%M"), SCHOOL_START, SCHOOL_END)
