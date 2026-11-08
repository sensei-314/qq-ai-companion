"""
health.py — 一个极简的服务健康面板（HTTP）。

用法：
    export MOLLY_HEALTH_TOKEN=<换成你自己的随机串>
    python health.py
    # 浏览器打开  http://<本机地址>:8899/?token=<你的串>

展示：systemd 服务状态、容器、内存、磁盘、最近日志。

安全提醒：
- **必须**自己设一个足够长的随机 token，不要用示例值；
- token 走 URL 参数，属于"够用但不严密"的方案；
- **只在内网 / SSH 隧道 / 反向代理后面用**，不要直接暴露在公网明文 HTTP 上。
"""

import hmac
import os
import subprocess
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

TOKEN = os.environ.get("MOLLY_HEALTH_TOKEN", "")
PORT = int(os.environ.get("MOLLY_HEALTH_PORT", "8899"))
SERVICE = os.environ.get("MOLLY_SERVICE", "molly")
LOG_PATH = os.environ.get("MOLLY_LOG", "molly.log")


def run(cmd):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        return (r.stdout or "").strip()
    except Exception as e:
        return f"error: {e}"


def page():
    svc = run(f"systemctl is-active {SERVICE}")
    docker = run("docker ps --format '{{.Names}} {{.Status}}'")
    free = run("free -h | head -2")
    disk = run("df -h / | tail -1")
    log = run(f"tail -10 {LOG_PATH}")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ok = "ok" if svc == "active" else "bad"
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>status</title>
<style>
body{{font-family:system-ui;background:#1e1e2e;color:#cdd6f4;padding:16px;font-size:15px}}
pre{{background:#181825;padding:10px;border-radius:8px;overflow-x:auto;font-size:12px;white-space:pre-wrap}}
h1{{font-size:20px}} h3{{margin-top:18px;font-size:15px}}
.ok{{color:#a6e3a1}} .bad{{color:#f38ba8}} .muted{{color:#9399b2;font-size:12px}}
</style></head><body>
<h1>service status</h1>
<p class="muted">{now}</p>
<p>{SERVICE}: <b class="{ok}">{svc}</b></p>
<h3>containers</h3><pre>{docker or '(none)'}</pre>
<h3>memory</h3><pre>{free}</pre>
<h3>disk</h3><pre>{disk}</pre>
<h3>recent log</h3><pre>{log}</pre>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _authorized(self):
        qs = parse_qs(urlparse(self.path).query)
        got = (qs.get("token") or [""])[0]
        return bool(TOKEN) and hmac.compare_digest(got, TOKEN)

    def do_GET(self):
        if not self._authorized():
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b"forbidden")
            return
        body = page().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit(
            "MOLLY_HEALTH_TOKEN 没有设置。先 export 一个随机串再用（别用示例值）。"
        )
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
