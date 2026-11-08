"""
onebot.py —— SnowLuma（OneBot 11）通道

HTTP：调动作（发消息、查资料）
WS：收事件（消息、好友申请、戳一戳）
"""

import json
import threading
import time

import requests
import websocket

from config import ONEBOT_HTTP, ONEBOT_WS, ONEBOT_TOKEN, ONEBOT_HTTP_TOKEN


class OneBot:
    def __init__(self, logger=print):
        self.logger = logger
        self.ws = None

    # ---------- HTTP ----------
    def call(self, action, params=None, timeout=15):
        try:
            r = requests.post(
                ONEBOT_HTTP,
                headers={"Authorization": f"Bearer {ONEBOT_HTTP_TOKEN}"},
                json={"action": action, "params": params or {}},
                timeout=timeout,
            )
            return r.json()
        except Exception as e:
            self.logger(f"[onebot] {action} fail: {e}")
            return None

    def send_private(self, user_id, text):
        r = self.call("send_private_msg", {"user_id": int(user_id), "message": text})
        return ((r or {}).get("data") or {}).get("message_id")

    def send_group(self, group_id, text):
        r = self.call("send_group_msg", {"group_id": int(group_id), "message": text})
        return ((r or {}).get("data") or {}).get("message_id")

    def send_poke(self, user_id):
        """戳一戳（2026-11-08 主人：她也要能戳别人）。"""
        return self.call("send_poke", {"user_id": int(user_id)})

    def delete_msg(self, message_id):
        """撤回消息（2026-11-08 主人：撤回要真的能撤）。"""
        try:
            return self.call("delete_msg", {"message_id": int(message_id)})
        except Exception as e:
            self.logger(f"[onebot] delete_msg fail: {e}")
            return None

    def send_private_image(self, user_id, path):
        import base64
        try:
            with open(path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
        except Exception as e:
            self.logger(f"[onebot] read image fail: {e}")
            return None
        return self.send_private(user_id, f"[CQ:image,file=base64://{b64}]")

    def send_group_image(self, group_id, path):
        import base64
        try:
            with open(path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
        except Exception as e:
            self.logger(f"[onebot] read image fail: {e}")
            return None
        return self.send_group(group_id, f"[CQ:image,file=base64://{b64}]")

    def get_friend_list(self):
        r = self.call("get_friend_list")
        return (r or {}).get("data") or []

    def get_group_list(self):
        r = self.call("get_group_list")
        return (r or {}).get("data") or []

    def get_group_member_list(self, group_id):
        r = self.call("get_group_member_list", {"group_id": int(group_id)})
        return (r or {}).get("data") or []

    def get_stranger_info(self, user_id):
        r = self.call("get_stranger_info", {"user_id": int(user_id), "no_cache": False})
        return (r or {}).get("data") or {}

    def set_friend_add_request(self, flag, approve):
        return self.call("set_friend_add_request", {"flag": flag, "approve": bool(approve)})

    # ---------- QQ 空间 ----------
    def send_qzone_msg(self, text):
        return self.call("send_qzone_msg", {"message": text})

    def get_qzone_msg_list(self, count=5):
        r = self.call("get_qzone_msg_list", {"count": count})
        return (r or {}).get("data") or {}

    def like_qzone(self, tid):
        """给一条动态点赞（2026-11-08，SnowLuma 的 like_qzone 需要 tid）。"""
        return self.call("like_qzone", {"tid": str(tid)})

    def comment_qzone(self, tid, content):
        """给动态写评论（2026-11-08 实测 comment_qzone 可用）。"""
        return self.call("comment_qzone", {"tid": str(tid), "content": str(content)})

    # ---------- WS ----------
    def listen(self, on_event):
        url = ONEBOT_WS + (ONEBOT_TOKEN or "")
        while True:
            try:
                ws = websocket.WebSocketApp(
                    url,
                    on_message=lambda w, m: self._on_raw(m, on_event),
                    on_open=lambda w: self.logger("[ws] connected"),
                    on_error=lambda w, e: self.logger(f"[ws] error: {e}"),
                )
                ws.run_forever()
            except Exception as e:
                self.logger(f"[ws] {e}")
            self.logger("[ws] closed, reconnect in 5s")
            time.sleep(5)

    def _on_raw(self, message, on_event):
        try:
            ev = json.loads(message)
        except Exception:
            return
        threading.Thread(target=on_event, args=(ev,), daemon=True).start()
