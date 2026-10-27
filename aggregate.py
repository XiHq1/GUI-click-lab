#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aggregate.py —— 把多次运行的 arms 结果汇总成「均值 ± 标准差」。

用法：
    python aggregate.py
    python aggregate.py --min-runs 3

只统计真实运行（排除 mock），并按样本数分组，避免把不同测试集混在一起。
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_runs(root: Path):
    """递归找出所有 *-arms 目录（兼容 results/<x>-arms 和 results/arms/<x>-arms 两种位置）。

    同时跳过 mock 干跑，避免把自测数据混进统计。
    """
    runs = []
    if not root.is_dir():
        return runs
    seen = set()
    for d in sorted(root.rglob("*-arms")):
        if not d.is_dir() or d in seen:
            continue
        seen.add(d)
        f = d / "summary.json"
        if not f.is_file():
            continue
        meta_f = d / "meta.json"
        if meta_f.is_file():
            try:
                if str(json.loads(meta_f.read_text(encoding="utf-8")).get("agent", "")).startswith("mock"):
                    continue
            except Exception:
                pass
        try:
            s = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        runs.append({"dir": d.name, **s})
    return runs


def stats(vals):
    if not vals:
        return None
    if len(vals) == 1:
        return f"{vals[0]:.1f}"
    return f"{statistics.mean(vals):.1f} ± {statistics.stdev(vals):.1f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(HERE / "results"),
                    help="扫描根目录，会递归找所有 *-arms 目录")
    ap.add_argument("--min-runs", type=int, default=1)
    ap.add_argument("--since", default="", help="只统计目录名不早于该前缀的运行，如 20261027")
    ap.add_argument("--out", default=str(HERE / "多次运行汇总.md"))
    args = ap.parse_args()

    runs = [r for r in load_runs(Path(args.root)) if r.get("n")]
    if args.since:
        runs = [r for r in runs if r["dir"] >= args.since]
    # 按样本数分组（同组=同一测试集）
    groups = {}
    for r in runs:
        groups.setdefault(r["n"], []).append(r)

    lines = ["# 多次运行汇总", ""]
    ok = False
    for n, rs in sorted(groups.items()):
        if len(rs) < args.min_runs:
            continue
        ok = True
        p0 = [r["rate"]["0"] * 100 for r in rs]
        p1 = [r["rate"]["1"] * 100 for r in rs]
        p2 = [r["rate"]["2"] * 100 for r in rs]
        lines += [
            f"## 测试集：{n} 个目标（{len(rs)} 次运行）", "",
            "| 路径 | 命中率（均值 ± 标准差） | 每次运行 |",
            "|---|---|---|",
            f"| P0 直接执行 | **{stats(p0)}%** | {', '.join(f'{v:.1f}' for v in p0)} |",
            f"| P1 补观测 | **{stats(p1)}%** | {', '.join(f'{v:.1f}' for v in p1)} |",
            f"| P2 追加推理 | **{stats(p2)}%** | {', '.join(f'{v:.1f}' for v in p2)} |",
            "",
        ]
        if len(rs) >= 2:
            lines += [
                f"- Δ(P1−P0)：**{statistics.mean([a-b for a, b in zip(p1, p0)]):+.1f}** 个百分点",
                f"- Δ(P2−P0)：**{statistics.mean([a-b for a, b in zip(p2, p0)]):+.1f}** 个百分点",
                "",
                "> 标准差反映的是**同一配置下的运行波动**。"
                "如果标准差接近甚至超过效应量，说明单次实验不足以支撑结论，必须重复。",
                "",
            ]
        lines += [
            "| 运行 | P0 | P1 | P2 | 救回 | 弄坏 | 裁剪没框住 |",
            "|---|---|---|---|---|---|---|",
        ]
        for r in rs:
            lines.append(
                f"| {r['dir']} | {r['rate']['0']:.1%} | {r['rate']['1']:.1%} | "
                f"{r['rate']['2']:.1%} | {r.get('rescued_by_p1')} | "
                f"{r.get('lost_by_p1')} | {r.get('crop_missed_target')} |")
        lines.append("")

    if not ok:
        lines.append(f"目前没有任何一组达到 {args.min_runs} 次运行。多跑几次 `python arms.py ...` 再来。")

    Path(args.out).write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    print(f"\n已写入 {args.out}")


if __name__ == "__main__":
    raise SystemExit(main())
