"""
fetch_backup.py —— 从服务器拉取最新备份到本地（手动运行）

用法：
    export MOLLY_SSH_HOST=your.server.ip
    export MOLLY_SSH_USER=root
    export MOLLY_SSH_PASSWORD=...    # 或用 MOLLY_SSH_KEY 指向私钥
    export MOLLY_BACKUP_DIR=./backups
    python fetch_backup.py
"""

import os
import sys

import paramiko

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HOST = os.environ.get("MOLLY_SSH_HOST", "")
USER = os.environ.get("MOLLY_SSH_USER", "root")
PWD = os.environ.get("MOLLY_SSH_PASSWORD", "")
KEY_FILE = os.environ.get("MOLLY_SSH_KEY", "")
LOCAL_DIR = os.environ.get(
    "MOLLY_BACKUP_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "backups")
)
REMOTE_BACKUP_DIR = os.environ.get("MOLLY_REMOTE_BACKUP_DIR", "/opt/backups")


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


def main():
    os.makedirs(LOCAL_DIR, exist_ok=True)
    t = connect()
    sftp = paramiko.SFTPClient.from_transport(t)
    entries = sftp.listdir_attr(REMOTE_BACKUP_DIR)
    files = [
        e for e in entries
        if e.filename.startswith("molly-") and e.filename.endswith(".tar.gz")
    ]
    if not files:
        print("服务器上还没有备份文件")
        return
    latest = max(files, key=lambda e: e.st_mtime)
    remote = f"{REMOTE_BACKUP_DIR}/{latest.filename}"
    local = os.path.join(LOCAL_DIR, latest.filename)
    sftp.get(remote, local)
    print(f"已下载：{latest.filename}（{os.path.getsize(local) / 1024 / 1024:.1f} MB）")
    print(f"位置：{LOCAL_DIR}")
    sftp.close()
    t.close()


if __name__ == "__main__":
    main()
