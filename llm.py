"""
llm.py —— DeepSeek 调用（直连 OpenAI 兼容接口）

要点：
  - 开思考（像人）；
  - 图片转 data URL（OpenAI image_url 格式）；
  - 空回复/报错返回 (None, error)。
"""

import base64
import os
import subprocess
import tempfile

import requests

from config import (
    API_KEY,
    API_URL,
    MODEL,
    THINKING,
    MAX_TOKENS,
    FFMPEG,
    VIDEO_MAX_SECONDS,
    VIDEO_FRAMES,
    VIDEO_COLUMNS,
    VIDEO_FRAME_WIDTH,
)


def image_data_url(url, timeout=15):
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    mime = (r.headers.get("content-type") or "image/jpeg").split(";")[0]
    if not mime.startswith("image/"):
        mime = "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(r.content).decode()}"


def video_contact_sheet(url, timeout=30):
    """视频/动图 → 抽帧拼成一张 PNG（和 DSH 版 ffmpeg 抽帧同思路）。"""
    if not FFMPEG or not os.path.exists(FFMPEG):
        return None
    try:
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        data = r.content
        if not data:
            return None
        with tempfile.TemporaryDirectory() as d:
            inp = os.path.join(d, "in.bin")
            out = os.path.join(d, "sheet.png")
            with open(inp, "wb") as f:
                f.write(data)
            rows = max(1, (VIDEO_FRAMES + VIDEO_COLUMNS - 1) // VIDEO_COLUMNS)
            vf = (
                f"fps=0.25,scale={VIDEO_FRAME_WIDTH}:-2,"
                f"tile={VIDEO_COLUMNS}x{rows}:padding=4:margin=4"
            )
            subprocess.run(
                [FFMPEG, "-y", "-i", inp, "-t", str(VIDEO_MAX_SECONDS), "-vf", vf, "-frames:v", "1", out],
                capture_output=True,
                timeout=45,
            )
            if not os.path.exists(out):
                return None
            with open(out, "rb") as f:
                png = f.read()
            return "data:image/png;base64," + base64.b64encode(png).decode()
    except Exception as e:
        print(f"[llm] video frame fail: {e}")
        return None


def _is_video(url):
    u = str(url).lower()
    return any(u.split("?")[0].endswith(ext) for ext in (".mp4", ".mov", ".mkv", ".webm", ".avi"))


def _is_gif(url):
    return ".gif" in str(url).lower().split("?")[0]


def build_messages(system, messages):
    out = [{"role": "system", "content": system}]
    for m in messages:
        imgs = m.get("images") or []
        if imgs:
            parts = []
            for u in imgs[:2]:
                try:
                    if _is_video(u) or _is_gif(u):
                        frame = video_contact_sheet(u)
                        if frame:
                            parts.append({"type": "image_url", "image_url": {"url": frame}})
                        continue
                    parts.append({"type": "image_url", "image_url": {"url": image_data_url(u)}})
                except Exception as e:
                    print(f"[llm] image fail: {e}")
            parts.append({"type": "text", "text": m.get("text") or "[图片]"})
            out.append({"role": "user", "content": parts})
        else:
            out.append({"role": m.get("role") or "user", "content": m.get("text") or ""})
    return out


def chat(system, messages, max_tokens=MAX_TOKENS, thinking=THINKING):
    if not API_KEY:
        return None, "DEEPSEEK_API_KEY 未配置"
    body = {
        "model": MODEL,
        "messages": build_messages(system, messages),
        "max_tokens": max_tokens,
        "stream": False,
        "thinking": {"type": "enabled" if thinking else "disabled"},
    }
    try:
        r = requests.post(
            API_URL,
            headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
            json=body,
            timeout=180,
        )
        j = r.json()
        if r.status_code != 200:
            return None, (j.get("error") or {}).get("message", f"HTTP {r.status_code}")
        text = (((j.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
        return (text or None), (None if text else "空回复")
    except Exception as e:
        return None, str(e)
