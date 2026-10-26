#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把基线与三路对照汇编成一份可读的报告。"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import Counter
from datetime import datetime
from pathlib import Path


def latest(root: Path) -> Path:
    dirs = [d for d in root.iterdir() if d.is_dir()] if root.is_dir() else []
    if not dirs:
        raise SystemExit(f"找不到结果目录：{root}")
    return max(dirs, key=lambda d: d.stat().st_mtime)


def read_csv(p: Path):
    with open(p, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def pct(x):
    return f"{x:.1%}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline-root", required=True)
    ap.add_argument("--arms-root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--tag", default="")
    args = ap.parse_args()

    bdir = latest(Path(args.baseline_root))
    adir = latest(Path(args.arms_root))
    base = read_csv(bdir / "results.csv")
    arms = read_csv(adir / "results.csv")
    meta = json.loads((adir / "summary.json").read_text(encoding="utf-8"))

    n_b = len(base)
    hit_b = sum(1 for r in base if r["hit"] == "True")
    dists = [float(r["dist"]) for r in base if r["dist"]]
    lats = [float(r["latency"]) for r in base if r["latency"]]
    tk = [int(r["completion_tokens"]) for r in base if r.get("completion_tokens")]

    # 按目标类型分组（id 前缀：g=普通, s=相似, t=极小）
    def cat(i):
        return {"g": "普通按钮", "s": "相似文案", "t": "极小字号"}.get(i.split("-")[0], "其它")

    by_cat = {}
    for r in base:
        c = cat(r["id"])
        by_cat.setdefault(c, []).append(r)

    n = meta["n"]
    h = meta["hit"]

    L = []
    L.append(f"# GUI 定位预研报告{args.tag}\n")
    L.append(f"- 生成时间：{datetime.now().isoformat(timespec='seconds')}")
    L.append(f"- 测试集：`tiny/`（29 个目标，9px 字号、低对比、部分遮挡、含相似文案）")
    L.append(f"- 基线运行：`{bdir.name}`｜三路运行：`{adir.name}`")
    L.append(f"- 模型画布：{meta.get('n')} 个目标 / 坐标空间 1024×1024")
    L.append("")

    L.append("## 一、基线：模型直接定位（P0）\n")
    L.append("| 指标 | 数值 |")
    L.append("|---|---|")
    L.append(f"| 命中率 | **{pct(hit_b / n_b)}**（{hit_b}/{n_b}） |")
    L.append(f"| 平均像素误差 | {statistics.mean(dists):.0f} px |")
    L.append(f"| 误差中位数 | {statistics.median(dists):.0f} px |")
    L.append(f"| 单步延迟 P50 / P95 | {sorted(lats)[len(lats)//2]:.2f}s / "
             f"{sorted(lats)[int(0.95*(len(lats)-1))]:.2f}s |")
    if tk:
        L.append(f"| 输出 token 中位数 | {statistics.median(tk):.0f} |")
    L.append("")

    L.append("### 按目标类型拆分\n")
    L.append("| 类型 | 任务数 | 命中率 | 说明 |")
    L.append("|---|---|---|---|")
    note = {"普通按钮": "12px 字号", "相似文案": "提交/提交并关闭/提交并新建",
            "极小字号": "9px，肉眼也吃力"}
    for c, rs in sorted(by_cat.items()):
        hh = sum(1 for r in rs if r["hit"] == "True")
        L.append(f"| {c} | {len(rs)} | {pct(hh/len(rs))} | {note.get(c,'')} |")
    L.append("")

    L.append("## 二、三路对照\n")
    L.append("| 路径 | 命中 | 命中率 | 相对直接执行 |")
    L.append("|---|---|---|---|")
    L.append(f"| P0 直接执行 | {h['0']}/{n} | {pct(h['0']/n)} | — |")
    L.append(f"| P1 补观测（裁剪放大） | {h['1']}/{n} | {pct(h['1']/n)} | {meta['delta_p1']:+.1%} |")
    L.append(f"| P2 追加推理 | {h['2']}/{n} | {pct(h['2']/n)} | {meta['delta_p2']:+.1%} |")
    L.append("")

    L.append("### 干预的收益与代价\n")
    L.append("| 指标 | P1 | P2 |")
    L.append("|---|---|---|")
    L.append(f"| 救回（P0 错 → 现在对） | {meta['rescued_by_p1']} | {meta['rescued_by_p2']} |")
    L.append(f"| 弄坏（P0 对 → 现在错） | {meta['lost_by_p1']} | {meta['lost_by_p2']} |")
    L.append(f"| P0 失败样本总数 | {meta['p0_failures']} | {meta['p0_failures']} |")
    L.append(f"| 裁剪窗口没框住目标 | {meta['crop_missed_target']} | — |")
    L.append("")
    L.append("> “裁剪没框住目标”是关键数字：P0 偏得太远时，围绕它的裁剪窗口里根本没有目标，"
             "补观测再多次也救不回来。这正是**需要预先判断收益**的理由。")
    L.append("")

    L.append("## 三、逐样本\n")
    L.append("| 目标 | P0 | P1 | P2 | 误差 P0/P1/P2 |")
    L.append("|---|---|---|---|---|")
    for r in arms:
        m = lambda k: "✓" if r[f"p{k}_hit"] == "True" else "✗"  # noqa: E731
        L.append(f"| {r['label']} | {m(0)} | {m(1)} | {m(2)} | "
                 f"{r['p0_dist']}/{r['p1_dist']}/{r['p2_dist']} |")
    L.append("")

    L.append("## 四、结论\n")
    L.append(
        f"在 29 个目标的困难测试集上，直接执行命中 {pct(hit_b/n_b)}；"
        f"补观测相对提升 {meta['delta_p1']:+.1%}（救回 {meta['rescued_by_p1']}、"
        f"弄坏 {meta['lost_by_p1']}），追加推理提升 {meta['delta_p2']:+.1%}"
        f"（救回 {meta['rescued_by_p2']}、弄坏 {meta['lost_by_p2']}）。"
        f"有 {meta['crop_missed_target']} 个失败样本的裁剪窗口不含目标，说明补观测的收益"
        f"依赖“P0 的偏差是否在窗口内”——这为“预测干预收益”提供了直接动机。"
    )
    L.append("")

    L.append("## 五、局限\n")
    L.append("1. 合成页面，不等于真实软件界面；29 个目标只能估计量级，不能做显著性检验。")
    L.append("2. 只有单次重复，模型输出有随机性（temperature=0 也不完全确定）。")
    L.append("3. P1 的裁剪策略很朴素（固定 320px 窗口），换策略结果会变。")
    L.append("4. 画布 1024×1024 是这个 API 的实现细节，换部署需重新标定。")
    L.append("5. 没有任何执行环节——“指得准”不等于“点得对”。")

    Path(args.out).write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L[:20]))
    print(f"\n已写入 {args.out}")


if __name__ == "__main__":
    raise SystemExit(main())
