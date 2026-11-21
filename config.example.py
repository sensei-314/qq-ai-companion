"""
config.example.py —— 所有可调参数集中在这。

用法：
    cp config.example.py config.py     # 然后填上你自己的值
    export DEEPSEEK_API_KEY=your-key-here     # key 更推荐放环境变量
"""

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ==================== 身份 ====================
SELF_ID = ""                    # 机器人自己的 QQ 号
OWNER_UIN = ""                  # 主人（最高权限）的 QQ 号
MAIN_USER_QQ = ""               # 主用户（可选）

# ==================== 模型 ====================
API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
API_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-flash"
THINKING = False                # 2026-11-07 主人：关思考省 token（理解力降一点，聊天够用）
MAX_TOKENS = 2048

# ==================== OneBot ====================
# 默认是本地（3002/3004 + 本地 token）；部署到服务器时用环境变量覆盖
ONEBOT_HTTP = os.environ.get("MOLLY_ONEBOT_HTTP", "http://127.0.0.1:3000/")
ONEBOT_WS = os.environ.get("MOLLY_ONEBOT_WS", "ws://127.0.0.1:3001/?access_token=")
ONEBOT_TOKEN = os.environ.get("MOLLY_ONEBOT_TOKEN", "")
ONEBOT_HTTP_TOKEN = os.environ.get("MOLLY_ONEBOT_HTTP_TOKEN", "")

# ==================== 记忆 ====================
PEOPLE_DIR = os.path.join(BASE_DIR, "people")
CONTEXT_LIMIT = 200             # 本对话最近多少条上文（2026-11-15 主人：150 → 200）
OTHER_SESSION_RECENT = 50       # 兼容旧名（未用）
OTHER_SESSION_ACTIVE = 100      # 3 天内聊过的人：每人最近条数（150 → 100，2026-11-15 省 token）
OTHER_SESSION_IDLE = 50         # 3 天前聊过的人：每人最近条数（2026-11-15）
GROUP_IDS = []                  # 她所在的群，示例：["123456789"]
GROUP_INFO = {}                 # 群号 → 一句说明（可选）
SNAPSHOT_GROUP = 100            # 机会事件里群历史的条数
SNAPSHOT_ACTIVE = 150           # 机会事件里活跃用户的条数
SNAPSHOT_IDLE = 50              # 机会事件里不活跃用户的条数
MEMORY_RECALL_LIMIT = 12        # 关键词检索最多几条

# ==================== 拟人 / 回复节奏 ====================
REACTION_MIN_SECONDS = 1.0      # 看到 → 开始打字（2026-11-08：上下文拉长后模型变慢，手动延迟调小）
REACTION_MAX_SECONDS = 3.0
REACTION_BUSY_CHANCE = 0.05     # 「在忙」长尾
REACTION_BUSY_EXTRA = (20, 50)  # 秒
REACTION_DISTRACT_CHANCE = 0.10 # 「走神」长尾
REACTION_DISTRACT_EXTRA = (5, 15)
TYPING_CHARS_PER_SECOND = 10.0  # 打字速度快一点（7.5 → 10）
MAX_BUBBLES = 2                 # 一轮最多几条气泡（2026-11-07 主人：回太多，降成 2）
BUBBLE_GAP_SECONDS = (0.6, 1.6)
DEBOUNCE_SECONDS = 4.0          # 连发合并窗口（2026-11-08 防深夜刷屏）
REPLY_COOLDOWN_SECONDS = 4.0    # 同一人回复后的冷却，冷却内新消息不触发新轮

# ==================== 主动消息 ====================
PROACTIVE_ENABLED = True
PROACTIVE_TICK_MINUTES = 30     # 检查频率
PROACTIVE_MIN_GAP_MINUTES = 60  # 两次主动最小间隔
PROACTIVE_GAP_JITTER = 0.2      # ±20%
PROACTIVE_MIN_IDLE_MINUTES = 30 # 刚聊过多久内不主动
PROACTIVE_NO_REPLY_HOURS = 1    # 对方没回多久后可再找

# 自由活动：到点有可能不找人，去发说说（2026-11-07 降频：15% → 5%，防营销号特征）
QZONE_CHANCE = 0.05

# ==================== 防封（2026-11-07 主人要求） ====================
# 全局发送频率上限（防刷屏/机器人特征）——只约束「主动消息」，被动回复不卡
SEND_RATE_PER_MINUTE = 10
SEND_RATE_PER_HOUR = 60
# 敏感词：命中就不发（政治/色情/诈骗类，宁可不回也别送人头）
BANNED_WORDS = [
    "习近平", "共产党", "政府", "政治", "六四", "法轮功",
    "裸聊", "约炮", "色情", "代开发票", "刷单", "博彩", "赌博",
    "加微信", "扫码领", "兼职日结", "贷款",
]

# 上学时段（主用户）：工作日不主动打扰，低概率「特别想」破例
SCHOOL_START = "07:30"
SCHOOL_END = "18:30"
SCHOOL_BREAK_CHANCE = 0.08

# 睡觉
SLEEP_START = "23:50"
SLEEP_END = "06:00"

# ==================== 语音/表情 ====================
VOICE_ENABLED = False
VOICE_CHANCE = 0.10
STICKER_LEARN = True
STICKER_MAX_PER_DAY = 13
STICKER_MAX_MB = 3
STICKERS_TOTAL_MAX_MB = 500   # 表情包库总量上限（2026-11-08 防撑爆：超了删最旧的）

# ffmpeg（视频/动图抽帧；Windows 本地和服务器路径不同，用环境变量覆盖）
FFMPEG = os.environ.get("MOLLY_FFMPEG", "ffmpeg")   # 指向 ffmpeg 可执行文件
VIDEO_MAX_SECONDS = 60
VIDEO_FRAMES = 6
VIDEO_COLUMNS = 3
VIDEO_FRAME_WIDTH = 360

# ==================== 权限 ====================
ALLOW_ALL_PRIVATE = True        # 私聊谁都能聊
