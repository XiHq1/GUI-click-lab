#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ping_model.py —— 连不上模型时先跑这个。

它只做两件事：
    1. 问服务器：你有哪些模型？
    2. 发一张图 + 一句话，看它回什么、花多久。

跑法：
    python ping_model.py --base-url http://127.0.0.1:1234
    python ping_model.py --base-url http://127.0.0.1:8080 --model qwen3-vl-8b
"""

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = Path(__file__).resolve().parent


def get(url, api_key=None, timeout=15):
    """带认证地 GET。之前这里没发 Authorization，导致必然 401。"""
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def pick_vl(ids):
    """从模型列表里挑一个能看图的。纯文本模型会返回 400。"""
    def score(name):
        n = name.lower()
        s = 0
        if "vl" in n:
            s += 2
        if "vision" in n or "omni" in n:
            s += 2
        if any(k in n for k in ("text", "code", "coder", "math", "rerank", "embed", "tts", "asr")):
            s -= 5
        return s

    ranked = sorted(ids, key=score, reverse=True)
    return ranked[0] if ranked else ""


def mask(key: str) -> str:
    """只显示前后几位，避免把密钥打印到屏幕/日志里。"""
    if not key:
        return "(空)"
    if len(key) <= 10:
        return key[:2] + "***"
    return f"{key[:6]}...{key[-4:]} (共 {len(key)} 字符)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:1234")
    ap.add_argument("--model", default="")
    ap.add_argument("--image", default=str(HERE / "shot_1280.png"))
    ap.add_argument("--api-key", default="", help="不填则读环境变量 GUI_LAB_API_KEY")
    args = ap.parse_args()

    api_key = args.api_key or os.environ.get("GUI_LAB_API_KEY", "")
    if not api_key:
        try:
            from keyutil import get_key
            api_key = get_key()
        except Exception:
            pass

    base = args.base_url.rstrip("/")
    if not base.endswith("/v1"):
        base += "/v1"

    print(f"0) 密钥：{mask(api_key)}")
    if not api_key:
        print("   ⚠ 没有读到密钥。云服务必须要；本地服务可忽略。")

    print(f"1) 检查服务：{base}/models")
    try:
        models = get(f"{base}/models", api_key=api_key)
        ids = [m.get("id") for m in models.get("data", [])]
        print("   可用模型：", ids or "（空）")
        if not ids:
            print("   ⚠ 服务起来了但没加载模型")
            return 1
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "ignore")[:300]
        except Exception:
            pass
        print(f"   ✗ 服务拒绝了请求：HTTP {e.code} {e.reason}")
        if e.code in (401, 403):
            print("   → 这是**密钥问题**，不是网络问题（服务器已经回应了）。依次检查：")
            print("      $env:GUI_LAB_API_KEY.Substring(0,3)   # 云服务一般是 sk- 开头")
            print("      到控制台确认这个 key 还在、账号已实名、有额度")
            print("      → 最省事：回控制台重新复制一次 key（一般只显示一次）")
        elif e.code == 404:
            print("   → 地址或模型名不对。确认 base_url 是服务商给的那个。")
        elif e.code == 429:
            print("   → 触发限流，等几分钟再试。")
        if body:
            print(f"   → 服务器原话：{body}")
        return 1
    except urllib.error.URLError as e:
        print(f"   ✗ 连不上（根本没到服务器）：{e.reason}")
        print("   → 本地服务：LM Studio 里点 Start Server；llama.cpp 确认进程和端口")
        print("   → 云服务：检查网址拼写、是否需要代理")
        return 1

    model = args.model or pick_vl(ids)
    if not args.model:
        print(f"   （没指定 --model，自动挑了 {model}）")
    if args.model and args.model not in ids:
        print(f"   ⚠ 你指定的 {args.model} 不在列表里，可能名字对不上")

    img = Path(args.image)
    if not img.exists():
        print(f"   ✗ 找不到图片 {img}，先跑 make_test_image.ps1")
        return 1

    b64 = base64.b64encode(img.read_bytes()).decode()
    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": 64,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                {"type": "text", "text": "这张截图里，文字为「保存文档」的按钮中心点在哪？"
                                         "只输出 <point>x,y</point>，坐标基于 1280x720 图像。"},
            ],
        }],
    }
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
    )
    print(f"2) 发一次请求（模型 {model}，图 {img.name}）")
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            data = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "ignore")[:400]
        except Exception:
            pass
        print(f"   ✗ 请求失败：HTTP {e.code}")
        if e.code == 400:
            print("   → 400 常见原因：这个模型不支持图片输入（多半是纯文本模型）")
            print(f"     当前用的是 {model}，换一个名字里带 vl / vision 的：")
            print("     python ping_model.py --base-url <地址> --model qwen3-vl-plus")
        elif e.code == 404:
            print("   → 模型名不存在，用 /models 列表里的名字")
        if body:
            print(f"   → 服务器原话：{body}")
        return 1
    except Exception as e:
        print(f"   ✗ 请求失败：{e}")
        return 1
    dt = time.perf_counter() - t0

    msg = data["choices"][0]["message"]
    content = msg.get("content") or ""
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content)

    print(f"   耗时 {dt:.2f}s")
    print(f"   原始输出：{content!r}")
    print(f"   token：{data.get('usage')}")

    from probe import parse_point
    pt = parse_point(content)
    if pt is None:
        print("   ✗ 解析不出坐标 —— 看原始输出，多半是模型没按格式回，或这不是 VLM")
        return 1
    print(f"   ✓ 解析到坐标 {pt}（应先乘 1.5 再落到 1920x1080 屏幕上）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
