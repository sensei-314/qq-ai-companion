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
            # 2026-11-14：NapCat 用标准 OneBot（POST /<action>），不再是 SnowLuma 的根路径格式
            url = f"{ONEBOT_HTTP.rstrip('/')}/{action}"
            r = requests.post(
                url,
                headers={"Authorization": f"Bearer {ONEBOT_HTTP_TOKEN}"},
                json=params or {},
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
        # 2026-11-14：API 参数是 content（之前用 message 一直失败）
        return self.call("send_qzone_msg", {"content": text})

    def get_qzone_msg_list(self, count=5):
        # NapCat 的参数是 pos/num，不是 count（2026-11-16 修）
        r = self.call("get_qzone_msg_list", {"pos": 0, "num": count})
        return (r or {}).get("data") or {}

    def like_qzone(self, tid, target_uin="", abstime=0):
        """给一条说说点赞（2026-11-21：必须带 target_uin + abstime 才生效）。"""
        params = {"tid": str(tid)}
        if target_uin:
            params["target_uin"] = str(target_uin)
        if abstime:
            params["abstime"] = int(abstime)
        return self.call("like_qzone", params)

    def unlike_qzone(self, tid, target_uin="", abstime=0):
        """取消点赞（参数同 like_qzone）。"""
        params = {"tid": str(tid)}
        if target_uin:
            params["target_uin"] = str(target_uin)
        if abstime:
            params["abstime"] = int(abstime)
        return self.call("unlike_qzone", params)

    def comment_qzone(self, tid, content, parent_comment_id=None):
        """给动态写评论/回复评论（2026-11-14：回复要 parent_comment_id）。"""
        params = {"tid": str(tid), "content": str(content)}
        if parent_comment_id:
            params["parent_comment_id"] = str(parent_comment_id)
        return self.call("comment_qzone", params)

    def qzone_detail(self, tid):
        """一条动态的详情（含评论列表，2026-11-14）。"""
        r = self.call("get_qzone_msg_detail", {"tid": str(tid)})
        return (r or {}).get("data") or {}

    def send_like(self, user_id, times=1):
        """给好友名片/主页点赞（2026-11-14 实测可用）。"""
        return self.call("send_like", {"user_id": int(user_id), "times": int(times)})

    def get_qzone_feeds(self, count=8):
        """好友动态列表（2026-11-14，含 uin/nickname/html/key）。

        2026-11-21：加 complete 参数后部分 feed 会带 tid，可用 detail 读内容。
        """
        r = self.call("get_qzone_feeds", {"count": count, "complete": True})
        return (r or {}).get("data") or {}

    def set_friend_remark(self, user_id, remark):
        """改 QQ 好友备注（2026-11-15，NapCat set_friend_remark）。"""
        return self.call(
            "set_friend_remark", {"user_id": int(user_id), "remark": str(remark or "")}
        )

    def get_guild_list(self):
        """她加入的频道列表（2026-11-14，NapCat 频道接口）。"""
        r = self.call("get_guild_list", {})
        return (r or {}).get("data") or []

    def get_guild_profile(self):
        """她在频道里的个人信息。"""
        r = self.call("get_guild_service_profile", {})
        return (r or {}).get("data") or {}

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
