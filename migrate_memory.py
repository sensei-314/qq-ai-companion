"""
migrate_memory.py —— 把 DSH 版 people 记忆迁到 Python 版

来源：$MOLLY_LEGACY_PEOPLE（旧版 people 目录）
目标：本目录 people/*.json + _global.json（全局时间线）

保留字段：role / text / at / images；多余的 who/userId/scene 丢弃。
"""

import glob
import json
import os

SRC = os.environ.get("MOLLY_LEGACY_PEOPLE", "")
DST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "people")


def main():
    if not SRC:
        raise SystemExit("MOLLY_LEGACY_PEOPLE 没有设置（旧版 people 目录）。")
    os.makedirs(DST, exist_ok=True)
    all_msgs = []
    count = 0
    for p in sorted(glob.glob(os.path.join(SRC, "*.json"))):
        base = os.path.basename(p)
        if base.startswith("_"):
            continue
        try:
            with open(p, "r", encoding="utf-8") as f:
                j = json.load(f)
        except Exception as e:
            print(f"skip {base}: {e}")
            continue
        qq = str(j.get("qq") or "")
        name = str(j.get("name") or qq or os.path.splitext(base)[0])
        msgs = []
        for m in j.get("messages") or []:
            item = {
                "role": m.get("role") or "user",
                "text": m.get("text") or "",
                "at": int(m.get("at") or 0),
            }
            if m.get("images"):
                item["images"] = m.get("images")
            msgs.append(item)
            all_msgs.append(
                {
                    "role": item["role"],
                    "name": name,
                    "qq": qq,
                    "text": item["text"],
                    "at": item["at"],
                }
            )
        if not msgs:
            continue
        out = os.path.join(DST, f"{name}.json")
        data = {
            "name": name,
            "qq": qq,
            "updatedAt": max([m["at"] for m in msgs] or [0]),
            "messages": msgs,
        }
        with open(out, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        count += 1
        print(f"migrated {name}.json: {len(msgs)} msgs")

    all_msgs.sort(key=lambda x: x["at"])
    with open(os.path.join(DST, "_global.json"), "w", encoding="utf-8") as f:
        json.dump({"messages": all_msgs[-200:]}, f, ensure_ascii=False, indent=1)
    print(f"done: {count} people, {len(all_msgs)} messages, global timeline built")


if __name__ == "__main__":
    main()
