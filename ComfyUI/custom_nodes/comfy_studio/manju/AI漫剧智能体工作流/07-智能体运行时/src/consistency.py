# -*- coding: utf-8 -*-
"""一致性层 —— 蓝图 §六「Consistency Agent」，全系统**最重要的一层**。

═══════════════════════════════════════════════════════════════════
它负责什么（蓝图原文）
═══════════════════════════════════════════════════════════════════
    「如果用户只是：改发色
      Consistency Agent 必须确保：
        Face = unchanged / Body = unchanged
        Clothing = unchanged / Equipment = unchanged
      只修改：Hair Color」

对应工作流的
  · `ASSET_CARD.yaml` 的 **fixed_features「100% 不可改动」**
  · 跨阶段一致性铁则 1~4
  · `TURNAROUND-STANDARD.md` §1.4 三视图负面词（一致性靠"锁定+负面词"双保险）

本模块提供四道检查
──────────────────
  1. `check_modify_scope`  —— 改一处时，**其余固定特征是否被误改**（最核心）
  2. `check_derivation`    —— 状态派生卡与母卡**指纹是否一致**
  3. `check_required`      —— 必填项是否齐全（用工作流的字段清单）
  4. `check_text_risk`     —— 文字风险（RULE-005：输图后必须逐字检查隐蔽位置）
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .schema import AssetCard

# 「改一处」时**不允许被动到**的字段（蓝图 §六 的 Face/Body/Clothing/Equipment）
PROTECTED_GROUPS: dict[str, list[str]] = {
    "Face": ["face_shape", "jaw", "cheekbone", "brow_ridge", "nose_bridge", "lips"],
    "Eyes": ["eye_shape", "eye_color"],
    "Body": ["height", "body_type", "shoulder_width"],
    "Signature": ["signature_points"],
}

# 修改意图 → 允许变动的字段（其余一律视为「越界」）
FIELD_TO_ALLOWED: dict[str, list[str]] = {
    "hair": ["hair_length", "hair_style", "hair_volume", "hair_parting", "bangs",
             "hair_color"],
    "hair_color": ["hair_color"],
    "hair_style": ["hair_length", "hair_style", "hair_volume", "hair_parting", "bangs"],
    "eyes": ["eye_shape", "eye_color"],
    "eye_color": ["eye_color"],
    "clothing": ["layers", "silhouette", "primary_color", "material"],
    "equipment": ["signature_accessory"],
    "color": ["primary_color"],
    "age": ["__age__"],
    "body": ["height", "body_type", "shoulder_width"],
    "cybernetic_arm": ["signature_points", "signature_accessory"],
    "cybernetic_leg": ["signature_points", "signature_accessory"],
    "cybernetic_eye": ["signature_points", "eye_color"],
}


@dataclass
class ConsistencyIssue:
    level: str          # error | warn | info
    code: str
    message: str
    field: str = ""
    expected: str = ""
    actual: str = ""


@dataclass
class ConsistencyReport:
    asset_id: str = ""
    ok: bool = True
    issues: list[ConsistencyIssue] = field(default_factory=list)

    def add(self, level: str, code: str, message: str, **kw) -> None:
        self.issues.append(ConsistencyIssue(level, code, message, **kw))
        if level == "error":
            self.ok = False

    def errors(self) -> list[ConsistencyIssue]:
        return [i for i in self.issues if i.level == "error"]

    def summary(self) -> str:
        e = len(self.errors())
        w = len([i for i in self.issues if i.level == "warn"])
        return f"{'✅ 通过' if self.ok else f'❌ {e} 处违规'}（{w} 处提醒）"


# ─────────────────────────────────────────────────────────────
# 1. 改一处不动其余 —— 最核心的一致性检查
# ─────────────────────────────────────────────────────────────

def check_modify_scope(old: AssetCard, new: AssetCard,
                       change_fields: list[str]) -> ConsistencyReport:
    """校验「只改了用户要求的那部分」。

    :param change_fields: 从用户指令解析出的意图（如 ["hair_color"]）
    """
    rep = ConsistencyReport(asset_id=new.id)
    allowed: set[str] = set()
    for f in change_fields:
        allowed |= set(FIELD_TO_ALLOWED.get(f, []))

    # ① 固定特征被改动？
    for grp, fields in PROTECTED_GROUPS.items():
        if grp == "Signature" and "signature_points" in allowed:
            continue
        for fld in fields:
            a, b = _get(old, fld), _get(new, fld)
            if a != b and fld not in allowed:
                rep.add("error", "FIXED_CHANGED",
                        f"{grp} 组的「{fld}」被改动，但用户只要求 {change_fields}——"
                        f"fixed_features 不可动（ASSET_CARD 铁则）",
                        field=fld, expected=str(a), actual=str(b))

    # ② 指纹必须不变（除明确允许的标志性识别点变更）
    if old.fingerprint() != new.fingerprint() and "signature_points" not in allowed:
        rep.add("error", "FINGERPRINT_DRIFT",
                f"固定特征指纹变了（{old.fingerprint()} → {new.fingerprint()}）；"
                f"若确需改身份，应递增主版本并通知全项目")

    # ③ stage_variables 里被误改的项（允许改，但要提醒）
    for fld in old.stage_variables.__dataclass_fields__:
        a = getattr(old.stage_variables, fld)
        b = getattr(new.stage_variables, fld)
        if a != b and fld not in allowed:
            rep.add("warn", "STAGE_CHANGED",
                    f"状态变量「{fld}」也变了（不在用户要求内）",
                    field=fld, expected=str(a), actual=str(b))

    # ④ 道具/场景类：结构不可动
    if old.type in ("prop", "environment"):
        for fld in ("structure", "craft"):
            a, b = _get(old, fld), _get(new, fld)
            if a != b and fld not in allowed:
                rep.add("error", "STRUCTURE_CHANGED",
                        f"{old.type} 的「{fld}」被改动，超出用户要求",
                        field=fld, expected=str(a), actual=str(b))

    return rep


def _get(card: AssetCard, dotted: str) -> object:
    """取字段：默认在 visual_dna，`__age__` 等特例直接取卡上字段。"""
    if dotted == "__age__":
        return card.age
    return getattr(card.visual_dna, dotted, None)


# ─────────────────────────────────────────────────────────────
# 2. 状态派生一致性
# ─────────────────────────────────────────────────────────────

def check_derivation(parent: AssetCard, child: AssetCard) -> ConsistencyReport:
    """状态派生卡必须与母卡**指纹一致**（ASSET_CARD 铁则 1：fixed_features 100% 沿用）。"""
    rep = ConsistencyReport(asset_id=child.id)
    if child.parent_asset != parent.id:
        rep.add("warn", "PARENT_MISMATCH",
                f"派生卡的 parent_asset={child.parent_asset!r}，与母卡 {parent.id} 不符")
    if parent.fingerprint() != child.fingerprint():
        rep.add("error", "DERIVATION_DRIFT",
                f"派生卡指纹与母卡不一致（{parent.fingerprint()} vs "
                f"{child.fingerprint()}）——fixed_features 被改动了")
    # voice / body_language 属 fixed_features，也必须一致
    for fld in ("voice_base_timbre", "voice_speed"):
        a = getattr(parent.fixed_features, fld)
        b = getattr(child.fixed_features, fld)
        if a != b:
            rep.add("warn", "FIXED_MISMATCH", f"fixed_features.{fld} 不一致",
                    field=fld, expected=str(a), actual=str(b))
    return rep


# ─────────────────────────────────────────────────────────────
# 3. 必填项完整性（用工作流的权威字段清单）
# ─────────────────────────────────────────────────────────────

def check_required(card: AssetCard, rules) -> ConsistencyReport:
    """按工作流的必填字段清单检查补全完整度。

    · 角色 → 检查视觉 DNA 的关键项（工作流没有单列"角色 25 字段"，
             用 ASSET_CARD 的 visual_dna 必需项）
    · 服装 → `TURNAROUND-STANDARD.md` §2.1 的 25 字段
    · 道具 → §3.1 的字段清单
    """
    rep = ConsistencyReport(asset_id=card.id)

    if card.type == "costume":
        need = rules.costume_fields
        blob = " ".join([card.notes, card.visual_dna.material,
                         card.visual_dna.structure, card.visual_dna.layers,
                         card.visual_dna.silhouette, card.stage_variables.full_outfit,
                         card.prompt_cn])
        missing = [f for f in need if f not in blob]
        if missing:
            rep.add("warn", "COSTUME_FIELDS",
                    f"服装必填字段缺 {len(missing)}/{len(need)} 项："
                    + "、".join(missing[:8]) + ("…" if len(missing) > 8 else ""))
    elif card.type == "prop":
        need = rules.prop_fields
        blob = " ".join([card.notes, card.visual_dna.structure, card.visual_dna.material,
                         card.visual_dna.craft, card.visual_dna.surface_texture,
                         card.visual_dna.wear, card.visual_dna.scale_reference,
                         card.prompt_cn])
        missing = [f for f in need if f not in blob]
        if missing:
            rep.add("warn", "PROP_FIELDS",
                    f"道具必填字段缺 {len(missing)}/{len(need)} 项："
                    + "、".join(missing[:8]) + ("…" if len(missing) > 8 else ""))
    elif card.type == "environment":
        # 场景 —— 按 §四·4.1 的 11 项必须生成要素检查（**不查角色 DNA**）
        sd = card.scene_dna
        CRIT = [("building", "建筑"), ("spatial_scale", "空间尺度"), ("materials", "材料"),
                ("light_source", "光线"), ("atmosphere", "氛围"), ("era", "时代"),
                ("circulation", "人物动线"), ("foreground", "前景"),
                ("midground", "中景"), ("background", "后景")]
        missing = [cn for f, cn in CRIT if not getattr(sd, f)]
        if missing:
            rep.add("error", "SCENE_ELEMENTS",
                    "场景必须生成要素缺失：" + "、".join(missing)
                    + "（§四·4.1 要求 11 项齐全）")
        if not (sd.architectural_style or sd.architectural_style_en):
            rep.add("warn", "NO_SCENE_STYLE",
                    "建筑风格为空 —— 快速公式要求写清风格，否则与 VISUAL_BIBLE 可能不一致")
        if not sd.locked_elements:
            rep.add("warn", "NO_SCENE_LOCK",
                    "多角度锁定项为空 —— §32 要求同一 ENV 锁定建筑/门窗/家具/地面/光源/主空间关系")
        # ⚠️ 场景**不需要**「纯白背景」——恰恰相反，§四 明文「环境不使用纯白背景」。

    elif card.type in ("expression", "pose"):
        # 表情/动作集 —— 按库 §一/§二 与 §三 产线规范检查
        sh = card.sheet_dna
        if not sh.owner:
            rep.add("error", "SHEET_NO_OWNER",
                    "未绑定所属角色 —— ID 规范要求 `EXP_<角色>_<表情名>` / "
                    "`POS_<3位>_<动作名>`，脱离角色的表情/动作集无法保证一致性")
        need = 16 if card.type == "expression" else 18
        if len(sh.items) < need:
            rep.add("warn", "SHEET_ITEMS_FEW",
                    f"{'表情' if card.type == 'expression' else '动作'}只有 "
                    f"{len(sh.items)} 项（基线要求 {need} 项）")
        if not sh.consistency_anchors:
            rep.add("error", "SHEET_NO_ANCHORS",
                    "一致性锚点为空 —— 铁律要求写满 FACE/HAIR/AGE 等，"
                    "否则「换表情变成换人」")
        if card.type == "expression" and set(sh.mutable_parts) - {
                "眉", "眼", "嘴", "面部肌肉", "微表情"}:
            rep.add("error", "EXPRESSION_RULE_BREACH",
                    "`mutable_parts` 超出 §10 铁律允许范围（只允许 眉/眼/嘴/肌肉/微表情）")

    else:
        # 角色：关键识别项不得为空
        CRIT = [("face_shape", "脸型"), ("eye_shape", "眼型"), ("hair_length", "发长"),
                ("hair_color", "发色"), ("body_type", "体型"), ("primary_color", "主色"),
                ("material", "材质")]
        missing = [cn for f, cn in CRIT if not getattr(card.visual_dna, f)]
        if missing:
            rep.add("error", "CHARACTER_DNA",
                    "关键视觉 DNA 缺失：" + "、".join(missing)
                    + "（缺了必然导致跨镜漂移）")
        if not card.fixed_features.facial_contour:
            rep.add("warn", "NO_FACIAL_CONTOUR",
                    "fixed_features.facial_contour 为空 —— 它是「五官轮廓」的锁定依据")
        if not card.visual_dna.signature_points:
            rep.add("warn", "NO_SIGNATURE",
                    "signature_points 为空 —— 建议 3~7 个不可轻易改变的识别点")

    if not card.id_registered:
        rep.add("error", "ID_NOT_REGISTERED",
                "id_registered=false：该 ID 未登记进 ID-REGISTRY，属违规")
    return rep


# ─────────────────────────────────────────────────────────────
# 4. 文字风险（RULE-005）
# ─────────────────────────────────────────────────────────────

# 输图后必须逐字检查的隐蔽位置（来自 TURNAROUND-STANDARD §1.6）
TEXT_RISK_SPOTS = ["背景招牌", "书页", "屏幕", "衣物印字", "包装", "道具铭文"]


def check_text_risk(prompt_en: str, negative: str) -> ConsistencyReport:
    """RULE-005：`no text` 不够，必须带**权重 1.8** 的反向词。

    ⚠️ 判定用「权重标记」`any text:1.8`，**不要找字面的 `(any text:1.8)`**：
    权威文档 §1.6 的正文用反引号写 `` `(any text:1.8)` `` 作**说明**，
    但同一节的「反向追加」代码块里，它是嵌在更大括号组中的 —— 实际形态是
        (text, font, …, view labels, any text:1.8), signature, …
    即 `(` 在行首、`)` 在 `any text:1.8` 之后。按字面对找会**误报缺失**（实测踩到）。
    真正的关键词是 **权重 1.8**（文档原话：「缺了它模型仍会生成标注文字」）。
    """
    rep = ConsistencyReport()
    if "any text:1.8" not in negative:
        rep.add("error", "TEXT_WEIGHT_MISSING",
                "反向词缺权重标记 `any text:1.8` —— 权威文档 §1.6 明确"
                "「缺了它模型仍会生成标注文字」")
    for kw in ("no text", "watermark", "logo"):
        if kw not in prompt_en.lower() and kw not in negative.lower():
            rep.add("warn", "TEXT_NOT_BLOCKED", f"未显式禁止 `{kw}`")
    if "NO TEXT" not in prompt_en and "text" not in negative.lower():
        rep.add("warn", "POSITIVE_NOT_BLOCKED",
                "正向段未追加 `NO TEXT, no annotations, no labels, no words`")
    return rep


def text_risk_checklist() -> list[str]:
    """输图后的人工复核清单（RULE-005 要求「逐字检查隐蔽位置」）。"""
    return [f"{s} 是否出现文字" for s in TEXT_RISK_SPOTS]


# ─────────────────────────────────────────────────────────────
# 5. 汇总
# ─────────────────────────────────────────────────────────────

def full_check(card: AssetCard, rules, parent: AssetCard | None = None,
               old: AssetCard | None = None,
               change_fields: list[str] | None = None) -> ConsistencyReport:
    """跑全部适用检查，合并成一份报告。"""
    rep = ConsistencyReport(asset_id=card.id)
    for sub in filter(None, [
        check_required(card, rules),
        check_text_risk(card.prompt_en, card.negative_prompt),
        check_derivation(parent, card) if parent else None,
        check_modify_scope(old, card, change_fields or []) if (old and change_fields) else None,
    ]):
        rep.issues.extend(sub.issues)
        rep.ok = rep.ok and sub.ok
    return rep
