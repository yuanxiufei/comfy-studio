# -*- coding: utf-8 -*-
"""00 总控的路由 —— 输入 → 该进哪个 agent。

规则来源：`00-总控路由.md` §二 路由表 + §七 指令速查。
**但触发词写在 `registry.py`**（声明式）—— 因为那是"哪个词属于哪个模块"的
事实，和模块本身放在一起才不会失联；路由**算法**在这里。

判定原则（与工作流 §八·5 一致）：**不确定就问一句，不猜**。
故低置信度时不硬选，返回候选列表 + 那句唯一的追问。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .registry import AGENTS, REGISTRY, AgentSpec


@dataclass
class RouteResult:
    agent: AgentSpec | None = None
    scores: dict[str, int] = field(default_factory=dict)
    reason: str = ""
    confident: bool = False
    candidates: list[str] = field(default_factory=list)

    @property
    def question(self) -> str:
        return ("你现在手上有的是「一句话创意 / 小说 / 剧本 / 分镜表 / 成片」"
                "中的哪一种？")


def route(text: str) -> RouteResult:
    """按触发词打分路由。

    · **长触发词权重更高**（「帮我做一部漫剧」比「剧本」更具体）
    · 命中 `orchestrator` 的"全流程"类词 → 直接进总控（用户要的是整条链路）
    · 分数为 0 → 不硬选，回总控 + 那句唯一追问（工作流 §八·5）
    """
    # ⚠️ 去掉**全部空白**后再匹配 —— 用户会写「40集」而注册表写「40 集」，
    #    不做归一就永远命中不了（实测踩到：`帮我做一部40集的废土漫剧` 零命中）。
    t = re.sub(r"\s+", "", text or "")

    scores: dict[str, int] = {}
    for spec in REGISTRY:
        s = 0
        for kw in spec.triggers:
            k = re.sub(r"\s+", "", kw)
            if k and k in t:
                # 长词更具体 → 权重更高（上限 4，避免长句压倒一切）
                s += min(4, max(1, len(k) // 2))
        if s:
            scores[spec.key] = s

    if not scores:
        return RouteResult(
            agent=AGENTS["orchestrator"],
            reason="无模块触发词命中 → 交总控判定（工作流 §八·5：不确定就问一句，不猜）",
            confident=False,
        )

    best = max(scores.values())
    top = [k for k, v in scores.items() if v == best]
    # 严格大于第二名才算"自信"；并列时优先序号靠前（生产顺序上更上游）
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    confident = len(top) == 1 and (
        len(ranked) == 1 or ranked[0][1] > ranked[1][1])

    key = ranked[0][0]
    spec = AGENTS[key]
    if key == "orchestrator":
        reason = f"命中全流程触发词 → 总控调度（{spec.summary}）"
    elif confident:
        reason = f"命中「{spec.name}」触发词（得分 {best}，唯一最高）"
    else:
        reason = (f"最高分指向「{spec.name}」（{best}），但与 "
                  f"{'/'.join(k for k, _ in ranked[1:3])} 相近 —— **建议先确认**")

    return RouteResult(
        agent=spec,
        scores=dict(ranked),
        reason=reason,
        confident=confident,
        candidates=[AGENTS[k].name for k, _ in ranked[:3]],
    )


def table() -> str:
    """打印「用户说 → 进哪个 agent」速查表（由注册表生成，永不与代码失联）。"""
    rows = ["| 用户说（触发词示例） | 进哪个 agent | 模块 |", "|---|---|---|"]
    for spec in REGISTRY:
        kws = " · ".join(spec.triggers[:6])
        rows.append(f"| {kws} | **{spec.name}** | {spec.no} |")
    return "\n".join(rows)
