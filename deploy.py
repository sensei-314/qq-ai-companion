"""
deploy.py —— 一键部署：本地改完 → 上传服务器 → 重启 → 看日志

用法：
    export MOLLY_SSH_HOST=your.server.ip
    export MOLLY_SSH_USER=root
    export MOLLY_SSH_PASSWORD=...        # 或者用 MOLLY_SSH_KEY 指向私钥文件
    python deploy.py                     # 上传 + 重启 + 看日志
    python deploy.py --logs              # 只看日志
    python deploy.py --restart           # 只重启

上传内容：当前目录下所有 .py，加可选的 persona.md / 数据目录。
凭据**全部从环境变量读**，本文件不含任何主机、账号或密钥。
"""

import os
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

# 可选上传的额外文件/目录（存在才传）
EXTRA_FILES = ["persona.md"]
EXTRA_DIRS = ["people", "stickers"]


def connect():
    if not HOST:
        raise SystemExit("MOLLY_SSH_HOST 没有设置。")
    t = paramiko.Transport((HOST, 22))
    if KEY_FILE:
        pkey = paramiko.RSAKey.from_private_key_file(KEY_FILE)
        t.connect(username=USER, pkey=pkey)
    else:
        if not PWD:
            raise SystemExit("MOLLY_SSH_PASSWORD 或 MOLLY_SSH_KEY 必须设一个。")
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


def run(transport, cmd):
    ch = transport.open_session()
    ch.exec_command(cmd)
    out = b""
    while True:
        data = ch.recv(65536)
        if not data:
            break
        out += data
    return out.decode("utf-8", "replace"), ch.recv_exit_status()


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "deploy"
    t = connect()
    if mode in ("deploy", "restart"):
        if mode == "deploy":
            sftp = paramiko.SFTPClient.from_transport(t)
            print("上传中...")
            py_files = [f for f in os.listdir(LOCAL_DIR) if f.endswith(".py")]
            for f in py_files + EXTRA_FILES:
                p = os.path.join(LOCAL_DIR, f)
                if os.path.exists(p):
                    sftp_upload(sftp, p, f"{REMOTE_DIR}/{f}")
            for d in EXTRA_DIRS:
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
