# -*- coding: utf-8 -*-
"""动作 Agent —— `POS_` 资产（角色动作集）。

权威依据（**只读**）：
  · `02-服化道/引擎/EXPRESSION-POSE-LIBRARY.md` §二 动作库（§11）
      基础 18 动作（**关键要点为库中原词**）· 「动作必须符合」6 条铁律 · 追加负面词
  · `00-总控路由.md` §四 ID 规范：`POS_<3位>_<动作名>`

⚠️ 与表情的差别：动作**没有「只改一处」的铁律**，但受**外部约束** ——
   §11 明文要求动作必须符合「**服装限制**」与「**道具使用方式**」
   （长袍不能做紧身裤动作；握持方式要与 PROP 资产卡一致）。
   故动作集必须携带 `clothing_state`（对应 `CST_00X_状态`）与 `prop_ids`。
"""

from __future__ import annotations

from .schema import AssetCard, SheetDNA

# ─────────────────────────────────────────────────────────────
# 基础 18 动作（§二，关键要点 = 库中原词）
# ─────────────────────────────────────────────────────────────
BASELINE_18: list[tuple[str, str, str]] = [
    # (动作, 关键要点, 服装限制注意)
    ("站立", "重心分布、肩线水平", "长袍下摆自然垂坠"),
    ("行走", "步幅、手臂反向摆动", "裙摆/披风动势"),
    ("奔跑", "前倾角度、腾空瞬间", "衣料飞起方向"),
    ("坐", "脊椎曲线、腿部叠放", "下摆铺展"),
    ("跪", "膝盖着地角度", "膝部布料压痕"),
    ("躺", "身体轴线、头部转向", "衣料贴合"),
    ("转身", "腰部带动、发丝惯性", "披风离心"),
    ("回头", "颈肩分离、视线落点", "发丝甩动"),
    ("抬手", "肩胛联动、指节形态", "袖口变形"),
    ("拔武器", "握持方式、手腕角度", "肩甲限制"),
    ("持物", "握持姿势与道具 ID 对应", "手部与道具比例"),
    ("拥抱", "双方重心、臂围合度", "双人衣料交叠"),
    ("对峙", "距离、视线、对称/失衡", "武器指向"),
    ("防御", "护住重心、格挡点", "护具受力面"),
    ("攻击", "发力链（脚→腰→肩→手）", "动作幅度受服装限制"),
    ("跌倒", "失衡瞬间、支撑点", "衣料撕裂可能"),
    ("扶墙", "手部接触点、身体倾斜", "墙面材质对应"),
    ("回眸", "头肩扭转极限、眼神", "发丝弧线"),
]

# 常用子集
SUBSET_6 = ["站立", "行走", "回头", "抬手", "持物", "对峙"]

# ⭐ 18 动作的**英文**（动作库只给了中文要点，英文由本项目补齐）。
# ⚠️ 缺了它，`ITEMS` / `LAYOUT` 两行会往英文 prompt 里塞进 400+ 个汉字。
BASELINE_18_EN: dict[str, str] = {
    "站立": "standing, weight distributed, shoulder line level",
    "行走": "walking, stride length, arms swinging in opposition",
    "奔跑": "running, forward lean angle, airborne moment",
    "坐": "sitting, spinal curve, legs crossed",
    "跪": "kneeling, knee-on-ground angle",
    "躺": "lying down, body axis, head turned",
    "转身": "turning, waist-led rotation, hair inertia",
    "回头": "looking back, neck-shoulder separation, gaze target",
    "抬手": "raising a hand, scapula follow-through, knuckle shape",
    "拔武器": "drawing a weapon, grip method, wrist angle",
    "持物": "holding an object, grip matched to the prop ID",
    "拥抱": "embracing, both centres of gravity, arm enclosure",
    "对峙": "standoff, distance, eyelines, balance or asymmetry",
    "防御": "defending, guarding the centre of gravity, block point",
    "攻击": "attacking, force chain foot to waist to shoulder to hand",
    "跌倒": "falling, moment of imbalance, support point",
    "扶墙": "leaning on a wall, hand contact point, body tilt",
    "回眸": "glancing back, extreme head-shoulder twist, gaze",
}

# 允许变的（中英成对）
MUTABLE_PARTS_EN = ["pose", "centre of gravity", "limb angles", "motion"]

# ⭐ §11「动作必须符合」6 条 —— 逐条进 `physics_checks`，prompt 里必须逐项体现
PHYSICS_CHECKS = [
    "人体结构 — 关节活动范围正确",
    "重心 — 有真实支撑点与重心线",
    "力学 — 发力链合理",
    "角色身份 — 姿态气质与身份匹配（贵族/武士/平民不通用）",
    "服装限制 — 长袍不能做紧身裤动作，重甲不能灵活翻滚",
    "道具使用方式 — 握持方式与 PROP 资产卡记录一致",
]

# 上述 6 条的**英文**（进 English prompt）。
# ⚠️ 缺了它，`PHYSICS CHECKS:` 那一行会在英文 prompt 里塞进整段中文。
PHYSICS_CHECKS_EN = [
    "human anatomy — correct joint range of motion",
    "centre of gravity — real support point and gravity line",
    "mechanics — plausible force chain",
    "character identity — posture and bearing match the character's station",
    "costume limits — no tight-trouser poses in long robes, no agile rolls in heavy armour",
    "prop usage — grip must match the PROP asset card",
]

# 动作 prompt 追加负面词（§二 原文，固定）
EXTRA_NEGATIVE = ("broken limbs, reversed joints, extra arms, "
                  "unbalanced center of gravity, floating")

# 动作集的「可变部分」= 姿态本身；锁定的 = 角色身份相关
MUTABLE_PARTS = ["姿态", "重心", "四肢角度", "动势"]
CONSISTENCY_ANCHORS = ["FACE", "HAIR", "AGE", "BODY PROPORTION", "CLOTHING STATE"]


def complete(card: AssetCard, parsed, rules=None, llm=None) -> tuple[AssetCard, list[str]]:
    """补全动作集（默认基础 18 动作；点名数量时取子集）。"""
    notes: list[str] = []
    sh: SheetDNA = card.sheet_dna
    text = parsed.raw

    n = 18
    for k in (6, 18):
        if f"{k}式" in text or f"{k} 式" in text or f"{k}个动作" in text:
            n = k
            break
    items = BASELINE_18[:n] if n == 18 else [
        t for t in BASELINE_18 if t[0] in SUBSET_6]

    sh.sheet_kind = "pose"
    sh.items = [a for a, _, _ in items]
    # ⚠️ 英文用 `BASELINE_18_EN` —— 曾误写成 `f"{a}, {p}"`（a、p 都是中文），
    #    结果「英文」列整段是中文，还进了 `ITEMS` 与 `LAYOUT` 两行。
    sh.items_en = [BASELINE_18_EN.get(a, a) for a, _, _ in items]
    sh.is_baseline = (n == 18)
    sh.layout = ("pose sheet, multiple poses of the same character side by side, full body"
                 if n > 7 else "2x3 grid, full body")
    sh.consistency_anchors = list(CONSISTENCY_ANCHORS)
    sh.mutable_parts = list(MUTABLE_PARTS)
    sh.mutable_parts_en = list(MUTABLE_PARTS_EN)
    sh.physics_checks = list(PHYSICS_CHECKS)
    sh.physics_checks_en = list(PHYSICS_CHECKS_EN)
    if parsed.related_ids:
        sh.owner = parsed.related_ids[0]

    # 服装状态 / 道具引用（§三 产线规范：动作图必须带这两项）
    sh.clothing_state = next((i for i in parsed.related_ids if i.startswith(("CST_", "COSTUME-"))), "")
    sh.prop_ids = [i for i in parsed.related_ids
                   if i.startswith(("PRP_", "PROP-"))]

    notes.append(f"动作集：{'基础 18 动作' if sh.is_baseline else f'{len(sh.items)} 个动作'}")
    notes.append("§11「动作必须符合」6 条已写入 physics_checks（人体结构/重心/力学/身份/服装限制/道具）")
    if not sh.owner:
        notes.append("⚠️ 未指定所属角色 —— 动作需挂在角色上，请在指令里带上角色 ID")
    if not sh.clothing_state:
        notes.append("⚠️ 未指定服装状态 —— 动作幅度受服装限制（长袍 ≠ 紧身裤）；"
                     "建议在指令里带上 `CST_00X_状态`")
    if not sh.prop_ids:
        notes.append("ℹ️ 未引用道具 —— 若动作涉及持物/拔武器，握持方式须与 `PRP_` 资产卡一致")
    return card, notes


def _sheet_size(text: str) -> int:
    for k in (6, 18):
        if f"{k}式" in text or f"{k} 式" in text or f"{k}个动作" in text:
            return k
    return 18


def id_hint(parsed) -> tuple[str, str]:
    """ID 片段 —— `POS_<3位>_<动作名>`（`00-总控路由.md` §四）。"""
    n = _sheet_size(parsed.raw)
    return "", (f"基础{n}动作" if n == 18 else f"动作{n}式")


def build_card(parsed, asset_id: str, now: str) -> AssetCard:
    owner = parsed.related_ids[0] if parsed.related_ids else ""
    return AssetCard(
        id=asset_id, type="pose",
        name=parsed.name or "动作集",
        source=parsed.raw, created_at=now, updated_at=now,
        world=parsed.world,
        parent_asset=owner,
        # ⚠️ 原写法 `locked = editable = MUTABLE_PARTS` —— 语义反转（见 expression_agent）。
        #    现由 `agent._create` 按 §四·补 A/B 统一设置。
    )


def negative_extra() -> str:
    """动作图必须追加的负面词（§二 原文）。"""
    return EXTRA_NEGATIVE
