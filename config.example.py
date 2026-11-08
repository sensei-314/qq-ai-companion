"""配置模板。复制成 config.py 再改。

    cp config.example.py config.py

config.py 已在 .gitignore 里，**永远不要提交它**。
"""

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ===== 身份 =====
# 机器人自己的 QQ 号
SELF_ID = 0
# 主人 QQ 号（最高权限）
OWNER_UIN = 0
# 主用户 QQ 号（可留 0）
MAIN_USER_QQ = 0

# ===== 模型 =====
# 建议用环境变量，别写在文件里：export DEEPSEEK_API_KEY=sk-...
API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
API_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-flash"
THINKING = False
MAX_TOKENS = 2048

# ===== OneBot（SnowLuma）=====
ONEBOT_HTTP = "http://127.0.0.1:3000"
ONEBOT_WS = "ws://127.0.0.1:3001"
ONEBOT_TOKEN = ""
ONEBOT_HTTP_TOKEN = ""

# ===== 记忆 =====
PEOPLE_DIR = os.path.join(BASE_DIR, "people")
CONTEXT_LIMIT = 150
OTHER_SESSION_RECENT = 25
MEMORY_RECALL_LIMIT = 50

# ===== 拟人：反应延迟 =====
REACTION_MIN_SECONDS = 1.0
REACTION_MAX_SECONDS = 3.0
REACTION_BUSY_CHANCE = 0.05
REACTION_BUSY_EXTRA = (20, 50)
REACTION_DISTRACT_CHANCE = 0.10
REACTION_DISTRACT_EXTRA = (5, 15)

# ===== 拟人：分条 =====
TYPING_CHARS_PER_SECOND = 10
MAX_BUBBLES = 2
BUBBLE_GAP_SECONDS = (0.6, 1.6)
DEBOUNCE_SECONDS = 4
REPLY_COOLDOWN_SECONDS = 4

# ===== 主动消息 =====
PROACTIVE_ENABLED = True
PROACTIVE_TICK_MINUTES = 15
PROACTIVE_MIN_GAP_MINUTES = 60
PROACTIVE_GAP_JITTER = 0.2
PROACTIVE_MIN_IDLE_MINUTES = 10
PROACTIVE_NO_REPLY_HOURS = 1
QZONE_CHANCE = 0.05

# ===== 防封 =====
SEND_RATE_PER_MINUTE = 10
SEND_RATE_PER_HOUR = 60
BANNED_WORDS = []

# ===== 作息（北京时间）=====
SCHOOL_START = "07:30"
SCHOOL_END = "18:30"
SCHOOL_BREAK_CHANCE = 0.08
SLEEP_START = "23:50"
SLEEP_END = "07:30"

# ===== 语音 =====
VOICE_ENABLED = False
VOICE_CHANCE = 0.0

# ===== 表情包 =====
STICKER_LEARN = True
STICKER_MAX_PER_DAY = 13
STICKER_MAX_MB = 3
STICKERS_TOTAL_MAX_MB = 500

# ===== 视频 / 动图抽帧 =====
FFMPEG = "ffmpeg"
VIDEO_MAX_SECONDS = 60
VIDEO_FRAMES = 12
VIDEO_COLUMNS = 4
VIDEO_FRAME_WIDTH = 320

# ===== 权限 =====
# True = 任何人私聊都会回（陌生人也能聊）
ALLOW_ALL_PRIVATE = True
