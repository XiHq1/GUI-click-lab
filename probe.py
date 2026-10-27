#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
probe.py —— 最小 GUI 定位实验（不插虚拟机、不装任何第三方包）

它做的事只有一件：
    给模型一张截图 + 一个目标名称，让模型说出目标中心点的坐标，
    然后拿标准答案（labels.json）比对，算命中率 / 像素误差 / 延迟。

两种模式：
    python probe.py --mock          # 假模型（完美定位 + 噪声），用来验证链路
    python probe.py --base-url http://127.0.0.1:1234 --model qwen3-vl-8b   # 真模型

产出（results/时间戳/）：
    results.csv     每条样本一行
    summary.json    总体指标
    report.html     可视化报告（红点=模型预测，蓝框=标准答案）
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import math
import os
import random
import re
import statistics
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = Path(__file__).resolve().parent

PROMPT = """你是 GUI 定位模型。截图尺寸是 {w}x{h} 像素。
请在界面中找到文字为「{label}」的控件，给出该控件中心点的像素坐标。
只输出一行，严格使用这个格式：<point>x,y</point>
其中 x 在 0 到 {w1} 之间，y 在 0 到 {h1} 之间，都是整数。不要输出任何解释。"""


# ----------------------------------------------------------------- 解析
# 模型可能输出多段文字：思考过程 + 最终答案。
# 规则：先剥掉  thinking...<｜end▁of▁thinking｜> 块，再取"最后一次"匹配（答案总在后面）。
PATTERNS = [
    r"<point>\s*(-?\d+(?:\.\d+)?)\s*[,，]\s*(-?\d+(?:\.\d+)?)\s*</point>",
    r"\(\s*(-?\d+(?:\.\d+)?)\s*[,，]\s*(-?\d+(?:\.\d+)?)\s*\)",
    r'"?(?:point|x|y)"?\s*[:=]\s*\[?\s*(-?\d+(?:\.\d+)?)\s*[,，]\s*(-?\d+(?:\.\d+)?)',
    r"(-?\d+(?:\.\d+)?)\s*[,，]\s*(-?\d+(?:\.\d+)?)",
]


def parse_point(text: str):
    """从模型输出里抠出 (x, y)。兼容 Thinking 模型的多段输出。"""
    if not text:
        return None
    # 1) 去掉思维链块（Qwen 用  thinking，其它用 <thinking>）
    clean = re.sub(r"<think(?:ing)?>.*?</think(?:ing)?>", " ", text, flags=re.S | re.I)
    # 2) 每种格式取最后一次匹配
    for pat in PATTERNS:
        found = re.findall(pat, clean)
        if found:
            x, y = found[-1]
            return float(x), float(y)
    return None


def to_screen(px: float, py: float, coord_mode: str, mw: int, mh: int, sw: int, sh: int):
    """把模型输出的坐标换算成真实屏幕坐标。"""
    if coord_mode == "norm1000":          # 模型输出 0-1000 的归一化坐标
        return px / 1000.0 * sw, py / 1000.0 * sh
    # 默认 abs：模型输出的是"我喂给它的那张图"的像素坐标
    return px * sw / mw, py * sh / mh


# ----------------------------------------------------------------- 打分
def score_point(sx: float, sy: float, el: dict):
    """返回 (是否命中 bbox, 到 bbox 中心的像素距离)。"""
    cx = el["x"] + el["w"] / 2
    cy = el["y"] + el["h"] / 2
    dist = math.hypot(sx - cx, sy - cy)
    inside = (el["x"] <= sx <= el["x"] + el["w"]) and (el["y"] <= sy <= el["y"] + el["h"])
    return inside, dist


# ----------------------------------------------------------------- 模型
#
# 重要约定：predict() 只能收到「图片 + 目标名称」。
# 标准答案（坐标）绝不作为参数传入 —— 想偷看也没有途径。
# 假模型需要的答案在构造时就注入到自己内部，出了这个类就用不到。
#
class MockModel:
    """假模型：知道正确答案，加一点高斯噪声。用来验证整条链路是通的。"""

    name = "mock"

    def __init__(self, truth: dict, noise: float = 6.0, coord_mode: str = "abs"):
        self.truth = truth          # label -> element（只在这里存着）
        self.noise = noise
        self.coord_mode = coord_mode

    def predict(self, image_path: Path, label: str, mw: int, mh: int):
        el = self.truth[label]
        sw, sh = 1920, 1080
        cx = el["x"] + el["w"] / 2 + random.gauss(0, self.noise)
        cy = el["y"] + el["h"] / 2 + random.gauss(0, self.noise)
        if self.coord_mode == "norm1000":
            px, py = cx / sw * 1000, cy / sh * 1000
        else:
            px, py = cx * mw / sw, cy * mh / sh
        text = f"<point>{px:.0f},{py:.0f}</point>"
        time.sleep(0.05)
        return text, 0.05


class VLM:
    """OpenAI 兼容接口（LM Studio / llama.cpp / vLLM 都行）。"""

    def __init__(self, base_url: str, model: str, api_key: str = "none",
                 timeout: int = 300, max_tokens: int = 64):
        self.base_url = base_url.rstrip("/")
        if not self.base_url.endswith("/v1"):
            self.base_url += "/v1"
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.max_tokens = max_tokens

    def predict(self, image_path: Path, label: str, mw: int, mh: int):
        b64 = base64.b64encode(image_path.read_bytes()).decode()
        prompt = PROMPT.format(w=mw, h=mh, w1=mw - 1, h1=mh - 1, label=label)
        payload = {
            "model": self.model,
            "temperature": 0,
            "max_tokens": self.max_tokens,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                    {"type": "text", "text": prompt},
                ],
            }],
        }
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
        )
        t0 = time.perf_counter()
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            data = json.loads(r.read().decode())
        dt = time.perf_counter() - t0
        self.last_usage = data.get("usage") or {}   # token 数，成本项 c_k 要用
        return data["choices"][0]["message"]["content"], dt


# ----------------------------------------------------------------- 报告
def write_report(out_dir: Path, rows: list, meta: dict, mw: int, mh: int):
    parts = []
    for r in rows:
        color = "#1aa260" if r["hit"] else "#e5484d"
        box = (
            f'<div class="box" style="left:{r["bx1"]}px;top:{r["by1"]}px;'
            f'width:{r["bw1"]}px;height:{r["bh1"]}px"></div>'
        )
        dot = (
            f'<div class="dot" style="left:{r["px_m"]}px;top:{r["py_m"]}px;'
            f'background:{color}"></div>'
        )
        parts.append(box + dot)
    overlay = "\n".join(parts)

    table = "\n".join(
        f"<tr class='{'ok' if r['hit'] else 'bad'}'>"
        f"<td>{r['idx']}</td><td>{r['label']}</td><td>{r['raw'][:60]}</td>"
        f"<td>({r['px']:.0f}, {r['py']:.0f})</td>"
        f"<td>({r['sx']:.0f}, {r['sy']:.0f})</td>"
        f"<td>{r['dist']:.0f}</td><td>{'✓' if r['hit'] else '✗'}</td>"
        f"<td>{r['latency']:.2f}s</td></tr>"
        for r in rows
    )

    html = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>GUI 定位实验结果</title>
<style>
 body{{font-family:"Microsoft YaHei",system-ui,sans-serif;background:#f6f8fc;margin:0;padding:28px;color:#1e2430}}
 h1{{font-size:22px;margin:0 0 6px}} .meta{{color:#6b7488;font-size:14px;margin-bottom:20px}}
 .wrap{{position:relative;width:{mw}px;border:1px solid #d7deea;border-radius:10px;overflow:hidden;background:#fff}}
 .wrap img{{display:block;width:{mw}px}}
 .box{{position:absolute;border:1px solid rgba(59,108,246,.55);border-radius:4px}}
 .dot{{position:absolute;width:10px;height:10px;border-radius:50%;margin:-5px 0 0 -5px;
       box-shadow:0 0 0 2px #fff, 0 0 6px rgba(0,0,0,.35)}}
 table{{border-collapse:collapse;margin-top:22px;font-size:13px;background:#fff}}
 th,td{{border:1px solid #e3e8f0;padding:6px 10px;text-align:left}}
 th{{background:#eef2f9}} tr.ok td:nth-child(7){{color:#1aa260;font-weight:700}}
 tr.bad td:nth-child(7){{color:#e5484d;font-weight:700}}
 .sum{{margin-top:16px;font-size:15px}}
</style></head><body>
<h1>GUI 定位实验结果</h1>
<div class="meta">模型：{meta['model']}｜图像：{mw}×{mh}｜样本：{len(rows)}｜生成时间：{meta['time']}</div>
<div class="wrap"><img src="{meta['image']}">{overlay}</div>
<div class="sum">命中率 <b>{meta['hit_rate']:.1%}</b>　平均像素误差 <b>{meta['mean_dist']:.0f}px</b>　
延迟 P50 <b>{meta['p50']:.2f}s</b> / P95 <b>{meta['p95']:.2f}s</b></div>
<table><tr><th>#</th><th>目标</th><th>模型原始输出</th><th>模型坐标</th><th>换算后</th><th>误差(px)</th><th>命中</th><th>延迟</th></tr>
{table}</table>
</body></html>"""
    (out_dir / "report.html").write_text(html, encoding="utf-8")


# ----------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser(description="最小 GUI 定位实验")
    ap.add_argument("--labels", default=str(HERE / "labels.json"))
    ap.add_argument("--mock", action="store_true", help="用假模型验证链路")
    ap.add_argument("--noise", type=float, default=6.0, help="假模型的噪声（像素）")
    ap.add_argument("--base-url", default="http://127.0.0.1:1234", help="LM Studio 默认 1234，llama.cpp 常用 8080")
    ap.add_argument("--model", default="qwen3-vl-8b")
    ap.add_argument("--api-key", default="", help="不填则读环境变量 GUI_LAB_API_KEY")
    ap.add_argument("--coord-mode", choices=["abs", "norm1000"], default="abs",
                    help="abs=模型输出的是图片像素坐标；norm1000=归一化到 0-1000")
    ap.add_argument("--coord-space", default="",
                    help="模型坐标所在的画布尺寸，如 1024x1024；默认等于图片尺寸。"
                         "云 API 常把图缩到方形画布，这时必须显式指定")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 个目标（0=全部）")
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--include-disabled", action="store_true", help="把不可点击的干扰项也当目标")
    ap.add_argument("--seed", type=int, default=0, help="随机种子（假模型的噪声可复现）")
    ap.add_argument("--show-prompt", action="store_true", help="打印发给模型的完整提示词（确认没泄题）")
    ap.add_argument("--max-tokens", type=int, default=64,
                    help="单次输出上限；Thinking 模型要调到 2048 以上，否则思考被截断")
    ap.add_argument("--out", default=str(HERE / "results"))
    args = ap.parse_args()

    if args.seed:
        random.seed(args.seed)

    labels = json.loads(Path(args.labels).read_text(encoding="utf-8"))
    img_path = HERE / labels["image_1280"]
    mw, mh = labels["model_input"]
    sw, sh = labels["screen"]

    # 模型坐标所在的画布：默认和图片一样；云 API 常见 1024x1024
    if args.coord_space:
        cw, ch = (int(v) for v in args.coord_space.lower().replace("*", "x").split("x"))
    else:
        cw, ch = mw, mh
    if (cw, ch) != (mw, mh):
        print(f"坐标画布：{cw}x{ch}（图片 {mw}x{mh}，将按比例换算）")

    targets = [e for e in labels["elements"] if e["clickable"] or args.include_disabled]
    targets = targets[args.offset:]
    if args.limit:
        targets = targets[:args.limit]
    if not targets:
        print("没有可跑的目标")
        return 1

    if args.mock:
        # 答案只在假模型内部使用；真模型那条路拿不到任何坐标
        truth = {e["label"]: e for e in labels["elements"]}
        model = MockModel(truth, args.noise, args.coord_mode)
    else:
        key = args.api_key or os.environ.get("GUI_LAB_API_KEY", "none")
        if not key or key == "none":
            try:
                from keyutil import get_key
                key = get_key() or "none"
            except Exception:
                pass
        model = VLM(args.base_url, args.model, key, max_tokens=args.max_tokens)

    if args.show_prompt:
        first = targets[0]["label"]
        print("=" * 78)
        print("下面是真正发给模型的全部文字（没有坐标）：")
        print(PROMPT.format(w=mw, h=mh, w1=mw - 1, h1=mh - 1, label=first))
        print("=" * 78)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = Path(args.out) / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"模型：{getattr(model, 'name', args.model)}｜目标：{len(targets)} 个｜图像：{mw}x{mh}")
    print("-" * 78)

    rows = []
    for i, el in enumerate(targets, 1):
        try:
            raw, dt = model.predict(img_path, el["label"], mw, mh)
        except Exception as e:
            print(f"[{i}] {el['label']} 调用失败：{e}")
            continue

        pt = parse_point(raw)
        if pt is None:
            print(f"[{i}] {el['label']} 解析失败，原始输出：{raw[:80]!r}")
            continue

        sx, sy = to_screen(pt[0], pt[1], args.coord_mode, cw, ch, sw, sh)
        hit, dist = score_point(sx, sy, el)

        # 模型坐标换算回"图片空间"，才能画在 1280 的图上
        if args.coord_mode == "norm1000":
            px_m, py_m = pt[0] / 1000 * mw, pt[1] / 1000 * mh
        else:
            px_m, py_m = pt[0] * mw / cw, pt[1] * mh / ch

        rows.append({
            "idx": i, "id": el["id"], "label": el["label"],
            "raw": raw.replace("\n", " "),
            # 模型原话里的坐标（可能是 1280 像素，也可能是 0-1000）
            "px": pt[0], "py": pt[1],
            # 换算到小图空间（只用来画报告）
            "px_m": px_m, "py_m": py_m,
            # 换算到大屏空间（和标准答案比较用）
            "sx": sx, "sy": sy,
            # 标准答案：小图版 与 大屏版，两套都留着，避免混淆
            "bx1": el["x1"], "by1": el["y1"], "bw1": el["w1"], "bh1": el["h1"],
            "bx": el["x"], "by": el["y"], "bw": el["w"], "bh": el["h"],
            # 成绩
            "dist": dist, "hit": hit, "latency": dt, "clickable": el["clickable"],
            # 成本：token 数（Thinking 模型这一列会明显变大，正是 c_k 的来源）
            "prompt_tokens": (getattr(model, "last_usage", None) or {}).get("prompt_tokens", ""),
            "completion_tokens": (getattr(model, "last_usage", None) or {}).get("completion_tokens", ""),
        })
        flag = "✓" if hit else "✗"
        print(f"[{i:2d}] {flag} {el['label']:<10s} 预测=({pt[0]:6.0f},{pt[1]:6.0f}) "
              f"误差={dist:6.1f}px  {dt:5.2f}s")

    if not rows:
        print("没有成功样本")
        return 1

    hits = [r["hit"] for r in rows]
    dists = [r["dist"] for r in rows]
    lats = sorted(r["latency"] for r in rows)

    def pct(v, q):
        return v[min(len(v) - 1, int(round(q * (len(v) - 1))))]

    meta = {
        "model": getattr(model, "name", args.model),
        "time": stamp,
        # 报告在 results/<时间戳>/ 下，图片在项目根目录，所以用相对路径
        "image": Path(os.path.relpath(img_path, out_dir)).as_posix(),
        "hit_rate": sum(hits) / len(hits),
        "mean_dist": statistics.mean(dists),
        "p50": pct(lats, 0.5),
        "p95": pct(lats, 0.95),
    }

    with open(out_dir / "results.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    (out_dir / "summary.json").write_text(
        json.dumps({"meta": meta, "by_section": _by_section(rows)}, ensure_ascii=False, indent=2),
        encoding="utf-8")

    write_report(out_dir, rows, meta, mw, mh)

    print("-" * 78)
    print(f"命中率 {meta['hit_rate']:.1%}｜平均误差 {meta['mean_dist']:.0f}px"
          f"｜延迟 P50 {meta['p50']:.2f}s / P95 {meta['p95']:.2f}s")
    print(f"结果目录：{out_dir}")
    print(f"打开报告：{(out_dir / 'report.html').as_uri()}")
    return 0


def _by_section(rows):
    """按元素类型分开统计，方便看出模型是"全都不会"还是"只在小按钮上翻车"。"""
    groups = {}
    for r in rows:
        key = r["id"].split("-")[0]
        groups.setdefault(key, []).append(r)
    return {
        k: {
            "n": len(v),
            "hit_rate": sum(x["hit"] for x in v) / len(v),
            "mean_dist": statistics.mean(x["dist"] for x in v),
        }
        for k, v in groups.items()
    }


if __name__ == "__main__":
    raise SystemExit(main())
