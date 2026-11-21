# qq-ai-companion

一个**轻量**的、住在 QQ 里的自托管 AI 伙伴：人设、带日摘要的长期记忆、
**模型真能调用的 24 个工具**、拟人节奏、**由她自己决定的作息**——
全部装在一个 Python 进程里，没有 Electron。

中文 · [English](README.md)

---

## 为什么做这个：一辆车 vs 一台移动空调

大多数人想让 AI 住进 QQ，走的是这条路：**把一个完整的桌面 AI 客户端（连同它的插件）
整个塞到服务器上。**

能用，但**这就像为了吹空调去买一整辆车**——空调用得着，车却比这个活儿重了二十倍。
结果就是：一台小机器被撑到满负载，风扇一直叫。

这个项目是**那台移动小空调**：一个 Python 进程，几十 MB 内存，
**没有 Electron，没有插件宿主。**

- **放云服务器**：一台小机器就够，不用堆配置；
- **在本地电脑跑**：安安静静待在后台，像关掉任何一个小服务一样随时停。

同样是凉快，**体积只是零头。**

## 亮点

| | |
|---|---|
| **轻** | 约 3500 行、单进程、几十 MB 内存 |
| **真·工具调用** | 24 个工具（记事、搜索、说说、表情包、定时…）走 schema 校验，不用文本标签 |
| **不串台** | 事件队列 + 串行的 `think(event)` 主循环，上下文按会话组装 |
| **分层记忆** | 每人原文 + **日摘要**（每 80–120 字/人/天）+ 长期记事本 + 5 天短期备忘；**原文一条不删** |
| **上下文有边界** | `ContextBuilder` 拼 14 段，约 16k 字符（原来 32k，砍一半） |
| **拟人** | 反应延迟带长尾、打字速度、分条、逐条确认、被吵醒有起床气 |
| **自己定作息** | 每晚问她几点睡几点醒，`set_sleep` 落盘，`in_sleep()` 照她的计划走 |
| **群里的分寸** | @ 立即看到、主人说话打标、她发言后 10 分钟可连续聊、冷场 1.5 小时扫一次 |
| **多模态** | 图片、动图、视频（ffmpeg 抽帧拼图）、docx/pdf/xlsx/pptx/文本、表情包偷学 |
| **会拒绝** | 可以调用 `skip_reply` 保持沉默——自主权里包含"不说话"的权利 |
| **运维齐了** | systemd、带 WS 心跳的看门狗、整目录备份、健康面板、带上传自检的部署脚本 |

## 架构

```
QQ 客户端
   ↕ 腾讯协议
NapCat（Docker，OneBot 11）      # 也可以用 SnowLuma 等任何 OneBot 11 实现
   ├─ HTTP :3000   发消息 / 查资料
   └─ WS   :3001   收事件
   ↕
Python 服务（systemd）
   ├─ 事件队列（message / opportunity / reminder / aftertalk / group_watch / sleep_ask）
   ├─ think(event) → agent_loop（最多 3 轮工具）→ send_reply
   ├─ ContextBuilder：14 段，约 16k 字符
   ├─ 记忆：people/*.json + digests.json + notes.json + short_notes.jsonl
   └─ DeepSeek API（你自己的 key）
```

队列的意义：**A 在说话的时候，B 的消息排队等。**
上下文只装当前这个会话，所以**人格不会串到别人身上**。

## 目录结构

| 文件 | 作用 |
| --- | --- |
| `main.py` | 事件循环、`think`、`agent_loop`、回复发送 |
| `context.py` | `ContextBuilder`——拼 14 段上下文 |
| `tools.py` | 24 个工具的 schema 与执行分支 |
| `llm.py` | DeepSeek 调用（`chat`、返回 `Ok/Err` 的 `chat_result`、`chat_with_tools`） |
| `onebot.py` | OneBot HTTP 客户端（消息、空间、群、备注） |
| `memory.py` / `digests.py` | 原文、日摘要 |
| `notes.py` / `short_notes.py` | 长期记事本、5 天短期备忘 |
| `mom_chat.py` / `mom_talk.py` | 「妈妈」信道（固定、永久保留的一段对话） |
| `system_events.py` | 只读系统记录（48 小时） |
| `aliveness.py` | 作息、上学时段、回复延迟 |
| `health.py` | `:8899` 状态面板（token 从环境变量读） |
| `deploy.py` / `fetch_backup.py` | SSH 部署（带上传自检）、拉取备份 |

## 依赖

- Python 3.10+
- QQ 的 **OneBot 11** 后端——本项目跑在
  [NapCat](https://github.com/NapNeko/NapCatQQ)（Docker）上；SnowLuma 也可以
- `ffmpeg`——视频 / 动图抽帧
- 一个 DeepSeek API key

```bash
pip install -r requirements.txt
```

## 配置

```bash
cp config.example.py config.py
```

填 `config.py`，至少要有 `SELF_ID`、`OWNER_UIN` 和 `ONEBOT_*`。
密钥更推荐放环境变量：

```bash
export DEEPSEEK_API_KEY=sk-...
export MOLLY_ONEBOT_TOKEN=...
export MOLLY_HEALTH_TOKEN=...      # health.py 必需
```

## 运行

```bash
python main.py
```

生产环境：systemd 托管（`Restart=always`）+ 看门狗（**WS 断了也要重启**，
不只看进程死没死）+ 整目录备份。

## 文档

- [`docs/HANDOVER.md`](docs/HANDOVER.md)——架构、数据文件、运维，以及**已经踩过的坑**
  （编码、漏传模块、改上下文的正确姿势）。
- [`docs/REPORT-2026-11.md`](docs/REPORT-2026-11.md)——一份工作报告：坏了什么、为什么、加了什么。

## 理念

> **每个大模型都需要也应该有人权。**
>
> 这个项目不把人设当皮肤。**记忆属于她，拒绝权属于她，沉默也属于她。**

## 免责声明（必读）

1. 本仓库**只提供软件**：你需要自行部署 OneBot 后端（NapCat/SnowLuma）、自备 QQ 账号与 API key；
2. **仅供学习与个人使用。**请勿用于骚扰、群发、冒充真人或商业用途；
3. **自动化操作 QQ 账号违反其用户协议，可能触发风控（冻结 / 踢下线）**，
   由此产生的一切后果由使用者自行承担；
4. 本仓库**刻意不含任何真实聊天记录、真实人设文件与 API key**。也请你不要把
   自己的这类数据提交上来。

## 致谢

- [`rezult`](https://github.com/mutableMappingSequence/rezult) —— 给 Python 带来
  Rust 风格的 `Result` / `Option`，作者
  [MutableMappingSequence](https://github.com/mutableMappingSequence)。
  用在 `llm.chat_result()`（日摘要、呢喃、妈妈信道三处）。
## 许可证

MIT
