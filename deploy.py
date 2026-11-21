"""
deploy.py —— 一键部署：本地改完 → 上传服务器 → 重启 → 看日志

用法：
    export MOLLY_SSH_HOST=your.server.ip
    export MOLLY_SSH_USER=root
    export MOLLY_SSH_KEY=~/.ssh/id_ed25519     # 或者用 MOLLY_SSH_PASSWORD
    python deploy.py            # 上传 + 重启 + 看最近日志
    python deploy.py --logs     # 只看日志
    python deploy.py --restart  # 只重启

凭据全部从环境变量读，本文件不含任何主机、账号或密钥。
"""

import os
import re as _re
import stat
import sys

import paramiko

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HOST = os.environ.get("MOLLY_SSH_HOST", "")
USER = os.environ.get("MOLLY_SSH_USER", "root")
PWD = os.environ.get("MOLLY_SSH_PASSWORD", "")
KEY_FILE = os.environ.get("MOLLY_SSH_KEY", "")
LOCAL_DIR = os.path.dirname(os.path.abspath(__file__))
REMOTE_DIR = os.environ.get("MOLLY_REMOTE_DIR", "/opt/molly")
SERVICE = os.environ.get("MOLLY_SERVICE", "molly")

# 需要上传的文件/目录（新增模块记得加进来！）
UPLOAD_FILES = [
    "config.py", "memory.py", "llm.py", "onebot.py", "aliveness.py",
    "persona.py", "stickers.py", "notes.py", "search.py", "file_reader.py",
    "actions.py", "main.py", "tools.py", "health.py", "system_events.py",
    "mom_chat.py", "digests.py", "short_notes.py", "context.py",
    "persona.md", "操作手册.md", "主人赠言.txt",
]
UPLOAD_DIRS = ["people", "stickers"]


def connect():
    if not HOST:
        raise SystemExit("MOLLY_SSH_HOST 没有设置。")
    t = paramiko.Transport((HOST, 22))
    if KEY_FILE:
        t.connect(username=USER, pkey=paramiko.Ed25519Key.from_private_key_file(
            os.path.expanduser(KEY_FILE)))
    else:
        if not PWD:
            raise SystemExit("MOLLY_SSH_KEY 或 MOLLY_SSH_PASSWORD 必须设一个。")
        t.connect(username=USER, password=PWD)
    return t


def sftp_upload(sftp, local, remote):
    st = os.stat(local)
    if stat.S_ISDIR(st.st_mode):
        try:
            sftp.stat(remote)
        except IOError:
            sftp.mkdir(remote)
        for name in os.listdir(local):
            if name.startswith("."):
                continue
            sftp_upload(sftp, os.path.join(local, name), f"{remote}/{name}")
    else:
        sftp.put(local, remote)
        print(f"  ↑ {remote}")


def run(transport, cmd, timeout=120):
    ch = transport.open_session()
    ch.exec_command(cmd)
    out = b""
    while True:
        data = ch.recv(65536)
        if not data:
            break
        out += data
    return out.decode("utf-8", "replace"), ch.recv_exit_status()


def check_upload_cover():
    """自检：main.py import 的本地模块必须都在 UPLOAD_FILES 里。

    踩过两次坑：mom_chat.py / context.py 漏传，服务启动直接 ModuleNotFoundError。
    """
    try:
        src = open(os.path.join(LOCAL_DIR, "main.py"), encoding="utf-8").read()
    except Exception:
        return []
    local_mods = {
        f[:-3] for f in os.listdir(LOCAL_DIR)
        if f.endswith(".py") and f not in ("deploy.py", "health.py")
    }
    imported = set(_re.findall(r"^import (\w+)", src, _re.M))
    imported |= set(_re.findall(r"^from (\w+) import", src, _re.M))
    have = {f[:-3] for f in UPLOAD_FILES if f.endswith(".py")}
    return sorted((imported & local_mods) - have)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "deploy"
    t = connect()
    if mode in ("deploy", "restart"):
        if mode == "deploy":
            missing = check_upload_cover()
            if missing:
                print("警告：这些模块不在 UPLOAD_FILES 里，服务器可能起不来：", missing)
            sftp = paramiko.SFTPClient.from_transport(t)
            print("上传中...")
            for f in UPLOAD_FILES:
                p = os.path.join(LOCAL_DIR, f)
                if os.path.exists(p):
                    sftp_upload(sftp, p, f"{REMOTE_DIR}/{f}")
            for d in UPLOAD_DIRS:
                p = os.path.join(LOCAL_DIR, d)
                if os.path.isdir(p):
                    sftp_upload(sftp, p, f"{REMOTE_DIR}/{d}")
        print("重启...")
        out, _ = run(t, f"systemctl restart {SERVICE}; sleep 2; systemctl is-active {SERVICE}")
        print(out.strip())
    out, _ = run(t, f"tail -30 {REMOTE_DIR}/{SERVICE}.log 2>/dev/null || echo '(no log yet)'")
    print("---- 最近日志 ----")
    print(out)
    t.close()


if __name__ == "__main__":
    main()
