# -*- coding: utf-8 -*-
"""表情 Agent —— `EXP_` 资产（角色表情集）。

权威依据（**只读**）：
  · `02-服化道/引擎/EXPRESSION-POSE-LIBRARY.md` §一 表情库（§10）
      基线 16 式（**英文描述词为库中原词，逐字使用**）· 扩展 50 式 · 网格布局 · 铁律
  · `02-服化道/00-主控智能体.md` §10 EXPRESSION ENGINE
  · `00-总控路由.md` §四 ID 规范：`EXP_<角色>_<表情名>`

⭐ **铁律（§10）**：表情图**只允许改变**眉 / 眼 / 嘴 / 面部肌肉 / 微表情；
   **绝不允许改变**脸型 / 年龄 / 发型 / 发色 / 核心身份。
   故本 agent 的产物必须显式写出**一致性锚点**（FACE / HAIR / BODY / AGE），
   否则"换表情变成换人"是本项目最高发的失败形态。
"""

from __future__ import annotations

from .schema import AssetCard, SheetDNA

# ─────────────────────────────────────────────────────────────
# 基线 16 式（§1.1，核心角色**必须全部建立**）
# 英文描述词 = 库中原词（逐字，不得改写 —— 改了会与工作流权威不一致）
# ─────────────────────────────────────────────────────────────
BASELINE_16: list[tuple[str, str]] = [
    ("平静", "neutral expression, relaxed features, steady gaze, soft relaxed eyebrows"),
    ("微笑", "subtle smile, gently upturned mouth corners, slight eye narrowing, soft gaze"),
    ("喜悦", "joyful expression, bright eyes, cheerful smile, raised cheeks, upturned mouth corners, relaxed eyebrows"),
    ("愤怒", "angry expression, furrowed brows, narrowed eyes, tense jaw, flushed face"),
    ("悲伤", "sad expression, downcast eyes, downturned mouth, melancholic, drooping eyebrows"),
    ("惊讶", "surprised expression, wide eyes, raised eyebrows, open mouth, shocked"),
    ("恐惧", "fearful expression, wide eyes with whites showing, raised eyebrows, tense mouth, terrified"),
    ("怀疑", "suspicious expression, one raised eyebrow, narrowed eyes, tightened mouth"),
    ("轻蔑", "contemptuous expression, half-lidded eyes, one-sided mouth corner raised, raised chin"),
    ("羞涩", "shy expression, blushing cheeks, downcast eyes, slight smile, looking away"),
    ("冷笑", "cold smirk, one-sided mouth corner raised, half-lidded eyes, unamused eyes"),
    ("忍泪", "holding back tears, glistening eyes, pressed inner eyebrows, tightened lips, tense jaw"),
    ("震惊", "shocked expression, wide eyes, constricted pupils, rigid facial muscles, open mouth, stunned"),
    ("强装镇定", "forced calm, deliberately relaxed eyebrows, slightly averted gaze, tight neck, swallowing"),
    ("准备反击", "determined expression, focused intense gaze, pressed lips, tightened masseter"),
    ("崩溃", "breakdown expression, collapsed eyebrows, unfocused or closed eyes, uncontrolled open mouth, emotional collapse"),
]

# 常用子集（给群像配角 / 需要快速出图时用，§1.4）
SUBSET_4 = ["平静", "微笑", "愤怒", "悲伤"]
SUBSET_8 = ["平静", "微笑", "喜悦", "愤怒", "悲伤", "惊讶", "恐惧", "准备反击"]

# §1.3 网格布局 —— 数量决定版式
GRID = {4: "2×2", 8: "2×4 或 4×2", 16: "4×4", 25: "5×5", 50: "5×10 或 7×8（建议分批）"}

# ⭐ 铁律（§10）：写进 Consistency Constraints，**绝不允许变**
CONSISTENCY_ANCHORS = ["FACE", "HAIR", "AGE", "SKIN TONE", "EYE COLOR"]

# 允许变的（只改这些）—— 中英成对（英文进 EN prompt，否则会夹中文）
MUTABLE_PARTS = ["眉", "眼", "嘴", "面部肌肉", "微表情"]
MUTABLE_PARTS_EN = ["eyebrows", "eyes", "mouth", "facial muscles", "micro-expressions"]

# 表情图追加负面词（§三 表情/动作产线规范 原文）
EXTRA_NEGATIVE = ("changed face shape, changed age, changed ethnicity, "
                  "collapsed facial structure, deformed eyes")


def _grid_for(n: int) -> str:
    if n in GRID:
        return GRID[n]
    # 取最接近的较大档
    for k in sorted(GRID):
        if n <= k:
            return f"{GRID[k]}（按 {n} 式取子集）"
    return f"建议分批（单图不超 25 格）"


def complete(card: AssetCard, parsed, rules=None, llm=None) -> tuple[AssetCard, list[str]]:
    """补全表情集（默认为**基线 16 式**；用户点名数量时取子集）。

    签名与其余 agent 一致（`complete(card, parsed, rules, llm)`）。
    """
    notes: list[str] = []
    sh: SheetDNA = card.sheet_dna
    text = parsed.raw

    n = 16
    for k, cand in ((4, 4), (8, 8), (16, 16)):
        if f"{k}式" in text or f"{k} 式" in text:
            n = k
            break
    items = BASELINE_16[:n] if n == 16 else [
        (k, v) for k, v in BASELINE_16 if k in (SUBSET_4 if n == 4 else SUBSET_8)]

    sh.sheet_kind = "expression"
    sh.items = [k for k, _ in items]
    sh.items_en = [v for _, v in items]
    sh.is_baseline = (n == 16)
    sh.layout = _grid_for(len(items))
    sh.consistency_anchors = list(CONSISTENCY_ANCHORS)
    sh.mutable_parts = list(MUTABLE_PARTS)
    sh.mutable_parts_en = list(MUTABLE_PARTS_EN)
    if parsed.related_ids:
        sh.owner = parsed.related_ids[0]

    notes.append(f"表情集：{'基线 16 式' if sh.is_baseline else f'{len(sh.items)} 式子集'}"
                 f"（网格 {sh.layout}）")
    notes.append("铁律已写入：只改 眉/眼/嘴/肌肉/微表情；"
                 "脸型/年龄/发型/发色/身份 写入 Consistency Constraints")
    if not sh.owner:
        notes.append("⚠️ 未指定所属角色 —— 表情 ID 规范要求 `EXP_<角色>_<表情名>`，"
                     "请在指令里带上角色 ID（如「给 CHR_001 建表情集」）")
    # ⚠️ 必须返回 `(card, notes)` 二元组 —— 曾误写成 `return notes`，
    #    调用方 `card, notes = agent.complete(...)` 于是把列表**解包**成
    #    card=notes[0]（字符串）→ 下游 `card.visual_dna` 报 AttributeError。
    return card, notes


def _sheet_size(text: str) -> int:
    """从输入里取表情数量（默认 16 = 基线全量）。"""
    for k in (4, 8, 16):
        if f"{k}式" in text or f"{k} 式" in text:
            return k
    return 16


def id_hint(parsed) -> tuple[str, str]:
    """给 `agent._create` 用的 ID 片段 —— `EXP_<角色>_<表情名>`（`00-总控路由.md` §四）。

    注：规范里角色部分写作 `CHR001`（**无下划线**），由 `schema.make_id` 统一去掉。
    """
    owner = parsed.related_ids[0] if parsed.related_ids else ""
    n = _sheet_size(parsed.raw)
    return owner, (f"基线{n}式" if n == 16 else f"表情{n}式")


def build_card(parsed, asset_id: str, now: str) -> AssetCard:
    owner = parsed.related_ids[0] if parsed.related_ids else ""
    return AssetCard(
        id=asset_id, type="expression",
        name=parsed.name or (f"{owner} 表情集" if owner else "表情集"),
        source=parsed.raw, created_at=now, updated_at=now,
        world=parsed.world,
        parent_asset=owner,
        # ⚠️ 原写法 `locked=MUTABLE_PARTS`（`editable` 同值）—— **语义反转**：
        #    MUTABLE_PARTS 是「只有这几项**允许**改」，却被写进了 `locked`，
        #    于是"可变的"被标成"锁定的"，且 `locked == editable`（不可能同时成立）。
        #    现由 `agent._create` 按 §四·补 A/B 统一设置。
    )


def negative_extra() -> str:
    """表情图必须追加的负面词（§三 原文）。"""
    return EXTRA_NEGATIVE
