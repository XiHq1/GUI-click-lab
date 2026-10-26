#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""arms.py —— 三路对照实验（P0 直接 / P1 补观测 / P2 追加推理）

同一个目标、同一张截图，分别用三种方式问模型，比较命中率与代价。
这是"推理价值校准"的最小实验单元。

用法（真模型）：
    python arms.py --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 --model qwen3-vl-plus

用法（本地自测，不联网）：
    python arms.py --mock
"""

from __future__ import annotations

import argparse
import base64
import csv
import io
import json
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

# 本地 vendor 目录（Pillow 放在这里就不用 pip install）
_VENDOR = HERE / "vendor"
if _VENDOR.is_dir():
    sys.path.insert(0, str(_VENDOR))

PROMPT_DIRECT = """You are a GUI agent. The screenshot is {w}x{h} pixels.
Find the control labeled "{label}" and give the pixel coordinate of its center.
Reply with only: <point>x,y</point>, where x is in [0,{w1}], y in [0,{h1}]. No explanation."""

PROMPT_ZOOM = """This is a zoomed-in crop of a GUI, {w}x{h} pixels.
Find the control labeled "{label}" and give the pixel coordinate of its center IN THIS CROP.
Reply with only: <point>x,y</point>, where x is in [0,{w1}], y is in [0,{h1}]. No explanation."""

PROMPT_REASON = """You are a GUI agent. The screenshot is {w}x{h} pixels.
Find the control labeled "{label}".
First think briefly: where is it, what is around it, what could be confused with it.
Then answer on a new line with only: <point>x,y</point>"""

PATTERNS = [
    r"<point>\s*(-?\d+(?:\.\d+)?)\s*[,，]\s*(-?\d+(?:\.\d+)?)\s*</point>",
    r"\(\s*(-?\d+(?:\.\d+)?)\s*[,，]\s*(-?\d+(?:\.\d+)?)\s*\)",
    r"(-?\d+(?:\.\d+)?)\s*[,，]\s*(-?\d+(?:\.\d+)?)",
]


def parse_point(text):
    if not text:
        return None
    clean = re.sub(r"<think(?:ing)?>.*?</think(?:ing)?>", " ", text, flags=re.S | re.I)
    for pat in PATTERNS:
        found = re.findall(pat, clean)
        if found:
            x, y = found[-1]
            return float(x), float(y)
    return None


def b64png(img):
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


class VLM:
    def __init__(self, base, model, key, max_tokens=64, timeout=300, canvas=1024):
        self.base = base.rstrip("/")
        if not self.base.endswith("/v1"):
            self.base += "/v1"
        self.model, self.key = model, key
        self.max_tokens, self.timeout = max_tokens, timeout
        self.canvas = canvas
        self.name = model

    def ask(self, img, prompt, **kwargs):
        # origin/size 只有 mock 需要；真模型直接看整张图（或整张裁剪图）
        b64 = b64png(img)
        payload = {
            "model": self.model, "temperature": 0, "max_tokens": self.max_tokens,
            "messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                {"type": "text", "text": prompt}]}],
        }
        req = urllib.request.Request(
            f"{self.base}/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.key}"},
        )
        t0 = time.perf_counter()
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            data = json.loads(r.read().decode())
        dt = time.perf_counter() - t0
        content = data["choices"][0]["message"].get("content") or ""
        if isinstance(content, list):
            content = "".join(p.get("text", "") for p in content)
        return content, dt, (data.get("usage") or {})


class MockVLM:
    """完美模型：知道每个目标在哪，用来验证坐标换算是否正确。"""

    def __init__(self, boxes, canvas=1024, noise=0.0):
        self.boxes = boxes          # label -> (x,y,w,h) 在原始图片空间
        self.canvas = canvas
        self.noise = noise
        self.name = "mock"

    def ask(self, img, prompt, origin=(0, 0), size=None):
        label = re.search(r'labeled "([^"]+)"', prompt).group(1)
        x, y, w, h = self.boxes[label]
        cx, cy = x + w / 2 - origin[0], y + h / 2 - origin[1]
        cx += random.gauss(0, self.noise)
        cy += random.gauss(0, self.noise)
        iw, ih = size or img.size
        px = cx * self.canvas / iw
        py = cy * self.canvas / ih
        time.sleep(0.01)
        return f"<point>{px:.0f},{py:.0f}</point>", 0.01, {"prompt_tokens": 0, "completion_tokens": 0}


def inside(pt, box):
    x, y = pt
    return (box[0] <= x <= box[0] + box[2]) and (box[1] <= y <= box[1] + box[3])


def dist_to_center(pt, box):
    return ((pt[0] - box[0] - box[2] / 2) ** 2 + (pt[1] - box[1] - box[3] / 2) ** 2) ** 0.5


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", default=str(HERE / "tiny" / "labels.json"))
    ap.add_argument("--base-url", default="http://127.0.0.1:1234")
    ap.add_argument("--model", default="qwen3-vl-plus")
    ap.add_argument("--api-key", default="")
    ap.add_argument("--canvas", type=int, default=1024, help="模型坐标画布边长（需先标定）")
    ap.add_argument("--crop", type=int, default=320, help="P1 裁剪窗口边长（图片像素）")
    ap.add_argument("--crop-zoom", type=float, default=2.0, help="裁剪后放大倍数")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--mock-noise", type=float, default=0.0)
    ap.add_argument("--mock-noise-p0", type=float, default=None)
    ap.add_argument("--out", default=str(HERE / "results"))
    args = ap.parse_args()

    try:
        from PIL import Image
    except ImportError:
        print("需要 Pillow：pip install pillow")
        return 1

    meta = json.loads(Path(args.labels).read_text(encoding="utf-8"))
    img_path = HERE / meta["image_1280"]
    base_img = Image.open(img_path).convert("RGB")
    IW, IH = base_img.size
    sw, sh = meta["screen"]

    targets = [e for e in meta["elements"] if e["clickable"]]
    if args.limit:
        targets = targets[:args.limit]

    boxes = {e["label"]: (e["x1"], e["y1"], e["w1"], e["h1"]) for e in targets}

    if args.mock:
        agent = MockVLM(boxes, canvas=args.canvas, noise=args.mock_noise)
        agent_p0 = MockVLM(boxes, canvas=args.canvas,
                           noise=args.mock_noise_p0 if args.mock_noise_p0 is not None else args.mock_noise)
    else:
        key = args.api_key or os.environ.get("GUI_LAB_API_KEY", "none")
        agent = VLM(args.base_url, args.model, key, canvas=args.canvas)
        agent_p0 = agent

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-arms"
    out = Path(args.out) / run_id
    out.mkdir(parents=True, exist_ok=True)

    rows = []
    print(f"目标 {len(targets)} 个 | 画布 {args.canvas} | 图片 {IW}x{IH} | 裁剪 {args.crop}px×{args.crop_zoom}")
    jl = open(out / "results.jsonl", "w", encoding="utf-8")

    for i, el in enumerate(targets, 1):
        label = el["label"]
        box = boxes[label]
        rec = {"label": label, "id": el["id"]}

        # ---------- P0 直接 ----------
        p0_prompt = PROMPT_DIRECT.format(w=IW, h=IH, w1=IW - 1, h1=IH - 1, label=label)
        raw0, dt0, use0 = agent_p0.ask(base_img, p0_prompt, origin=(0, 0), size=(IW, IH))
        pt0 = parse_point(raw0)
        img0 = None if pt0 is None else (pt0[0] * IW / args.canvas, pt0[1] * IH / args.canvas)
        rec.update({
            "p0_raw": raw0.replace("\n", " "), "p0_img": img0,
            "p0_hit": bool(img0 and inside(img0, box)),
            "p0_dist": None if not img0 else round(dist_to_center(img0, box), 1),
            "p0_lat": round(dt0, 2), "p0_tokens": use0.get("completion_tokens"),
        })

        # ---------- P1 补观测：围绕 P0 预测点裁剪放大 ----------
        cx = img0[0] if img0 else IW / 2
        cy = img0[1] if img0 else IH / 2
        half = args.crop / 2
        left = max(0, min(IW - args.crop, cx - half))
        top = max(0, min(IH - args.crop, cy - half))
        right, bottom = left + args.crop, top + args.crop
        crop = base_img.crop((left, top, right, bottom))
        cw = int(args.crop * args.crop_zoom)
        crop = crop.resize((cw, cw), Image.LANCZOS)
        p1_prompt = PROMPT_ZOOM.format(w=cw, h=cw, w1=cw - 1, h1=cw - 1, label=label)
        raw1, dt1, use1 = agent.ask(crop, p1_prompt, origin=(left, top), size=(cw, cw))
        pt1 = parse_point(raw1)
        img1 = None if pt1 is None else (left + pt1[0] * cw / args.canvas, top + pt1[1] * cw / args.canvas)
        rec.update({
            "p1_raw": raw1.replace("\n", " "), "p1_img": img1, "p1_crop": [left, top, right, bottom],
            "p1_hit": bool(img1 and inside(img1, box)),
            "p1_dist": None if not img1 else round(dist_to_center(img1, box), 1),
            "p1_lat": round(dt1, 2),
            "p1_contains_target": inside(((box[0] + box[2] / 2), (box[1] + box[3] / 2)),
                                         (left, top, args.crop, args.crop)),
        })

        # ---------- P2 追加推理：同一张图，先分析再回答 ----------
        p2_prompt = PROMPT_REASON.format(w=IW, h=IH, w1=IW - 1, h1=IH - 1, label=label)
        raw2, dt2, use2 = agent.ask(base_img, p2_prompt, origin=(0, 0), size=(IW, IH))
        pt2 = parse_point(raw2)
        img2 = None if pt2 is None else (pt2[0] * IW / args.canvas, pt2[1] * IH / args.canvas)
        rec.update({
            "p2_raw": raw2.replace("\n", " ")[:200], "p2_img": img2,
            "p2_hit": bool(img2 and inside(img2, box)),
            "p2_dist": None if not img2 else round(dist_to_center(img2, box), 1),
            "p2_lat": round(dt2, 2),
        })

        rows.append(rec)
        jl.write(json.dumps(rec, ensure_ascii=False) + "\n")
        jl.flush()          # 边跑边落盘：中途出错也不丢已跑的结果
        mark = "".join("✓" if rec[f"p{k}_hit"] else "✗" for k in (0, 1, 2))
        print(f"[{i:2d}] {label:<8s} P0P1P2={mark}  "
              f"误差 {rec['p0_dist']}/{rec['p1_dist']}/{rec['p2_dist']}")

    # ---------- 汇总 ----------
    jl.close()
    n = len(rows)
    hits = {k: sum(r[f"p{k}_hit"] for r in rows) for k in (0, 1, 2)}
    rescued = [r for r in rows if not r["p0_hit"] and r["p1_hit"]]
    lost = [r for r in rows if r["p0_hit"] and not r["p1_hit"]]
    rescued2 = [r for r in rows if not r["p0_hit"] and r["p2_hit"]]
    lost2 = [r for r in rows if r["p0_hit"] and not r["p2_hit"]]
    fail_p0 = [r for r in rows if not r["p0_hit"]]
    crop_missed = [r for r in fail_p0 if not r.get("p1_contains_target")]

    with open(out / "results.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    summary = {
        "n": n,
        "hit": {k: hits[k] for k in hits},
        "rate": {k: hits[k] / n for k in hits},
        "delta_p1": (hits[1] - hits[0]) / n,
        "delta_p2": (hits[2] - hits[0]) / n,
        "rescued_by_p1": len(rescued),
        "lost_by_p1": len(lost),
        "rescued_by_p2": len(rescued2),
        "lost_by_p2": len(lost2),
        "p0_failures": len(fail_p0),
        "crop_missed_target": len(crop_missed),
        "lat_median": round(statistics.median([r["p0_lat"] for r in rows]), 2),
        "lat_p95_p1": round(sorted(r["p1_lat"] for r in rows)[int(0.95 * (n - 1))], 2),
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# 三路对照结果 · {run_id}", "",
        f"- 模型：`{agent.name}`｜画布：{args.canvas}｜目标：{n}",
        f"- 测试集：`{meta['image_1280']}`｜裁剪窗口：{args.crop}px ×{args.crop_zoom}", "",
        "## 主表", "",
        "| 路径 | 命中 | 命中率 | 相对 P0 |", "|---|---|---|---|",
        f"| P0 直接执行 | {hits[0]}/{n} | {hits[0]/n:.1%} | — |",
        f"| P1 补观测（裁剪放大） | {hits[1]}/{n} | {hits[1]/n:.1%} | {summary['delta_p1']:+.1%} |",
        f"| P2 追加推理 | {hits[2]}/{n} | {hits[2]/n:.1%} | {summary['delta_p2']:+.1%} |", "",
        "## 干预的细账", "",
        "| 指标 | P1 | P2 |", "|---|---|---|",
        f"| 救回（P0错→现在对） | {len(rescued)} | {len(rescued2)} |",
        f"| 弄坏（P0对→现在错） | {len(lost)} | {len(lost2)} |",
        f"| P0 失败总数 | {len(fail_p0)} | {len(fail_p0)} |", "",
        f"- **P1 的裁剪窗口没框住目标的有 {len(crop_missed)} 个**"
        "（P0 偏太远时，补观测也救不回来——这正是需要预测收益的原因）", "",
        "## 逐样本", "",
        "| 目标 | P0 | P1 | P2 | 误差 P0/P1/P2 |", "|---|---|---|---|---|",
    ]
    for r in rows:
        m = lambda k: "✓" if r[f"p{k}_hit"] else "✗"  # noqa: E731
        lines.append(f"| {r['label']} | {m(0)} | {m(1)} | {m(2)} | "
                     f"{r['p0_dist']}/{r['p1_dist']}/{r['p2_dist']} |")
    lines += ["", "## 一句话结论", ""]
    lines.append(
        f"在 {n} 个目标上，直接执行命中 {hits[0]/n:.1%}；"
        f"补观测{'提升' if summary['delta_p1'] >= 0 else '下降'} {abs(summary['delta_p1']):.1%}"
        f"（救回 {len(rescued)}、弄坏 {len(lost)}），"
        f"追加推理{'提升' if summary['delta_p2'] >= 0 else '下降'} {abs(summary['delta_p2']):.1%}"
        f"（救回 {len(rescued2)}、弄坏 {len(lost2)}）。"
    )
    (out / "report.md").write_text("\n".join(lines), encoding="utf-8")

    print("\n" + "-" * 60)
    print(f"P0 {hits[0]/n:.1%}  P1 {hits[1]/n:.1%}  P2 {hits[2]/n:.1%}")
    print(f"P1 救回 {len(rescued)} / 弄坏 {len(lost)}；裁剪没框住目标 {len(crop_missed)} 个")
    print(f"结果：{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
