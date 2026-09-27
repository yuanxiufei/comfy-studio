# -*- coding: utf-8 -*-
"""通用模块加载器 —— 为**任意** agent 从工作流文档装配角色知识。

═══════════════════════════════════════════════════════════════════
为什么是「通用」的
═══════════════════════════════════════════════════════════════════
工作流的每个模块文档里，都**自带**这几段（这是工作流的既定体例）：

    ## 输入分流 / 输入与前置检查   ← 它接受什么输入
    ## 输出纪律                   ← 它怎么输出
    ## 初始化指令                 ← 它开场该说什么（"XX 引擎已就位"）

所以"让某个模块成为可独立运行的 agent"**不需要为它写代码** —— 只要：

    ① 从 `registry.py` 拿到它的 `role_docs`
    ② 把它们读进来
    ③ 抽出「初始化指令 / 输出纪律」（有就抽，没有就跳过）
    ④ 叠加**所有模块共同**的约束：ID 命名与交接协议 + 该模块门禁

第 ④ 步是这个运行时的价值所在：**单个模块文档不会重复写"ID 交接协议"**，
但每个模块都必须遵守 —— 由运行时统一叠加，模块文档改动它自动跟随。

> ⚠️ 只读：本模块**不写**工作流任何文件（同 `rule_source.py`）。
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from .registry import AgentSpec
from .rule_source import RuleSource

# ─────────────────────────────────────────────────────────────
# Markdown 小工具
# ─────────────────────────────────────────────────────────────

_HEADING = re.compile(r"^(#{1,6})\s*(.+?)\s*$")


def _headings(text: str) -> list[tuple[int, int, str]]:
    """返回 [(行号, 级别, 标题文本)]，跳过代码块内的 `#`。"""
    out, fence = [], False
    for i, line in enumerate(text.splitlines()):
        if line.lstrip().startswith("```"):
            fence = not fence
            continue
        if fence:
            continue
        m = _HEADING.match(line)
        if m:
            out.append((i, len(m.group(1)), m.group(2)))
    return out


def section(text: str, *keywords: str, level: int | None = 2) -> str:
    """抽出**标题含任一关键词**的章节，直到同级或更高级标题为止。

    :param level: 限定标题级别（默认 2 = `##`）；**传 None 表示任意级别**。
                  按需取原文时应传 None —— 否则 `## 一、角色三视图标准` 下的
                  `### 1.6 文字屏蔽…` 取不到（实测踩到）。

    ⚠️ 抽不到就返回空串 —— **不要**抛错：各模块体例不完全一致
    （如 `02` 没有「输出纪律」段），强行要求会导致半数模块无法加载。
    调用方据此降级即可（这也是它能"通用"的原因）。
    """
    hs = [h for h in _headings(text)
          if (level is None or h[1] == level) and any(k in h[2] for k in keywords)]
    if not hs:
        return ""
    start_i, lvl, _ = hs[0]
    lines = text.splitlines()
    end_i = len(lines)
    for i, l, _t in _headings(text):
        if i > start_i and l <= lvl:
            end_i = i
            break
    return "\n".join(lines[start_i:end_i]).strip()


def outline(text: str, max_level: int = 3) -> str:
    """返回文档的**章节目录**（用于 ref_docs —— 只给索引，不占 token 全文）。"""
    out = []
    for _, lvl, title in _headings(text):
        if lvl <= max_level:
            out.append("  " * (lvl - 1) + "- " + title)
    return "\n".join(out)


# ─────────────────────────────────────────────────────────────
# 加载器
# ─────────────────────────────────────────────────────────────

class ModuleLoader:
    """从工作流读取任意 agent 的角色知识。

    :param workflow_root: 工作流根；None 时借 `RuleSource` 的自动探测（含 `WORKFLOW_ROOT` 环境变量）。
    """

    def __init__(self, workflow_root: str | os.PathLike | None = None):
        rs = RuleSource(workflow_root)
        self.root: Path | None = rs.workflow_root
        self._cache: dict[str, str] = {}

    # ── 底层读取 ──
    def text(self, rel: str) -> str:
        """读工作流里的一份文档（相对工作流根）。缺失返回空串。"""
        if rel in self._cache:
            return self._cache[rel]
        t = ""
        if self.root:
            p = Path(self.root) / rel
            if p.is_file():
                try:
                    t = p.read_text(encoding="utf-8")
                except Exception:
                    t = ""
        self._cache[rel] = t
        return t

    def exists(self, rel: str) -> bool:
        return bool(self.text(rel))

    def missing(self, spec: AgentSpec) -> list[str]:
        """列出该 agent 登记了但**实际不存在**的文档（供 `doctor` 诚实报告）。"""
        return [r for r in (spec.role_docs + spec.ref_docs) if not self.exists(r)]

    # ── 该 agent 的体例段落 ──
    def init_instruction(self, spec: AgentSpec) -> str:
        """「初始化指令」—— 该模块开场该说的话（`XX 引擎已就位…请先告诉我…`）。

        逐份 role_doc 找，取第一个有的。找不到时**由运行时合成**一句兜底
        （不能因为文档缺这段，agent 就无法独立启动）。
        """
        for rel in spec.role_docs:
            s = section(self.text(rel), "初始化指令", "初始化")
            if s:
                return s
        forms = " / ".join(spec.input_forms) or "输入"
        return (f"> **{spec.name}已就位。**\n>\n"
                f"> 我负责：{spec.summary}\n>\n"
                f"> 请先告诉我你手上有什么（{forms}），以及本次目标。")

    def output_discipline(self, spec: AgentSpec) -> str:
        """「输出纪律」。没有就返回空串（部分模块体例里没有这一段）。"""
        for rel in spec.role_docs:
            s = section(self.text(rel), "输出纪律", "输出规范")
            if s:
                return s
        return ""

    def input_section(self, spec: AgentSpec) -> str:
        """「输入分流 / 输入与前置检查」—— 它接受什么输入。"""
        for rel in spec.role_docs:
            s = section(self.text(rel), "输入分流", "输入与前置", "输入")
            if s:
                return s
        return ""

    # ── 全局叠加：所有模块共同遵守的约束 ──
    def id_protocol(self) -> str:
        """`00-总控路由.md` §四 跨模块资产 ID 交接协议（每个模块都必须遵守）。"""
        t = self.text("00-总控路由.md")
        return section(t, "跨模块资产 ID 交接协议", "交接协议")

    def gate_standard(self, spec: AgentSpec) -> str:
        """三门禁表里**属于本模块**的那一行 + 判定标准。"""
        t = self.text("00-总控路由.md")
        gate = section(t, "三门禁", "Gate")
        if not gate or not spec.gate:
            return ""
        keep = [l for l in gate.splitlines()
                if spec.gate in l or l.strip().startswith("|") or
                spec.name.split("引擎")[0] in l]
        return "\n".join(keep).strip()

    def global_guard(self) -> str:
        """§六 全局一致性守护（四张单子 + 未决项跟踪）。"""
        return section(self.text("00-总控路由.md"), "全局一致性守护")

    # ── 装配 System Prompt ──
    def system_prompt(self, spec: AgentSpec, *, brief: bool = False) -> str:
        """为一个 agent 装配完整 System Prompt。

        :param brief: True 时 role_docs 也只给**目录**（省 token，用于快速核对结构）
        """
        blocks = [
            f"# 角色\n\n你是「AI 漫剧 · {spec.name}」agent"
            f"（模块 {spec.no}{'（总控）' if spec.key == 'orchestrator' else ''}）。\n"
            f"职责：{spec.summary}\n"
            f"交付物：{' · '.join(spec.outputs) or '（见角色文档）'}",
            self.init_instruction(spec),
        ]

        inp = self.input_section(spec)
        if inp:
            blocks.append("# 你的输入分流\n\n" + inp)

        # 角色知识：原文（或目录）
        parts = ["# 你的工作规范（**权威文档原文，逐字遵守**）"]
        for rel in spec.role_docs:
            t = self.text(rel)
            if not t:
                parts.append(f"\n## 【缺失】{rel}\n> ⚠️ 该文档未找到 —— 运行 `python main.py doctor` 查看。")
                continue
            parts.append(f"\n## 来源：`{rel}`\n")
            parts.append(outline(t) if brief else t)
        blocks.append("\n".join(parts))

        # 参考素材：只给目录（按需展开，避免 prompt 爆炸）
        if spec.ref_docs:
            r = ["# 参考素材（**目录**；需要某节时用 `python main.py doc <路径>` 取原文）",
                 "| 文档 | 章节 |", "|---|---|"]
            for rel in spec.ref_docs:
                t = self.text(rel)
                if not t:
                    r.append(f"| `{rel}` | ⚠️ 缺失 |")
                    continue
                hs = [h[2] for h in _headings(t) if h[1] <= 3][:8]
                r.append(f"| `{rel}` | {' · '.join(hs) if hs else '（无标题）'} |")
            blocks.append("\n".join(r))

        # ⭐ 全局叠加
        common = ["# 跨模块共同约束（**任何模块都不得违背**）"]
        idp = self.id_protocol()
        if idp:
            common.append("\n## 一、资产 ID 命名与交接协议（`00-总控路由.md` §四）\n\n" + idp)
        g = self.gate_standard(spec)
        if g:
            common.append(f"\n## 二、本模块门禁：**{spec.gate}**\n\n{g}")
        gg = self.global_guard()
        if gg:
            common.append("\n## 三、全局一致性守护（四张单子 + 未决项跟踪）\n\n" + gg)
        od = self.output_discipline(spec)
        if od:
            common.append("\n## 四、输出纪律\n\n" + od)
        if len(common) > 1:
            blocks.append("\n".join(common))

        return "\n\n---\n\n".join(b for b in blocks if b.strip())
