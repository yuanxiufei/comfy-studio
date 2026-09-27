# -*- coding: utf-8 -*-
"""Router Agent —— 判断用户想做什么（蓝图 §二）。

输入「帮我设计一个废土女佣兵」→ `asset_type = character, operation = create`
输入「把她的头发换成银色」    → `asset_type = character, operation = modify,
                                  target = previous, change = hair_color`
输入「设计她腰上的枪」        → `asset_type = prop, operation = create`

实现策略：先用规则（`nl_parser`）判定；LLM 可用时再用它复核/补正，
但**只在规则置信度低时**才启用 LLM，避免无谓消耗。

⚠️ 本文件有个**同名函数**（2026-09-27 逐项核对过，**不是重复**）：
    `dispatcher.route()` 是**模块级**路由（这句话该进哪个 agent，返回 `RouteResult`）；
    本文件的 `route()` 是**资产库内**的意图判定（create/modify/query + 资产类型，返回 `Route`）。
    两者输入输出与层级都不同 —— 都叫 `route` 只是中文里"路由"一词的两种用法。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from .nl_parser import MODIFY_VERBS, ParsedInput, parse as rule_parse

# ⚠️ 这张表是**查询判定的唯一来源**（`agent._search_term` 也用它抽过滤词 ——
#    两处各存一份必然漂移，那是本项目反复强调的「同一知识两处维护」）。
#    实测踩到：原表**没有「查看」**，于是
#        `python main.py "查看 CHR_001"` → 意图判成 **create** →
#        真的建了一张名叫「查看 CHR_001」的垃圾资产（而不是查 CHR_001）。
#    ⭐ 只放**明确表示"要看/要查"的动词**；`所有/全部` 这类**修饰词不得入表** ——
#       本判定是 `any(w in text)` 且**覆盖** create/modify，加了会把
#       「生成所有角色的三视图」这类创建请求误判成查询。
QUERY_WORDS = ["列出", "列一下", "查找", "查一下", "查询", "查看", "看看",
               "有哪些", "有那些", "找出", "找一下", "搜一下", "搜",
               "list", "show", "find"]
# ⚠️ **修改类动词这里不另存一份** —— 唯一来源是 `nl_parser.MODIFY_VERBS`
#    （它已在 `_detect_modify()` 里判过 modify，连"把"字句都算进去了）。
#    2026-09-27 之前本文件存着第二份（少一个「减掉」），后果与上面那张查询表同款：
#    两份表必然漂移，而漂移**不报错**（少一个词只是某句话判错）。

ROUTER_SYSTEM = """你是 AI 漫剧资产库的指令路由器。判断用户想做什么，只返回 JSON：
{"operation": "create|modify|query", "asset_type": "character|costume|prop|environment",
 "target_asset": "", "change_fields": [], "reason": ""}
asset_type 判定：描述人 → character；描述衣物 → costume；
描述器物（枪/刀/装置/护甲/道具）→ prop；描述场所 → environment。
若用户在改已有资产（含「改成/换成/增加/去掉」或指代「她/他/它」）→ modify。"""


@dataclass
class Route:
    operation: str = "create"
    asset_type: str = "character"
    target_asset: str = ""
    change_fields: list[str] = field(default_factory=list)
    reason: str = ""
    source: str = "rule"

    def to_dict(self) -> dict:
        return {"operation": self.operation, "asset_type": self.asset_type,
                "target_asset": self.target_asset,
                "change_fields": self.change_fields, "reason": self.reason,
                "source": self.source}


def route(text: str, llm=None, default_type: str = "") -> tuple[Route, ParsedInput]:
    """返回 (路由结果, 解析结果)。"""
    parsed = rule_parse(text, default_type)

    r = Route(operation=parsed.operation, asset_type=parsed.asset_type,
              target_asset=parsed.target_asset,
              change_fields=parsed.change_fields, source="rule")
    r.reason = (f"规则命中：{'修改类动词' if parsed.operation == 'modify' else '创建'} · "
                f"类型={parsed.asset_type} · 置信度={parsed.confidence:.1f}")

    if any(w in text for w in QUERY_WORDS):
        r.operation = "query"
        r.reason = "命中查询类动词"
    # ⭐ **修改优先于查询**：两句都出现时（「查看一下，把头发改成蓝色」）用户要的是改。
    #    这里复用的是 `nl_parser` 的**同一张表**（不是副本）—— 故 precedence 也是唯一的。
    if any(w in text for w in MODIFY_VERBS):
        r.operation = "modify"

    # 规则置信度低 → 交给 LLM 复核（有 Key 时）
    if llm is not None and getattr(llm, "available", False) and parsed.confidence < 0.6:
        try:
            out = llm.complete_json(ROUTER_SYSTEM, text)
            r.operation = out.get("operation", r.operation)
            r.asset_type = out.get("asset_type", r.asset_type)
            r.target_asset = out.get("target_asset", r.target_asset) or r.target_asset
            cf = out.get("change_fields") or r.change_fields
            r.change_fields = cf if isinstance(cf, list) else r.change_fields
            r.reason = f"LLM 复核（规则置信度 {parsed.confidence:.1f}）：" \
                       f"{out.get('reason', '')}"
            r.source = "llm"
            parsed.parser = "llm"
            parsed.asset_type = r.asset_type
            parsed.operation = r.operation
        except Exception as e:
            r.reason += f"｜LLM 复核失败，保留规则结果：{e}"

    return r, parsed
