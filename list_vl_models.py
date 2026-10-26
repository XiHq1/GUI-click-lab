#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""列出当前 key 能用的视觉模型（名字里带 vl / vision / omni 的）。

用法：
    python list_vl_models.py --base-url https://dashscope.aliyuncs.com/compatible-mode/v1
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--api-key", default="")
    ap.add_argument("--all", action="store_true", help="列出全部模型，不过滤")
    args = ap.parse_args()

    key = args.api_key or os.environ.get("GUI_LAB_API_KEY", "")
    base = args.base_url.rstrip("/")
    if not base.endswith("/v1"):
        base += "/v1"

    req = urllib.request.Request(
        f"{base}/models",
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode('utf-8', 'ignore')[:300]}")
        return 1

    ids = [m.get("id", "") for m in data.get("data", [])]
    print(f"共 {len(ids)} 个模型")

    vl = [i for i in ids if any(k in i.lower() for k in ("vl", "vision", "omni"))]
    show = ids if args.all else vl
    if not show:
        print("没有找到视觉模型。去控制台『模型广场』开通。")
        return 1

    print(f"\n视觉模型（{len(show)} 个）：")
    for i in sorted(show):
        print("  " + i)

    eight = [i for i in vl if "8b" in i.lower()]
    print()
    if eight:
        print("含 8B 的：", eight)
    else:
        print("⚠ 列表里没有 8B 的视觉模型。")
        print("  可选：用 qwen3-vl-flash（最接近小模型）或本地跑 8B。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
