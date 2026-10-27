#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_all.py —— 一条命令跑完预研：基线 + 三路对照 + 汇编报告。

用法（真模型）：
    python run_all.py --base-url https://dashscope.aliyuncs.com/compatible-mode/v1 --model qwen3-vl-plus

用法（自测，不联网）：
    python run_all.py --mock
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent   # src/
ROOT = HERE.parent                       # 仓库根目录


def run(cmd):
    print("\n$ " + " ".join(str(c) for c in cmd))
    r = subprocess.run(cmd, cwd=HERE)
    if r.returncode != 0:
        print(f"命令失败（{r.returncode}），后续步骤跳过")
        return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", default=str(ROOT / "assets" / "tiny" / "labels.json"))
    ap.add_argument("--base-url", default="http://127.0.0.1:1234")
    ap.add_argument("--model", default="qwen3-vl-plus")
    ap.add_argument("--canvas", type=int, default=1024)
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    py = sys.executable
    common = ["--labels", args.labels]
    if args.limit:
        common += ["--limit", str(args.limit)]

    if args.mock:
        base_cmd = [py, "probe.py", "--mock", "--out", str(ROOT / "results" / "baseline")] + common
        arms_cmd = [py, "arms.py", "--mock", "--out", str(ROOT / "results" / "arms")] + common
    else:
        api = ["--base-url", args.base_url, "--model", args.model]
        base_cmd = ([py, "probe.py", "--out", str(ROOT / "results" / "baseline")]
                    + common + api + ["--coord-space", f"{args.canvas}x{args.canvas}"])
        arms_cmd = ([py, "arms.py", "--out", str(ROOT / "results" / "arms")]
                    + common + api + ["--canvas", str(args.canvas)])

    if not run(base_cmd):
        return 1
    if not run(arms_cmd):
        return 1

    tag = "（干跑，不可用于结论）" if args.mock else ""
    out_md = ROOT / "docs" / "预研报告.md"
    run([py, "compile_report.py", "--baseline-root", str(ROOT / "results" / "baseline"),
         "--arms-root", str(ROOT / "results" / "arms"), "--out", str(out_md), "--tag", tag])
    print(f"\n报告：{out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
