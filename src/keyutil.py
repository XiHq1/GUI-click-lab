# -*- coding: utf-8 -*-
"""统一读取 API Key，优先级：命令行参数 > 环境变量 > 项目根目录 key.txt。

Windows 上环境变量只在当前 PowerShell 窗口有效，关掉就没了，
所以支持把 key 放进 key.txt（已被 .gitignore 排除，不会提交）。
"""

from __future__ import annotations

import os
from pathlib import Path

_KEY_FILE = Path(__file__).resolve().parent.parent / "key.txt"


def get_key(cli_value: str = "") -> str:
    if cli_value:
        return cli_value.strip()

    env = os.environ.get("GUI_LAB_API_KEY", "").strip()
    if env:
        return env

    if _KEY_FILE.is_file():
        txt = _KEY_FILE.read_text(encoding="utf-8").strip()
        if txt:
            return txt

    return ""


def key_file_path() -> Path:
    return _KEY_FILE
