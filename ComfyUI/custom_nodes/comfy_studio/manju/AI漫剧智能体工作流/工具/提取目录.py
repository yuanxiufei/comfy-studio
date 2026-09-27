#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI漫剧智能体工作流 · 规格目录提取器
================================================

用途：从「规格原文」中提取章节标题，用于：
  1. 融入新规格前做**冗余审计**（看有多少节、是否重复）
  2. 构建/更新 `_规格原文/README.md` 的**章节落点索引**
  3. 核对提炼是否覆盖了全部章节

用法：
    python 工具/提取目录.py                          # 扫描所有 _规格原文
    python 工具/提取目录.py 某规格.md                 # 指定文件
    python 工具/提取目录.py 某规格.md --lines         # 附带每节行号区间

背景：融入用户规格时，必须先把 80 节左右的内容映射到提炼版，
      否则无法证明「提炼」而非「阉割」。本工具负责这一步的输入。
"""

import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 中文数字章节标题，如 "# 一、智能体基本信息" 或 "## 二、智能体定位"
# 注：允许 ## / ### 层级——同一份规格里可能混用（实测 §一/§二 用 ##，§三起用 #）。
#     因为要求「中文数字 + 、」，不会误匹配 "## 6.1 年龄" 或 "### Frame 01"。
SEC_RE = re.compile(r"^#{1,3}\s*([一二三四五六七八九十百零]+)、\s*(.+?)\s*$", re.M)

# 兜底：阿拉伯数字编号的标题，如 "## 1. 总览"
SEC_RE_ARABIC = re.compile(r"^#{1,2}\s*(\d+)[.、]\s*(.+?)\s*$", re.M)


def find_specs():
    """找出所有 _规格原文 目录下的 md（排除 README）。"""
    out = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        if os.path.basename(dirpath) != "_规格原文":
            continue
        for fn in filenames:
            if fn.endswith(".md") and fn != "README.md":
                out.append(os.path.join(dirpath, fn))
    return sorted(out)


def extract(path, with_lines=False):
    txt = open(path, encoding="utf-8").read()
    secs = [(m.group(1), m.group(2), m.start()) for m in SEC_RE.finditer(txt)]
    if not secs:
        secs = [(m.group(1), m.group(2), m.start()) for m in SEC_RE_ARABIC.finditer(txt)]
    lines = txt.splitlines()

    rows = []
    for i, (num, title, pos) in enumerate(secs):
        start = txt[:pos].count("\n") + 1
        if with_lines:
            if i + 1 < len(secs):
                end = txt[: secs[i + 1][2]].count("\n") + 1
            else:
                end = len(lines)
            rows.append((i + 1, num, title, start, end))
        else:
            rows.append((i + 1, num, title, start, None))
    return rows, len(lines), len(txt.encode("utf-8"))


def main():
    argv = [a for a in sys.argv[1:]]
    with_lines = "--lines" in argv
    argv = [a for a in argv if not a.startswith("--")]

    specs = [os.path.abspath(a) if os.path.exists(a) else os.path.join(ROOT, a)
             for a in argv] if argv else find_specs()

    if not specs:
        print("未找到任何规格原文（_规格原文/ 目录下的 md）")
        return 1

    grand = 0
    for path in specs:
        if not os.path.exists(path):
            print(f"[跳过] 不存在：{path}")
            continue
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        rows, nlines, nbytes = extract(path, with_lines)
        grand += len(rows)

        print("=" * 72)
        print(f"{rel}")
        print(f"  {nlines} 行 ｜ {nbytes / 1024:.1f} KB ｜ {len(rows)} 节")
        if with_lines:
            print(f"  {'序':>3}  {'行区间':>13}  标题")
            print("  " + "-" * 66)
            for idx, num, title, s, e in rows:
                print(f"  {idx:>3}  {s:>5}-{e:<6}  #{num}、{title}")
        else:
            for idx, num, title, _, _ in rows:
                print(f"{idx:>4}. #{num}、{title}")
        print()

    print("=" * 72)
    print(f"合计 {len(specs)} 份规格，{grand} 节")
    print()
    print("用途提示：")
    print("  · 融入新规格前 → 用本清单做冗余审计（找出重复的输出模板/指令/流程）")
    print("  · 提炼完成后   → 把每节映射到提炼版章节，写入 _规格原文/README.md")
    print("  · 勾选验收     → 确认无「仅原文」节被遗漏（或明确标注）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
