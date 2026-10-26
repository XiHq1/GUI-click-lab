#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
selftest.py —— 不联网、不开浏览器，只验证"逻辑"是否正确。

跑法：python selftest.py
全绿说明：解析、坐标换算、打分这三个最容易写错的地方是对的。
"""

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from probe import parse_point, to_screen, score_point, MockModel  # noqa: E402

FAIL = 0


def check(name, cond, extra=""):
    global FAIL
    if cond:
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}  {extra}")


print("[1] 解析模型输出")
cases = [
    ("<point>134,154</point>", (134, 154)),
    ("<point> 134 , 154 </point>", (134, 154)),
    ("点击位置：(134, 154)", (134, 154)),
    ('{"point": [134, 154]}', (134, 154)),
    ("坐标是 134，154 。", (134, 154)),
    # Thinking 模型：思考里先出现干扰数字，最终答案在后面
    ("思考：可能在 (100,200)，也可能是 (300,400)。\n<point>134,154</point>", (134, 154)),
    ("thinking：先看左边 50,60，再看右边。\n最终 <point>134,154</point>", (134, 154)),
    ("<think>候选 11,22 和 33,44</think>\n<point>134,154</point>", (134, 154)),
    ("抱歉，我无法定位", None),
]
for raw, want in cases:
    got = parse_point(raw)
    if want is None:
        check(repr(raw), got is None, f"got={got}")
    else:
        check(repr(raw), got == want, f"got={got} want={want}")

print("[2] 坐标换算")
# 模型看的是 1280x720，真实屏幕 1920x1080 → 缩放 1.5
x, y = to_screen(100, 200, "abs", 1280, 720, 1920, 1080)
check("abs 换算", abs(x - 150) < 1e-6 and abs(y - 300) < 1e-6, f"got=({x},{y})")
x, y = to_screen(500, 500, "norm1000", 1280, 720, 1920, 1080)
check("norm1000 换算", abs(x - 960) < 1e-6 and abs(y - 540) < 1e-6, f"got=({x},{y})")

print("[3] 打分")
el = {"x": 100, "y": 200, "w": 300, "h": 96}   # 中心 (250, 248)
hit, dist = score_point(250, 248, el)
check("正中命中", hit and abs(dist) < 1e-6)
hit, dist = score_point(100, 200, el)
check("左上角命中", hit)
hit, dist = score_point(99, 200, el)
check("越界未命中", not hit)
hit, dist = score_point(250, 400, el)
check("距离计算", abs(dist - 152) < 1e-6, f"dist={dist}")

print("[4] 假模型端到端")
m = MockModel({"保存文档": el}, noise=0.0, coord_mode="abs")
raw, _ = m.predict(Path("shot_1280.png"), "保存文档", 1280, 720)
pt = parse_point(raw)
sx, sy = to_screen(pt[0], pt[1], "abs", 1280, 720, 1920, 1080)
hit, dist = score_point(sx, sy, el)
check("无噪声时应精确命中", hit and dist < 1.0, f"dist={dist}")

print()
if FAIL:
    print(f"有 {FAIL} 项失败")
    sys.exit(1)
print("全部通过 ✅")
