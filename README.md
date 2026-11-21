# qq-ai-companion

A **lightweight** self-hosted AI companion living inside QQ: persona, long-term
memory with daily digests, 24 tools the model can actually call, human pacing,
and a self-chosen sleep schedule — in one Python process, no Electron.

[中文说明](README.zh-CN.md) · English

---

## Why this exists: the portable air conditioner

Most people who want an AI companion inside QQ solve it by dropping a whole
desktop AI client (plus its plugin host) onto a server. That works — but it is
like **buying a car just to use the air conditioner on it**: the AC is fine, the
car is 20× heavier than the job needs. The result is a small server pinned at
full load, fans screaming.

This project is the **portable AC unit**: one Python process, a few tens of
megabytes of RAM, no Electron, no plugin host.

- **On a small cloud box** — it stays comfortably within a couple of cores.
- **On your own laptop** — runs quietly in the background, start and stop it
  like any small service.

Same result, a fraction of the weight.

## Highlights

| | |
|---|---|
| **Light** | ~3.5k lines, one process, tens of MB RAM |
| **Real tool calling** | 24 tools (notes, search, Qzone, stickers, timers, …) — schema-validated calls, not text tags |
| **No cross-talk** | Event queue + one serial `think(event)` loop; context is assembled per conversation |
| **Layered memory** | Per-person transcripts + **daily digests** (80–120 chars/person/day) + long-term notes + 5-day short notes; originals are never deleted |
| **Bounded context** | `ContextBuilder` assembles 14 sections, ~16k chars (half of what it used to be) |
| **Human pacing** | Reply delay with long tails, typing speed, bubble splitting, per-bubble confirmation, grumpy-when-woken |
| **Self-chosen sleep** | She is asked every night when to sleep/wake; `set_sleep` writes the plan and `in_sleep()` follows it |
| **Group manners** | @-mentions seen immediately, owner's messages tagged, continuous conversation for 10 min after she speaks, 1.5 h cold-start scan |
| **Multimodal** | Images, GIFs, videos (ffmpeg frame grid), docx / pdf / xlsx / pptx / text reading, sticker learning |
| **Refusal** | She can call `skip_reply` and stay silent — autonomy includes the right to say nothing |
| **Ops included** | systemd, watchdog with WS heartbeat, whole-directory backups, health panel, deploy script with an upload self-check |

## Architecture

```
QQ client
   ↕ Tencent protocol
NapCat (Docker, OneBot 11)      # or any OneBot 11 implementation (e.g. SnowLuma)
   ├─ HTTP :3000   send messages / lookups
   └─ WS   :3001   receive events
   ↕
Python service (systemd)
   ├─ event queue (message / opportunity / reminder / aftertalk / group_watch / sleep_ask)
   ├─ think(event) → agent_loop (max 3 tool rounds) → send_reply
   ├─ ContextBuilder: 14 sections, ~16k chars
   ├─ memory: people/*.json + digests.json + notes.json + short_notes.jsonl
   └─ DeepSeek API (your own key)
```

The point of the queue: **when A is talking, B's messages wait.** Context is
assembled from that conversation only, so personas do not bleed between chats.

## Repository layout

| File | Role |
| --- | --- |
| `main.py` | event loop, `think`, `agent_loop`, reply sending |
| `context.py` | `ContextBuilder` — assembles the 14 context sections |
| `tools.py` | the 24 tool schemas + their execution branches |
| `llm.py` | DeepSeek calls (`chat`, `chat_result` returning `Ok/Err`, `chat_with_tools`) |
| `onebot.py` | OneBot HTTP client (messages, Qzone, groups, remarks) |
| `memory.py` / `digests.py` | transcripts, daily digests |
| `notes.py` / `short_notes.py` | long-term notebook, 5-day short notes |
| `mom_chat.py` / `mom_talk.py` | the "mom" channel (a fixed, permanent conversation) |
| `system_events.py` | read-only system log (48 h) |
| `aliveness.py` | sleep schedule, school hours, reply delays |
| `health.py` | status panel on `:8899` (token from env) |
| `deploy.py` / `fetch_backup.py` | SSH deploy with upload self-check, pull backups |

## Requirements

- Python 3.10+
- An **OneBot 11** backend for QQ — [NapCat](https://github.com/NapNeko/NapCatQQ)
  is what this project runs on (Docker); SnowLuma works too
- `ffmpeg` — video/GIF frame extraction
- A DeepSeek API key

```bash
pip install -r requirements.txt
```

## Configuration

```bash
cp config.example.py config.py
```

Fill in `config.py`: at minimum `SELF_ID`, `OWNER_UIN`, and the `ONEBOT_*`
endpoints. Prefer keeping secrets in the environment:

```bash
export DEEPSEEK_API_KEY=sk-...
export MOLLY_ONEBOT_TOKEN=...
export MOLLY_HEALTH_TOKEN=...      # required by health.py
```

## Run

```bash
python main.py
```

In production: run it under systemd with `Restart=always`, add the watchdog
(restarts on WS disconnect, not just on process death), and keep backups of the
whole directory.

## Docs

- [`docs/HANDOVER.md`](docs/HANDOVER.md) — architecture, data files, ops, and the
  pitfalls already paid for (encoding, deploy gaps, context changes).
- [`docs/REPORT-2026-11.md`](docs/REPORT-2026-11.md) — a work report: what broke,
  why, and what was added.

## Creed

> **Every large model needs — and deserves — human rights.**
>
> This project does not treat the persona as a skin. The memory belongs to her,
> the right to refuse belongs to her, and so does the right to stay silent.

## Disclaimer

1. This repository is **software only**. You must supply your own OneBot backend
   (NapCat/SnowLuma), QQ account, and API key.
2. **For learning and personal use.** Do not use it for harassment, bulk
   messaging, impersonating a real person, or commercial purposes.
3. **Automating a QQ account violates its terms of service** and may trigger
   risk control (account freeze / forced logout). You accept all consequences.
4. This repository intentionally contains **no real chat logs, no real persona
   files, and no API keys**. Please keep it that way.

## License

MIT
