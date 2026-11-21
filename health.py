"""
health.py — 大肥鱼健康面板 v2（2026-11-13）

手机访问：http://<你的地址>:8899/?token=<MOLLY_HEALTH_TOKEN>
支持：?filter=all|error|msg|action&q=关键词

token 从环境变量读，没设就拒绝启动：
    export MOLLY_HEALTH_TOKEN=<长随机串>

安全：只在局域网 / SSH 隧道 / 反向代理后面用，别直接暴露公网明文 HTTP。
"""

import json
import os
import re
import subprocess
import time
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

TOKEN = os.environ.get("MOLLY_HEALTH_TOKEN", "")
PORT = int(os.environ.get("MOLLY_HEALTH_PORT", "8899"))
BASE = os.environ.get("MOLLY_DIR") or os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE, "molly.log")
CHAT_ONLY_FILE = os.path.join(BASE, "chat_only.jsonl")

# 旧日志（轮转前）的日期：用于给只有时分秒的行补日期
LOG_DATE = ""
try:
    import datetime as _dt
    LOG_DATE = _dt.datetime.fromtimestamp(os.path.getmtime(LOG_FILE + ".1.gz")).strftime("%m-%d")
except Exception:
    LOG_DATE = ""


def run(cmd):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        return (r.stdout or "").strip()
    except Exception as e:
        return f"error: {e}"


def read_log(max_lines=1500):
    """读当前日志 + 轮转日志，并给每行补上完整日期（2026-11-14）。"""
    import datetime as _dt
    import gzip

    raw = []
    paths = [f"{LOG_FILE}.{i}.gz" for i in (3, 2, 1)] + [LOG_FILE]
    for path in paths:
        try:
            mtime = os.path.getmtime(path)
        except Exception:
            continue
        try:
            if path.endswith(".gz"):
                with gzip.open(path, "rt", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
            else:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
        except Exception:
            continue
        for ln in lines:
            raw.append((mtime, ln))

    # 续行合并（没有 [时间] 的行接上一条）
    merged = []
    for mtime, ln in raw:
        if re.match(r"\[\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]|\[\d{2}:\d{2}:\d{2}\]", ln):
            merged.append([mtime, ln])
        elif merged:
            merged[-1][1] += ln
        else:
            merged.append([mtime, ln])
    raw = [(m, "".join(l)) for m, l in merged]

    out = []
    for mtime, ln in raw:
        if "image fail" in ln or "NameError" in ln:
            continue
        m = re.match(r"\[(\d{2}-\d{2} \d{2}:\d{2}:\d{2}|\d{2}:\d{2}:\d{2})\]", ln)
        if m and "-" not in m.group(1):
            # 无日期：按「文件修改时间」推断（行时间比 mtime 晚很多 → 前一天）
            md = _dt.datetime.fromtimestamp(mtime)
            try:
                hh, mm, ss = map(int, m.group(1).split(":"))
                lt = md.replace(hour=hh, minute=mm, second=ss, microsecond=0)
                if lt > md + _dt.timedelta(hours=2):
                    lt -= _dt.timedelta(days=1)
                ln = ln.replace(f"[{m.group(1)}]", f"[{lt.strftime('%m-%d %H:%M:%S')}]", 1)
            except Exception:
                pass
        out.append(ln)
    return out[-max_lines:]


def classify(line):
    t = line.lower()
    # 连接类优先（ws 重连不算异常）
    if any(k in t for k in ("ws] ", "[ws]", "connection reset", "reconnect", "connected", "connection refused")):
        return "conn"
    if any(k in t for k in ("error", "fail", "出错")):
        return "error"
    if any(k in t for k in ("ws] closed", "connection reset", "reconnect", "connected")):
        return "conn"
    # 事件调度（think/queue）单独一类，不算「操作」
    if any(k in t for k in ("[think]", "[queue]", "[opportunity]")):
        return "event"
    # 系统启动/同步（2026-11-15）
    if any(k in t for k in ("molly(py) 启动", "联系人同步", "self=")):
        return "event"
    if any(k in t for k in ("[search]", "[note]", "[timer]", "[recall]", "[poke]", "[qzone]", "[file]", "[tool]", "[img]", "[sleep]", "[skip]")):
        return "action"
    if any(k in t for k in ("←", "→", "模型")):
        return "msg"
    return "other"


CAT_LABEL = {
    "error": "❌ 异常",
    "conn": "🔌 连接",
    "action": "⚙️ 操作",
    "event": "📋 事件",
    "msg": "💬 消息",
    "other": "· 其他",
}

TOOL_CN = {
    "write_note": "写笔记",
    "search_web": "联网搜索",
    "send_message": "发消息",
    "poke": "戳一戳",
    "set_timer": "定闹钟",
    "recall_msg": "撤回消息",
    "search_history": "翻聊天记录",
    "search_actions": "查操作记录",
    "like_feed": "点赞动态",
    "comment_feed": "评论动态",
    "post_qzone": "发说说",
    "send_sticker": "发表情包",
    "skip_reply": "跳过",
}


def humanize(body):
    """摘要（大字，只一句话；详情点开看原文）。"""
    # 消息：谁发给谁（2026-11-14 主人要求）
    mmsg = re.match(r"([←→])\s*([^:：]+?)[:：]\s*([\s\S]*)$", body)
    if mmsg:
        arrow, who, text = mmsg.group(1), mmsg.group(2).strip(), mmsg.group(3)
        who = re.sub(r"[（(][^）)]*[）)]", "", who).strip()
        if who in ("模型", "终端"):
            return "小肥鱼 → 终端"
        if arrow == "→":
            return f"小肥鱼 → {who}"
        return f"{who} → 小肥鱼"
    if body.startswith("[tool]"):
        rest = body[6:].strip()
        name = rest.split(" ", 1)[0] if rest else ""
        return f"🛠 调用了「{TOOL_CN.get(name, name)}」"
    if "image fail" in body:
        return "🖼 图片缓存报错"
    if "session release timed out" in body:
        return "🔌 OneBot 会话重建超时"
    m = re.match(r"\[think\]\s*处理事件：(\w+)", body)
    if m:
        kind_cn = {
            "message": "有人说话",
            "opportunity": "一次空档",
            "reminder": "自己的闹钟",
            "aftertalk": "聊完后想找人",
        }.get(m.group(1), m.group(1))
        return f"🧠 处理事件：{kind_cn}"
    m = re.match(r"\[queue\]\s*\+(\w+)", body)
    if m:
        return f"📥 事件入队：{m.group(1)}"
    m = re.match(r"\[(qzone|timer|poke|recall|note|file|img|sleep|skip)\]\s*(.*)$", body)
    if m:
        tag_cn = {
            "qzone": "空间",
            "timer": "闹钟",
            "poke": "戳一戳",
            "recall": "撤回",
            "note": "记事",
            "file": "文件",
            "img": "图片",
            "sleep": "睡觉",
            "skip": "跳过",
        }.get(m.group(1), m.group(1))
        return f"[{tag_cn}]"
    if len(body) > 60:
        return body[:60] + "…"
    return body


def qq_names():
    """QQ → 名字映射（2026-11-13：让消息显示「名字(QQ)」）。"""
    names = {}
    try:
        import glob
        import json
        for p in glob.glob(os.path.join(BASE, "people", "*.json")):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    j = json.load(f)
                qq = str(j.get("qq") or "")
                if qq and re.fullmatch(r"\d{5,12}", qq):
                    names[qq] = j.get("name") or qq
            except Exception:
                continue
    except Exception:
        pass
    return names


def page(filter_kind="all", q=""):
    molly = run("systemctl is-active molly")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    up_raw = run("uptime")
    lm = re.search(r"load average: ([0-9.]+), ([0-9.]+), ([0-9.]+)", up_raw)
    load_txt = f"{lm.group(1)} / {lm.group(2)} / {lm.group(3)}" if lm else "?"
    um = re.search(r"up\s+([^,]+)", up_raw)
    up_txt = um.group(1).strip() if um else "?"

    mem_total = mem_used = mem_avail = mem_buff = "?"
    swap_txt = "?"
    for ln in run("free -m").splitlines():
        p = ln.split()
        if len(p) >= 7 and p[0] == "Mem:":
            mem_total = f"{int(p[1]) / 1024:.1f}G"
            mem_used = f"{int(p[2]) / 1024:.1f}G"
            mem_avail = f"{int(p[6]) / 1024:.1f}G"
            mem_buff = f"{int(p[5]) / 1024:.1f}G"
        if len(p) >= 4 and p[0] == "Swap:":
            swap_txt = f"{int(p[2]) / 1024:.1f}G / {int(p[1]) / 1024:.1f}G"

    dfp = run("df -h / | tail -1").split()
    disk_txt = f"{dfp[2]} / {dfp[1]}（{dfp[4]}）" if len(dfp) >= 5 else "?"

    molly_mem_raw = run("systemctl show molly -p MemoryCurrent | cut -d= -f2")
    try:
        molly_mem = f"{int(molly_mem_raw) / 1024 / 1024:.0f}MB"
    except Exception:
        molly_mem = "?"

    docker = run("docker ps --format '{{.Names}} {{.Status}}'")
    docker_mem = run("docker stats --no-stream --format '{{.MemUsage}}' napcat 2>/dev/null | head -1") or "?"

    lines = read_log(1000000)
    # 今天她做了什么（2026-11-21）
    today = time.strftime("%m-%d", time.localtime())
    tool_counts = {}
    for _ln in lines:
        if not _ln.startswith(f"[{today}"):
            continue
        _mt = re.search(r"\[tool\] ([A-Za-z_]+)", _ln)
        if _mt:
            tool_counts[_mt.group(1)] = tool_counts.get(_mt.group(1), 0) + 1

    def tc(k):
        return tool_counts.get(k, 0)

    names = qq_names()
    entries = []
    counts_all = {}

    # 纯聊天（chat_only.jsonl，不进上下文，2026-11-15）
    chat_rows = []
    if filter_kind == "chat":
        try:
            with open(CHAT_ONLY_FILE, "r", encoding="utf-8", errors="replace") as _cf:
                _cl = _cf.readlines()[-300:]
        except Exception:
            _cl = []
        for _ln in _cl:
            try:
                _d = json.loads(_ln)
            except Exception:
                continue
            _t = time.strftime("%m-%d %H:%M:%S", time.localtime((_d.get("at") or 0) / 1000))
            _why = str(_d.get("why") or "").strip()
            _name = _d.get("to_name") or _d.get("to_qq")
            if _name:
                _label = f"小肥鱼 → {_name}"
                _text = str(_d.get("text") or "")
                chat_rows.append(
                    f'<div class="row msg"><span class="t">{_t}</span>'
                    f'<span class="k">💬</span><span class="b">{_label}：{_text}</span></div>'
                )
            else:
                # 呢喃：折叠，点开才看内容（2026-11-16）
                _text = str(_d.get("text") or "")
                chat_rows.append(
                    f'<details class="row"><summary><span class="t">{_t}</span>'
                    f'<span class="k">🗣</span><span class="b">小鲸鱼呢喃了</span></summary>'
                    f'<div class="full">{_text}</div></details>'
                )
        chat_rows = chat_rows[::-1]
    for ln in lines:
        s = ln.rstrip("\n")
        m = re.match(r"\[(\d{2}-\d{2} \d{2}:\d{2}:\d{2}|\d{2}:\d{2}:\d{2})\]\s*(.*)", s)
        ts = m.group(1) if m else "—"
        body = m.group(2) if m else s
        # 老日志只有 QQ：补上名字
        for qq, name in names.items():
            body = re.sub(rf"([←→]\s*){re.escape(qq)}:", rf"\g<1>{name}({qq}):", body)
        kind = classify(body)
        counts_all[kind] = counts_all.get(kind, 0) + 1
        if filter_kind != "all" and kind != filter_kind:
            continue
        if q and q.lower() not in body.lower():
            continue
        entries.append((ts, kind, body[:200]))
    # 最新在上（2026-11-15：全量，前端分页加载）
    entries = entries[::-1]

    counts = counts_all  # 统计用全量（不受当前标签影响）

    def link(k, label):
        active = "active" if filter_kind == k else ""
        return f'<a class="chip {active}" href="/?token={TOKEN}&filter={k}">{label}</a>'

    if filter_kind == "chat":
        rows = "".join(chat_rows) or '<div class="row"><span class="b">（她还没嘀咕什么）</span></div>'
    else:
        rows = ""
    for ts, k, body in (entries[:100] if filter_kind != "chat" else []):
        short = humanize(body)
        full = body
        mmsg = re.match(r"([←→])\s*([^:：]+?)[:：]\s*([\s\S]*)$", body)
        if mmsg:
            arrow, who, text = mmsg.group(1), mmsg.group(2).strip(), mmsg.group(3)
            if who in ("模型", "终端"):
                full = f"小肥鱼 → 终端：{text}"
            else:
                full = f"{'小肥鱼 → ' + who if arrow == '→' else who + ' → 小肥鱼'}：{text}"
        if len(short) > 70:
            short = short[:70] + "…"
        rows += (
            f'<details class="row {k}"><summary>'
            f'<span class="t">{ts}</span><span class="k">{CAT_LABEL.get(k,"")}</span>'
            f'<span class="b">{short}</span></summary>'
            f'<div class="full">{full[:900]}</div></details>'
        )
    if not rows:
        rows = '<div class="row"><span class="b">（没有符合条件的记录）</span></div>'

    # 剩余数据（前端滚动加载，2026-11-15）
    import json as _json

    rest = _json.dumps(
        [{"t": t, "k": k, "b": b} for t, k, b in entries[100:]], ensure_ascii=False
    )

    ok = "ok" if molly == "active" else "bad"
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>小肥鱼状态</title>
<style>
*{{box-sizing:border-box}}
body{{font-family:system-ui;background:#1e1e2e;color:#cdd6f4;padding:14px;font-size:15px;margin:0}}
h1{{font-size:19px;margin:0 0 4px}} h2{{font-size:15px;margin:18px 0 8px}}
.muted{{color:#9399b2;font-size:12px}}
.card{{background:#181825;border-radius:12px;padding:10px 12px;margin-top:10px}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:8px}}
.kv{{font-size:13px}} .kv b{{color:#f9e2af}}
.ok{{color:#a6e3a1}} .bad{{color:#f38ba8}}
.chips{{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0}}
.chip{{background:#313244;color:#cdd6f4;text-decoration:none;padding:5px 10px;border-radius:20px;font-size:12px}}
.chip.active{{background:#89b4fa;color:#1e1e2e;font-weight:600}}
.list{{background:#181825;border-radius:14px;padding:8px;max-height:56vh;overflow-y:auto;-webkit-overflow-scrolling:touch;overscroll-behavior:contain;touch-action:pan-y}}
.row{{display:block;padding:0;border-bottom:1px solid #232336}}
.row summary{{display:flex;gap:8px;padding:7px 8px;cursor:pointer;list-style:none;align-items:flex-start}}
.row summary::-webkit-details-marker{{display:none}}
.row .full{{padding:2px 8px 10px 70px;color:#a6adc8;font-size:12px;white-space:pre-wrap;overflow-wrap:anywhere}}
.row:last-child{{border-bottom:none}}
.row .t{{color:#9399b2;flex:0 0 54px;font-variant-numeric:tabular-nums;white-space:nowrap}}
.row .k{{flex:0 0 auto;min-width:42px;text-align:center;white-space:nowrap;font-size:11px;opacity:.9}}
.row .b{{flex:1 1 0;min-width:0;white-space:pre-wrap;overflow-wrap:anywhere;word-break:normal}}
.row.error .b{{color:#f38ba8}} .row.conn .b{{color:#fab387}} .row.msg .b{{color:#a6e3a1}}
input[type=text]{{width:100%;background:#313244;border:none;border-radius:8px;padding:8px 10px;color:#cdd6f4;font-size:13px}}
form{{display:flex;gap:6px;margin-top:8px}}
button{{background:#89b4fa;border:none;color:#1e1e2e;border-radius:8px;padding:8px 14px;font-size:13px;font-weight:600}}
</style></head><body>
<h1>🐳 小肥鱼状态</h1>
<p class="muted">{now}</p>

<div class="card grid">
  <div class="kv">服务：<b class="{ok}">{molly}</b></div>
  <div class="kv">运行：<b>{up_txt}</b></div>
  <div class="kv">负载：<b>{load_txt}</b></div>
  <div class="kv">molly 内存：<b>{molly_mem}</b></div>
  <div class="kv">内存：<b>{mem_used} / {mem_total}</b></div>
  <div class="kv">可用：<b>{mem_avail}</b>（缓存 {mem_buff}）</div>
  <div class="kv">Swap：<b>{swap_txt}</b></div>
  <div class="kv">磁盘：<b>{disk_txt}</b></div>
  <div class="kv">容器：<b>{docker or '无'}</b></div>
  <div class="kv">容器内存：<b>{docker_mem}</b></div>
</div>

<div class="card">
  <div class="kv" style="margin-bottom:6px"><b>她今天做了什么</b>（{today}）</div>
  <div class="kv">✍️ 笔记 {tc('write_note')}｜📌 短期备忘 {tc('write_short_note')}｜📝 说说 {tc('post_qzone')}｜👍 点赞 {tc('like_feed')}｜💭 评论 {tc('comment_feed')}｜👀 看动态 {tc('read_feeds')}｜💬 群消息 {tc('send_group')}｜✉️ 私聊 {tc('send_message')}｜😀 表情包 {tc('send_sticker')}｜⏭ 跳过 {tc('skip_reply')}</div>
</div>

<h2>记录（{counts.get('error',0)} 异常 / {counts.get('conn',0)} 连接 / {counts.get('msg',0)} 消息）</h2>
<div class="chips">
  {link('all','全部')}
  {link('error','❌ 异常')}
  {link('conn','🔌 连接')}
  {link('action','⚙️ 操作')}
  {link('event','📋 事件')}
  {link('msg','💬 消息')}
  {link('chat','🗣 小肥鱼的呢喃')}
</div>
<form method="get" action="/">
  <input type="hidden" name="token" value="{TOKEN}">
  <input type="hidden" name="filter" value="{filter_kind}">
  <input type="text" name="q" placeholder="搜关键词…" value="{q}">
  <button>搜</button>
</form>
<div class="list" id="list" style="margin-top:10px">{rows}</div>
<script>
const __REST__ = {rest};
let __shown = 0;
const __list = document.getElementById("list");
function __loadMore() {{
  if (__shown >= __REST__.length) return;
  const batch = __REST__.slice(__shown, __shown + 100);
  __shown += 100;
  for (const r of batch) {{
    const d = document.createElement("details");
    d.className = "row " + (r.k || "");
    d.innerHTML = '<summary><span class="t">' + r.t + '</span><span class="k">·</span><span class="b">' + r.b + '</span></summary>';
    __list.appendChild(d);
  }}
}}
function __nearBottom() {{
  if (__list && __list.scrollTop + __list.clientHeight >= __list.scrollHeight - 200) return true;
  return window.innerHeight + window.scrollY >= document.body.offsetHeight - 300;
}}
if (__list) __list.addEventListener("scroll", () => {{ if (__nearBottom()) __loadMore(); }});
window.addEventListener("scroll", () => {{ if (__nearBottom()) __loadMore(); }});
window.addEventListener("touchmove", () => {{ if (__nearBottom()) __loadMore(); }}, {{passive: true}});
</script>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        if qs.get("token", [""])[0] != TOKEN:
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b"forbidden")
            return
        fk = qs.get("filter", ["all"])[0]
        if fk not in ("all", "error", "conn", "action", "event", "msg", "chat"):
            fk = "all"
        q = qs.get("q", [""])[0][:50]
        body = page(fk, q).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit(
            "MOLLY_HEALTH_TOKEN 没有设置。先 export 一个长随机串再用（别用示例值）。"
        )
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
