# -*- coding: utf-8 -*-
"""交接清单 + 门禁 —— 跨模块协作的机器化守门。

依据：`00-总控路由.md` §四（交接清单七字段）· §五（三门禁）· §六（全局一致性守护）。

⭐ 为什么这两个要做成**工具**而不是只写进 prompt：
    工作流 §六 记录过一次真实事故 —— EP01 走通时，唯一的真实阻塞
    （「AI 生成音乐商用授权」）**拖到 06 合规阶段才首次发现**，此时全片已做完。
    根因是「交接清单」与「门禁」**全靠人记**。给出可执行的骨架 + 校验，
    才能在下游之前把问题拦下来。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .registry import REGISTRY, AgentSpec

# `00-总控路由.md` §四「交接清单（每个模块交付时必须给出）」的七字段
HANDOVER_FIELDS = ["交付模块", "交付物", "新增 ID", "引用 ID",
                   "锁定项", "风格锚点", "未决项"]


def skeleton(spec: AgentSpec) -> str:
    """生成该模块的交接清单骨架（可直接粘贴填充）。"""
    out = [f"```text",
           f"交付模块：{spec.no}-{spec.name.replace('引擎', '')}",
           f"交付物：{(' / '.join(spec.outputs)) or '<文件/资产清单>'}",
           "新增 ID：<本模块新分配的 ID>",
           "引用 ID：<引用的上游 ID>",
           "锁定项：<本模块锁定的 LOCK_*>",
           "风格锚点：<当前生效的风格英文锚点>",
           "未决项：<待用户确认或下游处理的事项>",
           "```"]
    return "\n".join(out)


@dataclass
class Report:
    ok: bool = True
    missing: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def render(self) -> str:
        if self.ok and not self.notes:
            return "✅ 通过"
        lines = []
        for m in self.missing:
            lines.append(f"  ❌ 缺字段：{m}")
        for n in self.notes:
            lines.append(f"  ⚠️ {n}")
        return "\n".join(lines)


def check_handover(text: str, spec: AgentSpec) -> Report:
    """校验一份交接清单是否齐七字段 + 是否遗漏未决项。

    「未决项」**允许写"无"**，但**不允许整行缺失** —— 那是"忘了想"的典型形态
    （正是 EP01 事故的成因）。
    """
    rep = Report()
    for f in HANDOVER_FIELDS:
        if not re.search(re.escape(f) + r"\s*[:：]", text):
            rep.missing.append(f)
    if "未决项" in text and re.search(r"未决项\s*[:：]\s*$", text, re.M):
        rep.notes.append("「未决项」为空 —— 应显式写「无」或列出，不可留空")
    rep.ok = not rep.missing
    return rep


def check_gate(text: str, spec: AgentSpec) -> Report:
    """按该模块的门禁标准做**关键词级**预检。

    ⚠️ 这是**预检**不是判定：门禁的最终判定需要人/模型对内容质量负责。
    这里只拦「明显没做」（如分镜门禁要求的九列、叙事目的一个字都没提）。
    """
    rep = Report()
    if not spec.gate:
        rep.notes.append(f"{spec.name} 未登记门禁（该模块不是门禁检查点）")
        return rep
    for c in spec.gate_checks:
        if not any(k in text for k in c.any_of):
            rep.missing.append(f"{c.label}（判据关键词一个都没检出："
                               f"{' / '.join(c.any_of[:4])}）")
    rep.ok = not rep.missing
    if not rep.ok:
        rep.notes.append(f"门禁「{spec.gate}」未过 → **不得推进下一模块**"
                         f"（工作流 §五）；用户要求跳过时先列风险再二次确认")
    return rep


def gate_overview() -> str:
    """三门禁一览（**由注册表生成**，不手写 —— 免与代码失联）。"""
    rows = ["| 门禁 | 检查模块 | 通过标准 |", "|---|---|---|"]
    for spec in REGISTRY:
        if spec.gate:
            rows.append(f"| **{spec.gate}** | {spec.no} {spec.name} | "
                        f"{' · '.join(c.label for c in spec.gate_checks)} |")
    return "\n".join(rows)
