# molly（小肥鱼）项目交接文档

> 给下一个接手这个项目的会话/开发者。
> 读完这份，你应该能：跑起来、改代码、排查常见故障、不踩已踩过的坑。

---

## 1. 这是什么

一个跑在 QQ 里的**长期人格 bot**（名字：大肥鱼 / 小肥鱼），不是群机器人，是「住在一个 QQ 号里的角色」：

- 有主人（最高权限）、有朋友、有群；
- 有完整记忆（原文 + 压缩摘要）、长期记事本 + 短期备忘；
- 有隐私（可以拒绝、可以讲条件）、有作息（自己定睡觉时间）；
- 会主动：空档时发说说、看动态、写笔记、找人说话；
- 有「终端」概念：她能调用 24 个工具（记事、搜索、改备注、发表情包……）。

技术栈：Python 3（系统 python，无 venv）+ NapCat（QQ 客户端，docker）+ systemd。

---

## 2. 架构

```
QQ 账号（NapCat 容器，端口 3000 HTTP / 3001 WS）
        │  OneBot v11
        ▼
molly（Python 进程，systemd: molly.service）
   ├─ main.py        事件循环 + think + agent_loop + 回复发送
   ├─ context.py     上下文构建（ContextBuilder 类）
   ├─ tools.py       24 个工具的定义与执行
   ├─ llm.py         DeepSeek 调用（chat / chat_result / chat_with_tools）
   ├─ onebot.py      OneBot HTTP 客户端
   ├─ memory.py      people 会话存储
   ├─ notes.py       长期记事本
   ├─ short_notes.py 短期备忘（5 天）
   ├─ digests.py     记忆压缩（日摘要）
   ├─ mom_chat.py    「和妈妈」的固定对话
   ├─ system_events.py 系统记录（只读，48h）
   ├─ actions.py     操作日志
   ├─ persona.py / persona.md  人设
   ├─ aliveness.py   作息/学校时间/延迟
   ├─ stickers.py    表情包库
   ├─ search.py      搜索
   ├─ file_reader.py 文件读取（txt/pdf/docx/xlsx/pptx）
   └─ health.py      健康面板（:8899）
```

### 事件流

```
收消息 → memory.append → 防抖 → enqueue("message")
       → worker_loop → think(event) → handle_xxx_event
       → agent_loop（最多 3 轮工具）→ send_reply
```

事件类型：`message` / `opportunity`（30 分钟空档）/ `reminder` / `aftertalk` / `group_watch` / `sleep_ask`。

---

## 3. 文件清单（服务器 `/opt/molly/`）

| 文件 | 作用 |
|---|---|
| `main.py` | 主流程：事件队列、think、agent_loop、回复、各事件 handler |
| `context.py` | `ContextBuilder`：拼 14 段上下文 |
| `tools.py` | 24 个工具的 schema + 执行分支 |
| `llm.py` | DeepSeek API（`chat` 元组版 / `chat_result` Result 版 / `chat_with_tools`） |
| `onebot.py` | OneBot HTTP（发送、空间、群、备注等） |
| `memory.py` | `people/QQ<qq>.json` 读写 |
| `notes.py` / `short_notes.py` | 长期 / 短期备忘 |
| `digests.py` | 日摘要压缩 |
| `mom_chat.py` / `mom_talk.py` | 和「妈妈」的通信；终端对话脚本 |
| `system_events.py` | 系统记录（启动/作息，48h） |
| `actions.py` | 操作日志 `actions.jsonl` |
| `persona.md` / `操作手册.md` / `主人赠言.txt` | 人设文本（可编辑） |
| `config.py` | 模型、QQ 号、频率参数 |
| `health.py` | 面板（8899） |
| `deploy.py` | **本地部署脚本**（Windows 上跑，SFTP 上传 + 重启） |
| `molly-watchdog.sh` / `molly-backup.sh` | 看门狗 / 备份 |

### 数据文件

| 文件 | 内容 |
|---|---|
| `people/QQ<qq>.json` | 每人的消息（含 `at` 毫秒 + `time` 字符串） |
| `notes.json` | 长期记事本 |
| `short_notes.jsonl` | 短期备忘（5 天） |
| `mom_chat.jsonl` | 和妈妈的对话（永久） |
| `digests.json` | 日摘要（人 → 日期 → 摘要） |
| `system_events.jsonl` | 系统记录（48h） |
| `sleep_plan.json` | 她定的作息 |
| `qzone_times.json` / `comment_times.json` / `proactive.json` | 频率限制 |
| `group_sent.json` | 群发言去重（持久化） |
| `stickers/` | 表情包 |

---

## 4. 部署

### 本地 → 服务器

```bash
# 本地（Windows）
python deploy.py
```

`deploy.py` 做的事：
1. **自检**：`main.py` import 的本地模块是否都在 `UPLOAD_FILES` 里（缺了会警告）；
2. SFTP 上传代码/文本；
3. `systemctl restart molly`；
4. 打印日志尾部。

> ⚠️ **踩过两次**：新增模块忘了加进 `UPLOAD_FILES`，导致服务器启动失败（`ModuleNotFoundError`）。自检就是为此加的。

### 服务器

- 服务：`systemctl status molly`
- 日志：`tail -f /opt/molly/molly.log`
- 面板：`http://<ip>:8899/?token=<健康面板 token>`

---

## 5. 运维

| 定时器 | 时间 | 作用 |
|---|---|---|
| `molly-watchdog.timer` | 每 5 分钟 | molly 挂了 / WS 断 / 掉登录 → 自动恢复 |
| `molly-backup.timer` | 每天 04:00 | 备份整个 `/opt/molly`（保留 7 天） |
| `molly-night-stop/start.timer` | — | **已停用**（作息改由她自己定，见 §7.4） |

**看门狗的判定**（`molly-watchdog.sh`）：
1. molly 服务不在 → 重启；
2. napcat 容器不在 → 启动；
3. 3000/3001 端口没监听 → 记日志；
4. `get_login_info` 失败 → 重启 napcat 尝试快速登录；
5. molly 在跑但没有到 3001 的 ESTAB 连接 → 重启 molly（WS 心跳）。

---

## 6. 关键机制

### 6.1 上下文（`context.ContextBuilder`）

14 段，顺序按「越靠后越重要」：

```
你在哪 → 现在是谁在说话 → 赠言 → 人设 → 手册 → 回复要求 → 工具
→ 最近操作 → 系统记录 → 更早的回忆(压缩) → 妈妈的对话
→ 别人那边(每人 8 条) → 短期备忘 → 记事本(倒数第二) → 翻到的记录(最后)
```

- **群聊时 `with_others=False`**：不带「别人那边」；
- 约 16k 字符（之前 32k，砍了一半）；
- 改这个文件后**必须对比输出**（改前存快照，改后逐段比对，见 §9）。

### 6.2 群聊（`handle_group_watch_event`）

| 场景 | 行为 |
|---|---|
| 有人 @ 她 | 立即给她看（**不强制回**） |
| 主人在群里说话（没 @） | 标【主人】，立即给她看 |
| 她 10 分钟内发过言 | 别人接话立即看（连续聊） |
| 冷场 | **1.5 小时**扫一次 |

群发言去重落盘（`group_sent.json`），同一句不会重复发；对「新人进群」不打招呼。

### 6.3 记忆压缩（`digests.py`）

- 超过 24h 的对话 → 按「人 × 日」压成 80–120 字；
- 后台每 6 小时增量；
- 上下文只挂最近 7 天摘要；
- **原文一条不删**。

### 6.4 作息（`set_sleep` + `aliveness.in_sleep`）

- 每天 23:45 问她睡不睡、几点睡、几点醒（最晚 7:00）；
- 写 `sleep_plan.json`；
- `in_sleep()` **优先读这份计划**（24h 内有效），没计划才回退 `config.SLEEP_START/END`；
- 固定夜间停机 timer 已停用，避免和她定的时间打架。

### 6.5 和「妈妈」聊（`mom_chat.py` / `mom_talk.py`）

- 她：`talk_to_mom` 工具写一句 → `mom_chat.jsonl`；
- 「妈妈」（DSH 会话）：`python3 mom_talk.py --mom "要说的话"` 直接对话（不经过 QQ、不用工具）；
- 记录永久保留，上下文第 9 段完整带上。

### 6.6 工具执行（`tools.execute_tool`）

- 24 个工具，`if name == "xxx"` 分支（**还没注册表化**）；
- 入口统一记 `actions.log_action("调用", name)`；
- `skip_reply` 在 `ctx["must_reply"]=True` 时拒绝（聊天必须回）。

---

## 7. 已知限制（接口做不到，不是没修）

1. **好友动态评论列表读不了**：NapCat 的 `get_qzone_comment_list` 一直「参数无效」；
2. **点赞**：已修好（需要 `tid + target_uin + abstime` 三件套，缺一不可）；
3. **群消息 WS 推送**：NapCat 不推，只能靠「她发过言后 10 分钟」窗口；
4. **频道**：NapCat 的 guild 接口是空实现；
5. **空友爱看**：她的号能力全关（内测灰度）；
6. **NapCat 重启掉登录**：这台机器的硬伤，看门狗会自动快速登录，失败需扫码；
7. **封号风险**：第三方协议实现，腾讯随时可能变；她的号 11-16 被封过一次。

---

## 8. 接手须知（重点）

### 8.1 改代码前

1. **服务器 `/opt/molly` 是权威**，本地可能落后——先比对 md5（见 §9.2）；
2. 改完 **`python -m py_compile`** 全部改动文件；
3. **部署后看日志**，确认 `[ws] connected` 且无 Traceback；
4. 新增模块 **必须加进 `deploy.py` 的 `UPLOAD_FILES`**。

### 8.2 验证一致性

```bash
# 服务器
cd /opt/molly && md5sum *.py
# 本地
python -c "import hashlib;print(hashlib.md5(open('main.py','rb').read()).hexdigest())"
```

### 8.3 改上下文的正确姿势

1. 改前：跑一次 `build_full_system` 存快照（去掉时间戳）；
2. 改后：再跑一次，逐段对比；
3. **段标题必须一致**（14 段），内容差异只允许是动态数据（时间、新消息）。

### 8.4 测试别污染真实数据

- 写类工具（笔记/短期备忘/妈妈对话）**重定向到 `/tmp`**；
- **注意变量名**：`notes.py` 用 `NOTES_FILE`，`short_notes.py`/`mom_chat.py` 用 `FILE`——猜错就写进真实数据；
- 发消息类工具用 **FakeBot**，不要真发；
- 测试完**删痕迹**：notes/short/mom_chat/actions 里的测试条目。

### 8.5 敏感信息（不要提交到 Git）

- 服务器地址与 root 密码
- DeepSeek API Key
- OneBot HTTP token / WS token
- 面板 token
- NapCat WebUI token
- QQ 号（主人/朋友）

**这些只应存在于本地脚本/环境变量，不进仓库。**

---

## 9. 常见故障速查

| 现象 | 先查 |
|---|---|
| 她完全不说话 | `systemctl status molly`、`tail molly.log` |
| 她收到但无视 | `in_sleep()` 是否 True、`sleep_plan.json` |
| 群里 @ 她不回 | 群冷却 30s、`group_sent.json` 去重、WS 是否连上 |
| 表情包发不出 | `stickers/index.json`、`send_sticker` 的 `target_qq` |
| 点赞没效果 | 参数必须 `tid + target_uin + abstime` |
| 启动即退出 | `deploy.py` 是否漏传模块（看 `ModuleNotFoundError`） |
| 面板空白 | `molly-health` 服务、8899 端口、日志正则 |

---

## 10. 参考

- OneBot v11 协议
- NapCat 文档：`https://napcat.napier.uk/`（或官方仓库）
- DeepSeek API：`https://api.deepseek.com`

---

*交接文档生成于 2026-11-21。改动请同步更新本文档。*
