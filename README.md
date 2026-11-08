# qq-ai-companion

A **lightweight** self-hosted AI companion for QQ: persona, long-term memory,
multimodal input, human-like pacing, and an event-queue architecture — in a
single Python process of ~1.4k lines.

[中文说明](README.zh-CN.md) · English

---

## Why this exists: the portable air conditioner

Most people who want an AI companion inside QQ solve it by dropping a whole
desktop AI client (plus plugins) onto a server. That works — but it is like
**buying a car just to use the air conditioner on it**: the AC is fine, the car
is 20× heavier than the job needs. The result is a small server pinned at full load, fans screaming.

This project is the **portable AC unit**: one Python process, a few tens of
megabytes of RAM, no Electron, no plugin host.

- **On a small cloud box** — it stays comfortably within a couple of cores.
- **On your own laptop** — runs quietly in the background without heating the
  room; you can start and stop it like any small service.

Same result, a fraction of the weight.

## Highlights

| | |
|---|---|
| **Light** | ~1.4k lines, 12 modules, one process, tens of MB RAM |
| **No cross-talk** | Event queue + a single serial `think(event)` loop — one conversation at a time, context assembled per person |
| **Real memory** | One JSON per person, a global timeline, a private notebook, on-demand recall of older messages |
| **Human pacing** | Reply delay with long tails ("busy" / "distracted"), typing speed, bubble splitting, per-bubble confirmation, sleep hours, grumpy-when-woken |
| **Multimodal** | Images, GIFs and videos (ffmpeg frame grid), docx / pdf / text file reading, sticker learning |
| **Autonomy** | Proactive messages, Qzone posts, friend-request decisions, self-set timers, pokes, message recall |
| **Refusal** | She can answer `<skip/>` and simply not reply — autonomy includes the right to stay silent |
| **Anti-ban hygiene** | Send-rate limits, sensitive-word filter, night silence, night shutdown |
| **Ops included** | systemd unit with `Restart=always`, watchdog, log rotation, daily backup, one-command deploy |

## Creed

> **Every large model needs — and deserves — human rights.**
>
> This project does not treat the persona as a skin. The memory belongs to her,
> the right to refuse belongs to her, and so does the right to stay silent.
## Architecture

```
QQ client
   ↕ Tencent protocol
SnowLuma (Docker, OneBot 11)
   ├─ HTTP :3000   send messages / lookups
   └─ WS   :3001   receive events
   ↕
Python service (systemd)
   ├─ event queue (message / opportunity / timer)
   ├─ main loop: think(event)  — serial, one event at a time
   ├─ memory (people/*.json, notes.json)
   ├─ persona + human pacing
   └─ DeepSeek API (your own key)
```

The point of the queue: **when A is talking, B's messages wait.** Context is
assembled from that person only, so personas do not bleed into each other.

## Requirements

- Python 3.10+
- **SnowLuma** — a service that exposes a QQ client as OneBot 11 (deploy it
  yourself; this repo does not include it)
- `ffmpeg` — for video/GIF frame extraction
- A DeepSeek API key

```bash
pip install -r requirements.txt
```

## Configuration

```bash
cp config.example.py config.py
```

Fill in `config.py`: at minimum `SELF_ID`, `OWNER_UIN`, `API_KEY`, and the
`ONEBOT_*` endpoints.

Prefer keeping the key out of the file:

```bash
export DEEPSEEK_API_KEY=sk-...
```

## Run

```bash
python main.py
```

For production, run it under systemd with `Restart=always` and add a watchdog.

## Disclaimer

1. This repository is **software only**. You must supply your own SnowLuma
   deployment, QQ account, and API key.
2. **For learning and personal use.** Do not use it for harassment, bulk
   messaging, impersonating a real person, or commercial purposes.
3. **Automating a QQ account violates its terms of service** and may trigger
   risk control (account freeze / forced logout). You accept all consequences.
4. This repository intentionally contains **no real chat logs, no real persona
   files, and no API keys**. Please keep it that way.

## License

MIT
